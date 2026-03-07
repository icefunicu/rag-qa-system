package api

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

func (a *API) handleListMessages(w http.ResponseWriter, r *http.Request) {
	sessionID := chi.URLParam(r, "sessionID")
	if _, err := uuid.Parse(sessionID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid sessionID")
		return
	}

	exists, err := a.store.ChatSessionExists(r.Context(), sessionID)
	if err != nil {
		a.logger.Printf("query chat session failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query chat session failed")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "chat session not found")
		return
	}

	messages, err := a.store.ListChatMessages(r.Context(), sessionID)
	if err != nil {
		a.logger.Printf("list chat messages failed: %v", err)
		writeError(w, http.StatusInternalServerError, "list chat messages failed")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"items": messages,
		"count": len(messages),
	})
}

func (a *API) handleCreateMessageStream(w http.ResponseWriter, r *http.Request) {
	sessionID := chi.URLParam(r, "sessionID")
	if _, err := uuid.Parse(sessionID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid sessionID")
		return
	}

	exists, err := a.store.ChatSessionExists(r.Context(), sessionID)
	if err != nil {
		a.logger.Printf("query chat session failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query chat session failed")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "chat session not found")
		return
	}

	var req struct {
		Question string `json:"question"`
		Scope    Scope  `json:"scope"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	req.Question = strings.TrimSpace(req.Question)
	if req.Question == "" {
		writeError(w, http.StatusBadRequest, "question is required")
		return
	}
	if len(req.Question) > 8000 {
		writeError(w, http.StatusBadRequest, "question too long, max 8000")
		return
	}
	if err := req.Scope.Validate(); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if statusCode, err := a.validateScopeResources(r.Context(), req.Scope); err != nil {
		writeError(w, statusCode, err.Error())
		return
	}

	scopeBytes, _ := json.Marshal(req.Scope)
	scopePayload := string(scopeBytes)

	// Save user message
	_, err = a.store.CreateChatMessage(r.Context(), sessionID, "user", req.Question, &scopePayload, nil, nil)
	if err != nil {
		a.logger.Printf("save user message failed: %v", err)
		writeError(w, http.StatusInternalServerError, "save user message failed")
		return
	}

	// Prepare request to python RAG
	payload := map[string]any{
		"question": req.Question,
		"scope":    req.Scope,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "encode rag request failed")
		return
	}

	url := strings.TrimRight(a.cfg.RAGServiceURL, "/") + "/v1/rag/query/stream"
	proxyReq, err := http.NewRequestWithContext(r.Context(), http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "create rag request failed")
		return
	}
	proxyReq.Header.Set("Content-Type", "application/json")
	proxyReq.Header.Set("Accept", "text/event-stream")

	resp, err := a.httpClient.Do(proxyReq)
	if err != nil {
		// Fallback for network error
		a.logger.Printf("proxy to rag stream failed: %v", err)
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(map[string]any{"error": "rag service proxy failed"})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		a.logger.Printf("rag stream backend returned %d: %s", resp.StatusCode, string(raw))
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(map[string]any{"error": "rag service returned error status"})
		return
	}

	// Headers for SSE
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, "streaming not supported")
		return
	}

	// Read stream, tee it out, collect full response for DB
	scanner := bufio.NewScanner(resp.Body)
	var answerSentences []AnswerSentence
	var citations []Citation

	for scanner.Scan() {
		line := scanner.Text()
		fmt.Fprintf(w, "%s\n", line)
		if strings.HasPrefix(line, "data: ") {
			dataRaw := strings.TrimPrefix(line, "data: ")
			var event struct {
				Type string          `json:"type"`
				Data json.RawMessage `json:"data"`
			}
			if err := json.Unmarshal([]byte(dataRaw), &event); err == nil {
				if event.Type == "sentence" {
					var snt AnswerSentence
					if err := json.Unmarshal(event.Data, &snt); err == nil {
						answerSentences = append(answerSentences, snt)
					}
				} else if event.Type == "citation" {
					var cit Citation
					if err := json.Unmarshal(event.Data, &cit); err == nil {
						citations = append(citations, cit)
					}
				}
			}
		} else if line == "" {
			flusher.Flush()
		}
	}

	if err := scanner.Err(); err != nil {
		a.logger.Printf("read ssh stream failed: %v", err)
	}

	compAnswer := map[string]any{
		"answer_sentences": answerSentences,
		"citations":        citations,
	}
	compBytes, _ := json.Marshal(compAnswer)
	compPayload := string(compBytes)
	traceID := w.Header().Get("X-Request-Id")

	// Collect sentences into a single content block for easy viewing
	var textParts []string
	for _, s := range answerSentences {
		textParts = append(textParts, s.Text)
	}
	fullText := strings.Join(textParts, " ")

	_, err = a.store.CreateChatMessage(r.Context(), sessionID, "assistant", fullText, nil, &compPayload, &traceID)
	if err != nil {
		a.logger.Printf("save assistant message failed: %v", err)
	}
}

func (a *API) handleCreateFeedback(w http.ResponseWriter, r *http.Request) {
	messageID := chi.URLParam(r, "messageID")
	if _, err := uuid.Parse(messageID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid messageID")
		return
	}

	var req struct {
		Rating  int      `json:"rating"`
		Tags    []string `json:"tags"`
		Comment string   `json:"comment"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if req.Rating != 1 && req.Rating != -1 {
		writeError(w, http.StatusBadRequest, "rating must be 1 (upvote) or -1 (downvote)")
		return
	}

	if err := a.store.CreateAnswerFeedback(r.Context(), messageID, req.Rating, req.Tags, req.Comment); err != nil {
		a.logger.Printf("create feedback failed: %v", err)
		writeError(w, http.StatusInternalServerError, "create feedback failed")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]string{"message_id": messageID, "status": "recorded"})
}
