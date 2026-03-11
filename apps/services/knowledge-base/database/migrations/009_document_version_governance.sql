ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS version_family_key TEXT NOT NULL DEFAULT '';
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS version_label TEXT NOT NULL DEFAULT '';
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS version_status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS is_current_version BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ NULL;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS effective_to TIMESTAMPTZ NULL;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS supersedes_document_id UUID NULL REFERENCES kb_documents(id) ON DELETE SET NULL;

UPDATE kb_documents
SET version_family_key = id::text
WHERE version_family_key = '';

UPDATE kb_documents
SET version_label = CONCAT('v', GREATEST(version_number, 1))
WHERE version_label = '';

ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS version_family_key TEXT NOT NULL DEFAULT '';
ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS version_label TEXT NOT NULL DEFAULT '';
ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS version_number INTEGER NULL;
ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS version_status TEXT NOT NULL DEFAULT '';
ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS is_current_version BOOLEAN NULL;
ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ NULL;
ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS effective_to TIMESTAMPTZ NULL;
ALTER TABLE kb_upload_sessions ADD COLUMN IF NOT EXISTS supersedes_document_id UUID NULL REFERENCES kb_documents(id) ON DELETE SET NULL;

DROP INDEX IF EXISTS idx_kb_documents_base_source_uri_unique;

CREATE INDEX IF NOT EXISTS idx_kb_documents_base_family_current
    ON kb_documents(base_id, version_family_key, is_current_version, version_status, version_number DESC);

CREATE INDEX IF NOT EXISTS idx_kb_documents_effective_window
    ON kb_documents(base_id, effective_from, effective_to);

CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_documents_base_source_uri_current_unique
    ON kb_documents(base_id, source_type, source_uri)
    WHERE source_uri <> '' AND is_current_version = TRUE;
