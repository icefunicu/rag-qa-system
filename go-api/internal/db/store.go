package db

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
)

var ErrNotFound = errors.New("resource not found")

type Store struct {
	db *sql.DB
}

type Corpus struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Description string    `json:"description"`
	OwnerUserID string    `json:"owner_user_id"`
	CreatedAt   time.Time `json:"created_at"`
}

type CreateCorpusInput struct {
	Name        string
	Description string
	OwnerUserID string
}

type CreateDocumentInput struct {
	CorpusID   string
	FileName   string
	FileType   string
	SizeBytes  int64
	StorageKey string
	CreatedBy  string
}

type IngestJob struct {
	ID         string    `json:"id"`
	DocumentID string    `json:"document_id"`
	Status     string    `json:"status"`
	Progress   int       `json:"progress"`
	ErrorMsg   string    `json:"error_message,omitempty"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

type ChatSession struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	CreatedBy string    `json:"created_by"`
	CreatedAt time.Time `json:"created_at"`
}

func NewStore(dsn string) (*Store, error) {
	conn, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}

	if err := conn.Ping(); err != nil {
		return nil, err
	}

	return &Store{db: conn}, nil
}

func (s *Store) Close() error {
	return s.db.Close()
}

func (s *Store) CreateCorpus(ctx context.Context, input CreateCorpusInput) (Corpus, error) {
	corpusID := uuid.NewString()
	now := time.Now().UTC()

	_, err := s.db.ExecContext(
		ctx,
		`INSERT INTO corpora (id, name, description, owner_user_id, created_at)
		 VALUES ($1, $2, $3, $4, $5)`,
		corpusID,
		input.Name,
		input.Description,
		input.OwnerUserID,
		now,
	)
	if err != nil {
		return Corpus{}, err
	}

	return Corpus{
		ID:          corpusID,
		Name:        input.Name,
		Description: input.Description,
		OwnerUserID: input.OwnerUserID,
		CreatedAt:   now,
	}, nil
}

func (s *Store) ListCorpora(ctx context.Context) ([]Corpus, error) {
	rows, err := s.db.QueryContext(
		ctx,
		`SELECT id, name, COALESCE(description, ''), owner_user_id, created_at
		 FROM corpora
		 ORDER BY created_at DESC`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	corpora := make([]Corpus, 0)
	for rows.Next() {
		var item Corpus
		if err := rows.Scan(&item.ID, &item.Name, &item.Description, &item.OwnerUserID, &item.CreatedAt); err != nil {
			return nil, err
		}
		corpora = append(corpora, item)
	}

	return corpora, rows.Err()
}

func (s *Store) CorpusExists(ctx context.Context, corpusID string) (bool, error) {
	var exists bool
	err := s.db.QueryRowContext(
		ctx,
		`SELECT EXISTS(SELECT 1 FROM corpora WHERE id = $1)`,
		corpusID,
	).Scan(&exists)
	return exists, err
}

func (s *Store) CreateDocumentAndJob(ctx context.Context, input CreateDocumentInput) (string, IngestJob, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return "", IngestJob{}, err
	}
	defer func() {
		_ = tx.Rollback()
	}()

	documentID := uuid.NewString()
	jobID := uuid.NewString()
	now := time.Now().UTC()

	_, err = tx.ExecContext(
		ctx,
		`INSERT INTO documents (id, corpus_id, file_name, file_type, size_bytes, storage_key, status, created_by, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, 'uploaded', $7, $8)`,
		documentID,
		input.CorpusID,
		input.FileName,
		input.FileType,
		input.SizeBytes,
		input.StorageKey,
		input.CreatedBy,
		now,
	)
	if err != nil {
		return "", IngestJob{}, err
	}

	_, err = tx.ExecContext(
		ctx,
		`INSERT INTO ingest_jobs (id, document_id, status, progress, created_at, updated_at)
		 VALUES ($1, $2, 'queued', 0, $3, $3)`,
		jobID,
		documentID,
		now,
	)
	if err != nil {
		return "", IngestJob{}, err
	}

	if err := tx.Commit(); err != nil {
		return "", IngestJob{}, err
	}

	return documentID, IngestJob{
		ID:         jobID,
		DocumentID: documentID,
		Status:     "queued",
		Progress:   0,
		CreatedAt:  now,
		UpdatedAt:  now,
	}, nil
}

func (s *Store) GetIngestJob(ctx context.Context, jobID string) (IngestJob, error) {
	row := s.db.QueryRowContext(
		ctx,
		`SELECT id, document_id, status, progress, COALESCE(error_message, ''), created_at, updated_at
		 FROM ingest_jobs
		 WHERE id = $1`,
		jobID,
	)

	var job IngestJob
	if err := row.Scan(&job.ID, &job.DocumentID, &job.Status, &job.Progress, &job.ErrorMsg, &job.CreatedAt, &job.UpdatedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return IngestJob{}, ErrNotFound
		}
		return IngestJob{}, err
	}

	return job, nil
}

func (s *Store) CreateChatSession(ctx context.Context, title, createdBy string) (ChatSession, error) {
	sessionID := uuid.NewString()
	now := time.Now().UTC()

	_, err := s.db.ExecContext(
		ctx,
		`INSERT INTO chat_sessions (id, title, created_by, created_at)
		 VALUES ($1, $2, $3, $4)`,
		sessionID,
		title,
		createdBy,
		now,
	)
	if err != nil {
		return ChatSession{}, err
	}

	return ChatSession{
		ID:        sessionID,
		Title:     title,
		CreatedBy: createdBy,
		CreatedAt: now,
	}, nil
}

func (s *Store) ChatSessionExists(ctx context.Context, sessionID string) (bool, error) {
	var exists bool
	err := s.db.QueryRowContext(
		ctx,
		`SELECT EXISTS(SELECT 1 FROM chat_sessions WHERE id = $1)`,
		sessionID,
	).Scan(&exists)
	return exists, err
}
