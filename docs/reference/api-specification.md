# API 规范

本文档是仓库唯一的 API 文档，覆盖当前项目对前端开放的核心接口，包括：

- 认证与健康检查
- 统一聊天与工作流
- 知识库、文档上传、检索与调试
- 连接器与同步调度
- Prompt Template 与 Agent Profile
- 运营分析看板

默认本地地址：

- Gateway：`http://localhost:8080`
- KB Service：`http://localhost:8300`

## 1. 通用约定

### 认证

除健康检查外，大多数业务接口都需要：

```http
Authorization: Bearer <ACCESS_TOKEN>
```

登录接口：

- `POST /api/v1/auth/login`

### 内容类型

- 普通接口：`application/json`
- 流式问答：`text/event-stream`

### 常见错误码

| HTTP 状态码 | `code` | 含义 |
|---|---|---|
| `400` | `analytics_view_invalid` / 其他业务错误 | 请求参数合法但业务不成立 |
| `401` | `unauthorized` | 未登录或 token 无效 |
| `403` | `permission_denied` | 权限不足 |
| `404` | `not_found` | 资源不存在 |
| `409` | `conflict` | 状态冲突或重复操作 |
| `422` | `validation_error` | 参数校验失败 |
| `429` | `too_many_inflight_requests` | 高成本接口触发背压保护 |
| `500` | `internal_error` | 服务内部异常 |
| `502` | `upstream_error` | Gateway 访问上游服务失败 |

## 2. 健康检查

### `GET /healthz`

- 用于存活探针
- 返回 `200 {"status":"ok"}`

### `GET /readyz`

- Gateway 会检查数据库、KB Service 与模型配置
- KB Service 会检查数据库、对象存储与 Qdrant
- 关键依赖未就绪时返回 `503`

## 3. 认证

### `POST /api/v1/auth/login`

请求示例：

```json
{
  "email": "admin@local",
  "password": "ChangeMe123!"
}
```

响应关键字段：

- `access_token`
- `token_type`
- `user`

## 4. 统一聊天与工作流

### `v2` LangGraph 运行时

新增基于 LangGraph 的 `thread / run / interrupt` 语义：

- `POST /api/v2/chat/threads`
- `GET /api/v2/chat/threads/{thread_id}`
- `GET /api/v2/chat/threads/{thread_id}/messages`
- `POST /api/v2/chat/threads/{thread_id}/runs`
- `GET /api/v2/chat/runs/{run_id}`
- `POST /api/v2/chat/runs/{run_id}/resume`
- `POST /api/v2/chat/interrupts/{interrupt_id}/submit`

`v2` 关键字段：

- `status`
- `run`
- `interrupt`
- `step_events`
- `verification`
- `thread_id`

说明：

- `v2` 的 `run` 由 LangGraph checkpoint 驱动，可在 `interrupted` 状态下继续恢复
- `interrupt` 用于人工澄清和证据不足场景
- `v1` 的 `workflow_run` 仍保留，但实现上已退化为运行投影/审计视图

运行时依赖基线：

- `api-gateway` 当前固定使用 `langgraph==0.5.4` 与 `langgraph-checkpoint-postgres==2.0.25`
- `knowledge-base` 当前固定使用 `langgraph==0.5.4`
- 若部署环境仍使用 `langgraph < 0.5`，`checkpoint-postgres` 会发出兼容性 `DeprecationWarning`

### `POST /api/v1/chat/sessions`

创建聊天会话。

请求示例：

```json
{
  "title": "报销问答",
  "execution_mode": "agent",
  "scope": {
    "mode": "multi",
    "corpus_ids": ["kb:uuid-1", "kb:uuid-2"],
    "document_ids": [],
    "allow_common_knowledge": false,
    "agent_profile_id": "profile-uuid",
    "prompt_template_id": "template-uuid"
  }
}
```

### `PATCH /api/v1/chat/sessions/{id}`

可更新字段：

- `title`
- `scope`
- `execution_mode`

### `POST /api/v1/chat/sessions/{id}/messages`

发送一条消息并等待完整回答。

可选请求头：

- `Idempotency-Key: <value>`

响应关键字段：

- `answer`
- `answer_mode`
- `execution_mode`
- `strategy_used`
- `evidence_status`
- `grounding_score`
- `refusal_reason`
- `safety`
- `citations`
- `retrieval`
- `latency`
- `cost`
- `trace_id`
- `llm_trace`
- `message`
- `workflow_run`

### `POST /api/v1/chat/sessions/{id}/messages/stream`

SSE 流式回答，事件顺序：

- `metadata`
- `citation`
- `answer`
- `message`
- `done`

`metadata` 会额外包含：

- `execution_mode`
- `workflow_run`
- `resume`
- `retrieval`
- `safety`

### `GET /api/v1/chat/sessions/{id}/workflow-runs`

列出当前会话下的工作流执行记录。

### `GET /api/v1/chat/workflow-runs/{run_id}`

查询单次工作流执行详情。

### `POST /api/v1/chat/workflow-runs/{run_id}/retry`

重试失败的工作流运行。

当前约束：

- 仅允许重试 `status=failed`
- 默认复用原始 `scope_snapshot`
- 会创建新的 `message` 和新的 `workflow_run`

### `PUT /api/v1/chat/sessions/{id}/messages/{message_id}/feedback`

提交用户反馈。

请求示例：

```json
{
  "verdict": "up",
  "reason_code": "grounded",
  "notes": "引用充分"
}
```

## 5. `execution_mode`

适用接口：

- `POST /api/v1/chat/sessions`
- `PATCH /api/v1/chat/sessions/{id}`
- `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/chat/sessions/{id}/messages/stream`

可选值：

- `grounded`
- `agent`

说明：

- 默认值为 `grounded`
- `agent` 仍受当前 `scope` 约束
- `agent` 模式的工具能力由 Agent Profile 控制

当前已落地工具：

- `search_scope`
- `list_scope_documents`
- `search_corpus`
- `calculator`

## 6. 知识库与文档管理

### 知识库

- `POST /api/v1/kb/bases`
- `GET /api/v1/kb/bases`
- `GET /api/v1/kb/bases/{base_id}`
- `PATCH /api/v1/kb/bases/{base_id}`
- `DELETE /api/v1/kb/bases/{base_id}`

### 文档

- `GET /api/v1/kb/bases/{base_id}/documents`
- `GET /api/v1/kb/documents/{document_id}`
- `GET /api/v1/kb/documents/{document_id}/versions`
- `GET /api/v1/kb/documents/{document_id}/versions/{version_id}/content`
- `GET /api/v1/kb/documents/{document_id}/versions/{version_id}/diff`
- `PATCH /api/v1/kb/documents/{document_id}`
- `DELETE /api/v1/kb/documents/{document_id}`
- `GET /api/v1/kb/documents/{document_id}/events`
- `GET /api/v1/kb/documents/{document_id}/visual-assets`

文档对象新增的版本治理字段：

- `version_family_key`：同一份业务文档的版本家族标识。
- `version_label`：面向业务展示的版本标签，例如 `v2`、`2026-Q1`。
- `version_number`：整数版本号，便于排序和治理。
- `version_status`：当前支持 `active | draft | superseded | archived`。
- `is_current_version`：是否作为默认检索候选版本。
- `effective_from` / `effective_to`：版本生效时间窗口。
- `supersedes_document_id`：当前版本替代的是哪一个旧文档。
- `effective_now`：服务端计算字段，表示当前时刻是否处于生效窗口。

### `GET /api/v1/kb/documents/{document_id}/versions`

- 返回当前文档所在版本家族的全部版本。
- 默认按 `is_current_version DESC, version_number DESC, created_at DESC` 排序。
- 适合前端做“当前版本 + 历史版本”面板，也适合运营排查旧版为何还被引用。

### `GET /api/v1/kb/documents/{document_id}/versions/{version_id}/content`

- 返回指定历史版本或当前版本的正文内容。
- 输出里包含 `sections[*].text_content` 和拼接后的 `full_text`，方便前端做“查看历史版本原文”。
- `include_disabled=true` 时也会返回被人工禁用的切片，适合治理排查。

### `GET /api/v1/kb/documents/{document_id}/versions/{version_id}/diff`

- 默认把 `version_id` 指向的版本和当前页面文档做差异对比。
- 也支持通过 `compare_to_document_id` 指定另一个同家族版本做对比。
- 返回：
  - `source`
  - `target`
  - `diff.summary`
  - `diff.diff_text`
- `diff.summary` 当前包含 `added_chunks`、`removed_chunks`、`modified_chunks`、`changed_sections`，便于直接向业务方解释“新版具体改了哪些地方”。

### `PATCH /api/v1/kb/documents/{document_id}`

除 `file_name`、`category` 外，还支持以下版本治理字段：

```json
{
  "version_family_key": "expense-policy",
  "version_label": "2026-Q1",
  "version_number": 3,
  "version_status": "active",
  "is_current_version": true,
  "effective_from": "2026-03-11T00:00:00Z",
  "effective_to": null,
  "supersedes_document_id": "old-doc-uuid"
}
```

规则说明：

- `is_current_version=true` 时，`version_status` 必须是 `active`。
- 如果 `effective_from` 在未来，文档暂时不能标记为 current；建议先保持 `active + is_current_version=false`，等正式切换时再升 current。
- 同一 `base_id + version_family_key` 下切换 current 版本时，服务端会自动取消同家族其他 current 标记，并把仍是 `active` 的旧版本降为 `superseded`。
- `supersedes_document_id` 必须和当前文档属于同一个知识库。

常见文档状态：

- `uploaded`
- `parsing_fast`
- `fast_index_ready`
- `hybrid_ready`
- `ready`

## 7. 上传与 Ingest

推荐上传链路：

- `POST /api/v1/kb/uploads`
- `GET /api/v1/kb/uploads/{upload_id}`
- `POST /api/v1/kb/uploads/{upload_id}/parts/presign`
- `POST /api/v1/kb/uploads/{upload_id}/complete`
- `GET /api/v1/kb/ingest-jobs/{job_id}`
- `POST /api/v1/kb/ingest-jobs/{job_id}/retry`

### `POST /api/v1/kb/uploads`

除了基础上传字段，也支持在导入时直接声明版本治理信息：

```json
{
  "base_id": "base-uuid",
  "file_name": "expense-policy-2026.pdf",
  "file_type": "pdf",
  "size_bytes": 204800,
  "category": "finance",
  "version_family_key": "expense-policy",
  "version_label": "2026-Q1",
  "version_number": 3,
  "version_status": "active",
  "is_current_version": true,
  "effective_from": "2026-03-11T00:00:00Z",
  "effective_to": null,
  "supersedes_document_id": "doc-previous-version"
}
```

导入时的默认行为：

- 如果没有提供任何版本字段，系统会把该文档当作一个独立版本家族，默认生成 `v1`、`version_number=1`、`is_current_version=true`。
- 如果提供了 `supersedes_document_id`，但没有显式传 `version_family_key` / `version_number` / `version_label`，服务端会继承旧文档的版本家族，并自动把版本号递增、版本标签补成 `vN`。

说明：

- 旧的 legacy 上传接口已移除
- 新链路统一走 upload session + multipart / complete 模型

## 8. 检索、问答与调试

### 检索

### `POST /api/v1/kb/retrieve`

纯检索接口，不触发 LLM 生成。

响应关键字段：

- `items`
- `retrieval`
- `trace_id`

### `POST /api/v2/kb/retrieve`

LangGraph 编排版检索接口。

除 `v1` 字段外，额外返回：

- `graph.engine`
- `graph.entrypoint`
- `graph.final_node`
- `graph.trace_id`

说明：

- 运行时依赖基线与 Gateway `v2` 一致，当前要求 `langgraph==0.5.4`

### `POST /api/v1/kb/retrieve/debug`

检索调试工作台接口。

用途：

- 查看 Top-K 召回结果
- 查看 rerank 分数与信号分数
- 排查 zero-hit、低质量召回和排序问题

响应关键字段：

- `query`
- `items[*].debug.rank`
- `items[*].debug.score`
- `items[*].debug.signal_scores`
- `items[*].debug.rerank_score`
- `retrieval`
- `trace_id`

### 知识库问答

### `POST /api/v2/kb/query`

LangGraph 编排版知识库问答接口。

除 `v1` 字段外，额外返回：

- `graph.engine`
- `graph.entrypoint`
- `graph.final_node`
- `graph.trace_id`

说明：

- 运行时依赖基线与 Gateway `v2` 一致，当前要求 `langgraph==0.5.4`

- `POST /api/v1/kb/query`
- `POST /api/v1/kb/query/stream`

版本选择规则：

- 当请求显式传入 `document_ids` 时，系统会严格按这些文档 ID 检索。企业用户可以手动指定旧制度、旧合同、旧手册做追溯查询。
- 当请求不传 `document_ids` 时，系统默认只在“当前生效版本”中检索，也就是同时满足：
  - `query_ready = true`
  - `source_deleted_at IS NULL`
  - `version_status = active`
  - `is_current_version = true`
  - 当前时间落在 `effective_from / effective_to` 生效窗口内
- 这条规则用于解决“旧版本和新版本同时存在时，系统默认应该选谁”的企业场景问题。

流式接口事件顺序：

- `metadata`
- `citation`
- `answer`
- `done`

## 9. Chunk 治理

### `GET /api/v1/kb/documents/{document_id}/chunks`

查看文档切片详情。

查询参数：

- `include_disabled=true|false`

### `PATCH /api/v1/kb/chunks/{chunk_id}`

人工修改切片文本，或启用 / 禁用切片。

请求示例：

```json
{
  "text_content": "更新后的切片正文",
  "disabled": false,
  "disabled_reason": "",
  "manual_note": "修正 OCR 噪音"
}
```

### `POST /api/v1/kb/chunks/{chunk_id}/split`

手动拆分单个切片。

### `POST /api/v1/kb/chunks/merge`

手动合并连续切片。

## 10. 连接器与同步

### 直接执行型接口

- `POST /api/v1/kb/connectors/local-directory/sync`
- `POST /api/v1/kb/connectors/notion/sync`

### 连接器注册表

- `GET /api/v1/kb/connectors`
- `POST /api/v1/kb/connectors`
- `GET /api/v1/kb/connectors/{connector_id}`
- `PATCH /api/v1/kb/connectors/{connector_id}`
- `DELETE /api/v1/kb/connectors/{connector_id}`
- `GET /api/v1/kb/connectors/{connector_id}/runs`
- `POST /api/v1/kb/connectors/{connector_id}/sync`
- `POST /api/v1/kb/connectors/run-due`

连接器同步的版本行为：

- 同一 `source_type + source_uri` 在 current 视角下只保留一个当前版本。
- 当连接器检测到内容哈希变化时，不再原地覆盖旧文档，而是创建一个新的文档版本，并把旧 current 版本自动降为 `superseded`。
- 当只是文件名变化或来源恢复时，仍沿用原文档更新，避免无意义地制造新版本。
- KB Service 内部的定时同步 runner 只有在存在 `schedule_enabled=true` 的连接器时才会启动；当没有任何已启用调度的连接器时，runner 会自动停掉，避免空转占用资源。

当前支持的连接器类型：

- `local_directory`
- `notion`
- `web_crawler`
- `feishu_document`
- `dingtalk_document`
- `sql_query`

说明：

- `sql_query` 通过 `dsn_env` 引用后端环境变量中的 DSN，避免在请求体中直接传递敏感连接串
- `run-due` 适合配合外部 cron / worker 做定时执行

## 11. Prompt Template 与 Agent Profile

### Prompt Template

- `GET /api/v1/platform/prompt-templates`
- `POST /api/v1/platform/prompt-templates`
- `GET /api/v1/platform/prompt-templates/{template_id}`
- `PATCH /api/v1/platform/prompt-templates/{template_id}`
- `DELETE /api/v1/platform/prompt-templates/{template_id}`

请求示例：

```json
{
  "name": "财务规范回答",
  "content": "先给结论，再列引用和风险。",
  "visibility": "public",
  "tags": ["finance", "grounded"],
  "favorite": true
}
```

### Agent Profile

- `GET /api/v1/platform/agent-profiles`
- `POST /api/v1/platform/agent-profiles`
- `GET /api/v1/platform/agent-profiles/{profile_id}`
- `PATCH /api/v1/platform/agent-profiles/{profile_id}`
- `DELETE /api/v1/platform/agent-profiles/{profile_id}`

请求示例：

```json
{
  "name": "报销制度审阅员",
  "description": "面向企业报销流程问答",
  "persona_prompt": "你是财务制度分析师，优先给出审批链和风险提示。",
  "enabled_tools": ["search_scope", "search_corpus", "calculator"],
  "default_corpus_ids": ["kb:uuid-1"],
  "prompt_template_id": "template-uuid"
}
```

## 12. 运营分析看板

项目只保留这一份看板 API 说明，不再拆出单独文档。

### Gateway 看板

#### `GET /api/v1/analytics/dashboard`

用途：

- 聚合知识库创建、文档 ready 漏斗、问答质量、反馈趋势、成本趋势
- 供前端运营看板直接渲染

权限：

- `view=personal` 需要 `chat.use`
- `view=admin` 额外需要 `platform_admin`

Query 参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `view` | `personal \| admin` | `personal` | 聚合范围 |
| `days` | `int` | `14` | 滚动时间窗口，范围 `1-90` |

响应顶层字段：

- `view`
- `days`
- `hot_terms`
- `zero_hit`
- `satisfaction`
- `usage`
- `funnel`
- `ingest_health`
- `qa_quality`
- `data_quality`

`funnel` 关键字段：

- `knowledge_bases_created`
- `documents_uploaded`
- `documents_ready`
- `chat_sessions_with_questions`
- `questions_asked`
- `answer_outcomes`
- `feedback`

`qa_quality` 关键字段：

- `summary`
- `answer_mode_distribution`
- `evidence_status_distribution`
- `zero_hit`
- `low_quality`

`data_quality` 关键字段：

- `unsupported_fields`
- `degraded_sections`

#### 请求示例

```bash
curl -X GET "http://localhost:8080/api/v1/analytics/dashboard?view=admin&days=30" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### KB Service 看板

#### `GET /api/v1/kb/analytics/dashboard`

用途：

- 为 Gateway 提供知识库创建、文档上传、`ready` 漏斗与 ingest 健康度聚合
- 也可供前端在需要时直接消费

权限：

- `view=personal` 需要 `kb.read`
- `view=admin` 需要 `kb.manage` 或平台管理员权限

Query 参数与 Gateway 保持一致：

- `view=personal|admin`
- `days=1..90`

#### 请求示例

```bash
curl -X GET "http://localhost:8300/api/v1/kb/analytics/dashboard?view=personal&days=14" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

### 指标说明

- `knowledge_bases_created`：按知识库创建时间统计
- `documents_uploaded`：按文档上传时间统计
- `documents_ready`：按文档进入 `ready` 的时间统计
- `zero_hit.selected_candidates_zero`：严格以 `selected_candidates = 0` 为准
- 顶层 `zero_hit`：兼容旧口径，命中条件是“无引用”或 `selected_candidates = 0`
- `stalled_documents`：当前非 `ready/failed` 且超过阈值未更新的文档数

### 降级行为

当 KB analytics 上游暂时不可用时，Gateway 仍可能返回 `200`，但：

- `ingest_health = null`
- `funnel` 中部分 KB 字段为 `null`
- 具体原因写入 `data_quality.degraded_sections`

## 13. 审计与运维接口

- `GET /api/v1/audit/events`
- `GET /metrics`

## 14. 背压与安全

以下高成本接口有 in-flight 背压保护：

- `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/chat/sessions/{id}/messages/stream`
- `POST /api/v1/kb/query`
- `POST /api/v1/kb/query/stream`

超限时返回：

- HTTP `429`
- `code=too_many_inflight_requests`

以下接口会返回 `safety` 字段，或在 SSE `metadata` 中返回：

- `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/chat/sessions/{id}/messages/stream`
- `POST /api/v1/kb/query`
- `POST /api/v1/kb/query/stream`

## 15. 基线验证

在仓库根目录执行：

```powershell
python scripts/quality/check-encoding.py
cd apps/web && npm run build
python -m compileall packages/python apps/services/api-gateway apps/services/knowledge-base
docker compose config --quiet
```
