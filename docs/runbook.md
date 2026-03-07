# 运行手册

本手册面向本地值班、演示环境维护和日常开发排障。目标是让维护者在最短时间内回答三个问题：

1. 问题发生在哪一层
2. 现在是否影响主链路
3. 该如何安全恢复

## 统一排障原则

### 先确认现象，再确认范围

- 是单个文档失败，还是全部上传都失败
- 是预览异常，还是入库结果异常
- 是聊天接口失败，还是只有某个知识库范围失败

### 先看状态，再看日志

- 页面中先看文档状态、任务进度、事件时间线
- 再用 `.\logs.bat` 或 `.\scripts\aggregate-logs.ps1` 查跨服务日志

### 不做破坏性恢复

除非你明确知道影响范围，否则不要直接删库、删卷、重置向量库。

## 第一响应清单

发现故障时，先执行：

```powershell
docker compose ps
.\logs.bat -l ERROR -s go-api py-worker py-rag-service
```

确认：

- PostgreSQL、Redis、MinIO、Qdrant 是否在线
- `go-api` 是否能接收请求
- `py-worker` 是否仍在消费队列
- `py-rag-service` 是否仍能响应

## 场景 1：文档上传后一直处理中

### 现象

- 页面状态长时间停留在 `uploaded` 或 `indexing`
- 文档详情里时间线停止增长

### 快速判断

```powershell
.\logs.bat -f -s go-api py-worker
.\logs.bat -f -s py-worker -k embedding
```

### 正常路径应该看到

- `go-api` 打印 `[upload] completed`
- `py-worker` 依次进入 `downloading -> parsing -> chunking -> embedding -> indexing -> verifying`

### 如果没有 `[upload] completed`

优先排查：

- 前端是否成功通知 `POST /v1/documents/upload`
- MinIO 中对象是否存在
- `go-api` 是否返回了错误但前端未感知

### 如果 Worker 一直没接单

优先排查：

- Redis 是否可用
- `INGEST_QUEUE_KEY` 是否一致
- `py-worker` 进程是否还在运行

### 如果 Worker 卡在某个阶段

常见含义：

| 阶段 | 可能原因 |
| --- | --- |
| `downloading` | MinIO 不可达、对象不存在、网络问题 |
| `parsing` | 文档损坏、解析器异常、编码问题 |
| `embedding` | 嵌入模型超时、外部 LLM 网关异常 |
| `indexing` | Qdrant 不可达、向量写入失败 |
| `verifying` | Qdrant 与数据库状态不一致 |

### 如果 `embedding` 很慢但日志仍在推进

这通常不是“卡死”，而是单批 embedding 吞吐不足。当前版本已经支持批量 embedding 和更细粒度的进度推进，优先检查：

- `.env` 中的 `EMBEDDING_BATCH_SIZE` 是否至少为 `16`
- `.env` 中的 `EMBEDDING_BATCH_MAX_CHARS` 是否过小
- `.env` 中的 `DEFAULT_CHUNK_SIZE` 是否仍是较小值
- 宿主机执行 `ollama ps` 时，模型是否仍显示为纯 CPU

推荐的本地加速档位：

- `EMBEDDING_BATCH_SIZE=16`
- `EMBEDDING_BATCH_MAX_CHARS=24000`
- `EMBEDDING_KEEP_ALIVE=1h`
- `EMBEDDING_TIMEOUT_SECONDS=120`
- `DEFAULT_CHUNK_SIZE=2048`
- `DEFAULT_CHUNK_OVERLAP=64`

如果你已经改了参数但任务还是极慢，优先重启宿主机 Ollama，再重新提交该文档的入库任务。

## 场景 2：在线预览乱码

### 现象

- 文档内容能打开，但中文出现乱码
- 预览内容和实际文本不一致

### 快速判断

1. 查看预览弹窗中的 `编码` 标识
2. 查看 `go-api` 的 `[preview]` 日志
3. 如果入库结果也错，再看 Worker `parsing` 阶段

命令：

```powershell
.\logs.bat -f -s go-api -k preview
.\logs.bat -f -s py-worker -k parsing
```

### 处理建议

- 如果只是在线预览乱码，先确认对象存储原始文件编码
- 如果预览正常但问答内容异常，说明问题更可能出在 Worker 解析阶段
- 若文件编码极端特殊且未被当前探测覆盖，建议先转成 UTF-8 再重新上传

## 场景 3：聊天接口返回 401 / 403

### 401

通常表示：

- Token 缺失
- Token 过期
- Redis 中会话不存在

处理步骤：

1. 重新登录
2. 查看 `go-api` 认证相关错误
3. 确认 Redis 正常

### 403

通常表示：

- Member 角色尝试访问 Admin 页面或接口

处理步骤：

- 使用 Admin 账号登录
- 确认前端路由守卫与后端角色判断一致

## 场景 4：聊天接口返回 503 / 空答案

### 快速判断

```powershell
.\logs.bat -f -s go-api py-rag-service
```

优先确认：

- `py-rag-service` 是否存活
- 外部 LLM 提供商是否可达
- Qdrant 是否可检索

### 常见原因

| 现象 | 常见原因 |
| --- | --- |
| 503 | RAG 服务不可用、Go API 代理失败 |
| 长时间超时 | 外部模型慢、检索慢、网络抖动 |
| 空答案 | 检索为空、证据过滤过严、模型未生成内容 |

## 场景 5：删除文档失败

当前删除动作会尝试同时清理：

- PostgreSQL 文档记录
- MinIO 原始对象
- Qdrant 关联向量

如果删除失败，先看：

```powershell
.\logs.bat -f -s go-api -k delete
```

若提示 `document has active ingest job`：

- 等待当前入库任务结束后再删
- 不要强行删数据库记录，否则容易留下脏向量

## 场景 6：数据库迁移未生效

### 现象

- 服务启动时报缺表或缺列
- 旧数据卷升级后，新增功能不可用

### 处理步骤

```powershell
docker compose build db-migrate
docker compose run --rm db-migrate
docker compose ps
```

现在的迁移脚本会把已执行文件记录到 `schema_migrations` 表，并保存文件校验和。

如果仍异常，再检查：

- `db-migrate` 镜像是否已按最新迁移脚本与 SQL 重新构建
- `db-migrate` 容器日志是否显示脚本执行成功
- `schema_migrations` 中是否已经存在对应迁移文件记录

## 常用 SQL 查询

### 查看最近入库任务

```sql
SELECT j.id,
       j.document_id,
       j.status,
       j.progress,
       j.error_message,
       j.error_category,
       j.updated_at
FROM ingest_jobs j
ORDER BY j.updated_at DESC
LIMIT 20;
```

### 查看某个文档最近事件

```sql
SELECT e.job_id,
       e.stage,
       e.message,
       e.created_at
FROM ingest_events e
WHERE e.job_id = '<job_id>'
ORDER BY e.created_at ASC;
```

### 查看文档与任务状态

```sql
SELECT d.id,
       d.file_name,
       d.status AS document_status,
       j.status AS job_status,
       j.progress,
       j.updated_at
FROM documents d
LEFT JOIN ingest_jobs j ON j.document_id = d.id
ORDER BY j.updated_at DESC NULLS LAST;
```

## 恢复策略建议

### 可以安全尝试的动作

- 重启单个容器
- 重新登录
- 重新上传单个文档
- 补跑 `db-migrate`
- 导出日志快照

### 需要谨慎的动作

- 手动修改数据库状态
- 手动清空 Redis 队列
- 直接删除 Qdrant 数据
- 删除数据卷

## 升级到更正式环境前的建议

- 为关键依赖补监控与告警
- 为 `.env` 中的敏感值换成密钥管理系统
- 补充备份和恢复演练
- 补充 OpenAPI 与回归测试流水线
