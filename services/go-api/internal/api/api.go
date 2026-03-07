package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"rag-p/go-api/internal/auth"
	"rag-p/go-api/internal/config"
	"rag-p/go-api/internal/db"
	"rag-p/go-api/internal/queue"
	"rag-p/go-api/internal/storage"
)

type contextKey string

const claimsKey contextKey = "contextKey"
const commonKnowledgePrefix = "【常识补充】"

type API struct {
	cfg        config.Config
	store      *db.Store
	auth       *auth.Manager
	publisher  *queue.Publisher
	s3         *storage.S3Client
	httpClient *http.Client
	logger     *log.Logger
	rdb        *redis.Client
}

func New(cfg config.Config, store *db.Store, authManager *auth.Manager, rdb *redis.Client, logger *log.Logger) (*API, error) {
	publisher, err := queue.NewPublisher(cfg.RedisURL, cfg.IngestQueueKey)
	if err != nil {
		return nil, err
	}

	s3Client, err := storage.NewS3Client(
		cfg.S3Endpoint,
		cfg.S3PublicEndpoint,
		cfg.S3AccessKey,
		cfg.S3SecretKey,
		cfg.S3Bucket,
		cfg.S3UseSSL,
		cfg.S3PresignExpiryMinute,
	)
	if err != nil {
		_ = publisher.Close()
		return nil, err
	}

	return &API{
		cfg:       cfg,
		store:     store,
		auth:      authManager,
		publisher: publisher,
		s3:        s3Client,
		rdb:       rdb,
		httpClient: &http.Client{
			Timeout: 15 * time.Second,
		},
		logger: logger,
	}, nil
}

func (a *API) Close() {
	if a.publisher != nil {
		_ = a.publisher.Close()
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
			r.Post("/corpora/batch-delete", a.handleBatchDeleteCorpora)
			r.Delete("/corpora/{corpusID}", a.handleDeleteCorpus)
			r.Get("/corpora/{corpusID}/documents", a.handleListCorpusDocuments)
			r.Get("/documents/{documentID}", a.handleGetDocumentDetail)
			r.Get("/documents/{documentID}/events", a.handleListDocumentEvents)
			r.Get("/documents/{documentID}/preview", a.handleGetDocumentPreview)
			r.Delete("/documents/{documentID}", a.handleDeleteDocument)
			r.Put("/documents/{documentID}/content", a.handleUpdateDocumentContent)

			r.Post("/documents/upload-url", a.handleCreateUploadURL)
			r.Post("/documents/upload", a.handleUploadDocument)
			r.Get("/ingest-jobs/{jobID}", a.handleGetIngestJob)
			r.Post("/ingest-jobs/{jobID}/cancel", a.handleCancelIngestJob)

			r.Post("/documents/batch-delete", a.handleBatchDeleteDocuments)

			r.Group(func(r chi.Router) {
				r.Use(a.requireAdmin)
				r.Get("/admin/logs", a.handleAdminLogs)
			})

			r.Post("/chat/sessions", a.handleCreateSession)
			r.Get("/chat/sessions", a.handleListSessions)
			r.Post("/chat/sessions/{sessionID}/messages", a.handleCreateMessage)
			r.Get("/chat/sessions/{sessionID}/messages", a.handleListMessages)
			r.Post("/chat/sessions/{sessionID}/messages/stream", a.handleCreateMessageStream)
			r.Post("/chat/messages/{messageID}/feedback", a.handleCreateFeedback)
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

		claims, ok := a.auth.Validate(r.Context(), parts[1])
		if !ok {
			writeError(w, http.StatusUnauthorized, "invalid or expired token")
			return
		}

		ctx := context.WithValue(r.Context(), claimsKey, claims)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func (a *API) requireAdmin(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		claims, ok := r.Context().Value(claimsKey).(auth.Claims)
		if !ok || claims.Role != auth.RoleAdmin {
			writeError(w, http.StatusForbidden, "admin access required")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func mustClaims(ctx context.Context) auth.Claims {
	claims, _ := ctx.Value(claimsKey).(auth.Claims)
	return claims
}

func (a *API) handleHealth(w http.ResponseWriter, r *http.Request) {
	if r.URL.Query().Get("depth") != "full" {
		writeJSON(w, http.StatusOK, map[string]any{
			"status":  "ok",
			"service": "go-api",
			"time":    time.Now().UTC().Format(time.RFC3339),
		})
		return
	}

	checks := make(map[string]any)
	degradedServices := make([]string, 0, 3)
	suggestions := make([]string, 0, 3)
	overallStatus := "ok"
	checkClient := &http.Client{Timeout: 2 * time.Second}
	checkCtx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	dbStatus := "ok"
	if err := a.store.DB().PingContext(checkCtx); err != nil {
		dbStatus = "unhealthy"
		overallStatus = "unhealthy"
		suggestions = append(suggestions, "Check PostgreSQL availability and connection pool saturation.")
		a.logger.Printf("[health] postgres ping failed: %v", err)
	}
	checks["postgres"] = dbStatus

	redisStatus := "ok"
	if a.publisher != nil {
		if err := a.publisher.Client().Ping(checkCtx).Err(); err != nil {
			redisStatus = "unhealthy"
			if overallStatus != "unhealthy" {
				overallStatus = "degraded"
			}
			degradedServices = append(degradedServices, "redis")
			suggestions = append(suggestions, "Check Redis queue connectivity before ingest traffic increases.")
			a.logger.Printf("[health] redis ping failed: %v", err)
		}
	}
	checks["redis"] = redisStatus

	ragStatus := "ok"
	ragURL := strings.TrimRight(a.cfg.RAGServiceURL, "/") + "/healthz?depth=full"
	resp, err := func() (*http.Response, error) {
		req, reqErr := http.NewRequestWithContext(checkCtx, http.MethodGet, ragURL, nil)
		if reqErr != nil {
			return nil, reqErr
		}
		return checkClient.Do(req)
	}()
	if err != nil {
		ragStatus = "unhealthy"
		if overallStatus == "ok" {
			overallStatus = "degraded"
		}
		degradedServices = append(degradedServices, "rag_service")
		suggestions = append(suggestions, "Verify py-rag-service health and upstream model provider availability.")
		a.logger.Printf("[health] rag service check failed: %v", err)
	} else if resp.StatusCode != http.StatusOK {
		ragStatus = "unhealthy"
		if overallStatus == "ok" {
			overallStatus = "degraded"
		}
		degradedServices = append(degradedServices, "rag_service")
		suggestions = append(suggestions, "Verify py-rag-service health and upstream model provider availability.")
		a.logger.Printf("[health] rag service returned status=%d", resp.StatusCode)
		resp.Body.Close()
	} else {
		var ragPayload struct {
			Status string `json:"status"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&ragPayload); err != nil {
			ragStatus = "unhealthy"
			if overallStatus == "ok" {
				overallStatus = "degraded"
			}
			degradedServices = append(degradedServices, "rag_service")
			suggestions = append(suggestions, "Inspect py-rag-service /healthz response payload.")
			a.logger.Printf("[health] rag service decode failed: %v", err)
		} else if ragPayload.Status != "" && ragPayload.Status != "ok" {
			ragStatus = ragPayload.Status
			if overallStatus == "ok" {
				overallStatus = "degraded"
			}
			degradedServices = append(degradedServices, "rag_service")
		}
		resp.Body.Close()
	}
	checks["rag_service"] = ragStatus

	qdrantStatus := "ok"
	qdrantURL := strings.TrimRight(a.cfg.QdrantURL, "/") + "/healthz"
	resp, err = func() (*http.Response, error) {
		req, reqErr := http.NewRequestWithContext(checkCtx, http.MethodGet, qdrantURL, nil)
		if reqErr != nil {
			return nil, reqErr
		}
		return checkClient.Do(req)
	}()
	if err != nil || resp.StatusCode != http.StatusOK {
		qdrantStatus = "unhealthy"
		if overallStatus == "ok" {
			overallStatus = "degraded"
		}
		degradedServices = append(degradedServices, "qdrant")
		suggestions = append(suggestions, "Check Qdrant availability or switch query traffic to degraded mode.")
		a.logger.Printf("[health] qdrant check failed: %v", err)
		if resp != nil && resp.Body != nil {
			resp.Body.Close()
		}
	} else {
		resp.Body.Close()
	}
	checks["qdrant"] = qdrantStatus

	response := map[string]any{
		"status":  overallStatus,
		"service": "go-api",
		"time":    time.Now().UTC().Format(time.RFC3339),
		"checks":  checks,
	}
	if len(degradedServices) > 0 {
		response["degraded"] = degradedServices
	}
	if len(suggestions) > 0 {
		response["suggestions"] = suggestions
	}

	statusCode := http.StatusOK
	if overallStatus == "unhealthy" {
		statusCode = http.StatusServiceUnavailable
	}

	writeJSON(w, statusCode, response)
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

	email := strings.TrimSpace(strings.ToLower(req.Email))
	var claims auth.Claims
	var isValid bool

	if email == strings.ToLower(a.cfg.AdminEmail) && req.Password == a.cfg.AdminPassword {
		claims = auth.Claims{UserID: a.cfg.AdminUserID, Role: auth.RoleAdmin, Email: a.cfg.AdminEmail}
		isValid = true
	} else if email == strings.ToLower(a.cfg.MemberEmail) && req.Password == a.cfg.MemberPassword {
		claims = auth.Claims{UserID: a.cfg.MemberUserID, Role: auth.RoleMember, Email: a.cfg.MemberEmail}
		isValid = true
	}

	if !isValid {
		writeError(w, http.StatusUnauthorized, "invalid email or password")
		return
	}

	token, err := a.auth.CreateToken(r.Context(), claims)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to create session token")
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

func (a *API) handleDeleteCorpus(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())
	if claims.Role != auth.RoleAdmin {
		writeError(w, http.StatusForbidden, "only admin can delete corpus")
		return
	}

	corpusID := strings.TrimSpace(chi.URLParam(r, "corpusID"))
	if _, err := uuid.Parse(corpusID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid corpusID")
		return
	}

	exists, err := a.store.CorpusExists(r.Context(), corpusID)
	if err != nil {
		a.logger.Printf("query corpus failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query corpus failed")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "corpus not found")
		return
	}

	storageKeys, err := a.store.ListStorageKeysByCorpus(r.Context(), corpusID)
	if err != nil {
		a.logger.Printf("list corpus storage keys failed: %v", err)
		writeError(w, http.StatusInternalServerError, "list corpus resources failed")
		return
	}

	if err := a.purgeCorpusVectors(r.Context(), corpusID); err != nil {
		a.logger.Printf("purge corpus qdrant points failed: %v", err)
		writeError(w, http.StatusInternalServerError, "purge vector resources failed")
		return
	}
	if err := a.s3.RemoveObjects(r.Context(), storageKeys); err != nil {
		a.logger.Printf("purge corpus objects failed: %v", err)
		writeError(w, http.StatusInternalServerError, "purge object resources failed")
		return
	}

	deleted, err := a.store.DeleteCorpus(r.Context(), corpusID)
	if err != nil {
		a.logger.Printf("delete corpus failed: %v", err)
		writeError(w, http.StatusInternalServerError, "delete corpus failed")
		return
	}
	if !deleted {
		writeError(w, http.StatusNotFound, "corpus not found")
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (a *API) handleBatchDeleteCorpora(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())
	if claims.Role != auth.RoleAdmin {
		writeError(w, http.StatusForbidden, "only admin can delete corpus")
		return
	}

	var req struct {
		CorpusIDs []string `json:"corpus_ids"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	normalized, err := normalizeCorpusIDs(req.CorpusIDs)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if len(normalized) > 100 {
		writeError(w, http.StatusBadRequest, "corpus_ids too many, max 100")
		return
	}

	existing, err := a.store.CountCorporaByIDs(r.Context(), normalized)
	if err != nil {
		a.logger.Printf("count batch delete corpora failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query corpus failed")
		return
	}
	if existing != len(normalized) {
		writeError(w, http.StatusBadRequest, "corpus_ids contains non-existent corpus_id")
		return
	}

	storageKeys, err := a.store.ListStorageKeysByCorpora(r.Context(), normalized)
	if err != nil {
		a.logger.Printf("list corpora storage keys failed: %v", err)
		writeError(w, http.StatusInternalServerError, "list corpus resources failed")
		return
	}
	for _, corpusID := range normalized {
		if err := a.purgeCorpusVectors(r.Context(), corpusID); err != nil {
			a.logger.Printf("purge corpus qdrant points failed: corpus=%s err=%v", corpusID, err)
			writeError(w, http.StatusInternalServerError, "purge vector resources failed")
			return
		}
	}
	if err := a.s3.RemoveObjects(r.Context(), storageKeys); err != nil {
		a.logger.Printf("purge corpora objects failed: %v", err)
		writeError(w, http.StatusInternalServerError, "purge object resources failed")
		return
	}

	deletedCount, err := a.store.DeleteCorpora(r.Context(), normalized)
	if err != nil {
		a.logger.Printf("batch delete corpora failed: %v", err)
		writeError(w, http.StatusInternalServerError, "batch delete corpus failed")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"deleted_count": deletedCount,
	})
}

func (a *API) handleListCorpusDocuments(w http.ResponseWriter, r *http.Request) {
	corpusID := strings.TrimSpace(chi.URLParam(r, "corpusID"))
	if _, err := uuid.Parse(corpusID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid corpusID")
		return
	}

	exists, err := a.store.CorpusExists(r.Context(), corpusID)
	if err != nil {
		a.logger.Printf("query corpus failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query corpus failed")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "corpus not found")
		return
	}

	items, err := a.store.ListDocumentsByCorpus(r.Context(), corpusID)
	if err != nil {
		a.logger.Printf("list documents by corpus failed: %v", err)
		writeError(w, http.StatusInternalServerError, "list documents failed")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"items": items,
		"count": len(items),
	})
}

func (a *API) handleGetDocumentDetail(w http.ResponseWriter, r *http.Request) {
	documentID := strings.TrimSpace(chi.URLParam(r, "documentID"))
	if _, err := uuid.Parse(documentID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid documentID")
		return
	}

	item, err := a.store.GetDocumentByID(r.Context(), documentID)
	if err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "document not found")
			return
		}
		a.logger.Printf("query document detail failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query document detail failed")
		return
	}

	writeJSON(w, http.StatusOK, item)
}

func (a *API) handleListDocumentEvents(w http.ResponseWriter, r *http.Request) {
	documentID := strings.TrimSpace(chi.URLParam(r, "documentID"))
	if _, err := uuid.Parse(documentID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid documentID")
		return
	}

	if _, err := a.store.GetDocumentByID(r.Context(), documentID); err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "document not found")
			return
		}
		a.logger.Printf("query document detail failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query document detail failed")
		return
	}

	job, err := a.store.GetIngestJobByDocumentID(r.Context(), documentID)
	if err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeJSON(w, http.StatusOK, map[string]any{
				"items": []any{},
				"count": 0,
			})
			return
		}
		a.logger.Printf("query ingest job by document failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query ingest job failed")
		return
	}

	runtimeProgress, err := a.getRuntimeProgress(r.Context(), job.ID)
	if err != nil {
		a.logger.Printf("query runtime progress failed: jobID=%s err=%v", job.ID, err)
		runtimeProgress = nil
	}

	events, err := a.store.ListIngestEventsByJobID(r.Context(), job.ID)
	if err != nil {
		a.logger.Printf("list ingest events failed: jobID=%s err=%v", job.ID, err)
		writeError(w, http.StatusInternalServerError, "list ingest events failed")
		return
	}

	items := make([]map[string]any, 0, len(events)+1)
	for _, event := range events {
		item := map[string]any{
			"id":          event.ID,
			"document_id": documentID,
			"job_id":      event.JobID,
			"status":      event.Stage,
			"stage":       event.Stage,
			"created_at":  event.CreatedAt,
		}
		if event.Message != nil && strings.TrimSpace(*event.Message) != "" {
			item["message"] = *event.Message
		}
		items = append(items, item)
	}

	terminalStageExists := false
	for _, item := range items {
		status, _ := item["status"].(string)
		if status == job.Status {
			terminalStageExists = true
			break
		}
	}
	if job.ErrorMsg != "" || (!terminalStageExists && job.Status != "") {
		details := map[string]any{
			"progress": job.Progress,
		}
		if job.ErrorCategory != "" {
			details["error_category"] = job.ErrorCategory
		}
		if job.ErrorMsg != "" {
			details["error_message"] = job.ErrorMsg
		}

		item := map[string]any{
			"id":          job.ID + "-status",
			"document_id": documentID,
			"job_id":      job.ID,
			"status":      job.Status,
			"stage":       job.Status,
			"message":     strings.TrimSpace(job.ErrorMsg),
			"details":     details,
			"created_at":  job.UpdatedAt,
		}
		if item["message"] == "" {
			delete(item, "message")
		}
		items = append(items, item)
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"items":              items,
		"count":              len(items),
		"job_id":             job.ID,
		"job_status":         job.Status,
		"job_progress":       job.Progress,
		"job_error_message":  job.ErrorMsg,
		"job_error_category": job.ErrorCategory,
		"job_updated_at":     job.UpdatedAt,
		"job_runtime":        runtimeProgress,
	})
}

func (a *API) handleGetDocumentPreview(w http.ResponseWriter, r *http.Request) {
	documentID := strings.TrimSpace(chi.URLParam(r, "documentID"))
	if _, err := uuid.Parse(documentID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid documentID")
		return
	}

	claims := mustClaims(r.Context())
	startTime := time.Now()

	item, err := a.store.GetDocumentByID(r.Context(), documentID)
	if err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "document not found")
			return
		}
		a.logger.Printf("[preview] query document failed: documentID=%s user_id=%s err=%v", documentID, claims.UserID, err)
		writeError(w, http.StatusInternalServerError, "query document detail failed")
		return
	}

	a.logger.Printf("[preview] request: documentID=%s user_id=%s fileName=%s size=%d fileType=%s",
		documentID, claims.UserID, item.FileName, item.SizeBytes, item.FileType)

	if item.FileType == "txt" {
		previewLimit := a.cfg.MaxInlineTextBytes
		previewMode := "text"
		editable := true
		if item.SizeBytes > a.cfg.MaxInlineTextBytes {
			previewLimit = a.cfg.MaxPartialLoadBytes
			previewMode = "partial"
			editable = false
		}

		s3Start := time.Now()
		textResult, err := a.s3.ReadObjectText(r.Context(), item.StorageKey, previewLimit, previewMode == "partial")
		s3Duration := time.Since(s3Start)

		if err != nil {
			if errors.Is(err, storage.ErrObjectTooLarge) {
				a.logger.Printf("[preview] txt_too_large: documentID=%s user_id=%s size=%d limit=%d s3_ms=%d",
					documentID, claims.UserID, item.SizeBytes, previewLimit, s3Duration.Milliseconds())
				writeError(w, http.StatusRequestEntityTooLarge, fmt.Sprintf("txt content too large for preview, max %d bytes", previewLimit))
				return
			}
			a.logger.Printf("[preview] read_failed: documentID=%s user_id=%s err=%v s3_ms=%d",
				documentID, claims.UserID, err, s3Duration.Milliseconds())
			writeError(w, http.StatusInternalServerError, "read document content failed")
			return
		}

		warning := ""
		if previewMode == "partial" {
			if textResult.Truncated {
				warning = fmt.Sprintf(
					"File size (%d bytes) exceeds preview limit (%d bytes). Only showing the first %d bytes decoded as UTF-8.",
					item.SizeBytes,
					a.cfg.MaxPartialLoadBytes,
					a.cfg.MaxPartialLoadBytes,
				)
			} else {
				warning = fmt.Sprintf(
					"File size (%d bytes) exceeds inline edit limit (%d bytes). Preview is read-only.",
					item.SizeBytes,
					a.cfg.MaxInlineTextBytes,
				)
			}
		}

		a.logger.Printf("[preview] txt_%s: documentID=%s user_id=%s size=%d encoding=%s truncated=%t s3_ms=%d total_ms=%d",
			previewMode, documentID, claims.UserID, item.SizeBytes, textResult.Encoding, textResult.Truncated, s3Duration.Milliseconds(), time.Since(startTime).Milliseconds())
		writeJSON(w, http.StatusOK, map[string]any{
			"document":           item,
			"preview_mode":       previewMode,
			"editable":           editable,
			"text":               textResult.Text,
			"content_type":       "text/plain; charset=utf-8",
			"detected_encoding":  textResult.Encoding,
			"truncated":          textResult.Truncated,
			"max_inline_bytes":   a.cfg.MaxInlineTextBytes,
			"max_partial_bytes":  a.cfg.MaxPartialLoadBytes,
			"warning":            warning,
			"expires_in_seconds": 0,
		})
		return
	}

	s3Start := time.Now()
	viewURL, err := a.s3.NewDownloadURL(r.Context(), item.StorageKey)
	s3Duration := time.Since(s3Start)

	if err != nil {
		a.logger.Printf("[preview] url_creation_failed: documentID=%s user_id=%s err=%v s3_ms=%d",
			documentID, claims.UserID, err, s3Duration.Milliseconds())
		writeError(w, http.StatusInternalServerError, "create document preview url failed")
		return
	}

	a.logger.Printf("[preview] url_served: documentID=%s user_id=%s size=%d fileType=%s s3_ms=%d total_ms=%d",
		documentID, claims.UserID, item.SizeBytes, item.FileType, s3Duration.Milliseconds(), time.Since(startTime).Milliseconds())
	writeJSON(w, http.StatusOK, map[string]any{
		"document":           item,
		"preview_mode":       "url",
		"editable":           false,
		"view_url":           viewURL,
		"content_type":       contentTypeByFileType(item.FileType),
		"expires_in_seconds": a.cfg.S3PresignExpiryMinute * 60,
	})
}

func (a *API) handleUpdateDocumentContent(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Content string `json:"content"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	documentID := strings.TrimSpace(chi.URLParam(r, "documentID"))
	if _, err := uuid.Parse(documentID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid documentID")
		return
	}

	item, err := a.store.GetDocumentByID(r.Context(), documentID)
	if err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "document not found")
			return
		}
		a.logger.Printf("query document detail failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query document detail failed")
		return
	}

	if item.FileType != "txt" {
		writeError(w, http.StatusBadRequest, "only txt document supports online edit")
		return
	}
	if item.SizeBytes > a.cfg.MaxInlineTextBytes {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("document too large for online edit, max %d bytes", a.cfg.MaxInlineTextBytes))
		return
	}

	content := req.Content
	if strings.TrimSpace(content) == "" {
		writeError(w, http.StatusBadRequest, "content is required")
		return
	}

	contentBytes := int64(len([]byte(content)))
	if contentBytes > a.cfg.MaxInlineTextBytes {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("content too large for online edit, max %d bytes", a.cfg.MaxInlineTextBytes))
		return
	}

	if hasActiveJob, err := a.store.HasActiveIngestJob(r.Context(), documentID); err != nil {
		a.logger.Printf("query ingest job status failed: %v", err)
		writeError(w, http.StatusInternalServerError, "query ingest job status failed")
		return
	} else if hasActiveJob {
		writeError(w, http.StatusConflict, "document ingest is in progress, try later")
		return
	}

	previousText, err := a.s3.ReadObjectText(r.Context(), item.StorageKey, a.cfg.MaxInlineTextBytes, false)
	if err != nil {
		a.logger.Printf("read previous document content failed: %v", err)
		writeError(w, http.StatusInternalServerError, "read previous document content failed")
		return
	}

	sizeBytes, err := a.s3.PutObjectText(r.Context(), item.StorageKey, content)
	if err != nil {
		a.logger.Printf("update document object in S3 failed: %v", err)
		writeError(w, http.StatusInternalServerError, "update storage object failed")
		return
	}

	contentHash := hashTextContent(content)
	job, err := a.store.CreateReingestJobForDocument(r.Context(), documentID, int64(len([]byte(content))), contentHash, item.StorageKey)
	if err != nil {
		a.logger.Printf("create reingest job with version failed: %v", err)
		if _, restoreErr := a.s3.PutObjectText(r.Context(), item.StorageKey, previousText.Text); restoreErr != nil {
			a.logger.Printf("restore previous document content failed after db rollback: %v", restoreErr)
		}
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "document not found")
			return
		}
		writeError(w, http.StatusInternalServerError, "create reingest job failed")
		return
	}

	if err := a.publisher.PublishIngestJob(r.Context(), job.ID); err != nil {
		a.logger.Printf("enqueue reingest job failed: %v", err)
		_ = a.store.MarkIngestJobFailed(r.Context(), job.ID, documentID, "enqueue ingest job failed")
		writeError(w, http.StatusServiceUnavailable, "enqueue ingest job failed")
		return
	}

	writeJSON(w, http.StatusAccepted, map[string]any{
		"document_id": documentID,
		"job_id":      job.ID,
		"status":      "queued",
		"message":     "document content updated and queued for re-indexing",
		"size_bytes":  sizeBytes,
	})
}

func (a *API) handleCreateUploadURL(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())

	var req struct {
		CorpusID  string `json:"corpus_id"`
		FileName  string `json:"file_name"`
		FileType  string `json:"file_type"`
		SizeBytes int64  `json:"size_bytes"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	req.CorpusID = strings.TrimSpace(req.CorpusID)
	req.FileName = strings.TrimSpace(req.FileName)
	req.FileType = strings.ToLower(strings.TrimSpace(req.FileType))

	if req.CorpusID == "" || req.FileName == "" || req.FileType == "" {
		writeError(w, http.StatusBadRequest, "corpus_id, file_name, file_type are required")
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

	upload, err := a.s3.NewUploadURL(r.Context(), claims.UserID, req.CorpusID, req.FileName, req.FileType)
	if err != nil {
		a.logger.Printf("create upload url failed: %v", err)
		writeError(w, http.StatusInternalServerError, "create upload url failed")
		return
	}

	writeJSON(w, http.StatusOK, upload)
}

func (a *API) handleUploadDocument(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())

	var req struct {
		CorpusID        string `json:"corpus_id"`
		FileName        string `json:"file_name"`
		FileType        string `json:"file_type"`
		SizeBytes       int64  `json:"size_bytes"`
		StorageKey      string `json:"storage_key"`
		ContentHash     string `json:"content_hash"`
		DuplicatePolicy string `json:"duplicate_policy"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		a.logger.Printf("[upload] decode_request_failed: user_id=%s err=%v", claims.UserID, err)
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	req.CorpusID = strings.TrimSpace(req.CorpusID)
	req.FileName = strings.TrimSpace(req.FileName)
	req.FileType = strings.TrimSpace(strings.ToLower(req.FileType))
	req.StorageKey = strings.TrimSpace(req.StorageKey)
	req.ContentHash = strings.TrimSpace(req.ContentHash)
	req.DuplicatePolicy = strings.TrimSpace(strings.ToLower(req.DuplicatePolicy))

	// 默认策略为 new_version
	if req.DuplicatePolicy == "" {
		req.DuplicatePolicy = "new_version"
	}
	validPolicies := map[string]bool{"reject": true, "reuse_index": true, "new_version": true}
	if !validPolicies[req.DuplicatePolicy] {
		writeError(w, http.StatusBadRequest, "duplicate_policy must be reject, reuse_index, or new_version")
		return
	}

	a.logger.Printf("[upload] request: user_id=%s corpusID=%s fileName=%s fileType=%s size=%d storageKey=%s contentHash=%s dupPolicy=%s",
		claims.UserID, req.CorpusID, req.FileName, req.FileType, req.SizeBytes, req.StorageKey, req.ContentHash, req.DuplicatePolicy)

	if req.CorpusID == "" || req.FileName == "" || req.FileType == "" || req.StorageKey == "" {
		a.logger.Printf("[upload] validation_failed: user_id=%s reason=missing_required_fields", claims.UserID)
		writeError(w, http.StatusBadRequest, "corpus_id, file_name, file_type, storage_key are required")
		return
	}
	if _, ok := a.cfg.AllowedFileTypes[req.FileType]; !ok {
		a.logger.Printf("[upload] validation_failed: user_id=%s reason=unsupported_filetype fileType=%s", claims.UserID, req.FileType)
		writeError(w, http.StatusBadRequest, "unsupported file_type, only txt/pdf/docx")
		return
	}
	if req.SizeBytes <= 0 || req.SizeBytes > a.cfg.MaxUploadBytes {
		a.logger.Printf("[upload] validation_failed: user_id=%s reason=invalid_size size=%d max=%d",
			claims.UserID, req.SizeBytes, a.cfg.MaxUploadBytes)
		writeError(w, http.StatusBadRequest, fmt.Sprintf("size_bytes must be in (0, %d]", a.cfg.MaxUploadBytes))
		return
	}

	if _, err := uuid.Parse(req.CorpusID); err != nil {
		a.logger.Printf("[upload] validation_failed: user_id=%s reason=invalid_corpus_id corpusID=%s", claims.UserID, req.CorpusID)
		writeError(w, http.StatusBadRequest, "invalid corpus_id")
		return
	}
	if _, err := uuid.Parse(claims.UserID); err != nil {
		a.logger.Printf("[upload] validation_failed: user_id=%s reason=invalid_user_id_in_claims", claims.UserID)
		writeError(w, http.StatusBadRequest, "invalid user id in auth claims")
		return
	}

	exists, err := a.store.CorpusExists(r.Context(), req.CorpusID)
	if err != nil {
		a.logger.Printf("[upload] corpus_check_failed: user_id=%s corpusID=%s err=%v", claims.UserID, req.CorpusID, err)
		writeError(w, http.StatusInternalServerError, "query corpus failed")
		return
	}
	if !exists {
		a.logger.Printf("[upload] validation_failed: user_id=%s reason=corpus_not_found corpusID=%s", claims.UserID, req.CorpusID)
		writeError(w, http.StatusNotFound, "corpus not found")
		return
	}

	objectExists, err := a.s3.ObjectExists(r.Context(), req.StorageKey)
	if err != nil {
		a.logger.Printf("[upload] s3_check_failed: user_id=%s storageKey=%s err=%v", claims.UserID, req.StorageKey, err)
		writeError(w, http.StatusInternalServerError, "validate uploaded object failed")
		return
	}
	if !objectExists {
		a.logger.Printf("[upload] validation_failed: user_id=%s reason=object_not_found storageKey=%s", claims.UserID, req.StorageKey)
		writeError(w, http.StatusBadRequest, "object not found in S3 bucket, upload file first")
		return
	}

	// ── 幂等保护：同一 storage_key 不重复创建 ──
	existingDocID, err := a.store.GetDocumentByStorageKey(r.Context(), req.StorageKey)
	if err == nil && existingDocID != "" {
		a.logger.Printf("[upload] idempotent_hit: user_id=%s documentID=%s storageKey=%s", claims.UserID, existingDocID, req.StorageKey)
		job, err := a.store.GetIngestJobByDocumentID(r.Context(), existingDocID)
		if err == nil {
			writeJSON(w, http.StatusAccepted, map[string]any{
				"document_id":      existingDocID,
				"job_id":           job.ID,
				"status":           "queued",
				"duplicate_policy": "idempotent",
				"message":          "document metadata already accepted",
			})
			return
		}
	}

	// ── 内容去重：按 content_hash 检查是否已有相同内容 ──
	if req.ContentHash != "" {
		dupDocID, dupErr := a.store.FindDocumentByContentHash(r.Context(), req.CorpusID, req.ContentHash)
		if dupErr == nil && dupDocID != "" {
			switch req.DuplicatePolicy {
			case "reject":
				a.logger.Printf("[upload] duplicate_rejected: user_id=%s corpusID=%s contentHash=%s existingDocID=%s",
					claims.UserID, req.CorpusID, req.ContentHash, dupDocID)
				writeJSON(w, http.StatusConflict, map[string]any{
					"error":            "duplicate content detected",
					"existing_doc_id":  dupDocID,
					"duplicate_policy": "reject",
					"content_hash":     req.ContentHash,
				})
				return

			case "reuse_index":
				a.logger.Printf("[upload] duplicate_reused: user_id=%s corpusID=%s contentHash=%s existingDocID=%s",
					claims.UserID, req.CorpusID, req.ContentHash, dupDocID)
				job, jobErr := a.store.GetIngestJobByDocumentID(r.Context(), dupDocID)
				jobStatus := "unknown"
				jobID := ""
				if jobErr == nil {
					jobStatus = job.Status
					jobID = job.ID
				}
				writeJSON(w, http.StatusOK, map[string]any{
					"document_id":      dupDocID,
					"job_id":           jobID,
					"status":           jobStatus,
					"duplicate_policy": "reuse_index",
					"content_hash":     req.ContentHash,
					"message":          "identical content already indexed, reusing existing document",
				})
				return

			case "new_version":
				// 继续走正常创建流程，但会额外记录版本
				a.logger.Printf("[upload] duplicate_new_version: user_id=%s corpusID=%s contentHash=%s existingDocID=%s",
					claims.UserID, req.CorpusID, req.ContentHash, dupDocID)
			}
		}
	}

	startTime := time.Now()
	documentID, job, err := a.store.CreateDocumentAndJob(r.Context(), db.CreateDocumentInput{
		CorpusID:    req.CorpusID,
		FileName:    req.FileName,
		FileType:    req.FileType,
		SizeBytes:   req.SizeBytes,
		StorageKey:  req.StorageKey,
		ContentHash: req.ContentHash,
		CreatedBy:   claims.UserID,
	})
	dbDuration := time.Since(startTime)

	if err != nil {
		a.logger.Printf("[upload] create_document_job_failed: user_id=%s fileName=%s size=%d err=%v db_ms=%d",
			claims.UserID, req.FileName, req.SizeBytes, err, dbDuration.Milliseconds())
		writeError(w, http.StatusInternalServerError, "create ingest job failed")
		return
	}
	a.logger.Printf("[upload] document_created: user_id=%s documentID=%s jobID=%s db_ms=%d",
		claims.UserID, documentID, job.ID, dbDuration.Milliseconds())

	publishStart := time.Now()
	if err := a.publisher.PublishIngestJob(r.Context(), job.ID); err != nil {
		a.logger.Printf("[upload] enqueue_failed: user_id=%s documentID=%s jobID=%s err=%v publish_ms=%d",
			claims.UserID, documentID, job.ID, err, time.Since(publishStart).Milliseconds())
		_ = a.store.MarkIngestJobFailed(r.Context(), job.ID, documentID, "enqueue ingest job failed")
		writeError(w, http.StatusServiceUnavailable, "enqueue ingest job failed")
		return
	}
	publishDuration := time.Since(publishStart)

	totalDuration := time.Since(startTime)
	a.logger.Printf("[upload] completed: user_id=%s documentID=%s jobID=%s fileName=%s size=%d db_ms=%d publish_ms=%d total_ms=%d status=queued dupPolicy=%s",
		claims.UserID, documentID, job.ID, req.FileName, req.SizeBytes,
		dbDuration.Milliseconds(), publishDuration.Milliseconds(), totalDuration.Milliseconds(), req.DuplicatePolicy)

	writeJSON(w, http.StatusAccepted, map[string]any{
		"document_id":      documentID,
		"job_id":           job.ID,
		"status":           "queued",
		"duplicate_policy": req.DuplicatePolicy,
		"message":          "document metadata accepted and queued for indexing",
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

	runtimeProgress, err := a.getRuntimeProgress(r.Context(), job.ID)
	if err != nil {
		a.logger.Printf("query runtime progress failed: jobID=%s err=%v", job.ID, err)
		runtimeProgress = nil
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":               job.ID,
		"document_id":      job.DocumentID,
		"status":           job.Status,
		"progress":         job.Progress,
		"error_message":    job.ErrorMsg,
		"error_category":   job.ErrorCategory,
		"created_at":       job.CreatedAt,
		"updated_at":       job.UpdatedAt,
		"runtime_progress": runtimeProgress,
	})
}

// handleCancelIngestJob 取消进行中的 ingest job 并清理已产生的垃圾资源
func (a *API) handleCancelIngestJob(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())

	jobID := strings.TrimSpace(chi.URLParam(r, "jobID"))
	if _, err := uuid.Parse(jobID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid jobID")
		return
	}

	a.logger.Printf("[cancel] request: jobID=%s user_id=%s role=%s", jobID, claims.UserID, claims.Role)

	// 将 job 标记为 cancelled（事务内同时更新 document 状态和写入 event）
	documentID, previousStatus, err := a.store.CancelIngestJob(r.Context(), jobID)
	if err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "job not found")
			return
		}
		if strings.Contains(err.Error(), "only queued or running") {
			writeError(w, http.StatusConflict, err.Error())
			return
		}
		a.logger.Printf("[cancel] cancel job failed: jobID=%s err=%v", jobID, err)
		writeError(w, http.StatusInternalServerError, "cancel job failed")
		return
	}

	a.logger.Printf("[cancel] job cancelled: jobID=%s documentID=%s previousStatus=%s", jobID, documentID, previousStatus)

	// 异步清理垃圾资源（Qdrant 向量 + S3 文件），不阻塞响应
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()

		// 清理 Qdrant 中该文档的向量点
		if err := a.purgeDocumentVectors(ctx, documentID); err != nil {
			a.logger.Printf("[cancel] cleanup: purge qdrant failed: jobID=%s documentID=%s err=%v", jobID, documentID, err)
		} else {
			a.logger.Printf("[cancel] cleanup: qdrant purged: jobID=%s documentID=%s", jobID, documentID)
		}

		// 清理 S3 中的原始文件
		doc, err := a.store.GetDocumentByID(ctx, documentID)
		if err != nil {
			a.logger.Printf("[cancel] cleanup: get document failed: jobID=%s documentID=%s err=%v", jobID, documentID, err)
			return
		}
		if strings.TrimSpace(doc.StorageKey) != "" {
			if err := a.s3.RemoveObject(ctx, doc.StorageKey); err != nil {
				a.logger.Printf("[cancel] cleanup: remove s3 object failed: jobID=%s storageKey=%s err=%v", jobID, doc.StorageKey, err)
			} else {
				a.logger.Printf("[cancel] cleanup: s3 object removed: jobID=%s storageKey=%s", jobID, doc.StorageKey)
			}
		}
	}()

	writeJSON(w, http.StatusOK, map[string]any{
		"job_id":      jobID,
		"document_id": documentID,
		"status":      "cancelled",
		"message":     "job cancelled, resources are being cleaned up",
	})
}

// handleBatchDeleteDocuments 批量删除文档（三层清理：Qdrant → S3 → DB）
func (a *API) handleBatchDeleteDocuments(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())
	if claims.Role != auth.RoleAdmin {
		writeError(w, http.StatusForbidden, "only admin can delete documents")
		return
	}

	var req struct {
		DocumentIDs []string `json:"document_ids"`
	}
	if err := decodeJSONBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	if len(req.DocumentIDs) == 0 {
		writeError(w, http.StatusBadRequest, "document_ids is required")
		return
	}
	if len(req.DocumentIDs) > 100 {
		writeError(w, http.StatusBadRequest, "too many document_ids, max 100")
		return
	}

	// 验证所有 ID 格式
	for _, id := range req.DocumentIDs {
		if _, err := uuid.Parse(strings.TrimSpace(id)); err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid documentID: %s", id))
			return
		}
	}

	a.logger.Printf("[batch-delete] request: count=%d user_id=%s", len(req.DocumentIDs), claims.UserID)

	var deletedCount int
	var failedIDs []string

	for _, docID := range req.DocumentIDs {
		docID = strings.TrimSpace(docID)

		item, err := a.store.GetDocumentByID(r.Context(), docID)
		if err != nil {
			a.logger.Printf("[batch-delete] skip: documentID=%s err=%v", docID, err)
			failedIDs = append(failedIDs, docID)
			continue
		}

		// 清理 Qdrant 向量
		if err := a.purgeDocumentVectors(r.Context(), docID); err != nil {
			a.logger.Printf("[batch-delete] qdrant purge failed: documentID=%s err=%v", docID, err)
			failedIDs = append(failedIDs, docID)
			continue
		}

		// 清理 S3 文件
		if strings.TrimSpace(item.StorageKey) != "" {
			if err := a.s3.RemoveObject(r.Context(), item.StorageKey); err != nil {
				a.logger.Printf("[batch-delete] s3 remove failed: documentID=%s err=%v", docID, err)
				failedIDs = append(failedIDs, docID)
				continue
			}
		}

		// 删除 DB 记录（级联删除 doc_chunks、ingest_jobs、ingest_events）
		deleted, err := a.store.DeleteDocument(r.Context(), docID)
		if err != nil || !deleted {
			a.logger.Printf("[batch-delete] db delete failed: documentID=%s err=%v", docID, err)
			failedIDs = append(failedIDs, docID)
			continue
		}

		deletedCount++
	}

	a.logger.Printf("[batch-delete] completed: deleted=%d failed=%d user_id=%s", deletedCount, len(failedIDs), claims.UserID)

	result := map[string]any{
		"deleted_count": deletedCount,
		"total":         len(req.DocumentIDs),
	}
	if len(failedIDs) > 0 {
		result["failed_ids"] = failedIDs
	}

	writeJSON(w, http.StatusOK, result)
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

func (a *API) handleListSessions(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())

	sessions, err := a.store.ListChatSessions(r.Context(), claims.UserID)
	if err != nil {
		a.logger.Printf("list chat sessions failed: %v", err)
		writeError(w, http.StatusInternalServerError, "list chat sessions failed")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"items": sessions,
		"count": len(sessions),
	})
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

	if statusCode, err := a.validateScopeResources(r.Context(), req.Scope); err != nil {
		writeError(w, statusCode, err.Error())
		return
	}

	answerSentences, citations, queryErr := a.queryRAG(r.Context(), req.Question, req.Scope)
	if queryErr == nil {
		if err := validateAnswerContract(answerSentences, citations, req.Scope.AllowCommonKnowledge); err != nil {
			queryErr = fmt.Errorf("invalid rag response contract: %w", err)
		}
	}

	if queryErr != nil {
		a.logger.Printf("rag query failed, fallback to placeholder: %v", queryErr)
		answerSentences = []AnswerSentence{
			{
				Text:         commonKnowledgePrefix + " 当前问答服务暂不可用，请稍后重试。",
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

func (a *API) validateScopeResources(ctx context.Context, scope Scope) (int, error) {
	existingCorpora, err := a.store.CountCorporaByIDs(ctx, scope.CorpusIDs)
	if err != nil {
		a.logger.Printf("count scope corpora failed: %v", err)
		return http.StatusInternalServerError, errors.New("query scope corpora failed")
	}
	if existingCorpora != len(scope.CorpusIDs) {
		return http.StatusBadRequest, errors.New("scope contains non-existent corpus_id")
	}

	if len(scope.DocumentIDs) > 0 {
		readyDocs, err := a.store.CountReadyDocumentsByIDsAndCorpora(ctx, scope.CorpusIDs, scope.DocumentIDs)
		if err != nil {
			a.logger.Printf("count scope documents failed: %v", err)
			return http.StatusInternalServerError, errors.New("query scope documents failed")
		}
		if readyDocs != len(scope.DocumentIDs) {
			return http.StatusBadRequest, errors.New("scope contains unknown, non-ready, or out-of-corpus document_id")
		}
		return http.StatusOK, nil
	}

	return http.StatusOK, nil
}

func validateAnswerContract(answerSentences []AnswerSentence, citations []Citation, allowCommonKnowledge bool) error {
	if len(answerSentences) == 0 {
		return errors.New("answer_sentences must not be empty")
	}

	citationMap := make(map[string]struct{}, len(citations))
	for _, citation := range citations {
		citationID := strings.TrimSpace(citation.CitationID)
		if citationID == "" {
			return errors.New("citation_id must not be empty")
		}
		citationMap[citationID] = struct{}{}
	}

	commonCount := 0
	for _, sentence := range answerSentences {
		if strings.TrimSpace(sentence.Text) == "" {
			return errors.New("answer sentence text must not be empty")
		}
		if sentence.Confidence < 0 || sentence.Confidence > 1 {
			return errors.New("answer sentence confidence must be between 0 and 1")
		}

		switch sentence.EvidenceType {
		case "source":
			if len(sentence.CitationIDs) == 0 {
				return errors.New("source sentence must contain at least one citation_id")
			}
			for _, citationID := range sentence.CitationIDs {
				trimmed := strings.TrimSpace(citationID)
				if trimmed == "" {
					return errors.New("source sentence contains empty citation_id")
				}
				if _, ok := citationMap[trimmed]; !ok {
					return fmt.Errorf("source sentence citation_id not found: %s", trimmed)
				}
			}
		case "common_knowledge":
			commonCount++
			if len(sentence.CitationIDs) > 0 {
				return errors.New("common_knowledge sentence must not contain citation_ids")
			}
			if !strings.HasPrefix(sentence.Text, commonKnowledgePrefix) {
				return fmt.Errorf("common_knowledge sentence must start with prefix %q", commonKnowledgePrefix)
			}
		default:
			return fmt.Errorf("unsupported evidence_type: %s", sentence.EvidenceType)
		}
	}

	if commonCount > 0 {
		if !allowCommonKnowledge {
			return errors.New("common_knowledge sentence is not allowed by scope")
		}
		ratio := float64(commonCount) / float64(len(answerSentences))
		if ratio > 0.15 {
			return errors.New("common_knowledge sentence ratio exceeds 15% limit")
		}
	}

	return nil
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

func contentTypeByFileType(fileType string) string {
	switch strings.ToLower(strings.TrimSpace(fileType)) {
	case "pdf":
		return "application/pdf"
	case "docx":
		return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
	case "txt":
		return "text/plain; charset=utf-8"
	default:
		return "application/octet-stream"
	}
}

func hashTextContent(content string) string {
	sum := sha256.Sum256([]byte(content))
	return hex.EncodeToString(sum[:])
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

func normalizeCorpusIDs(corpusIDs []string) ([]string, error) {
	if len(corpusIDs) == 0 {
		return nil, errors.New("corpus_ids is required")
	}

	seen := make(map[string]struct{}, len(corpusIDs))
	normalized := make([]string, 0, len(corpusIDs))

	for _, raw := range corpusIDs {
		id := strings.TrimSpace(raw)
		if id == "" {
			return nil, errors.New("corpus_ids contains empty value")
		}
		if _, err := uuid.Parse(id); err != nil {
			return nil, fmt.Errorf("corpus_ids contains invalid uuid: %q", id)
		}
		if _, ok := seen[id]; ok {
			return nil, fmt.Errorf("corpus_ids contains duplicate value: %q", id)
		}
		seen[id] = struct{}{}
		normalized = append(normalized, id)
	}

	return normalized, nil
}

func (a *API) purgeCorpusVectors(ctx context.Context, corpusID string) error {
	qdrantURL := strings.TrimSpace(a.cfg.QdrantURL)
	collection := strings.TrimSpace(a.cfg.QdrantCollection)
	if qdrantURL == "" || collection == "" {
		return errors.New("qdrant config is missing")
	}

	payload := map[string]any{
		"filter": map[string]any{
			"must": []any{
				map[string]any{
					"key": "corpus_id",
					"match": map[string]any{
						"value": corpusID,
					},
				},
			},
		},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	endpoint := strings.TrimRight(qdrantURL, "/") + "/collections/" + url.PathEscape(collection) + "/points/delete?wait=true"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := a.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil
	}
	if resp.StatusCode >= http.StatusBadRequest {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return fmt.Errorf("qdrant delete failed: status=%d body=%s", resp.StatusCode, string(raw))
	}

	return nil
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeStructuredError(w, &APIError{
		Code:       getErrorCodeForStatus(status),
		Message:    message,
		StatusCode: status,
	})
}

func writeStructuredError(w http.ResponseWriter, apiErr *APIError) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(apiErr.StatusCode)

	traceID := w.Header().Get("X-Request-Id")

	_ = json.NewEncoder(w).Encode(map[string]any{
		"error":    apiErr.Message,
		"code":     apiErr.Code,
		"detail":   apiErr.Detail,
		"trace_id": traceID,
	})
}

func getErrorCodeForStatus(status int) string {
	switch status {
	case http.StatusBadRequest:
		return ErrCodeInvalidInput
	case http.StatusUnauthorized:
		return ErrCodeUnauthorized
	case http.StatusForbidden:
		return ErrCodeForbidden
	case http.StatusNotFound:
		return ErrCodeNotFound
	case http.StatusConflict:
		return ErrCodeConflict
	case http.StatusServiceUnavailable:
		return ErrCodeServiceUnavailable
	default:
		return ErrCodeInternal
	}
}

func getQueryLimit(r *http.Request, defaultLimit int) int {
	limitStr := r.URL.Query().Get("limit")
	if limitStr == "" {
		return defaultLimit
	}
	limit, err := strconv.Atoi(limitStr)
	if err != nil || limit <= 0 {
		return defaultLimit
	}
	if limit > 10000 {
		return 10000
	}
	return limit
}

func getQueryOffset(r *http.Request, defaultOffset int) int {
	offsetStr := r.URL.Query().Get("offset")
	if offsetStr == "" {
		return defaultOffset
	}
	offset, err := strconv.Atoi(offsetStr)
	if err != nil || offset < 0 {
		return defaultOffset
	}
	return offset
}

func (a *API) handleDeleteDocument(w http.ResponseWriter, r *http.Request) {
	claims := mustClaims(r.Context())
	if claims.Role != auth.RoleAdmin {
		writeError(w, http.StatusForbidden, "only admin can delete document")
		return
	}

	documentID := strings.TrimSpace(chi.URLParam(r, "documentID"))
	if _, err := uuid.Parse(documentID); err != nil {
		writeError(w, http.StatusBadRequest, "invalid documentID")
		return
	}

	startTime := time.Now()
	a.logger.Printf("[delete] request: documentID=%s user_id=%s role=%s", documentID, claims.UserID, claims.Role)

	item, err := a.store.GetDocumentByID(r.Context(), documentID)
	if err != nil {
		if errors.Is(err, db.ErrNotFound) {
			writeError(w, http.StatusNotFound, "document not found")
			return
		}
		a.logger.Printf("[delete] query document failed: documentID=%s user_id=%s err=%v", documentID, claims.UserID, err)
		writeError(w, http.StatusInternalServerError, "query document failed")
		return
	}

	if hasActiveJob, err := a.store.HasActiveIngestJob(r.Context(), documentID); err != nil {
		a.logger.Printf("[delete] check ingest job status failed: documentID=%s user_id=%s err=%v", documentID, claims.UserID, err)
		writeError(w, http.StatusInternalServerError, "check ingest job status failed")
		return
	} else if hasActiveJob {
		a.logger.Printf("[delete] rejected: documentID=%s user_id=%s reason=active_ingest_job", documentID, claims.UserID)
		writeError(w, http.StatusConflict, "document has active ingest job, please wait or cancel first")
		return
	}

	a.logger.Printf("[delete] starting: documentID=%s fileName=%s size=%d fileType=%s storageKey=%s",
		documentID, item.FileName, item.SizeBytes, item.FileType, item.StorageKey)

	qdrantStart := time.Now()
	if err := a.purgeDocumentVectors(r.Context(), documentID); err != nil {
		a.logger.Printf("[delete] purge qdrant failed: documentID=%s user_id=%s err=%v qdrant_ms=%d",
			documentID, claims.UserID, err, time.Since(qdrantStart).Milliseconds())
		writeError(w, http.StatusInternalServerError, "purge vector resources failed")
		return
	}
	a.logger.Printf("[delete] qdrant purged: documentID=%s qdrant_ms=%d", documentID, time.Since(qdrantStart).Milliseconds())

	s3Start := time.Now()
	if strings.TrimSpace(item.StorageKey) != "" {
		if err := a.s3.RemoveObject(r.Context(), item.StorageKey); err != nil {
			a.logger.Printf("[delete] remove s3 object failed: documentID=%s storageKey=%s err=%v s3_ms=%d",
				documentID, item.StorageKey, err, time.Since(s3Start).Milliseconds())
			writeError(w, http.StatusInternalServerError, "purge object storage failed")
			return
		}
		a.logger.Printf("[delete] s3 object removed: documentID=%s storageKey=%s s3_ms=%d",
			documentID, item.StorageKey, time.Since(s3Start).Milliseconds())
	}

	dbStart := time.Now()
	deleted, err := a.store.DeleteDocument(r.Context(), documentID)
	dbDuration := time.Since(dbStart)

	if err != nil {
		a.logger.Printf("[delete] delete document record failed: documentID=%s user_id=%s err=%v db_ms=%d",
			documentID, claims.UserID, err, dbDuration.Milliseconds())
		writeError(w, http.StatusInternalServerError, "delete document record failed")
		return
	}
	if !deleted {
		a.logger.Printf("[delete] document not found: documentID=%s user_id=%s db_ms=%d",
			documentID, claims.UserID, dbDuration.Milliseconds())
		writeError(w, http.StatusNotFound, "document not found")
		return
	}

	totalDuration := time.Since(startTime)
	a.logger.Printf("[delete] completed: documentID=%s fileName=%s size=%d user_id=%s qdrant_ms=%d s3_ms=%d db_ms=%d total_ms=%d",
		documentID, item.FileName, item.SizeBytes, claims.UserID,
		time.Since(qdrantStart).Milliseconds(),
		time.Since(s3Start).Milliseconds(),
		dbDuration.Milliseconds(),
		totalDuration.Milliseconds())
	w.WriteHeader(http.StatusNoContent)
}

func (a *API) purgeDocumentVectors(ctx context.Context, documentID string) error {
	qdrantURL := strings.TrimSpace(a.cfg.QdrantURL)
	collection := strings.TrimSpace(a.cfg.QdrantCollection)
	if qdrantURL == "" || collection == "" {
		return errors.New("qdrant config is missing")
	}

	payload := map[string]any{
		"filter": map[string]any{
			"must": []any{
				map[string]any{
					"key": "document_id",
					"match": map[string]any{
						"value": documentID,
					},
				},
			},
		},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	endpoint := strings.TrimRight(qdrantURL, "/") + "/collections/" + url.PathEscape(collection) + "/points/delete?wait=true"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := a.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil
	}
	if resp.StatusCode >= http.StatusBadRequest {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return fmt.Errorf("qdrant delete failed: status=%d body=%s", resp.StatusCode, string(raw))
	}

	return nil
}
