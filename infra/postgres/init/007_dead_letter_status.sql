-- Phase D: 支持 dead_letter 状态和错误分类
-- 扩展 ingest_jobs 的 status 约束以包含 dead_letter
-- 新增 error_category 字段用于失败分类

-- 1. 移除旧 CHECK 约束并添加新的（包含 dead_letter）
ALTER TABLE ingest_jobs DROP CONSTRAINT IF EXISTS ingest_jobs_status_check;
ALTER TABLE ingest_jobs ADD CONSTRAINT ingest_jobs_status_check
    CHECK (status IN ('queued', 'running', 'failed', 'done', 'dead_letter'));

-- 2. 新增错误分类字段
ALTER TABLE ingest_jobs
    ADD COLUMN IF NOT EXISTS error_category TEXT CHECK (
        error_category IS NULL OR error_category IN (
            'download_error', 'parse_error', 'embed_error',
            'index_error', 'verify_error', 'unknown'
        )
    );

-- 3. 扩展 ingest_events 的 stage 约束以覆盖完整阶段
ALTER TABLE ingest_events DROP CONSTRAINT IF EXISTS ingest_events_stage_check;
ALTER TABLE ingest_events ADD CONSTRAINT ingest_events_stage_check
    CHECK (stage IN (
        'queued', 'downloading', 'parsing', 'chunking', 'embedding',
        'indexing', 'verifying', 'done', 'failed', 'dead_letter'
    ));
