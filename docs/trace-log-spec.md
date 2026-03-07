# 日志与追踪规范

本规范用于统一开发、排障和后续接入日志平台时的认知。

当前仓库的日志并不是单一格式：

- `go-api` 以可读文本日志为主
- `py-worker` 输出 JSON 结构化日志
- `py-rag-service` 输出 JSON 结构化日志
- `frontend` 由本地托管脚本写入 `logs/dev/frontend.log`

因此本规范重点说明“如何关联一次业务动作”，而不是强制所有服务长成同一种格式。

## 关联一条业务链路时优先使用的标识

### 文档入库链路

优先级从高到低：

1. `job_id`
2. `document_id`
3. `storage_key`
4. 文件名

### 问答链路

优先级从高到低：

1. `session_id`
2. `message_id`
3. `request_id`
4. 用户问题文本片段

## 各服务日志特点

| 服务 | 格式 | 重点字段 / 关键词 |
| --- | --- | --- |
| `go-api` | 文本 | `[upload]`、`[preview]`、`[delete]`、`request_id` |
| `py-worker` | JSON | `job_id`、`status`、`queue`、异常栈 |
| `py-rag-service` | JSON | `request_id`、`query_id`、`duration_ms`、`retrieval_stats` |
| `frontend` | 文本 | 前端构建日志、运行时错误、网络请求失败 |

## 推荐日志字段

如果未来继续扩展日志，建议优先统一以下字段：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | UTC 时间戳 |
| `level` | 日志级别 |
| `service` | 服务名 |
| `message` | 人类可读消息 |
| `request_id` | HTTP 请求维度标识 |
| `job_id` | 入库任务标识 |
| `document_id` | 文档标识 |
| `session_id` | 会话标识 |
| `status` | 当前业务状态 |
| `duration_ms` | 耗时 |
| `error_category` | 业务错误分类 |

## 关键日志关键词

### 上传与入库

- `[upload] request`
- `[upload] completed`
- `[upload] enqueue_failed`
- `downloading`
- `parsing`
- `chunking`
- `embedding`
- `indexing`
- `verifying`
- `dead_letter`

### 预览与编辑

- `[preview] request`
- `[preview] txt_text`
- `[preview] txt_partial`
- `[preview] url_served`
- `detected_encoding`

### 删除

- `[delete] request`
- `[delete] completed`
- `active_ingest_job`

### 问答

- `request_id`
- `query_id`
- `retrieval_stats`
- `cache_info`

## 常用日志命令

### 持续跟随上传链路

```powershell
.\logs.bat -f -s go-api py-worker
```

### 只看错误

```powershell
.\logs.bat -l ERROR -s go-api py-worker py-rag-service
```

### 按关键词过滤

```powershell
.\logs.bat -f -s go-api -k upload
.\logs.bat -f -s py-worker -k embedding
.\logs.bat -f -s go-api -k preview
```

### 导出跨服务快照

```powershell
.\scripts\aggregate-logs.ps1 -Service go-api,py-worker,frontend
```

## 页面与日志的对应关系

当前前端上传组件已经会显示：

- 当前阶段
- 最近更新时间
- `jobID`
- `documentID`
- 推荐的日志排障命令

因此最短排障路径通常是：

1. 从页面复制 `jobID` 或 `documentID`
2. 使用 `.\logs.bat -k <id>` 过滤日志
3. 如需跨服务串联，再导出 `combined_<timestamp>.log`

## 建议的排障顺序

### 上传问题

1. `go-api` 是否打印 `[upload] completed`
2. `py-worker` 是否拿到 `job_id`
3. 当前卡在哪个阶段
4. 是否有 `error_category`

### 预览问题

1. `go-api` 是否打印 `[preview] request`
2. `detected_encoding` 是什么
3. 是否进入 `txt_partial` 或 `url_served`

### 问答问题

1. `go-api` 是否成功转发请求
2. `py-rag-service` 是否打印 `request_id`
3. `duration_ms` 是否异常偏高

## 未来接入 ELK / Loki / Datadog 时的建议

- 保留当前 JSON 字段命名，不要在不同 Python 服务里随意改名
- 给 Go API 增补结构化字段时，优先兼容现有关键词，如 `job_id`、`document_id`
- 所有服务统一输出 UTC 时间
- 不要在日志里打印密钥、Token、`.env` 原文和完整外部响应体
