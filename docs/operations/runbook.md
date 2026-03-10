# 运维手册

## 1. 启动顺序

推荐固定按下面顺序执行：

```powershell
make preflight
make init
make up
make smoke-eval
```

说明：

- `make preflight` 先确认代码和 compose 配置可运行
- `make init` 会先拉起 `postgres`、`minio`、`qdrant`，再执行 `stack-init`
- `make up` 会启动应用服务并等待核心健康检查
- `make smoke-eval` 用运行态链路验证 grounded 与 agent 模式

## 2. 关键服务

本地完整链路至少包含：

- `postgres`
- `minio`
- `qdrant`
- `kb-service`
- `kb-worker`
- `gateway`

检查命令：

```powershell
docker compose ps
.\logs.bat -l ERROR -s gateway kb-service kb-worker
```

## 3. `readyz` 排障

### `gateway /readyz`

重点检查：

- 数据库连接
- `kb-service` 可达性
- LLM 配置状态

### `kb-service /readyz`

重点检查：

- 数据库连接
- 对象存储访问
- `vector_store` 状态

如果 `vector_store` 失败，优先检查：

- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `FASTEMBED_MODEL_NAME`
- `FASTEMBED_SPARSE_MODEL_NAME`

## 4. Qdrant / FastEmbed

当前主链路已经切到 `langchain-qdrant`。

排障建议：

- 先确认 `qdrant` 容器已启动
- 再检查 collection 是否已由 `stack-init` 创建
- 如果历史索引 payload 和当前 metadata 结构不一致，执行：

```powershell
python scripts/dev/reindex-qdrant.py
```

## 5. smoke-eval 失败时看哪里

先确认：

- `.env` 中 `ADMIN_EMAIL`、`ADMIN_PASSWORD` 正确
- `http://localhost:8080/healthz` 可达
- `http://localhost:8300/healthz` 可达

再看：

- `artifacts/reports/agent_smoke_report.json`
- `artifacts/reports/agent_smoke_report.md`
- `gateway` 日志
- `kb-service` / `kb-worker` 日志

## 6. 常用验证命令

```powershell
python scripts/quality/check-encoding.py
cd apps/web && npm run build
python -m compileall packages/python apps/services/api-gateway apps/services/knowledge-base
python -m pytest tests -q
docker compose config --quiet
docker compose ps
```
