# 开发脚本与本地工作流

## 推荐顺序

```powershell
make preflight
make init
make up
make smoke-eval
```

这四步分别对应：

- `make preflight`：启动前基线检查
- `make init`：显式初始化数据库、对象存储和 Qdrant
- `make up`：启动完整项目并托管前端开发服务器
- `make smoke-eval`：上传最小样例文档并执行 grounded / agent / refusal smoke 评测

## 常用目标

| 命令 | 作用 |
| --- | --- |
| `make preflight` | 运行编码检查、前端构建、Python 编译、后端测试、compose 配置检查 |
| `make init` | 启动 `postgres`、`minio`、`qdrant` 并执行 `stack-init` |
| `make up` | 启动 `postgres`、`minio`、`qdrant`、`kb-service`、`kb-worker`、`gateway` 和前端 |
| `make down` | 停止本地环境 |
| `make logs` | 查看最近日志 |
| `make logs-follow` | 持续跟随日志 |
| `make smoke-eval` | 创建 smoke corpus、上传 fixture、等待 ingest 并跑 eval suite |

## 脚本入口

- `scripts/dev/preflight.ps1`
- `scripts/dev/init.ps1`
- `scripts/dev/up.ps1`
- `scripts/dev/down.ps1`
- `scripts/dev/smoke-eval.ps1`
- `scripts/dev/smoke_eval.py`

## smoke-eval 行为

`make smoke-eval` 会自动完成以下动作：

1. 读取 `.env` 中的 `ADMIN_EMAIL` 与 `ADMIN_PASSWORD`
2. 调用本地 `gateway` 登录
3. 创建两套 smoke knowledge base
4. 上传内置 fixture 文档
5. 轮询 ingest job，直到完成
6. 生成运行时 suite 配置
7. 调用 `scripts/evaluation/run-eval-suite.py`
8. 输出报告到 `artifacts/reports/agent_smoke_report.json` 和 `artifacts/reports/agent_smoke_report.md`

## 基线命令

```powershell
python scripts/quality/check-encoding.py
cd apps/web && npm run build
python -m compileall packages/python apps/services/api-gateway apps/services/knowledge-base
python -m pytest tests -q
docker compose config --quiet
```
