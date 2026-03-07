CREATE TABLE IF NOT EXISTS answer_feedback (
    id UUID PRIMARY KEY,
    message_id UUID NOT NULL REFERENCES chat_messages (id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    tags TEXT[],
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (message_id)
);
