package db

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
)

var ErrNotFound = errors.New("resource not found")

type Store struct {
	db *sql.DB
}

// DB 返回数据库连接（用于健康检查）
func (s *Store) DB() *sql.DB {
	return s.db
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
	CorpusID    string
	FileName    string
	FileType    string
	SizeBytes   int64
	StorageKey  string
	ContentHash string
	CreatedBy   string
}

type IngestJob struct {
	ID            string    `json:"id"`
	DocumentID    string    `json:"document_id"`
	Status        string    `json:"status"`
	Progress      int       `json:"progress"`
	ErrorMsg      string    `json:"error_message,omitempty"`
	ErrorCategory string    `json:"error_category,omitempty"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type ChatSession struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	CreatedBy string    `json:"created_by"`
	CreatedAt time.Time `json:"created_at"`
}

type DocumentListItem struct {
	ID        string    `json:"id"`
	CorpusID  string    `json:"corpus_id"`
	FileName  string    `json:"file_name"`
	FileType  string    `json:"file_type"`
	SizeBytes int64     `json:"size_bytes"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"created_at"`
}

type DocumentDetail struct {
	ID         string    `json:"id"`
	CorpusID   string    `json:"corpus_id"`
	FileName   string    `json:"file_name"`
	FileType   string    `json:"file_type"`
	SizeBytes  int64     `json:"size_bytes"`
	Status     string    `json:"status"`
	CreatedBy  string    `json:"created_by"`
	CreatedAt  time.Time `json:"created_at"`
	StorageKey string    `json:"-"`
}

func NewStore(dsn string, opts ...StoreOption) (*Store, error) {
	// 默认连接池配置
	config := storeConfig{
		maxOpenConns:    25,
		maxIdleConns:    5,
		connMaxLifetime: 5 * time.Minute,
	}

	// 应用可选配置
	for _, opt := range opts {
		opt(&config)
	}

	conn, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}

	// 配置连接池
	conn.SetMaxOpenConns(config.maxOpenConns)
	conn.SetMaxIdleConns(config.maxIdleConns)
	conn.SetConnMaxLifetime(config.connMaxLifetime)

	// 验证连接
	if err := conn.Ping(); err != nil {
		conn.Close()
		return nil, err
	}

	return &Store{db: conn}, nil
}

// storeConfig 数据库连接池配置
type storeConfig struct {
	maxOpenConns    int
	maxIdleConns    int
	connMaxLifetime time.Duration
}

// StoreOption 数据库配置选项
type StoreOption func(*storeConfig)

// WithMaxOpenConns 设置最大打开连接数
func WithMaxOpenConns(n int) StoreOption {
	return func(c *storeConfig) {
		if n > 0 {
			c.maxOpenConns = n
		}
	}
}

// WithMaxIdleConns 设置最大空闲连接数
func WithMaxIdleConns(n int) StoreOption {
	return func(c *storeConfig) {
		if n > 0 {
			c.maxIdleConns = n
		}
	}
}

// WithConnMaxLifetime 设置连接最大生命周期
func WithConnMaxLifetime(d time.Duration) StoreOption {
	return func(c *storeConfig) {
		if d > 0 {
			c.connMaxLifetime = d
		}
	}
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

func (s *Store) DeleteCorpus(ctx context.Context, corpusID string) (bool, error) {
	result, err := s.db.ExecContext(ctx, `DELETE FROM corpora WHERE id = $1`, corpusID)
	if err != nil {
		return false, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	return affected > 0, nil
}

func (s *Store) DeleteCorpora(ctx context.Context, corpusIDs []string) (int, error) {
	if len(corpusIDs) == 0 {
		return 0, nil
	}

	inClause, args := buildInClause(1, corpusIDs)
	query := fmt.Sprintf(`DELETE FROM corpora WHERE id IN (%s)`, inClause)

	result, err := s.db.ExecContext(ctx, query, args...)
	if err != nil {
		return 0, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return 0, err
	}

	return int(affected), nil
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

func (s *Store) CountCorporaByIDs(ctx context.Context, corpusIDs []string) (int, error) {
	if len(corpusIDs) == 0 {
		return 0, nil
	}

	inClause, args := buildInClause(1, corpusIDs)
	query := fmt.Sprintf(`SELECT COUNT(*) FROM corpora WHERE id IN (%s)`, inClause)

	var count int
	if err := s.db.QueryRowContext(ctx, query, args...).Scan(&count); err != nil {
		return 0, err
	}
	return count, nil
}

func (s *Store) CountReadyDocumentsInCorpora(ctx context.Context, corpusIDs []string) (int, error) {
	if len(corpusIDs) == 0 {
		return 0, nil
	}

	inClause, args := buildInClause(1, corpusIDs)
	query := fmt.Sprintf(`
		SELECT COUNT(*)
		FROM documents
		WHERE status = 'ready'
		  AND corpus_id IN (%s)
	`, inClause)

	var count int
	if err := s.db.QueryRowContext(ctx, query, args...).Scan(&count); err != nil {
		return 0, err
	}
	return count, nil
}

func (s *Store) CountReadyDocumentsByIDsAndCorpora(ctx context.Context, corpusIDs, documentIDs []string) (int, error) {
	if len(corpusIDs) == 0 || len(documentIDs) == 0 {
		return 0, nil
	}

	corpusClause, corpusArgs := buildInClause(1, corpusIDs)
	docClause, docArgs := buildInClause(1+len(corpusArgs), documentIDs)
	args := append(corpusArgs, docArgs...)

	query := fmt.Sprintf(`
		SELECT COUNT(*)
		FROM documents
		WHERE status = 'ready'
		  AND corpus_id IN (%s)
		  AND id IN (%s)
	`, corpusClause, docClause)

	var count int
	if err := s.db.QueryRowContext(ctx, query, args...).Scan(&count); err != nil {
		return 0, err
	}
	return count, nil
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

	if contentHash := strings.TrimSpace(input.ContentHash); contentHash != "" {
		_, err = tx.ExecContext(
			ctx,
			`INSERT INTO document_versions (id, document_id, version, content_hash, storage_key, created_at)
			 VALUES ($1, $2, $3, $4, $5, $6)`,
			uuid.NewString(),
			documentID,
			1,
			contentHash,
			input.StorageKey,
			now,
		)
		if err != nil {
			return "", IngestJob{}, err
		}
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
		`SELECT id, document_id, status, progress, COALESCE(error_message, ''), COALESCE(error_category, ''), created_at, updated_at
		 FROM ingest_jobs
		 WHERE id = $1`,
		jobID,
	)

	var job IngestJob
	if err := row.Scan(&job.ID, &job.DocumentID, &job.Status, &job.Progress, &job.ErrorMsg, &job.ErrorCategory, &job.CreatedAt, &job.UpdatedAt); err != nil {
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

func (s *Store) ListChatSessions(ctx context.Context, createdBy string) ([]ChatSession, error) {
	rows, err := s.db.QueryContext(
		ctx,
		`SELECT id, title, created_by, created_at
		 FROM chat_sessions
		 WHERE created_by = $1
		 ORDER BY created_at DESC`,
		createdBy,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	sessions := make([]ChatSession, 0)
	for rows.Next() {
		var item ChatSession
		if err := rows.Scan(&item.ID, &item.Title, &item.CreatedBy, &item.CreatedAt); err != nil {
			return nil, err
		}
		sessions = append(sessions, item)
	}

	return sessions, rows.Err()
}

func (s *Store) ListDocumentsByCorpus(ctx context.Context, corpusID string) ([]DocumentListItem, error) {
	rows, err := s.db.QueryContext(
		ctx,
		`SELECT id, corpus_id, file_name, file_type, size_bytes, status, created_at
		 FROM documents
		 WHERE corpus_id = $1
		 ORDER BY created_at DESC`,
		corpusID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]DocumentListItem, 0)
	for rows.Next() {
		var item DocumentListItem
		if err := rows.Scan(
			&item.ID,
			&item.CorpusID,
			&item.FileName,
			&item.FileType,
			&item.SizeBytes,
			&item.Status,
			&item.CreatedAt,
		); err != nil {
			return nil, err
		}
		items = append(items, item)
	}

	return items, rows.Err()
}

func (s *Store) GetDocumentByID(ctx context.Context, documentID string) (DocumentDetail, error) {
	row := s.db.QueryRowContext(
		ctx,
		`SELECT id, corpus_id, file_name, file_type, size_bytes, status, created_by, created_at, storage_key
		 FROM documents
		 WHERE id = $1`,
		documentID,
	)

	var item DocumentDetail
	if err := row.Scan(
		&item.ID,
		&item.CorpusID,
		&item.FileName,
		&item.FileType,
		&item.SizeBytes,
		&item.Status,
		&item.CreatedBy,
		&item.CreatedAt,
		&item.StorageKey,
	); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return DocumentDetail{}, ErrNotFound
		}
		return DocumentDetail{}, err
	}

	return item, nil
}

func (s *Store) HasActiveIngestJob(ctx context.Context, documentID string) (bool, error) {
	var exists bool
	err := s.db.QueryRowContext(
		ctx,
		`SELECT EXISTS (
			SELECT 1
			FROM ingest_jobs
			WHERE document_id = $1
			  AND status IN ('queued', 'running')
		)`,
		documentID,
	).Scan(&exists)
	return exists, err
}

func (s *Store) CreateReingestJobForDocument(ctx context.Context, documentID string, sizeBytes int64, contentHash, storageKey string) (IngestJob, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return IngestJob{}, err
	}
	defer func() {
		_ = tx.Rollback()
	}()

	jobID := uuid.NewString()
	now := time.Now().UTC()

	result, err := tx.ExecContext(
		ctx,
		`UPDATE documents
		 SET status = 'uploaded', size_bytes = $2
		 WHERE id = $1`,
		documentID,
		sizeBytes,
	)
	if err != nil {
		return IngestJob{}, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return IngestJob{}, err
	}
	if affected == 0 {
		return IngestJob{}, ErrNotFound
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
		return IngestJob{}, err
	}

	trimmedHash := strings.TrimSpace(contentHash)
	if trimmedHash != "" {
		var nextVersion int
		if err := tx.QueryRowContext(
			ctx,
			`SELECT COALESCE(MAX(version), 0) + 1 FROM document_versions WHERE document_id = $1`,
			documentID,
		).Scan(&nextVersion); err != nil {
			return IngestJob{}, err
		}

		_, err = tx.ExecContext(
			ctx,
			`INSERT INTO document_versions (id, document_id, version, content_hash, storage_key, created_at)
			 VALUES ($1, $2, $3, $4, $5, $6)
			 ON CONFLICT (document_id, content_hash) DO NOTHING`,
			uuid.NewString(),
			documentID,
			nextVersion,
			trimmedHash,
			storageKey,
			now,
		)
		if err != nil {
			return IngestJob{}, err
		}
	}

	if err := tx.Commit(); err != nil {
		return IngestJob{}, err
	}

	return IngestJob{
		ID:         jobID,
		DocumentID: documentID,
		Status:     "queued",
		Progress:   0,
		CreatedAt:  now,
		UpdatedAt:  now,
	}, nil
}

func (s *Store) ListStorageKeysByCorpus(ctx context.Context, corpusID string) ([]string, error) {
	rows, err := s.db.QueryContext(
		ctx,
		`SELECT DISTINCT storage_key
		 FROM documents
		 WHERE corpus_id = $1
		   AND storage_key <> ''`,
		corpusID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	keys := make([]string, 0)
	for rows.Next() {
		var key string
		if err := rows.Scan(&key); err != nil {
			return nil, err
		}
		if strings.TrimSpace(key) != "" {
			keys = append(keys, key)
		}
	}

	return keys, rows.Err()
}

func (s *Store) ListStorageKeysByCorpora(ctx context.Context, corpusIDs []string) ([]string, error) {
	if len(corpusIDs) == 0 {
		return []string{}, nil
	}

	inClause, args := buildInClause(1, corpusIDs)
	query := fmt.Sprintf(`
		SELECT DISTINCT storage_key
		FROM documents
		WHERE corpus_id IN (%s)
		  AND storage_key <> ''
	`, inClause)

	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	keys := make([]string, 0)
	for rows.Next() {
		var key string
		if err := rows.Scan(&key); err != nil {
			return nil, err
		}
		if strings.TrimSpace(key) != "" {
			keys = append(keys, key)
		}
	}

	return keys, rows.Err()
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

func (s *Store) DeleteDocument(ctx context.Context, documentID string) (bool, error) {
	result, err := s.db.ExecContext(ctx, `DELETE FROM documents WHERE id = $1`, documentID)
	if err != nil {
		return false, err
	}

	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	return affected > 0, nil
}

func (s *Store) MarkIngestJobFailed(ctx context.Context, jobID, docID, errorMessage string) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() {
		_ = tx.Rollback()
	}()

	_, err = tx.ExecContext(
		ctx,
		`UPDATE ingest_jobs
		 SET status = 'failed', progress = 0, error_message = $2, updated_at = NOW()
		 WHERE id = $1`,
		jobID,
		errorMessage,
	)
	if err != nil {
		return err
	}

	_, err = tx.ExecContext(
		ctx,
		`UPDATE documents
		 SET status = 'failed'
		 WHERE id = $1`,
		docID,
	)
	if err != nil {
		return err
	}

	return tx.Commit()
}

// CancelIngestJob 将 ingest job 和关联文档标记为 cancelled，并记录事件
func (s *Store) CancelIngestJob(ctx context.Context, jobID string) (string, string, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return "", "", err
	}
	defer func() {
		_ = tx.Rollback()
	}()

	// 获取 job 的 document_id 和当前状态
	var documentID, status string
	err = tx.QueryRowContext(
		ctx,
		`SELECT document_id, status FROM ingest_jobs WHERE id = $1`,
		jobID,
	).Scan(&documentID, &status)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return "", "", ErrNotFound
		}
		return "", "", err
	}

	// 只能取消 queued 或 running 状态的 job
	if status != "queued" && status != "running" {
		return "", "", fmt.Errorf("job status is %s, only queued or running jobs can be cancelled", status)
	}

	// 更新 job 状态为 cancelled
	_, err = tx.ExecContext(
		ctx,
		`UPDATE ingest_jobs
		 SET status = 'cancelled', progress = 0, error_message = 'cancelled by user', updated_at = NOW()
		 WHERE id = $1`,
		jobID,
	)
	if err != nil {
		return "", "", err
	}

	// 更新文档状态为 cancelled
	_, err = tx.ExecContext(
		ctx,
		`UPDATE documents
		 SET status = 'cancelled'
		 WHERE id = $1`,
		documentID,
	)
	if err != nil {
		return "", "", err
	}

	// 记录取消事件
	eventID := uuid.NewString()
	_, err = tx.ExecContext(
		ctx,
		`INSERT INTO ingest_events (id, job_id, stage, message, created_at)
		 VALUES ($1, $2, 'cancelled', 'job cancelled by user', NOW())`,
		eventID, jobID,
	)
	if err != nil {
		return "", "", err
	}

	if err := tx.Commit(); err != nil {
		return "", "", err
	}

	return documentID, status, nil
}

func buildInClause(start int, values []string) (string, []any) {
	placeholders := make([]string, 0, len(values))
	args := make([]any, 0, len(values))
	for idx, value := range values {
		placeholders = append(placeholders, fmt.Sprintf("$%d", start+idx))
		args = append(args, value)
	}
	return strings.Join(placeholders, ", "), args
}
