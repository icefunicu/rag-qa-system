-- Phase E: 支持 cancelled 状态
-- 扩展 ingest_jobs、documents、ingest_events 的 CHECK 约束以包含 cancelled

-- 1. 扩展 ingest_jobs status 约束
ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_status_check;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_status_check
    CHECK (status IN ('queued', 'running', 'failed', 'done', 'dead_letter', 'cancelled'));

-- 2. 扩展 documents status 约束
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_status_check
    CHECK (status IN ('uploaded', 'indexing', 'ready', 'failed', 'cancelled'));

-- 3. 扩展 ingest_events stage 约束
ALTER TABLE ingest_events DROP CONSTRAINT IF EXISTS ingest_events_stage_check;
ALTER TABLE ingest_events ADD CONSTRAINT ingest_events_stage_check
    CHECK (stage IN (
        'queued', 'downloading', 'parsing', 'chunking', 'embedding',
        'indexing', 'verifying', 'done', 'failed', 'dead_letter', 'cancelled'
    ));
