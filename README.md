# RAG-QA System

[![文档](https://img.shields.io/badge/docs-ready-brightgreen)](docs/README.md)
[![技术栈](https://img.shields.io/badge/stack-Go%20%7C%20Python%20%7C%20Vue%203-blue)](#技术栈)
[![运行方式](https://img.shields.io/badge/runtime-Docker%20Compose-2496ED)](#快速开始)
[![状态](https://img.shields.io/badge/status-active%20development-orange)](#路线图)

一个面向私有文档问答场景、强调可观测性与工程边界的 RAG 知识库系统。

RAG-QA System 不只是“上传文件然后提问”的演示项目。仓库覆盖了文档上传、异步入库、阶段进度追踪、在线预览、会话式问答，以及基础运维与排障入口，适合用于本地研发、方案演示、技术作品集展示和团队交接。

## 项目定位

很多 RAG 示例只展示最短路径，本仓库重点补齐那些真实工程里经常被忽略的部分：

- 入库过程可观测：上传之后不是黑盒，前端可以看到阶段状态与处理进度
- 服务边界清晰：Go 网关、Python 检索服务、Python Worker 与基础设施职责分离
- 文档操作完整：支持上传、预览、小型 TXT 在线修改、删除与重新索引
- 运维入口明确：附带日志查看、日志导出、运行手册与 API 文档

## 核心能力

- 知识库与文档管理
- 基于预签名 URL 的直传对象存储
- 异步入库流水线与状态追踪
- `txt / pdf / docx` 在线预览
- 面向中文文本的编码识别，降低 TXT 乱码概率
- 基于会话与知识库范围约束的问答能力
- 流式聊天接口
- 本地日志采集与故障排查脚本

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Element Plus |
| API 网关 | Go、Chi、Redis Session Storage |
| 检索服务 | Python、FastAPI、Qdrant |
| 入库 Worker | Python、Redis Queue、MinIO、Qdrant |
| 元数据存储 | PostgreSQL |
| 基础设施 | Docker Compose、Nginx、MinIO、Redis、Qdrant |

## 架构概览

### 主要组件

| 组件 | 路径 | 职责 |
| --- | --- | --- |
| Web Console | `apps/web` | 登录、聊天、知识库管理、文档详情与进度展示 |
| Go API Gateway | `services/go-api` | 鉴权、REST API、上传编排、会话持久化、RAG 代理 |
| Python RAG Service | `services/py-rag-service` | 检索、重排、答案生成、流式输出 |
| Python Worker | `services/py-worker` | 下载、解析、切分、向量化、索引、校验 |

### 文档入库流程

1. 前端向 Go API 请求上传用的预签名 URL
2. 浏览器将文件直接上传到 MinIO
3. 前端通知 Go API 创建文档记录与入库任务
4. Go API 将任务写入 Redis 队列
5. Worker 按 `queued -> downloading -> parsing -> chunking -> embedding -> indexing -> verifying` 执行处理
6. 前端轮询任务状态与事件时间线，展示阶段进度

更详细的链路说明见 [docs/assets/architecture/architecture-seq.md](docs/assets/architecture/architecture-seq.md)。

## 快速开始

### 环境要求

- Docker Desktop 或兼容的 Docker Compose 环境
- PowerShell 5.1+ 或 PowerShell 7+
- 如果你希望脱离 Docker 单独运行服务，还需要 Node.js 20+、Go 1.25+、Python 3.11+

### 1. 初始化环境变量

```powershell
Copy-Item .env.example .env
```

在对外分享、演示或部署前，至少替换以下值：

- `ADMIN_PASSWORD`
- `MEMBER_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `S3_SECRET_KEY`
- `EMBEDDING_API_KEY`
- `CHAT_API_KEY`（如使用独立聊天模型配置）

如果你希望直接复用本机 Ollama embedding，可保留以下默认项：

- `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`
- `EMBEDDING_PROVIDER=ollama`
- `EMBEDDING_MODEL=embeddinggemma:latest`
- `EMBEDDING_DIM=0`
- `EMBEDDING_BATCH_SIZE=32`
- `EMBEDDING_BATCH_MAX_CHARS=64000`
- `EMBEDDING_KEEP_ALIVE=1h`
- `EMBEDDING_TIMEOUT_SECONDS=120`
- `DEFAULT_CHUNK_SIZE=1536`
- `DEFAULT_CHUNK_OVERLAP=96`
- `LONG_TEXT_MODE_ENABLED=true`
- `LONG_TEXT_THRESHOLD_CHARS=250000`
- `LONG_TEXT_CHUNK_SIZE=2048`
- `LONG_TEXT_CHUNK_OVERLAP=32`
- `LONG_TEXT_EMBEDDING_BATCH_SIZE=96`
- `LONG_TEXT_EMBEDDING_BATCH_MAX_CHARS=256000`
- `LONG_TEXT_SPARSE_ONLY_ENABLED=true`
- `LONG_TEXT_SPARSE_ONLY_THRESHOLD_CHARS=2000000`
- `LONG_TEXT_SPARSE_CHUNK_CHARS=4096`
- `LONG_TEXT_SPARSE_CHUNK_OVERLAP_CHARS=256`
- `SECTION_SUMMARY_THRESHOLD_CHARS=250000`
- `SECTION_SUMMARY_CHARS=2000`
- `METADATA_SAMPLING_MAX_CHARS=120000`
- `SEARCH_TERMS_MAX_PER_CHUNK=64`
- `SECTION_TOP_K=8`
- `SECTION_EXPAND_CHUNK_LIMIT=6`
- `RAG_EVIDENCE_COVERAGE_THRESHOLD=0.45`
- `SPARSE_RETRIEVAL_ENABLED=true`

长文本模式会在源文本超过 `LONG_TEXT_THRESHOLD_CHARS` 时自动启用。对超长文本，Worker 会在文本超过 `LONG_TEXT_SPARSE_ONLY_THRESHOLD_CHARS` 时直接跳过 dense embedding，只持久化 `doc_chunks`，查询阶段由 `py-rag-service` 通过“问题级轻量分词 + PostgreSQL 词项命中排序”的稀疏检索链路立即接管，这样文档可以在几乎不等待向量化的情况下进入可查询状态。

当源文本超过 `SECTION_SUMMARY_THRESHOLD_CHARS` 时，系统会进一步切换到“section dense + chunk sparse”模式：Worker 先把文档抽成 `doc_sections` 和 `doc_chunks`，只对章节摘要打 dense 向量，chunk 检索改走 `search_terms + pg_trgm` 索引；查询端先召回章节，再展开证据块，并在回答前计算 `evidence_coverage`，证据不足时直接拒答。

长文本模式会在源文本超过 `LONG_TEXT_THRESHOLD_CHARS` 时自动启用，更大的切片窗口和更高的批次上限可以减少总分片数与 embedding 请求数。

其中 `EMBEDDING_DIM=0` 表示自动使用模型原生维度。当前仓库已经实测 `embeddinggemma:latest` 可正常返回 `768` 维向量，且在本机 CPU 上吞吐明显快于 `andersc/qwen3-embedding:0.6b`。
当前 Worker 会优先走 Ollama 原生 `/api/embed` 批量接口，并按批次推进进度。相比逐 chunk 单发请求，超大文档入库速度会明显提升。

### 2. 启动本地环境

推荐命令：

```powershell
make up
```

等价脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-up.ps1
```

默认启动脚本会先拉取可直接使用的远端镜像，再对本地构建服务执行 `docker compose build --pull`，随后定向重置 `db-migrate` 和 `minio-init` 这类一次性服务，最后执行 `docker compose up -d --remove-orphans`。这样既能尽量对齐最新镜像，也能保证数据库迁移在每次启动时重新检查并应用新增 SQL，而不会无差别重建所有长期运行容器。当前仓库还会把 PostgreSQL 初始化 SQL、迁移脚本与 Nginx 配置打进本地镜像，以避免 Windows 上的宿主机 bind mount 问题。

如果当前环境是离线的，或者你明确只想使用本地已有镜像，可以改为：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-up.ps1 -SkipPull
```

当 `.env` 中的 `EMBEDDING_PROVIDER` 或 `CHAT_PROVIDER` 设置为 `ollama` 时，启动脚本会先检查本机 Ollama 服务和目标模型是否就绪，再启动容器。

如果你要继续压榨本机 Ollama 吞吐，优先调整宿主机 Ollama，而不是盲目增加 worker 数量：

- 优先保证 Ollama 已实际使用 GPU；若 `ollama ps` 仍显示纯 CPU，先排查驱动与运行环境。
- 单机并发可尝试设置宿主机环境变量 `OLLAMA_NUM_PARALLEL`。
- 支持的显卡场景下可尝试开启 `OLLAMA_FLASH_ATTENTION=1`。
- 修改宿主机 Ollama 环境变量后，重启 Ollama 服务再重新入库。

如果模型或网关开始报超时、OOM 或 4xx 限流，先回退这几个参数：

- 把 `EMBEDDING_BATCH_SIZE` 从 `16` 降到 `8`
- 把 `EMBEDDING_BATCH_MAX_CHARS` 从 `24000` 降到 `16000`
- 把 `EMBEDDING_TIMEOUT_SECONDS` 从 `120` 提高到 `180`
- 把 `DEFAULT_CHUNK_SIZE` 从 `2048` 降到 `1024`

### 3. 访问入口

| 服务 | 地址 |
| --- | --- |
| Web Console | `http://localhost:5173` |
| Go API | `http://localhost:8080` |
| Nginx | `http://localhost` |
| Qdrant | `http://localhost:6333` |
| MinIO API | `http://localhost:19000` |
| MinIO Console | `http://localhost:19001` |

### 4. 默认本地账号

| 角色 | 邮箱 | 密码 |
| --- | --- | --- |
| 管理员 | `admin@local` | `ChangeMe123!` |
| 普通成员 | `member@local` | `ChangeMe123!` |

这些账号仅用于本地开发与演示。

### 5. 停止环境

```powershell
make down
```

## 项目结构

```text
.
|-- apps/
|   `-- web/
|-- docs/
|-- infra/
|-- scripts/
|-- services/
|   |-- go-api/
|   |-- py-rag-service/
|   `-- py-worker/
|-- tests/
`-- docker-compose.yml
```

## 文档导航

建议从这里开始：

- [文档总览](docs/README.md)
- [产品定义](docs/product-definition.md)
- [架构说明](docs/assets/architecture/architecture-seq.md)
- [开发脚本与工作流](docs/dev-scripts.md)
- [API 说明](docs/API_SPECIFICATION.md)
- [运行手册](docs/runbook.md)

## 开发与验证

在仓库根目录执行基础检查：

```powershell
python scripts/check_encoding.py
cd services/go-api && go test ./...
cd services/py-rag-service && python -m pytest -q
cd services/py-worker && python -m pytest -q
cd apps/web && npm run build
docker compose config --quiet
```

针对超大小说文本的专项评测集位于 `tests/evals/novel_large_doc_eval.json`，包含 40 个实体、章节概述、关系、多跳和主题问题，可作为大文档 RAG 的回归基准。

查看日志与排障可使用：

```powershell
.\logs.bat -f
.\logs.bat -f -s go-api py-worker
.\scripts\aggregate-logs.ps1 -Service go-api,py-worker,frontend
```

## 适用场景

- 内部文档问答原型验证
- 面试、汇报、路演或技术演示用的 RAG 工程样例
- 团队搭建“可观测入库型”RAG 系统时的参考仓库

## 当前边界

当前仓库以本地开发、演示和工程交接为主，不应被描述为已经完善生产化的多租户 SaaS 平台。

当前未覆盖：

- SSO / 企业级 IAM 集成
- 多租户隔离
- 高可用部署模板
- 备份与灾备策略
- 正式安全加固与合规审计

## 路线图

- 完善共享环境与部署说明
- 扩展评测与基准测试流程
- 持续补强贡献规范与发布流程
- 继续改进入库可观测性与失败恢复能力

## 参与贡献

欢迎通过边界清晰、可验证的 Pull Request 参与改进。

提交前建议先阅读：

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)

仓库已经提供以下 GitHub 模板：

- Bug 反馈
- 功能建议
- Pull Request

## 许可证

本项目使用 [MIT License](LICENSE)。
