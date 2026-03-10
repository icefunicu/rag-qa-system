# API 规范

本文档只记录当前仓库已经实现且和本次 LangChain 深度集成直接相关的公共契约。

## 1. 健康检查

### `GET /healthz`

- 用于进程存活探针
- 正常返回 `200 {"status":"ok"}`

### `GET /readyz`

- `gateway` 会检查数据库、`kb-service` 和 LLM 配置状态
- `kb-service` 会检查数据库、对象存储和 Qdrant / vector store
- 任一关键依赖未就绪时返回 `503`

## 2. 认证

### `POST /api/v1/auth/login`

```json
{
  "email": "admin@local",
  "password": "ChangeMe123!"
}
```

响应会返回：

- `access_token`
- `token_type`
- `user`

## 3. 统一聊天

### `POST /api/v1/chat/sessions`

创建会话并持久化默认 `scope` 与 `execution_mode`。

请求示例：

```json
{
  "title": "报销问答",
  "execution_mode": "grounded",
  "scope": {
    "mode": "single",
    "corpus_ids": ["kb:uuid-1"],
    "document_ids": [],
    "allow_common_knowledge": false
  }
}
```

### `PATCH /api/v1/chat/sessions/{id}`

- 可更新 `title`
- 可更新 `scope`
- 可更新 `execution_mode`

### `POST /api/v1/chat/sessions/{id}/messages`

请求头：

- `Authorization: Bearer <token>`
- `Idempotency-Key: <optional>`

请求体：

```json
{
  "question": "报销审批需要哪些角色签字？",
  "execution_mode": "agent",
  "scope": {
    "mode": "multi",
    "corpus_ids": ["kb:uuid-1", "kb:uuid-2"],
    "document_ids": [],
    "allow_common_knowledge": false
  }
}
```

返回关键字段：

- `answer`
- `answer_mode`
- `execution_mode`
- `strategy_used`
- `evidence_status`
- `grounding_score`
- `refusal_reason`
- `citations`
- `evidence_path`
- `retrieval`
- `latency`
- `cost`
- `trace_id`
- `message`

### `POST /api/v1/chat/sessions/{id}/messages/stream`

- SSE 主顺序固定为 `metadata -> citation -> answer -> message -> done`
- `metadata` 中会返回 `execution_mode`
- `agent` 模式下 `strategy_used` 为 `agent_grounded_qa`

## 4. `execution_mode` 说明

适用接口：

- `POST /api/v1/chat/sessions`
- `PATCH /api/v1/chat/sessions/{id}`
- `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/chat/sessions/{id}/messages/stream`

可选值：

- `grounded`
- `agent`

约束：

- 默认值是 `grounded`
- `agent` 只改变统一聊天入口的内部检索编排，不新增独立 API
- `agent` 仍然必须在当前 `scope` 内检索，且最终答案仍走 grounded answer 链

## 5. 知识库检索与问答

### `POST /api/v1/kb/retrieve`

返回：

- `items`
- `retrieval`
- `trace_id`

说明：

- 内部已经切换到 LangChain `Document` + `langchain-qdrant`
- 对外响应仍保持原有 evidence 结构

### `POST /api/v1/kb/query`

返回关键字段：

- `answer`
- `answer_mode`
- `citations`
- `retrieval`
- `trace_id`

### `POST /api/v1/kb/query/stream`

- SSE 顺序保持 `metadata -> citation -> answer -> done`
- 该接口仍然是严格 grounded，不启用 `common knowledge` 兜底，也不启用 `agent`

## 6. 上传与 ingest

推荐路径：

- `POST /api/v1/kb/uploads`
- `POST /api/v1/kb/uploads/{upload_id}/parts/presign`
- `POST /api/v1/kb/uploads/{upload_id}/complete`
- `GET /api/v1/kb/ingest-jobs/{job_id}`
- `POST /api/v1/kb/ingest-jobs/{job_id}/retry`

兼容路径仍保留：

- `POST /api/v1/kb/documents/upload`

## 7. 本地运行建议

```powershell
make preflight
make init
make up
make smoke-eval
```

## 8. 安全与背压补充

以下补充以当前仓库实际实现为准。

### 8.1 `safety` 字段

新增可选字段 `safety`，会出现在：

- `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/chat/sessions/{id}/messages/stream` 的 `metadata`
- `POST /api/v1/kb/query`
- `POST /api/v1/kb/query/stream` 的 `metadata`

字段结构：

```json
{
  "risk_level": "low | medium | high",
  "blocked": false,
  "action": "allow | warn | fallback | refuse",
  "reason_codes": ["prompt_injection_user"],
  "source_types": ["user"],
  "matched_signals": ["instruction_override"]
}
```

说明：

- `medium` 风险仍可能返回正常回答，但前端应提示 warning
- `high` 风险会触发阻断或 fallback

### 8.2 `refusal_reason`

`refusal_reason` 新增：

- `unsafe_prompt`

表示当前请求命中了提示注入/提示泄露/绕过引用类安全规则。

### 8.3 背压错误

以下高成本接口增加进程内 in-flight 背压保护：

- `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/chat/sessions/{id}/messages/stream`
- `POST /api/v1/kb/query`
- `POST /api/v1/kb/query/stream`

超限时返回：

```json
{
  "detail": "too many in-flight requests",
  "code": "too_many_inflight_requests",
  "trace_id": "..."
}
```

同时带响应头：

- `Retry-After: 1`

### 8.4 新增配置项

gateway：

- `GATEWAY_CHAT_MAX_IN_FLIGHT_GLOBAL`，默认 `32`
- `GATEWAY_CHAT_MAX_IN_FLIGHT_PER_USER`，默认 `4`

kb-service：

- `KB_QUERY_MAX_IN_FLIGHT_GLOBAL`，默认 `64`
- `KB_QUERY_MAX_IN_FLIGHT_PER_USER`，默认 `8`
