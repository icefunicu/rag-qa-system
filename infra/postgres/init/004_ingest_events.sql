CREATE TABLE IF NOT EXISTS ingest_events (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES ingest_jobs (id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'downloaded', 'parsed', 'embedded', 'indexed', 'done', 'failed', 'verified')),
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingest_events_job_id_created_at ON ingest_events (job_id, created_at);
