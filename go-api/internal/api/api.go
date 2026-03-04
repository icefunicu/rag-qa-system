package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"

	"rag-p/go-api/internal/auth"
	"rag-p/go-api/internal/config"
	"rag-p/go-api/internal/db"
)

type contextKey string

const claimsKey contextKey = "claims"

type API struct {
	cfg        config.Config
	store      *db.Store
	auth       *auth.Manager
	httpClient *http.Client
	logger     *log.Logger
}

func New(cfg config.Config, store *db.Store, authManager *auth.Manager, logger *log.Logger) *API {
	return &API{
		cfg:   cfg,
		store: store,
		auth:  authManager,
		httpClient: &http.Client{
			Timeout: 15 * time.Second,
		},
		logger: logger,
	}
}

func (a *API) Router() http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(30 * time.Second))

	r.Get("/healthz", a.handleHealth)

	r.Route("/v1", func(r chi.Router) {
		r.Post("/auth/login", a.handleLogin)
		r.Group(func(r chi.Router) {
			r.Use(a.requireAuth)

			r.Post("/corpora", a.handleCreateCorpus)
			r.Get("/corpora", a.handleListCorpora)

			r.Post("/documents/upload", a.handleUploadDocument)
			r.Get("/ingest-jobs/{jobID}", a.handleGetIngestJob)

			r.Post("/chat/sessions", a.handleCreateSession)
			r.Post("/chat/sessions/{sessionID}/messages", a.handleCreateMessage)
		})
	})

	return r
}

func (a *API) requireAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" {
			writeError(w, http.StatusUnauthorized, "missing authorization header")
			return
		}
		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "bearer") {
			writeError(w, http.StatusUnauthorized, "invalid authorization format")
			return
		}

		claims, ok := a.auth.Validate(parts[1])
		if !ok {
			writeError(w, http.StatusUnauthorized, "invalid or expired token")
			return
		}

		ctx := context.WithValue(r.Context(), claimsKey, claims)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func mustClaims(ctx context.Context) auth.Claims {
	claims, _ := ctx.Value(claimsKey).(auth.Claims)
	return claims
}

func (a *API) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "go-api",
		"time":    time.Now().UTC().Format(time.RFC3339),
	})
}

func (a *API) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if strings.TrimSpace(req.Email) == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "email and password are required")
		return
	}

	token, claims, err := a.auth.Login(req.Email, req.Password)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "invalid email or password")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"access_token": token,
		"user":         claims,
		"token_type":   "Bearer",
		"expires_in":   int(a.cfg.AuthTokenTTL.Seconds()),
	})
}

func (a *API) handleCreateCorpus(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())
	if claims.Role != auth.RoleAdmin {
		writeError(w, http.StatusForbidden, "only admin can create corpus")
		return
	}

	var req struct {
		Name        string `json:"name"`
		Description string `json:"description"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if len(req.Name) > 128 {
		writeError(w, http.StatusBadRequest, "name too long, max 128")
		return
	}

	corpus, err := a.store.CreateCorpus(r.Context(), db.CreateCorpusInput{
		Name:        req.Name,
		Description: strings.TrimSpace(req.Description),
		OwnerUserID: claims.UserID,
	})
	if err != nil {
		a.logger.Printf("create corpus failed: %v", err)
		writeError(w, http.StatusInternalServerError, "create corpus failed")
		return
	}

	writeJSON(w, http.StatusCreated, corpus)
}

func (a *API) handleListCorpora(w http.ResponseWriter, r *http.Request) {
	corpora, err := a.store.ListCorpora(r.Context())
	if err != nil {
		a.logger.Printf("list corpora failed: %v", err)
		writeError(w, http.StatusInternalServerError, "list corpora failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": corpora,
		"count": len(corpora),
	})
}

func (a *API) handleUploadDocument(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())

	var req struct {
		CorpusID   string `json:"corpus_id"`
		FileName   string `json:"file_name"`
		FileType   string `json:"file_type"`
		SizeBytes  int64  `json:"size_bytes"`
		StorageKey string `json:"storage_key"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	req.CorpusID = strings.TrimSpace(req.CorpusID)
	req.FileName = strings.TrimSpace(req.FileName)
	req.FileType = strings.TrimSpace(strings.ToLower(req.FileType))
	req.StorageKey = strings.TrimSpace(req.StorageKey)

	if req.CorpusID == "" || req.FileName == "" || req.FileType == "" || req.StorageKey == "" {
		writeError(w, http.StatusBadRequest, "corpus_id, file_name, file_type, storage_key are required")
		return
	}
	if _, ok := a.cfg.AllowedFileTypes[req.FileType]; !ok {
		writeError(w, http.StatusBadRequest, "unsupported file_type, only txt/pdf/docx")
		return
	}
	if req.SizeBytes <= 0 || req.SizeBytes > a.cfg.MaxUploadBytes {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("size_bytes must be in (0, %d]", a.cfg.MaxUploadBytes))
		return
	}

	if _, err := uuid.Parse(req.CorpusID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid corpus_id")
		return
	}
	if _, err := uuid.Parse(claims.UserID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid user id in auth claims")
		return
	}

	exists, err := a.store.CorpusExists(r.Context(), req.CorpusID)
	if err != nil {
		a.logger.Printf("query corpus failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query corpus failed")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "corpus not found")
		return
	}

	documentID, job, err := a.store.CreateDocumentAndJob(r.Context(), db.CreateDocumentInput{
		CorpusID:   req.CorpusID,
		FileName:   req.FileName,
		FileType:   req.FileType,
		SizeBytes:  req.SizeBytes,
		StorageKey: req.StorageKey,
		CreatedBy:  claims.UserID,
	})
	if err != nil {
		a.logger.Printf("create document/job failed: %v", err)
		writeError(w, http.StatusInternalServerError, "create ingest job failed")
		return
	}

	writeJSON(w, http.StatusAccepted, map[string]any{
		"document_id": documentID,
		"job_id":      job.ID,
		"status":      job.Status,
		"message":     "metadata accepted; direct S3 upload pipeline will be completed in Phase 2",
	})
}

func (a *API) handleGetIngestJob(w http.ResponseWriter, r *http.Request) {
	jobID := chi.URLParam(r, "jobID")
	if _, err := uuid.Parse(jobID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid jobID")
		return
	}

	job, err := a.store.GetIngestJob(r.Context(), jobID)
	if err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "job not found")
			return
		}
		a.logger.Printf("query ingest job failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query ingest job failed")
		return
	}

	writeJSON(w, http.StatusOK, job)
}

func (a *API) handleCreateSession(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())

	var req struct {
		Title string `json:"title"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	req.Title = strings.TrimSpace(req.Title)
	if req.Title == "" {
		req.Title = "Untitled Session"
	}
	if len(req.Title) > 200 {
		writeError(w, http.StatusBadRequest, "title too long, max 200")
		return
	}

	session, err := a.store.CreateChatSession(r.Context(), req.Title, claims.UserID)
	if err != nil {
		a.logger.Printf("create chat session failed: %v", err)
		writeError(w, http.StatusInternalServerError, "create chat session failed")
		return
	}

	writeJSON(w, http.StatusCreated, session)
}

func (a *API) handleCreateMessage(w http.ResponseWriter, r *http.Request) {
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

	answerSentences, citations, queryErr := a.queryRAG(r.Context(), req.Question, req.Scope)
	if queryErr != nil {
		a.logger.Printf("rag query failed, fallback to placeholder: %v", queryErr)
		answerSentences = []AnswerSentence{
			{
				Text:         "非资料证据：当前 RAG 引擎暂未返回结果，请稍后重试或缩小资料范围。",
				EvidenceType: "common_knowledge",
				CitationIDs:  []string{},
				Confidence:   0.15,
			},
		}
		citations = []Citation{}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"session_id":             sessionID,
		"answer_sentences":       answerSentences,
		"citations":              citations,
		"allow_common_knowledge": req.Scope.AllowCommonKnowledge,
	})
}

func (a *API) queryRAG(ctx context.Context, question string, scope Scope) ([]AnswerSentence, []Citation, error) {
	payload := map[string]any{
		"question": question,
		"scope":    scope,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, nil, err
	}

	url := strings.TrimRight(a.cfg.RAGServiceURL, "/") + "/v1/rag/query"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := a.httpClient.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, nil, fmt.Errorf("rag service returned status=%d body=%s", resp.StatusCode, string(raw))
	}

	var ragResp struct {
		AnswerSentences []AnswerSentence `json:"answer_sentences"`
		Citations       []Citation       `json:"citations"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&ragResp); err != nil {
		return nil, nil, err
	}
	return ragResp.AnswerSentences, ragResp.Citations, nil
}

func decodeJSONBody(r *http.Request, out any) error {
	if r.Body == nil {
		return errors.New("request body is required")
	}
	limited := io.LimitReader(r.Body, 1<<20)
	defer r.Body.Close()

	decoder := json.NewDecoder(limited)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(out); err != nil {
		return err
	}
	return nil
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]any{
		"error": message,
	})
}
