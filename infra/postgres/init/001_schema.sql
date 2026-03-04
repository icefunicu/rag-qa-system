CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS corpora (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    owner_user_id UUID NOT NULL REFERENCES app_users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    corpus_id UUID NOT NULL REFERENCES corpora (id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('txt', 'pdf', 'docx')),
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 524288000),
    storage_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('uploaded', 'indexing', 'ready', 'failed')),
    created_by UUID NOT NULL REFERENCES app_users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'failed', 'done')),
    progress INTEGER NOT NULL CHECK (progress >= 0 AND progress <= 100),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    created_by UUID NOT NULL REFERENCES app_users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO app_users (id, email, password_hash, role)
VALUES
    ('11111111-1111-1111-1111-111111111111', 'admin@local', 'dev-only', 'admin'),
    ('22222222-2222-2222-2222-222222222222', 'member@local', 'dev-only', 'member')
ON CONFLICT (email) DO NOTHING;

