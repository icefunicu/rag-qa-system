# RAG-QA 2.0

本仓库是一个本地离线优先的问答系统，当前结构分为三条清晰能力线：

- `AI 对话`：不绑定知识库，走网关上的通用模型代理，适合直接接入 `Qwen3.5`
- `小说内核`：独立处理超长中文小说的上传、切章、剧情与细节问答
- `企业库内核`：独立处理企业文档的上传、分段、事实问答与跨文档汇总

## 项目结构

```text
.
|-- apps/
|   |-- backend/
|   |   |-- gateway/
|   |   |-- novel-service/
|   |   `-- kb-service/
|   `-- web/
|-- packages/
|   `-- shared/
|-- infra/
|   |-- logging/
|   `-- postgres/
|-- scripts/
|   |-- dev/
|   |-- quality/
|   |-- observability/
|   `-- evals/
|-- tests/
|   `-- evals/
|-- docs/
`-- data/
```

## 三条能力线

### 1. AI 对话

- 入口路由：`/workspace/ai/chat`
- API：`GET /api/v1/ai/config`、`POST /api/v1/ai/chat`
- 通过 `gateway` 服务端代理模型请求，前端不暴露模型密钥
- 当前按 OpenAI-compatible 接口接入，便于切到 `Qwen3.5`

### 2. 小说线路

- 上传格式：首版仅接受 `txt`
- 索引结构：`chapter -> scene -> passage -> event_digest -> alias_graph`
- 状态流：`uploaded -> parsing -> fast_index_ready -> enhancing -> ready`
- 问答策略：`entity_detail`、`chapter_summary`、`plot_event`、`plot_causal`、`character_arc`、`setting_theme`

### 3. 企业库线路

- 上传格式：`txt / pdf / docx`
- 索引结构：`document -> section -> chunk`
- 状态流：`uploaded -> parsing -> fast_index_ready -> enhancing -> ready`
- 问答策略：`exact_match`、`section_summary`、`cross_doc_answer`、`policy_extract`

## 默认接口

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/ai/config`
- `POST /api/v1/ai/chat`
- `POST /api/v1/novel/libraries`
- `GET /api/v1/novel/libraries`
- `POST /api/v1/novel/documents/upload`
- `POST /api/v1/novel/query`
- `POST /api/v1/kb/bases`
- `GET /api/v1/kb/bases`
- `POST /api/v1/kb/documents/upload`
- `POST /api/v1/kb/query`

知识库问答结果固定带：

- `evidence_status`
- `grounding_score`
- `refusal_reason`
- `citations[]`

AI 对话结果固定带：

- `answer`
- `reasoning`
- `provider`
- `model`
- `finish_reason`
- `usage`

## 本地运行

### 1. 初始化环境变量

```powershell
Copy-Item .env.example .env
```

如果要接入 `Qwen3.5`，至少需要补这几项：

```dotenv
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=你的模型密钥
AI_MODEL=qwen3.5-plus
```

### 2. 启动开发环境

```powershell
make up
```

等价命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/up.ps1
```

### 3. 访问地址

- 前端开发环境：`http://localhost:5173`
- Gateway：`http://localhost:8080`
- Novel Service：`http://localhost:8100`
- KB Service：`http://localhost:8300`
- PostgreSQL：`localhost:5432`

宿主机端口可通过根目录 `.env` 中的 `GATEWAY_HOST_PORT`、`NOVEL_HOST_PORT`、`KB_HOST_PORT`、`POSTGRES_HOST_PORT` 覆盖；
服务间调用仍固定使用容器内端口 `8080 / 8100 / 8200 / 5432`。

默认本地账号：

- `admin@local / ChangeMe123!`
- `member@local / ChangeMe123!`

## 前端路由

- `/workspace/entry`
- `/workspace/ai/chat`
- `/workspace/novel/upload`
- `/workspace/novel/chat`
- `/workspace/novel/documents/:id`
- `/workspace/kb/upload`
- `/workspace/kb/chat`
- `/workspace/kb/documents/:id`

## 常用命令

```powershell
make up
make down
make logs
make logs-follow
make export-logs
make ci
```

## 验证

```powershell
python scripts/quality/check-encoding.py
cd apps/web && npm run build
python -m compileall packages/shared/python apps/backend/gateway apps/backend/novel-service apps/backend/kb-service
docker compose config --quiet
```

## 文档入口

- [docs/API_SPECIFICATION.md](docs/API_SPECIFICATION.md)
- [docs/dev-scripts.md](docs/dev-scripts.md)
- [docs/runbook.md](docs/runbook.md)
- [apps/web/README.md](apps/web/README.md)
