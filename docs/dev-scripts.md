# 开发脚本与本地工作流

本仓库提供一组 PowerShell 优先的开发脚本，用于启动环境、查看日志、导出日志和执行发布前检查。

如果你只想完成一件事：优先使用仓库根目录脚本，不要手工分别启动每个基础设施组件。

## 先决条件

- Docker Desktop / Docker Compose 可用
- PowerShell 可执行 `.ps1`
- 已从 `.env.example` 复制出 `.env`

```powershell
Copy-Item .env.example .env
```

## 一键启动

### 推荐方式

```powershell
make up
```

等价命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-up.ps1
```

如果当前环境无法访问镜像仓库，或你明确希望只使用本地已有镜像，可以改为：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-up.ps1 -SkipPull
```

默认会执行：

1. 校验 Docker 可用
2. 校验 `.env` 存在
3. `docker compose pull --ignore-buildable --include-deps --policy always`
4. `docker compose build --pull`（传入 `-NoBuild` 时跳过；会同时刷新本地基础设施镜像内的迁移脚本、初始化 SQL 与 Nginx 配置）
5. 定向重置 `db-migrate` 和 `minio-init` 这类一次性服务
6. `docker compose up -d --remove-orphans`
7. `db-migrate` 会重新执行，但已经记录过且校验和未变化的迁移会自动跳过
8. 等待核心服务健康检查
9. 托管前端开发服务器并输出访问地址

## 停止环境

```powershell
make down
```

等价命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-down.ps1 -Force
```

## 访问地址

| 服务 | 地址 |
| --- | --- |
| Web Console | `http://localhost:5173` |
| Go API | `http://localhost:8080` |
| Nginx | `http://localhost` |
| Qdrant | `http://localhost:6333` |
| MinIO API | `http://localhost:19000` |
| MinIO Console | `http://localhost:19001` |

## 常用脚本

| 命令 | 用途 |
| --- | --- |
| `make up` | 启动本地开发环境 |
| `make down` | 停止本地环境 |
| `make logs` | 查看日志 |
| `make logs-follow` | 持续跟随日志 |
| `make export-logs` | 导出日志快照 |
| `make ci` | 运行统一回归检查 |
| `python scripts/check_encoding.py` | 检查文本文件编码规范 |
| `powershell -File scripts/ci-check.ps1` | 运行回归检查 |
| `docker compose build db-migrate && docker compose run --rm db-migrate` | 手动补跑数据库迁移并确保使用最新脚本与 SQL |

## 日志查看

### 统一入口

```powershell
.\logs.bat
```

### 常用示例

```powershell
.\logs.bat -f
.\logs.bat -f -s go-api py-worker
.\logs.bat -l ERROR -s go-api py-worker py-rag-service
.\logs.bat -s frontend -f
.\logs.bat --stats
```

说明：

- `go-api` 日志以普通文本为主，重点看 `[upload]`、`[preview]`、`[delete]`
- `py-worker` 与 `py-rag-service` 默认输出 JSON 结构化日志
- `frontend` 日志来自 `logs/dev/frontend.log`

## 导出日志快照

```powershell
.\scripts\aggregate-logs.ps1
.\scripts\aggregate-logs.ps1 -Tail 2000
.\scripts\aggregate-logs.ps1 -Service go-api,py-worker,frontend
```

导出结果位于：

- `logs/export/ALL/*.log`
- `logs/export/ERROR/*.log`
- `logs/export/WARNING/*.log`
- `logs/export/combined_<timestamp>.log`

跨服务排查时优先看 `combined_<timestamp>.log`。

## 本地开发推荐流程

### 只想验证上传与问答主链路

```powershell
make up
.\logs.bat -f -s go-api py-worker
```

### 修改前端

```powershell
cd apps/web
npm install
npm run dev
npm run build
```

说明：仓库根脚本已能托管前端。只有在需要单独调试前端时才建议手工进入 `apps/web`。

### 修改 Go API

```powershell
cd services/go-api
go test ./...
go run cmd/server/main.go
```

### 修改 Python RAG Service

```powershell
cd services/py-rag-service
python -m pytest -q
python -m uvicorn app.main:app --reload --port 8000
```

### 修改 Python Worker

```powershell
cd services/py-worker
python -m pytest -q
python -m worker.main
```

## 发布前检查

### 最小检查集

```powershell
python scripts/check_encoding.py
cd services/go-api && go test ./...
cd services/py-rag-service && python -m pytest -q
cd services/py-worker && python -m pytest -q
docker compose config --quiet
```

### 一条命令检查

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ci-check.ps1
```

## 上传卡住时怎么查

如果页面长时间停留在“处理中”，按这个顺序排查：

1. 页面中记录 `jobID` 与 `documentID`
2. 查看 `go-api` 是否已经打印 `[upload] completed`
3. 查看 `py-worker` 当前停留在什么阶段
4. 必要时导出 `combined_<timestamp>.log`

常用命令：

```powershell
.\logs.bat -f -s go-api py-worker
.\logs.bat -f -s py-worker -k embedding
.\logs.bat -l ERROR -s go-api py-worker py-rag-service
.\scripts\aggregate-logs.ps1 -Service go-api,py-worker,frontend
```

Worker 阶段顺序：

- `queued`
- `downloading`
- `parsing`
- `chunking`
- `embedding`
- `indexing`
- `verifying`
- `done / failed / dead_letter`

## 在线预览乱码时怎么查

当前 TXT 预览已支持常见编码探测，但如果你仍然看到异常字符，按以下顺序排查：

1. 在文档预览弹窗中确认 `检测编码`
2. 查看 `go-api` 的 `[preview]` 日志
3. 如果是入库解析结果异常，再查看 `py-worker` 的 `parsing` 阶段日志

常用命令：

```powershell
.\logs.bat -f -s go-api -k preview
.\logs.bat -f -s py-worker -k parsing
```

## 手动补跑数据库迁移

旧卷升级或脚本中断时，可单独执行：

```powershell
docker compose build db-migrate
docker compose run --rm db-migrate
```

## 注意事项

- 默认脚本是 Windows / PowerShell 优先
- 默认账号与密码仅用于本地开发
- 公开发布前请替换 `.env` 中的敏感信息和默认凭据
