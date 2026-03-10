CREATE INDEX IF NOT EXISTS idx_chat_messages_user_role_created_desc
    ON chat_messages(user_id, role, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_role_created_desc
    ON chat_messages(role, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_message_feedback_created_desc
    ON chat_message_feedback(created_at DESC);
