package db

import (
	"context"
	"database/sql"
	"strings"
	"time"

	"github.com/google/uuid"
)

type DocumentVersion struct {
	ID          string    `json:"id"`
	DocumentID  string    `json:"document_id"`
	Version     int       `json:"version"`
	ContentHash string    `json:"content_hash"`
	StorageKey  string    `json:"storage_key"`
	CreatedAt   time.Time `json:"created_at"`
}

type IngestEvent struct {
	ID        string    `json:"id"`
	JobID     string    `json:"job_id"`
	Stage     string    `json:"stage"`
	Message   *string   `json:"message,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

type ChatMessage struct {
	ID            string    `json:"id"`
	SessionID     string    `json:"session_id"`
	Role          string    `json:"role"`
	Content       string    `json:"content"`
	ScopePayload  *string   `json:"scope_payload,omitempty"`
	AnswerPayload *string   `json:"answer_payload,omitempty"`
	TraceID       *string   `json:"trace_id,omitempty"`
	CreatedAt     time.Time `json:"created_at"`
}

type AnswerFeedback struct {
	ID        string    `json:"id"`
	MessageID string    `json:"message_id"`
	Rating    int       `json:"rating"`
	Tags      []string  `json:"tags,omitempty"`
	Comment   *string   `json:"comment,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

type AdminIngestEvent struct {
	CreatedAt     time.Time `json:"created_at"`
	JobID         string    `json:"job_id"`
	DocumentID    string    `json:"document_id"`
	FileName      string    `json:"file_name"`
	Stage         string    `json:"stage"`
	Message       string    `json:"message"`
	JobStatus     string    `json:"job_status"`
	ErrorMessage  string    `json:"error_message"`
	ErrorCategory string    `json:"error_category"`
}

// CreateDocumentVersion creates a new document version record.
func (s *Store) CreateDocumentVersion(ctx context.Context, docID string, version int, contentHash, storageKey string) (DocumentVersion, error) {
	id := uuid.NewString()
	now := time.Now().UTC()
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO document_versions (id, document_id, version, content_hash, storage_key, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6)`,
		id, docID, version, contentHash, storageKey, now)
	if err != nil {
		return DocumentVersion{}, err
	}
	return DocumentVersion{ID: id, DocumentID: docID, Version: version, ContentHash: contentHash, StorageKey: storageKey, CreatedAt: now}, nil
}

// CreateIngestEvent logs an ingest stage event.
func (s *Store) CreateIngestEvent(ctx context.Context, jobID, stage, message string) error {
	id := uuid.NewString()
	var msgPtr *string
	if message != "" {
		msgPtr = &message
	}
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO ingest_events (id, job_id, stage, message, created_at) VALUES ($1, $2, $3, $4, $5)`,
		id, jobID, stage, msgPtr, time.Now().UTC())
	return err
}

// CreateChatMessage records a chat message.
func (s *Store) CreateChatMessage(ctx context.Context, sessionID, role, content string, scopePayload, answerPayload, traceID *string) (ChatMessage, error) {
	id := uuid.NewString()
	now := time.Now().UTC()
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO chat_messages (id, session_id, role, content, scope_payload, answer_payload, trace_id, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
		id, sessionID, role, content, scopePayload, answerPayload, traceID, now)
	if err != nil {
		return ChatMessage{}, err
	}
	return ChatMessage{ID: id, SessionID: sessionID, Role: role, Content: content, ScopePayload: scopePayload, AnswerPayload: answerPayload, TraceID: traceID, CreatedAt: now}, nil
}

// CreateAnswerFeedback records user feedback on a message.
func (s *Store) CreateAnswerFeedback(ctx context.Context, messageID string, rating int, tags []string, comment string) error {
	id := uuid.NewString()
	var commPtr *string
	if comment != "" {
		commPtr = &comment
	}
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO answer_feedback (id, message_id, rating, tags, comment, created_at) VALUES ($1, $2, $3, $4, $5, $6)
		 ON CONFLICT (message_id) DO UPDATE SET rating = EXCLUDED.rating, tags = EXCLUDED.tags, comment = EXCLUDED.comment`,
		id, messageID, rating, tags, commPtr, time.Now().UTC())
	return err
}

// GetDocumentByStorageKey finds an existing document ID by its storage key.
func (s *Store) GetDocumentByStorageKey(ctx context.Context, storageKey string) (string, error) {
	var id string
	err := s.db.QueryRowContext(ctx, `SELECT id FROM documents WHERE storage_key = $1`, storageKey).Scan(&id)
	if err != nil {
		return "", err
	}
	return id, nil
}

// GetIngestJobByDocumentID finds the most recent ingest job for a document.
func (s *Store) GetIngestJobByDocumentID(ctx context.Context, docID string) (IngestJob, error) {
	row := s.db.QueryRowContext(
		ctx,
		`SELECT id, document_id, status, progress, COALESCE(error_message, ''), COALESCE(error_category, ''), created_at, updated_at
		 FROM ingest_jobs
		 WHERE document_id = $1
		 ORDER BY created_at DESC LIMIT 1`,
		docID,
	)

	var job IngestJob
	if err := row.Scan(&job.ID, &job.DocumentID, &job.Status, &job.Progress, &job.ErrorMsg, &job.ErrorCategory, &job.CreatedAt, &job.UpdatedAt); err != nil {
		if err == sql.ErrNoRows {
			return IngestJob{}, ErrNotFound
		}
		return IngestJob{}, err
	}
	return job, nil
}

// ListChatMessages lists messages for a session.
func (s *Store) ListChatMessages(ctx context.Context, sessionID string) ([]ChatMessage, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT id, session_id, role, content, scope_payload, answer_payload, trace_id, created_at 
		 FROM chat_messages WHERE session_id = $1 ORDER BY created_at ASC`, sessionID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var items []ChatMessage
	for rows.Next() {
		var item ChatMessage
		if err := rows.Scan(&item.ID, &item.SessionID, &item.Role, &item.Content, &item.ScopePayload, &item.AnswerPayload, &item.TraceID, &item.CreatedAt); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

// ListRecentIngestEvents returns recent ingest timeline rows joined with document metadata.
func (s *Store) ListRecentIngestEvents(ctx context.Context, keyword string, limit int) ([]AdminIngestEvent, error) {
	if limit <= 0 {
		limit = 100
	}

	filter := "%"
	trimmed := strings.TrimSpace(keyword)
	if trimmed != "" {
		filter = "%" + trimmed + "%"
	}

	rows, err := s.db.QueryContext(
		ctx,
		`SELECT e.created_at,
		        e.job_id,
		        j.document_id,
		        d.file_name,
		        e.stage,
		        COALESCE(e.message, ''),
		        j.status,
		        COALESCE(j.error_message, ''),
		        COALESCE(j.error_category, '')
		   FROM ingest_events e
		   JOIN ingest_jobs j ON j.id = e.job_id
		   JOIN documents d ON d.id = j.document_id
		  WHERE ($1 = '%' OR CAST(e.job_id AS TEXT) ILIKE $1
		                  OR CAST(j.document_id AS TEXT) ILIKE $1
		                  OR d.file_name ILIKE $1
		                  OR e.stage ILIKE $1
		                  OR COALESCE(e.message, '') ILIKE $1
		                  OR COALESCE(j.error_message, '') ILIKE $1)
		  ORDER BY e.created_at DESC
		  LIMIT $2`,
		filter,
		limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]AdminIngestEvent, 0)
	for rows.Next() {
		var item AdminIngestEvent
		if err := rows.Scan(
			&item.CreatedAt,
			&item.JobID,
			&item.DocumentID,
			&item.FileName,
			&item.Stage,
			&item.Message,
			&item.JobStatus,
			&item.ErrorMessage,
			&item.ErrorCategory,
		); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

// FindDocumentByContentHash 在同一 corpus 下按 content_hash 查找已有文档版本（用于去重策略）。
func (s *Store) FindDocumentByContentHash(ctx context.Context, corpusID, contentHash string) (string, error) {
	var docID string
	err := s.db.QueryRowContext(ctx,
		`SELECT dv.document_id FROM document_versions dv
		 JOIN documents d ON d.id = dv.document_id
		 WHERE d.corpus_id = $1 AND dv.content_hash = $2
		 LIMIT 1`,
		corpusID, contentHash).Scan(&docID)
	if err != nil {
		return "", err
	}
	return docID, nil
}

// GetLatestDocumentVersion 获取指定文档的最新版本号。
func (s *Store) GetLatestDocumentVersion(ctx context.Context, documentID string) (int, error) {
	var version int
	err := s.db.QueryRowContext(ctx,
		`SELECT COALESCE(MAX(version), 0) FROM document_versions WHERE document_id = $1`,
		documentID).Scan(&version)
	return version, err
}

// ListIngestEventsByJobID 查询某个 job 的全部 timeline 事件（按时间正序）。
func (s *Store) ListIngestEventsByJobID(ctx context.Context, jobID string) ([]IngestEvent, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT id, job_id, stage, message, created_at
		 FROM ingest_events
		 WHERE job_id = $1
		 ORDER BY created_at ASC`, jobID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var items []IngestEvent
	for rows.Next() {
		var item IngestEvent
		if err := rows.Scan(&item.ID, &item.JobID, &item.Stage, &item.Message, &item.CreatedAt); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}
