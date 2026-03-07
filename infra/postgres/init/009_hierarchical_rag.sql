CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS doc_sections (
    id TEXT PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    section_index INTEGER NOT NULL,
    section_title TEXT NOT NULL DEFAULT '',
    section_summary TEXT NOT NULL DEFAULT '',
    normalized_title TEXT NOT NULL DEFAULT '',
    normalized_summary TEXT NOT NULL DEFAULT '',
    search_terms TEXT[] NOT NULL DEFAULT '{}',
    page_or_loc TEXT NOT NULL DEFAULT '',
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    chunk_start_index INTEGER NOT NULL DEFAULT 0,
    chunk_end_index INTEGER NOT NULL DEFAULT 0,
    qdrant_point_id TEXT NOT NULL DEFAULT '',
    ingest_profile TEXT NOT NULL DEFAULT 'default',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, section_index)
);

ALTER TABLE doc_chunks
    ADD COLUMN IF NOT EXISTS section_id TEXT,
    ADD COLUMN IF NOT EXISTS section_title TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS normalized_text TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS search_terms TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS char_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ingest_profile TEXT NOT NULL DEFAULT 'default';

UPDATE doc_chunks
SET normalized_text = lower(regexp_replace(chunk_text, '\s+', ' ', 'g'))
WHERE normalized_text = '';

UPDATE doc_chunks
SET char_count = char_length(chunk_text)
WHERE char_count = 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'doc_chunks_section_id_fkey'
    ) THEN
        ALTER TABLE doc_chunks
        ADD CONSTRAINT doc_chunks_section_id_fkey
        FOREIGN KEY (section_id) REFERENCES doc_sections (id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_doc_sections_document_id ON doc_sections (document_id);
CREATE INDEX IF NOT EXISTS idx_doc_sections_document_section ON doc_sections (document_id, section_index);
CREATE INDEX IF NOT EXISTS idx_doc_sections_search_terms ON doc_sections USING GIN (search_terms);
CREATE INDEX IF NOT EXISTS idx_doc_sections_normalized_title_trgm ON doc_sections USING GIN (normalized_title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_doc_sections_normalized_summary_trgm ON doc_sections USING GIN (normalized_summary gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_document_section_chunk ON doc_chunks (document_id, section_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_search_terms ON doc_chunks USING GIN (search_terms);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_normalized_text_trgm ON doc_chunks USING GIN (normalized_text gin_trgm_ops);
