ALTER TABLE chat_workflow_runs
    ADD COLUMN IF NOT EXISTS graph_thread_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS graph_run_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS current_node TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS checkpoint_ns TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS checkpoint_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS interrupt_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS interrupt_state TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_chat_workflow_runs_graph_thread_created
    ON chat_workflow_runs(graph_thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_workflow_runs_graph_run
    ON chat_workflow_runs(graph_run_id);

CREATE TABLE IF NOT EXISTS chat_graph_interrupts (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES chat_workflow_runs(id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_graph_interrupts_run_created
    ON chat_graph_interrupts(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_graph_interrupts_user_status
    ON chat_graph_interrupts(user_id, status, created_at DESC);
