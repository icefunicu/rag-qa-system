# API 说明

本文档描述当前双内核系统和独立 AI 对话能力的公开接口。统一入口由 `gateway` 暴露，前端默认只访问 `gateway`。

## 服务边界

### Gateway

- 默认地址：`http://localhost:8080`
- 可通过根目录 `.env` 中的 `GATEWAY_HOST_PORT` 覆盖宿主机端口
- 职责：登录认证、身份透传、路由聚合、AI 对话代理
- 对外前缀：`/api/v1`

### Novel Service

- 默认地址：`http://localhost:8100`
- 可通过根目录 `.env` 中的 `NOVEL_HOST_PORT` 覆盖宿主机端口
- 职责：小说库管理、TXT 上传、章节/场景索引、剧情问答
- 通过 `gateway` 暴露为 `/api/v1/novel/*`

### KB Service

- 默认地址：`http://localhost:8300`
- 可通过根目录 `.env` 中的 `KB_HOST_PORT` 覆盖宿主机端口；容器内服务端口仍为 `8200`
- 职责：知识库管理、多文件上传、事实问答
- 通过 `gateway` 暴露为 `/api/v1/kb/*`

## 认证

### 登录

`POST /api/v1/auth/login`

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
  "token_type": "bearer",
  "user": {
    "id": "11111111-1111-1111-1111-111111111111",
    "email": "admin@local",
    "role": "admin"
  }
}
```

后续请求头：

```http
Authorization: Bearer <access_token>
```

### 当前用户

`GET /api/v1/auth/me`

## AI 对话接口

### 获取 AI 配置状态

`GET /api/v1/ai/config`

响应示例：

```json
{
  "enabled": true,
  "configured": true,
  "provider": "openai-compatible",
  "model": "qwen3.5-plus",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "timeout_seconds": 120,
  "default_temperature": 0.7,
  "default_max_tokens": 2048,
  "has_system_prompt": true
}
```

### 发起 AI 对话

`POST /api/v1/ai/chat`

请求体：

```json
{
  "messages": [
    {
      "role": "user",
      "content": "帮我整理一份项目上线检查清单。"
    }
  ],
  "system_prompt": "你是一个简洁、可靠的中文助手。",
  "temperature": 0.7,
  "max_tokens": 2048
}
```

响应体：

```json
{
  "answer": "可以按环境、部署、监控三部分检查……",
  "reasoning": "",
  "provider": "openai-compatible",
  "model": "qwen3.5-plus",
  "finish_reason": "stop",
  "usage": {
    "total_tokens": 1234
  }
}
```

约束：

- `messages` 至少 1 条，最多 32 条
- 单条 `content` 最长 12000 字符
- 总消息内容最长 50000 字符
- 支持的 `role` 仅有 `system`、`user`、`assistant`

## 小说接口

### 小说库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/novel/libraries` | 创建小说库 |
| `GET` | `/api/v1/novel/libraries` | 获取小说库列表 |
| `GET` | `/api/v1/novel/libraries/{library_id}/documents` | 获取小说库下文档列表 |

### 小说文档上传

`POST /api/v1/novel/documents/upload`

请求类型：`multipart/form-data`

表单字段：

- `library_id`
- `title`
- `volume_label`
- `spoiler_ack`
- `file`

约束：

- 首版仅接受 `.txt`
- 成功后文档先进入 `uploaded`
- 后台继续推进到 `fast_index_ready` 和 `ready`

### 小说文档详情与事件

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/novel/documents/{document_id}` | 获取文档详情 |
| `GET` | `/api/v1/novel/documents/{document_id}/events` | 获取事件时间线 |

小说状态枚举：

- `uploaded`
- `parsing`
- `fast_index_ready`
- `enhancing`
- `ready`
- `failed`

### 小说问答

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/novel/query` | 非流式问答 |
| `POST` | `/api/v1/novel/query/stream` | SSE 流式问答 |

SSE 事件约定，适用于 `/api/v1/novel/query/stream` 与 `/api/v1/kb/query/stream`：

- `metadata`：先返回策略、证据状态、拒答原因
- `citation`：返回 0 到多条引用
- `answer`：可能返回多次，`answer` 字段按累积文本递增，最后一条为完整答案
- `done`：流式输出结束

请求体：

```json
{
  "library_id": "library-id",
  "question": "第 12 章发生了什么？",
  "document_ids": [],
  "debug": false
}
```

小说 `strategy_used` 可能取值：

- `entity_detail`
- `chapter_summary`
- `plot_event`
- `plot_causal`
- `character_arc`
- `setting_theme`

响应公共字段：

- `answer`
- `strategy_used`
- `evidence_status`
- `grounding_score`
- `refusal_reason`
- `citations[]`

`citations[]` 字段：

- `unit_id`
- `document_id`
- `section_title`
- `char_range`
- `quote`

## 企业库接口

### 知识库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/kb/bases` | 创建知识库 |
| `GET` | `/api/v1/kb/bases` | 获取知识库列表 |
| `GET` | `/api/v1/kb/bases/{base_id}/documents` | 获取知识库下文档列表 |

### 企业库文档上传

`POST /api/v1/kb/documents/upload`

请求类型：`multipart/form-data`

表单字段：

- `base_id`
- `category`
- `files`

约束：

- 接受 `.txt`、`.pdf`、`.docx`
- 支持一次上传多个文件

### 企业库文档详情与事件

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/kb/documents/{document_id}` | 获取文档详情 |
| `GET` | `/api/v1/kb/documents/{document_id}/events` | 获取事件时间线 |

### 企业库问答

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/kb/query` | 非流式问答 |
| `POST` | `/api/v1/kb/query/stream` | SSE 流式问答 |

企业库 `strategy_used` 可能取值：

- `exact_match`
- `section_summary`
- `cross_doc_answer`
- `policy_extract`

## 错误模型

常见状态码：

| 状态码 | 含义 |
| --- | --- |
| `400` | 参数错误或文件类型不支持 |
| `401` | 未登录或 token 无效 |
| `403` | 权限不足 |
| `404` | 资源不存在 |
| `500` | 服务内部错误 |
| `502` | 网关调用下游或模型服务失败 |
| `503` | 下游服务或 AI 对话未配置 |

## 推荐调用顺序

### AI 对话

```text
1. POST /api/v1/auth/login
2. GET  /api/v1/ai/config
3. POST /api/v1/ai/chat
```

### 小说线路

```text
1. POST /api/v1/auth/login
2. POST /api/v1/novel/libraries
3. POST /api/v1/novel/documents/upload
4. GET  /api/v1/novel/documents/{document_id}
5. GET  /api/v1/novel/documents/{document_id}/events
6. POST /api/v1/novel/query 或 /api/v1/novel/query/stream
```

### 企业库线路

```text
1. POST /api/v1/auth/login
2. POST /api/v1/kb/bases
3. POST /api/v1/kb/documents/upload
4. GET  /api/v1/kb/documents/{document_id}
5. GET  /api/v1/kb/documents/{document_id}/events
6. POST /api/v1/kb/query 或 /api/v1/kb/query/stream
```
