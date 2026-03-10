CREATE INDEX IF NOT EXISTS idx_kb_bases_created_by_created_desc
    ON kb_bases(created_by, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_kb_bases_created_desc
    ON kb_bases(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_kb_documents_created_by_created_desc
    ON kb_documents(created_by, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_kb_documents_created_by_ready_desc
    ON kb_documents(created_by, ready_at DESC);

CREATE INDEX IF NOT EXISTS idx_kb_documents_ready_desc
    ON kb_documents(ready_at DESC);

CREATE INDEX IF NOT EXISTS idx_kb_ingest_jobs_document_created_desc
    ON kb_ingest_jobs(document_id, created_at DESC);
