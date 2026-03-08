# 开发脚本与本地工作流

本仓库按职责拆分脚本目录，默认使用 PowerShell 管理双内核开发环境。

## 脚本目录

- `scripts/dev`：开发启动、停止、前端托管
- `scripts/quality`：编码检查与回归校验
- `scripts/observability`：日志导出与观测辅助
- `scripts/evals`：评测与基准脚本

## 前置条件

- Docker Desktop 可用
- PowerShell 可执行 `.ps1`
- 已从 `.env.example` 复制出 `.env`

```powershell
Copy-Item .env.example .env
```

## 一键启动

```powershell
make up
```

等价命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/up.ps1
```

可选参数：
- `-SkipPull`
- `-NoBuild`
- `-SkipFrontend`
- `-SkipHealthCheck`
- `-AttachLogs`

## 停止环境

```powershell
make down
```

等价命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/down.ps1 -Force
```

## 访问地址

| 服务 | 地址 |
| --- | --- |
| Web Console | `http://localhost:5173` |
| Gateway | `http://localhost:8080` |
| Novel Service | `http://localhost:8100` |
| KB Service | `http://localhost:8300` |
| PostgreSQL | `localhost:5432` |

> 说明：宿主机端口可通过根目录 `.env` 中的 `GATEWAY_HOST_PORT`、`NOVEL_HOST_PORT`、`KB_HOST_PORT`、`POSTGRES_HOST_PORT` 覆盖。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `make up` | 启动本地环境 |
| `make down` | 停止本地环境 |
| `make logs` | 查看最近日志 |
| `make logs-follow` | 持续跟随日志 |
| `make export-logs` | 导出日志快照 |
| `make ci` | 执行基础回归检查 |
| `make test` | 执行前端构建和 Python 语法检查 |
| `python scripts/quality/check-encoding.py` | 检查文本文件编码 |

## 日志查看

```powershell
.\logs.bat -f -s gateway novel-service kb-service
.\logs.bat -f -s frontend
.\logs.bat -l ERROR -s gateway novel-service kb-service
.\logs.bat --stats
```

## 导出日志

```powershell
.\scripts\observability\aggregate-logs.ps1
.\scripts\observability\aggregate-logs.ps1 -Tail 2000
.\scripts\observability\aggregate-logs.ps1 -Service gateway,novel-service,frontend
```

## 单独调试

```powershell
cd apps/backend/gateway
python -m uvicorn app.main:app --reload --port 8080
```

```powershell
cd apps/backend/novel-service
python -m uvicorn app.main:app --reload --port 8100
```

```powershell
cd apps/backend/kb-service
python -m uvicorn app.main:app --reload --port 8200
```

```powershell
cd apps/web
npm install
npm run dev
npm run build
```

## 发布前检查

```powershell
python scripts/quality/check-encoding.py
cd apps/web && npm run build
python -m compileall packages/shared/python apps/backend/gateway apps/backend/novel-service apps/backend/kb-service
docker compose config --quiet
```
