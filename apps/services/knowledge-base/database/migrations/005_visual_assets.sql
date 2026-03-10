CREATE TABLE IF NOT EXISTS kb_visual_assets (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    asset_index INTEGER NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'embedded',
    page_number INTEGER NULL,
    file_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    storage_key TEXT NOT NULL DEFAULT '',
    thumbnail_key TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    ocr_text TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, asset_index)
);

CREATE INDEX IF NOT EXISTS idx_kb_visual_assets_document_created
    ON kb_visual_assets(document_id, asset_index ASC);
CREATE INDEX IF NOT EXISTS idx_kb_visual_assets_status
    ON kb_visual_assets(status, created_at DESC);

ALTER TABLE kb_sections
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'text';
ALTER TABLE kb_sections
    ADD COLUMN IF NOT EXISTS page_number INTEGER NULL;
ALTER TABLE kb_sections
    ADD COLUMN IF NOT EXISTS asset_id UUID NULL REFERENCES kb_visual_assets(id) ON DELETE SET NULL;

ALTER TABLE kb_chunks
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'text';
ALTER TABLE kb_chunks
    ADD COLUMN IF NOT EXISTS page_number INTEGER NULL;
ALTER TABLE kb_chunks
    ADD COLUMN IF NOT EXISTS asset_id UUID NULL REFERENCES kb_visual_assets(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_kb_sections_asset_id ON kb_sections(asset_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_asset_id ON kb_chunks(asset_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_source_kind ON kb_chunks(source_kind, document_id);
