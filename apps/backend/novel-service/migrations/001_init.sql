CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS novel_libraries (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS novel_documents (
    id UUID PRIMARY KEY,
    library_id UUID NOT NULL REFERENCES novel_libraries(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    volume_label TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    status TEXT NOT NULL,
    chapter_count INTEGER NOT NULL DEFAULT 0,
    scene_count INTEGER NOT NULL DEFAULT 0,
    passage_count INTEGER NOT NULL DEFAULT 0,
    stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS novel_document_events (
    id BIGSERIAL PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES novel_documents(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS novel_chapters (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES novel_documents(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS novel_scenes (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES novel_documents(id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES novel_chapters(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    scene_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    search_text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS novel_passages (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES novel_documents(id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES novel_chapters(id) ON DELETE CASCADE,
    scene_id UUID NOT NULL REFERENCES novel_scenes(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    scene_index INTEGER NOT NULL,
    passage_index INTEGER NOT NULL,
    text_content TEXT NOT NULL,
    search_text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS novel_event_digests (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES novel_documents(id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES novel_chapters(id) ON DELETE CASCADE,
    scene_id UUID NOT NULL REFERENCES novel_scenes(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    scene_index INTEGER NOT NULL,
    who_text TEXT NOT NULL,
    where_text TEXT NOT NULL,
    what_text TEXT NOT NULL,
    result_text TEXT NOT NULL,
    search_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS novel_aliases (
    id BIGSERIAL PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES novel_documents(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    canonical TEXT NOT NULL,
    kind TEXT NOT NULL,
    first_chapter_index INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_novel_documents_library_id ON novel_documents(library_id);
CREATE INDEX IF NOT EXISTS idx_novel_documents_status ON novel_documents(status);
CREATE INDEX IF NOT EXISTS idx_novel_document_events_doc ON novel_document_events(document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_novel_chapters_doc ON novel_chapters(document_id, chapter_index);
CREATE INDEX IF NOT EXISTS idx_novel_chapters_title_trgm ON novel_chapters USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_novel_scenes_doc ON novel_scenes(document_id, chapter_index, scene_index);
CREATE INDEX IF NOT EXISTS idx_novel_scenes_search_trgm ON novel_scenes USING gin (search_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_novel_passages_doc ON novel_passages(document_id, chapter_index, scene_index, passage_index);
CREATE INDEX IF NOT EXISTS idx_novel_passages_search_trgm ON novel_passages USING gin (search_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_novel_event_digests_doc ON novel_event_digests(document_id, chapter_index, scene_index);
CREATE INDEX IF NOT EXISTS idx_novel_event_digests_search_trgm ON novel_event_digests USING gin (search_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_novel_aliases_doc ON novel_aliases(document_id);
CREATE INDEX IF NOT EXISTS idx_novel_aliases_alias_trgm ON novel_aliases USING gin (alias gin_trgm_ops);

