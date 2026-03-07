# API 总览

本文件是面向人阅读的 API 说明，目标是帮助你在几分钟内理解：

- 如何认证
- 资源模型是什么
- 上传和问答应该按什么顺序调用
- 哪些接口是公开给 Web Console 使用的

如果你需要机器可读契约，请使用 [openapi.yaml](openapi.yaml)。

## 1. 服务边界

### Go API Gateway

默认本地地址：`http://localhost:8080`

职责：

- 登录认证
- 知识库与文档管理
- 上传编排
- 文档预览与在线修改
- 会话与消息持久化
- 问答请求转发

除 `/healthz` 外，公开业务接口均挂在 `/v1` 前缀下。

### Python RAG Service

默认本地地址：`http://localhost:8000`

职责：

- 检索
- 重排
- 答案生成
- 流式输出

它通常由 Go API 代理访问，不建议前端直连。

## 2. 认证模型

### 登录

`POST /v1/auth/login`

请求体：

```json
{
  "email": "admin@local",
  "password": "ChangeMe123!"
}
```

成功响应：

```json
{
  "access_token": "<token>",
  "token_type": "Bearer",
  "expires_in": 7200,
  "user": {
    "user_id": "11111111-1111-1111-1111-111111111111",
    "role": "admin",
    "email": "admin@local"
  }
}
```

后续请求头：

```http
Authorization: Bearer <access_token>
```

### 角色

| 角色 | 能力 |
| --- | --- |
| `admin` | 聊天 + 知识库/文档管理 |
| `member` | 仅聊天 |

## 3. 资源模型

### Corpus

知识库容器，包含多个文档。

关键字段：

- `id`
- `name`
- `description`
- `owner_user_id`
- `created_at`

### Document

知识库中的单个文档。

关键字段：

- `id`
- `corpus_id`
- `file_name`
- `file_type`
- `size_bytes`
- `status`
- `created_at`

文档状态：

- `uploaded`
- `indexing`
- `ready`
- `failed`

### Ingest Job

表示一次入库处理过程。

关键字段：

- `id`
- `document_id`
- `status`
- `progress`
- `error_message`
- `error_category`
- `updated_at`

任务状态：

- `queued`
- `running`
- `done`
- `failed`
- `dead_letter`

### Ingest Event

表示入库过程中的阶段事件。

关键字段：

- `job_id`
- `stage`
- `message`
- `created_at`

## 4. 端点一览

### 健康检查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 基础或深度健康检查 |

### 认证

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/v1/auth/login` | 登录并获取 Bearer Token |

### 知识库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/v1/corpora` | 获取知识库列表 |
| `POST` | `/v1/corpora` | 创建知识库，仅 Admin |
| `DELETE` | `/v1/corpora/{corpus_id}` | 删除单个知识库，仅 Admin |
| `POST` | `/v1/corpora/batch-delete` | 批量删除知识库，仅 Admin |

### 文档

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/v1/corpora/{corpus_id}/documents` | 获取知识库下文档列表 |
| `GET` | `/v1/documents/{document_id}` | 获取文档详情 |
| `GET` | `/v1/documents/{document_id}/events` | 获取文档处理时间线 |
| `GET` | `/v1/documents/{document_id}/preview` | 获取预览内容或预签名 URL |
| `PUT` | `/v1/documents/{document_id}/content` | 在线修改小型 TXT |
| `DELETE` | `/v1/documents/{document_id}` | 删除文档，仅 Admin |
| `POST` | `/v1/documents/upload-url` | 申请预签名上传地址 |
| `POST` | `/v1/documents/upload` | 确认上传完成并创建入库任务 |
| `GET` | `/v1/ingest-jobs/{job_id}` | 查询入库任务状态 |

### 管理与排障
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/v1/admin/logs` | 管理员查看聚合日志；运行环境不支持容器日志时自动回退到持久化入库事件 |

### 会话与问答

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/v1/chat/sessions` | 创建会话 |
| `GET` | `/v1/chat/sessions` | 获取会话列表 |
| `GET` | `/v1/chat/sessions/{session_id}/messages` | 获取会话消息历史 |
| `POST` | `/v1/chat/sessions/{session_id}/messages` | 发送非流式消息 |
| `POST` | `/v1/chat/sessions/{session_id}/messages/stream` | 发送流式消息 |
| `POST` | `/v1/chat/messages/{message_id}/feedback` | 记录消息反馈 |

### Python RAG Service 内部接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/v1/rag/query` | 非流式检索问答 |
| `GET` | `/v1/rag/query/stream` | GET 方式流式问答 |
| `POST` | `/v1/rag/query/stream` | POST 方式流式问答 |

## 5. 推荐调用顺序

### 上传文档

```text
1. POST /v1/auth/login
2. POST /v1/documents/upload-url
3. PUT <upload_url> 到 MinIO
4. POST /v1/documents/upload
5. GET /v1/ingest-jobs/{job_id}
6. GET /v1/documents/{document_id}/events
```

### 发起问答

```text
1. POST /v1/auth/login
2. POST /v1/chat/sessions
3. POST /v1/chat/sessions/{session_id}/messages 或 /stream
4. GET /v1/chat/sessions/{session_id}/messages
5. POST /v1/chat/messages/{message_id}/feedback
```

### 5.1 查看管理日志

`GET /v1/admin/logs`

常用查询参数：

- `service`: 逗号分隔的服务名，例如 `go-api,py-worker,frontend`
- `keyword`: 关键词过滤，支持 `job_id`、`document_id`、文件名、阶段名等
- `tail`: 返回最近 N 行，默认 `100`，最大 `2000`

响应字段补充：

- `lines`: 日志行数组
- `count`: 实际返回行数
- `notes`: 当前日志来源说明；当运行环境无法直接访问 `docker compose logs` 时，这里会提示已降级为持久化事件回退

## 6. 文档上传接口说明

### 6.1 申请上传地址

`POST /v1/documents/upload-url`

请求体：

```json
{
  "corpus_id": "550e8400-e29b-41d4-a716-446655440000",
  "file_name": "example.txt",
  "file_type": "txt",
  "size_bytes": 1024
}
```

响应体：

```json
{
  "upload_url": "http://localhost:19000/...",
  "storage_key": "raw/user/corpus/file.txt"
}
```

### 6.2 确认上传完成

`POST /v1/documents/upload`

请求体：

```json
{
  "corpus_id": "550e8400-e29b-41d4-a716-446655440000",
  "storage_key": "raw/user/corpus/file.txt",
  "file_name": "example.txt",
  "file_type": "txt",
  "size_bytes": 1024
}
```

响应体：

```json
{
  "document_id": "doc_uuid",
  "job_id": "job_uuid",
  "status": "queued",
  "message": "document metadata accepted and queued for indexing"
}
```

## 7. 文档预览接口说明

`GET /v1/documents/{document_id}/preview`

根据文件类型和体积，预览接口会返回三种模式之一：

| `preview_mode` | 适用场景 | 行为 |
| --- | --- | --- |
| `text` | 小型 TXT | 返回完整文本，允许在线编辑 |
| `partial` | 较大 TXT | 返回只读文本预览，可能被截断 |
| `url` | PDF / DOCX / 超大文件 | 返回预签名 URL |

### `text` 示例

```json
{
  "document": { "id": "doc_uuid" },
  "preview_mode": "text",
  "editable": true,
  "text": "文档内容",
  "content_type": "text/plain; charset=utf-8",
  "detected_encoding": "utf-8",
  "truncated": false
}
```

### `partial` 示例

```json
{
  "document": { "id": "doc_uuid" },
  "preview_mode": "partial",
  "editable": false,
  "text": "部分预览内容",
  "content_type": "text/plain; charset=utf-8",
  "detected_encoding": "gb18030",
  "truncated": true,
  "max_partial_bytes": 10485760
}
```

## 8. 聊天接口作用域说明

问答请求中的 `scope` 是核心结构：

```json
{
  "mode": "single",
  "corpus_ids": ["550e8400-e29b-41d4-a716-446655440000"],
  "document_ids": [],
  "allow_common_knowledge": false
}
```

约束：

- `mode=single` 时必须且只能有一个 `corpus_id`
- `mode=multi` 时至少包含两个 `corpus_id`
- `document_ids` 如果提供，必须属于对应知识库且状态为 `ready`

## 9. 错误模型

错误响应统一为 JSON：

```json
{
  "error": "human readable message",
  "code": "invalid_input",
  "detail": null,
  "trace_id": ""
}
```

常见状态码：

| 状态码 | 含义 |
| --- | --- |
| `400` | 参数错误 |
| `401` | 未登录或 Token 失效 |
| `403` | 权限不足 |
| `404` | 资源不存在 |
| `409` | 状态冲突，例如入库仍在进行 |
| `500` | 服务端错误 |
| `503` | 下游不可用，例如 RAG 服务或队列不可用 |

## 10. 和前端实现有关的约定

- Web Console 默认通过 `/v1` 调用 Go API
- 上传完成后，前端会同时轮询 `/v1/ingest-jobs/{job_id}` 与 `/v1/documents/{document_id}/events`
- 在线修改只对小型 TXT 文档开放
- 流式问答优先走 `/v1/chat/sessions/{session_id}/messages/stream`

## 11. 进一步阅读

- [OpenAPI 契约](openapi.yaml)
- [架构说明](assets/architecture/architecture-seq.md)
- [运行手册](runbook.md)
