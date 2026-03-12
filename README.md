# RAG-QA 2.0

[![CI](https://img.shields.io/github/actions/workflow/status/icefunicu/rag-qa-system/ci.yml?branch=main&label=CI)](https://github.com/icefunicu/rag-qa-system/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/icefunicu/rag-qa-system)](LICENSE)
[![Stars](https://img.shields.io/github/stars/icefunicu/rag-qa-system?style=social)](https://github.com/icefunicu/rag-qa-system/stargazers)

![Vue](https://img.shields.io/badge/Vue%203-4FC08D?logo=vuedotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white)
![Element Plus](https://img.shields.io/badge/Element%20Plus-409EFF?logo=element&logoColor=white)
![Pinia](https://img.shields.io/badge/Pinia-FFD859?logo=pinia&logoColor=black)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?logo=langchain&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![MinIO](https://img.shields.io/badge/MinIO-C72E49?logo=minio&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?logo=qdrant&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![Pytest](https://img.shields.io/badge/Pytest-0A9EDC?logo=pytest&logoColor=white)

![RAG-QA Architecture](docs/assets/architecture-overview.svg)

一个面向中文场景的本地 RAG 问答系统。

如果你不熟悉技术，可以把它理解成一套“企业知识库问答平台”：

- 你上传公司制度、手册、合同、流程文档
- 系统把文档整理成可搜索的知识库
- 用户像聊天一样提问
- 系统回答时会尽量附上依据和引用位置，而不是只给一句模糊答案

这个仓库不是单页面演示，也不是只会“调用一个大模型”的 Demo。它包含前端、网关、知识库服务、异步处理 Worker、对象存储、向量检索、评测和运维脚本，适合做：

- 企业知识库问答
- 内部制度检索
- 多知识库统一聊天
- AI 应用后端工程样板
- RAG 产品原型和面试作品

## 目录

- [项目能做什么](#项目能做什么)
- [技术栈](#技术栈)
- [一句话看懂系统](#一句话看懂系统)
- [核心能力](#核心能力)
- [适合谁](#适合谁)
- [快速开始](#快速开始)
- [第一次使用怎么走](#第一次使用怎么走)
- [默认地址与账号](#默认地址与账号)
- [后端 .env 配置](#后端-env-配置)
- [支持的文件与连接器](#支持的文件与连接器)
- [系统架构](#系统架构)
- [AI 能力与治理](#ai-能力与治理)
- [评测与回归](#评测与回归)
- [开发与运维](#开发与运维)
- [项目结构](#项目结构)
- [安全与边界](#安全与边界)
- [常见问题](#常见问题)
- [验证命令](#验证命令)
- [更多说明](#更多说明)

## 项目能做什么

- 创建多个知识库，分别管理不同业务域的文档
- 上传 `txt`、`pdf`、`docx`、`png`、`jpg`、`jpeg` 文档
- 异步解析文档并建立检索索引
- 提供单知识库问答和统一聊天两种入口
- 返回引用、证据状态、检索耗时、链路追踪信息
- 支持 SSE 流式回答
- 支持工作流重试与最小恢复能力
- 支持本地目录同步和 Notion 页面同步
- 支持文档切片人工治理、切片禁用、手工合并/拆分和检索调试工作台
- 支持统一连接器注册表，可配置 Web、飞书、钉钉和 SQL 数据源同步
- 支持 Agent Profile、Prompt 模板库和工具开关
- 支持个人视角与管理员视角的运营分析看板
- 支持提示词版本管理、模型路由、重排、视觉 OCR
- 支持评测基线、回归门禁和反馈闭环

## 技术栈

### 前端

![Vue](https://img.shields.io/badge/Vue%203-4FC08D?logo=vuedotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white)
![Element Plus](https://img.shields.io/badge/Element%20Plus-409EFF?logo=element&logoColor=white)
![Pinia](https://img.shields.io/badge/Pinia-FFD859?logo=pinia&logoColor=black)

### 后端与 AI

![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?logo=langchain&logoColor=white)
![FastEmbed](https://img.shields.io/badge/FastEmbed-0F172A?logo=semanticweb&logoColor=white)
![RapidOCR](https://img.shields.io/badge/RapidOCR-111827?logo=googledocs&logoColor=white)

### 存储与基础设施

![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![MinIO](https://img.shields.io/badge/MinIO-C72E49?logo=minio&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?logo=qdrant&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)

### 质量保障

![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![Pytest](https://img.shields.io/badge/Pytest-0A9EDC?logo=pytest&logoColor=white)

## 一句话看懂系统

你可以把它理解成下面这条流水线：

1. 把文档放进系统。
2. 系统自动解析、切分、建立索引。
3. 用户提问。
4. 系统先检索证据，再生成答案。
5. 返回答案时一并附上引用、耗时、成本和追踪信息。

如果你只关心“能不能直接用”，答案是：可以，本仓库默认支持本地开发直接启动。

如果你关心“是不是工程化的”，答案也是：是，这里不是单脚本项目，而是完整服务拆分。

## 核心能力

| 能力 | 对非技术用户的意义 | 对技术团队的意义 |
| --- | --- | --- |
| 知识库管理 | 可以按部门、项目、主题分开管理资料 | 数据边界更清晰 |
| 多格式文档上传 | 常见办公文件可直接接入 | 复用统一 ingest 流程 |
| 证据化回答 | 回答尽量带出处，不只是“像是对的” | 便于做可信回答和排障 |
| 统一聊天 | 可以跨多个知识库问答 | 有统一网关和作用域控制 |
| 流式输出 | 回答时不用一直等到最后 | 更适合前端聊天体验 |
| 本地目录连接器 | 服务器目录里的文件可以同步进知识库 | 支持软删除和 freshness 元数据 |
| Notion 连接器 | 指定 Notion 页面可以同步进知识库 | 为企业连接器打下基线 |
| 工作流恢复 | 失败后可以从中间状态恢复，而不是整轮重跑 | 适合做复杂 AI 流程 |
| 评测门禁 | 能知道效果有没有变差 | 方便持续迭代 |
| 反馈闭环 | 用户可以标记回答好坏 | 反馈与模型、提示词、成本绑定 |

## 适合谁

- 想快速搭建一个“会回答公司文档问题”的产品原型
- 想做 AI 应用后端，而不是只写 Prompt Demo
- 想准备 RAG / AI 应用开发岗位作品集
- 想研究企业知识库、检索、评测、可观测性和治理问题

## 快速开始

### 环境要求

- Docker Desktop
- Python
- Node.js 和 npm
- PowerShell
- `make`

如果你的环境没有 `make`，也可以直接运行 `scripts/dev/*.ps1` 脚本。

### 1. 复制环境变量模板

```powershell
Copy-Item .env.example .env
```

### 2. 启动前检查

```powershell
make preflight
```

这个命令会检查：

- 文本编码
- 前端能否构建
- Python 代码能否编译
- 测试是否通过
- `docker compose` 配置是否有效

### 3. 初始化基础设施

```powershell
make init
```

它会准备：

- PostgreSQL
- MinIO
- Qdrant
- 数据库迁移和基础初始化

### 4. 启动完整项目

```powershell
make up
```

启动后会运行：

- `postgres`
- `minio`
- `qdrant`
- `kb-service`
- `kb-worker`
- `api-gateway`
- 前端开发服务

### 5. 停止项目

```powershell
make down
```

## 第一次使用怎么走

这一节改成可直接照做的操作手册，分两条路径：

- 简单版：适合先验证“系统能不能跑、能不能回答”
- 企业级版：适合接入真实资料，并打开数据同步能力

### 简单版操作手册

适合第一次本地体验，目标是在 10 到 20 分钟内完成一次完整问答闭环。

1. 准备环境变量。
   在仓库根目录执行：

   ```powershell
   Copy-Item .env.example .env
   ```

   然后至少补齐 `JWT_SECRET` 和 `LLM_API_KEY`。如果你直接用默认 Docker 配置，本地数据库、MinIO、Qdrant 配置通常不用再改。

2. 做启动前检查。

   ```powershell
   make preflight
   ```

   期望结果是检查通过，没有编码、构建或 compose 配置错误。

3. 初始化基础设施并启动项目。

   ```powershell
   make init
   make up
   ```

   启动完成后，确认下面两个地址可访问：

   - `http://localhost:8080/readyz`
   - `http://localhost:8300/readyz`

4. 登录前端。

   打开 `http://localhost:5173`，使用默认管理员账号登录：

   - 邮箱：`admin@local`
   - 密码：`ChangeMe123!`

5. 创建知识库。

   在前端新建一个知识库，例如：

   - 名称：`HR 手册`
   - 分类：`policy`
   - 描述：`员工制度和审批流程`

6. 上传一份测试文档。

   建议先上传一份小的 `txt`、`pdf` 或 `docx` 文件，例如报销制度、请假制度或入职手册。上传后等待文档状态从：

   - `uploaded`
   - `parsing_fast`
   - `fast_index_ready`
   - `hybrid_ready`
   - `ready`

   变成 `ready` 后再开始正式提问。

7. 做一次检索验证。

   如果你想先看召回质量，不让 LLM 生成答案，可以调用：

   ```bash
   curl -X POST http://localhost:8300/api/v1/kb/retrieve/debug \
     -H "Authorization: Bearer <ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{
       "base_id": "<KB_ID>",
       "question": "报销审批需要哪些角色签字？",
       "document_ids": [],
       "limit": 5
     }'
   ```

   期望能看到 Top-K 召回结果、分数和重排结果。

8. 做一次正式问答。

   你可以在前端聊天页提问，也可以直接调接口：

   ```bash
   curl -X POST http://localhost:8300/api/v1/kb/query \
     -H "Authorization: Bearer <ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{
       "base_id": "<KB_ID>",
       "question": "报销审批需要哪些角色签字？",
       "document_ids": []
     }'
   ```

   期望结果：

   - 返回 `answer`
   - 返回 `citations`
   - 返回 `trace_id`
   - 如果命中充分，`evidence_status` 应接近 `grounded`

9. 如果召回不理想，进入 chunk 治理。

   你可以查看文档 chunk，并手工修正文案、拆分、合并或禁用噪音 chunk。最常用入口是：

   - `GET /api/v1/kb/documents/{document_id}/chunks`
   - `PATCH /api/v1/kb/chunks/{chunk_id}`
   - `POST /api/v1/kb/chunks/{chunk_id}/split`
   - `POST /api/v1/kb/chunks/merge`

到这里，你已经完成了最小闭环：

- 系统启动成功
- 文档 ingest 成功
- 检索可用
- 回答可用
- 结果可治理

### 企业级操作手册（带数据同步）

适合把系统接进真实业务资料，目标是让知识库从“手工上传”升级到“持续同步”。

1. 先完成简单版第 1 到第 4 步。

   企业级接入不是替代简单版，而是在它的基础上继续做数据接入和治理。

2. 规划知识库边界。

   不要一上来把所有资料全塞进一个库。建议按业务域拆分，例如：

   - `HR 制度库`
   - `法务合同库`
   - `财务 FAQ 库`
   - `内部产品文档库`

   这样后续做权限、检索调试和运营分析会更清晰。

3. 配置后端 `.env` 中的连接器变量。

   最常见的是下面这组：

   ```env
   KB_LOCAL_CONNECTOR_ROOTS=E:\corp-docs;E:\shared\knowledge
   KB_LOCAL_CONNECTOR_MAX_FILES=256

   KB_NOTION_CONNECTOR_ENABLED=true
   KB_NOTION_API_TOKEN=secret_xxx
   KB_NOTION_API_BASE_URL=https://api.notion.com/v1
   KB_NOTION_API_VERSION=2022-06-28

   FEISHU_DOC_AUTH=Bearer your-feishu-token
   DINGTALK_DOC_AUTH=Bearer your-dingtalk-token
   REPORTING_DB_DSN=postgresql://user:password@host:5432/reporting
   ```

4. 接入企业本地目录连接器。

   适合已经沉淀在共享盘、服务器目录或挂载盘里的文档。

   操作顺序：

   1. 把可同步目录加入 `KB_LOCAL_CONNECTOR_ROOTS`
   2. 创建目标知识库，例如 `HR 制度库`
   3. 先用 `dry_run=true` 预览变更
   4. 确认后执行正式同步

   预演示例：

   ```bash
   curl -X POST http://localhost:8300/api/v1/kb/connectors/local-directory/sync \
     -H "Authorization: Bearer <ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{
       "base_id": "<KB_ID>",
       "source_path": "E:\\corp-docs\\hr",
       "category": "hr-policy",
       "recursive": true,
       "delete_missing": true,
       "dry_run": true,
       "max_files": 200
     }'
   ```

   正式执行时，把 `dry_run` 改成 `false`。如果源目录里文件删除了，且 `delete_missing=true`，系统会把对应知识库文档做软删除同步。

5. 接入 Notion 连接器。

   适合团队把制度、FAQ、产品说明写在 Notion 中的场景。

   操作顺序：

   1. 在 Notion 创建 integration
   2. 把目标页面授权给 integration
   3. 在 `.env` 中配置 `KB_NOTION_CONNECTOR_ENABLED=true` 和 `KB_NOTION_API_TOKEN`
   4. 从页面 URL 提取 page id
   5. 先做一轮手工同步验证

   示例：

   ```bash
   curl -X POST http://localhost:8300/api/v1/kb/connectors/notion/sync \
     -H "Authorization: Bearer <ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{
       "base_id": "<KB_ID>",
       "page_ids": ["xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
       "category": "notion-docs",
       "delete_missing": true,
       "dry_run": false,
       "max_pages": 20
     }'
   ```

   同步后，Notion 页面会被转成 UTF-8 文本，再进入统一 ingest 流程。

6. 如果你要长期运行，创建可调度连接器，而不是只用一次性同步接口。

   这一步适合正式环境。你可以先创建连接器对象，再让系统定时执行。

   示例：

   ```bash
   curl -X POST http://localhost:8300/api/v1/kb/connectors \
     -H "Authorization: Bearer <ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{
       "base_id": "<KB_ID>",
       "name": "HR Local Directory",
       "connector_type": "local_directory",
       "config": {
         "source_path": "E:\\corp-docs\\hr",
         "category": "hr-policy",
         "recursive": true,
         "delete_missing": true,
         "max_files": 200
       },
       "schedule": {
         "enabled": true,
         "interval_minutes": 60
       }
     }'
   ```

   然后可用下面两个入口：

   - 手工执行单个连接器：`POST /api/v1/kb/connectors/{connector_id}/sync`
   - 执行所有到期连接器：`POST /api/v1/kb/connectors/run-due`

7. 接入后做质量验收，不要只看“同步成功”。

   企业环境至少要检查四件事：

   - 文档是否真的进入了目标知识库
   - 检索调试页里是否能召回正确 chunk
   - 正式问答是否有 `citations` 和合理 `grounding_score`
   - Zero-hit 和反馈数据是否能指导后续治理

8. 把治理流程纳入日常运维。

   推荐每周至少做一次：

   - 查看 `retrieve/debug` 里的低质量召回
   - 修正噪音 chunk
   - 关注 `analytics/dashboard` 中的 Zero-hit、热点问题和满意度趋势
   - 根据新资料继续扩充本地目录、Notion、Web 或 SQL 数据源

如果你是项目 Owner，建议第一次上线时按这个顺序推进：

1. 先用简单版跑通单库问答。
2. 再选一个真实业务域做企业级同步试点。
3. 先从本地目录或 Notion 二选一开始，不要同时接太多源。
4. 先稳定同步和检索质量，再扩大到飞书、钉钉、SQL 等更多数据源。

## 默认地址与账号

### 默认地址

- Web: `http://localhost:5173`
- Gateway: `http://localhost:8080`
- KB Service: `http://localhost:8300`
- Qdrant HTTP: `http://localhost:6333`
- Qdrant gRPC: `localhost:6334`
- MinIO API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

### 健康检查地址

- Gateway `healthz`: `http://localhost:8080/healthz`
- Gateway `readyz`: `http://localhost:8080/readyz`
- Gateway `metrics`: `http://localhost:8080/metrics`
- KB Service `healthz`: `http://localhost:8300/healthz`
- KB Service `readyz`: `http://localhost:8300/readyz`
- KB Service `metrics`: `http://localhost:8300/metrics`

### 本地默认账号

默认账号来自 [`.env.example`](/E:/Project/rag-qa-system/.env.example)。

- 管理员：`admin@local`
- 普通成员：`member@local`
- 默认密码：`ChangeMe123!`

注意：

- 这些账号只适合本地开发
- 非本地环境必须覆盖 `JWT_SECRET`、`ADMIN_PASSWORD`、`MEMBER_PASSWORD`

## 后端 .env 配置

如果你只是本地跑起来，最少需要确认这几组配置：

- 认证与基础环境：`APP_ENV`、`JWT_SECRET`
- 数据库：`KB_DATABASE_DSN`、`GATEWAY_DATABASE_DSN`
- 对象存储：`OBJECT_STORAGE_ENDPOINT`、`OBJECT_STORAGE_ACCESS_KEY`、`OBJECT_STORAGE_SECRET_KEY`、`OBJECT_STORAGE_BUCKET`
- 向量检索：`QDRANT_URL`、`QDRANT_COLLECTION`、`FASTEMBED_MODEL_NAME`、`FASTEMBED_SPARSE_MODEL_NAME`
- LLM：`LLM_ENABLED`、`LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`

### 一份本地可运行的最小示例

```env
APP_ENV=development
JWT_SECRET=replace-this-in-local-env

KB_DATABASE_DSN=postgresql://rag:rag@postgres:5432/kb_app
GATEWAY_DATABASE_DSN=postgresql://rag:rag@postgres:5432/gateway_app

OBJECT_STORAGE_ENDPOINT=http://minio:9000
OBJECT_STORAGE_ACCESS_KEY=minioadmin
OBJECT_STORAGE_SECRET_KEY=minioadmin
OBJECT_STORAGE_BUCKET=rag-assets

QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=kb-evidence
FASTEMBED_MODEL_NAME=BAAI/bge-small-zh-v1.5
FASTEMBED_SPARSE_MODEL_NAME=Qdrant/bm25

LLM_ENABLED=true
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=your-llm-api-key
LLM_MODEL=qwen3.5-plus
```

### Vercel 展示型 `.env` 模板

仓库新增了 [`.env.vercel.example`](/E:/Project/rag-qa-system/.env.vercel.example)。

这份模板只用于技术展示和部署补全，不用于真实生效的生产发布。约束如下：

- `Vercel` 场景下默认走远端 `Gateway`，前端使用 `--mode vercel` 构建
- `LLM`、`Embedding`、`Rerank`、`OCR`、对象存储、向量库、数据库都使用第三方或托管资源占位值
- 不包含真实密钥，也不会替代正式的生产发布配置

对应的展示型 CI 在 [`.github/workflows/vercel-showcase.yml`](/E:/Project/rag-qa-system/.github/workflows/vercel-showcase.yml)：

- 只校验 `Vercel` 专用环境模板是否满足“全部走第三方资源”的约束
- 只执行前端 `vercel mode` 构建并上传产物
- 不会调用真实 `vercel deploy`，也不会创建真实部署

本地验证命令：

```powershell
python scripts/quality/check-vercel-env.py .env.vercel.example
Copy-Item .env.vercel.example .env.vercel
cd apps/web
npm ci
npm run build -- --mode vercel
```

### 连接器相关配置怎么写

如果你要启用企业文档同步，建议把下面这些变量也补上：

```env
# 本地目录连接器
# Windows 可用分号分隔多个根目录；Linux / macOS 使用冒号
KB_LOCAL_CONNECTOR_ROOTS=E:\corp-docs;E:\shared\knowledge
KB_LOCAL_CONNECTOR_MAX_FILES=256

# Notion 连接器
KB_NOTION_CONNECTOR_ENABLED=true
KB_NOTION_API_TOKEN=secret_xxx
KB_NOTION_API_BASE_URL=https://api.notion.com/v1
KB_NOTION_API_VERSION=2022-06-28
KB_NOTION_CONNECTOR_MAX_PAGES=32

# URL / 飞书 / 钉钉鉴权头示例
FEISHU_DOC_AUTH=Bearer your-feishu-token
DINGTALK_DOC_AUTH=Bearer your-dingtalk-token

# SQL 连接器示例
REPORTING_DB_DSN=postgresql://user:password@host:5432/reporting
```

说明：

- `KB_LOCAL_CONNECTOR_ROOTS` 之外的目录不能被本地目录连接器扫描
- `KB_NOTION_CONNECTOR_ENABLED=true` 且 `KB_NOTION_API_TOKEN` 非空时，Notion 同步才会启用
- `FEISHU_DOC_AUTH`、`DINGTALK_DOC_AUTH`、`REPORTING_DB_DSN` 这些名字不是写死的
- 真正生效的是连接器请求体里的 `header_value_env` 或 `dsn_env`，它们会去读取你在部署环境里配置的环境变量名
- 不要把真实 `LLM_API_KEY`、Notion token、数据库连接串提交到仓库

### 连接器配置详解

连接器配置建议分成两层理解：

- 环境变量层：放敏感信息、白名单目录、平台开关
- 连接器请求体层：放某个知识库要同步哪些目录、哪些页面、哪些 URL、多久同步一次

为什么这样做：

- 敏感信息放 `.env` 更安全，不会跟随连接器对象被持久化到业务表
- 连接器对象只保存“要同步什么”和“怎么调度”，更适合审计、回放和多人协作
- 同一个密钥或数据源可以被多个连接器复用，不需要每次重复写密文

#### 1. 本地目录连接器要怎么配置

核心环境变量：

- `KB_LOCAL_CONNECTOR_ROOTS`
- `KB_LOCAL_CONNECTOR_MAX_FILES`

推荐写法：

```env
# Windows
KB_LOCAL_CONNECTOR_ROOTS=E:\corp-docs;E:\shared\knowledge

# Linux / macOS
KB_LOCAL_CONNECTOR_ROOTS=/mnt/corp-docs:/srv/shared/knowledge

KB_LOCAL_CONNECTOR_MAX_FILES=256
```

每个值的含义：

- `KB_LOCAL_CONNECTOR_ROOTS`
  定义允许被扫描的白名单根目录。只有这个范围内的目录才能通过连接器同步。
- `KB_LOCAL_CONNECTOR_MAX_FILES`
  限制单次同步最多处理多少个支持格式文件，避免误扫整盘、误扫海量目录或拖垮首次同步。

这些值从哪来：

- `KB_LOCAL_CONNECTOR_ROOTS`
  来自你部署机器上真实挂载的企业共享目录、NAS 挂载目录或业务资料目录。
- `KB_LOCAL_CONNECTOR_MAX_FILES`
  来自你对单次同步规模的控制要求。第一次通常建议从 `100` 到 `300` 开始。

为什么这么配：

- 本地目录连接器会直接访问服务所在机器的文件系统，不做白名单就是安全风险
- 大目录第一次很容易误扫过多文档，所以需要上限保护
- 先从小目录开始，可以更快完成首轮 ingest、调试 chunk 质量和纠正错误分类

目录里应该放什么：

- 推荐放业务原始文档或整理后的正式资料，例如制度说明、SOP、FAQ、产品手册、合同模板、会议纪要整理稿
- 当前支持的文件格式是 `txt`、`pdf`、`docx`、`png`、`jpg`、`jpeg`
- 如果是图片类文档，建议一张图片只表达一个主题，避免整批截图拼在一个文件里
- 如果是扫描件，建议先保证文字方向正确、内容清晰，避免 OCR 质量过低

目录里不建议放什么：

- Office 临时文件，例如 `~$xxx.docx`
- 下载中的半成品文件、缓存文件、`.tmp` 文件
- 压缩包、安装包、数据库导出、代码仓库、日志目录这类不适合作为知识库语料的内容
- 与业务问答无关的截图、表情包、宣传海报、重复导出的同一份资料

推荐摆放方式：

- 一个一级目录对应一个业务域，例如 `hr`、`finance`、`legal`
- 一个子目录对应一个主题或一类资料，例如 `制度`、`流程`、`模板`
- 同一份文档如果有历史版本，建议放在单独的 `archive`、`history` 或按日期分目录，避免新旧版本混在一起难治理
- 文件名尽量稳定且带业务语义，例如 `员工手册-v2026-03.docx`，不要长期使用 `新建文档(3).docx`

推荐目录结构示例：

```text
E:\corp-docs
├─ hr
│  ├─ policy
│  │  ├─ 员工手册-v2026-03.docx
│  │  └─ 请假制度-v2026-02.pdf
│  ├─ faq
│  │  └─ 社保公积金常见问题.txt
│  └─ archive
│     └─ 员工手册-v2025-12.docx
├─ finance
│  ├─ reimbursement
│  │  └─ 报销制度-v2026-01.pdf
│  └─ template
│     └─ 差旅报销模板.docx
└─ legal
   └─ contract
      └─ 标准采购合同模板.docx
```

接口请求体里最重要的字段：

- `source_path`
- `recursive`
- `delete_missing`
- `dry_run`
- `max_files`
- `category`

推荐原则：

- `source_path`
  写成某个明确的业务目录，不要直接指到盘符根目录
- `recursive=true`
  当资料分多层目录时使用；如果目录结构很乱，第一次也可以先关掉
- `delete_missing=true`
  适合把知识库和源目录保持一致；如果你担心误删，可以第一次先设成 `false`
- `dry_run=true`
  第一次一定建议先开，先看系统准备创建、更新、删除多少文档
- `category`
  建议映射成业务标签，例如 `hr-policy`、`finance-faq`、`legal-contract`

#### 2. Notion 连接器要怎么配置

官方入口：

- Notion Developers：<https://developers.notion.com/>
- Notion 帮助文档（连接 API / 授权页面）：<https://www.notion.so/help/add-and-manage-connections-with-the-api>

核心环境变量：

- `KB_NOTION_CONNECTOR_ENABLED`
- `KB_NOTION_API_TOKEN`
- `KB_NOTION_API_BASE_URL`
- `KB_NOTION_API_VERSION`
- `KB_NOTION_CONNECTOR_MAX_PAGES`

推荐写法：

```env
KB_NOTION_CONNECTOR_ENABLED=true
KB_NOTION_API_TOKEN=secret_xxx
KB_NOTION_API_BASE_URL=https://api.notion.com/v1
KB_NOTION_API_VERSION=2022-06-28
KB_NOTION_CONNECTOR_MAX_PAGES=32
```

这些值从哪来：

- `KB_NOTION_CONNECTOR_ENABLED`
  由你决定是否在当前环境启用 Notion 集成
- `KB_NOTION_API_TOKEN`
  来自 Notion integration
  获取方式：进入 Notion 开发者后台，创建 integration，然后复制 Internal Integration Token
- `KB_NOTION_API_BASE_URL`
  默认用官方 API 地址，一般不需要改
- `KB_NOTION_API_VERSION`
  用 Notion API 版本号，建议和当前实现保持一致
- `KB_NOTION_CONNECTOR_MAX_PAGES`
  控制单次同步最多拉取多少个页面，避免一次导入过大

按步骤配置 Notion 连接器：

1. 打开 Notion 官方开发者网站 `<https://developers.notion.com/>`
2. 创建一个 integration，填写名称，选择要接入的 workspace
3. 创建完成后复制 `Internal Integration Token`
4. 把 token 配到后端 `.env` 中，例如：

```env
KB_NOTION_CONNECTOR_ENABLED=true
KB_NOTION_API_TOKEN=secret_xxx
```

5. 打开你要同步的 Notion 页面
6. 在 Notion 页面右上角点击 `Share`
7. 在分享面板里找到 `Connections` 或 “连接到”，把刚才创建的 integration 加进去
8. 确认这个 integration 已经拿到该页面的访问权限；如果没有共享成功，即使 token 正确，同步也会失败
9. 复制页面 URL，从 URL 中提取 `page_id`
10. 先用 1 到 3 个页面做小范围测试，再逐步扩大同步范围

为什么这么配：

- Notion 是受权限控制的，只有 integration 被授权到的页面才能读取
- token 是敏感信息，必须放环境变量，不应出现在连接器对象或前端配置里
- 页数上限能避免误把试验空间或超大文档集一次性全部拉进来

接口请求体里最重要的字段：

- `page_ids`
- `delete_missing`
- `dry_run`
- `max_pages`
- `category`

怎么拿 `page_ids`：

- 从 Notion 页面 URL 中提取 page id
- page id 本质上是 32 位十六进制字符串
- 如果 URL 中带短横线，服务端会做标准化，但你仍然应该尽量传完整 page id

URL 示例：

- 页面 URL 可能类似：`https://www.notion.so/acme/AI-FAQ-2f8c6e8c0f2b4e08a9f0e9d6d7d4a123`
- 其中最后这一段里的 `2f8c6e8c0f2b4e08a9f0e9d6d7d4a123` 就是可用的 page id
- 有些 URL 会写成带短横线的形式，例如 `2f8c6e8c-0f2b-4e08-a9f0-e9d6d7d4a123`，也同样可以使用

为什么当前只传 `page_ids`，不支持“整个空间自动扫库”：

- 企业环境里 Notion 权限边界复杂，自动全量扫描很容易越权或误同步无关资料
- 明确指定页面更容易做试点、排障和责任归属

#### 3. URL / 飞书 / 钉钉连接器要怎么配置

这类连接器的关键不是只写 URL，而是把“认证信息”安全地从环境变量注入进去。

推荐环境变量：

```env
FEISHU_DOC_AUTH=Bearer your-feishu-token
DINGTALK_DOC_AUTH=Bearer your-dingtalk-token
```

这些值从哪来：

- 来自你们企业内部开放平台应用、服务账号或网关签发的访问令牌
- 具体是 `Bearer xxx`、`Bot xxx` 还是其他格式，取决于上游平台要求

接口 `config` 里常见写法：

```json
{
  "urls": ["https://example.feishu.cn/docx/xxxxx"],
  "header_name": "Authorization",
  "header_value_env": "FEISHU_DOC_AUTH",
  "delete_missing": true,
  "category": "feishu-policy"
}
```

字段解释：

- `header_name`
  HTTP 请求头名称，最常见是 `Authorization`
- `header_value_env`
  不是密钥本身，而是“去读取哪个环境变量”的名字

为什么要这样设计：

- 连接器对象会被持久化、列出、审计；如果直接把 token 存进去，安全风险太高
- 用 `header_value_env` 这种间接引用方式，既能支持不同平台，又不会把密钥写进数据库

#### 4. SQL 连接器要怎么配置

核心环境变量：

- `REPORTING_DB_DSN` 或你自定义的任意 `dsn_env`

推荐写法：

```env
REPORTING_DB_DSN=postgresql://user:password@host:5432/reporting
```

这个值从哪来：

- 来自 DBA、数据平台同学或你们内部报表库的只读连接串
- 强烈建议使用只读账号，不要使用有写权限的生产账号

接口 `config` 里最重要的字段：

- `dsn_env`
- `query`
- `id_column`
- `title_column`
- `text_column`
- `updated_at_column`
- `max_rows`

推荐原则：

- `dsn_env`
  写环境变量名，不写真实连接串
- `query`
  只写单条 `SELECT`
- `id_column`
  选稳定主键，便于增量更新和去重
- `text_column`
  选真正给用户检索和问答用的正文列
- `updated_at_column`
  选最后更新时间列，便于后续增量同步
- `max_rows`
  第一次同步建议保守，从 `100` 到 `500` 开始

为什么这样做：

- SQL 连接器的目标是把结构化文本转成知识库文档，不是给用户直接开放数据库访问
- 只允许 `SELECT` 是为了减少误操作风险
- 使用稳定 `id_column` 和 `updated_at_column`，后续同步才不会反复制造重复文档

## 支持的文件与连接器

### 支持的文档格式

- `txt`
- `pdf`
- `docx`
- `png`
- `jpg`
- `jpeg`

### 内置连接器

#### 1. 本地目录连接器

接口：

- `POST /api/v1/kb/connectors/local-directory/sync`

适合场景：

- 服务器上已经有一批文档，希望批量同步进知识库

特点：

- 只允许同步白名单目录
- 支持递归扫描
- 支持 dry run
- 支持“源文件消失后软删除”
- 会保存 `source_type`、`source_uri`、`source_updated_at`、`source_deleted_at`、`last_synced_at`

启用方式：

- 配置 `KB_LOCAL_CONNECTOR_ROOTS`

怎么用：

1. 先在后端 `.env` 里配置 `KB_LOCAL_CONNECTOR_ROOTS`
2. 确保要同步的目录位于白名单根目录内
3. 先把要导入的业务资料按主题放进明确子目录，不要直接把整个共享盘根目录丢进去
4. 第一次建议只选一个小目录，并把 `dry_run` 设成 `true`
5. 确认返回结果没有误扫后，再正式调用同步接口把文档批量导入指定知识库

最小示例：

```bash
curl -X POST http://localhost:8300/api/v1/kb/connectors/local-directory/sync \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "base_id": "<KB_ID>",
    "source_path": "E:\\corp-docs\\hr",
    "category": "hr-policy",
    "recursive": true,
    "delete_missing": true,
    "dry_run": false,
    "max_files": 200
  }'
```

返回里重点看：

- `counts.created`
- `counts.updated`
- `counts.deleted`
- `ignored_files`

如果你只是先预览会改动什么，把 `dry_run` 改成 `true`。

首次落地建议：

1. 先准备一个很小的试点目录，例如 `E:\corp-docs\hr\policy`
2. 放 3 到 10 份代表性文档，优先选择后续会被频繁问到的制度、流程、FAQ
3. 不要把历史归档、重复副本、临时草稿一开始就混进来
4. 先跑一次 `dry_run=true`，确认 `ignored_files` 和 `counts.*` 是否符合预期
5. 结果正常后，再扩大到更多目录

配置字段说明：

- `source_path`
  真实业务目录，必须位于 `KB_LOCAL_CONNECTOR_ROOTS` 白名单之内
- `recursive`
  是否递归扫描子目录。目录层级深时通常开 `true`
- `delete_missing`
  当源目录文件被删除时，是否同步标记知识库文档为缺失
- `dry_run`
  只做预演，不真正写入文档
- `max_files`
  单次同步文件数上限，建议第一轮先保守
- `category`
  用于给导入文档打业务标签，便于后续筛选和治理

#### 2. Notion 连接器

接口：

- `POST /api/v1/kb/connectors/notion/sync`

适合场景：

- 想把指定的 Notion 页面同步进知识库

特点：

- 只按明确传入的 `page_ids` 同步
- 不扫描整个 Notion 工作区
- 会把页面转换成 UTF-8 文本后走统一 ingest 流程
- 同样支持软删除和治理字段

启用方式：

- `KB_NOTION_CONNECTOR_ENABLED=true`
- `KB_NOTION_API_TOKEN=<your-token>`

怎么用：

1. 访问 Notion 官方开发者站点：<https://developers.notion.com/>
2. 创建 integration，并记录 `Internal Integration Token`
3. 在后端 `.env` 里配置 `KB_NOTION_CONNECTOR_ENABLED=true` 和 `KB_NOTION_API_TOKEN`
4. 打开要同步的页面，在 `Share` 中把该页面授权给这个 integration
5. 从页面 URL 中取出 `page_id`
6. 第一次先同步少量页面，并建议先把 `dry_run` 设成 `true`
7. 确认结果正确后，再改成正式同步

最小示例：

```bash
curl -X POST http://localhost:8300/api/v1/kb/connectors/notion/sync \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "base_id": "<KB_ID>",
    "page_ids": ["xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    "category": "notion-docs",
    "delete_missing": true,
    "dry_run": false,
    "max_pages": 20
  }'
```

说明：

- `page_ids` 只支持明确指定页面，不会自动扫描整个工作区
- 同步时会把页面内容转成 UTF-8 文本，再进入统一 ingest 流程
- 如果 Notion 页面后来更新，再次调用同步接口即可增量更新知识库文档
- 如果页面没有共享给对应的 integration，常见现象是同步失败、拿不到内容，或者页面被判定无权限

配置字段说明：

- `page_ids`
  明确要同步的页面 ID 列表
- `delete_missing`
  当某些页面不再纳入本轮同步时，是否把知识库里的历史对应文档标记为移除
- `dry_run`
  先看本次同步计划，不真正写入
- `max_pages`
  本轮允许同步的最大页面数
- `category`
  给这批 Notion 文档统一打分类标签

#### 3. 统一连接器注册表

接口：

- `GET /api/v1/kb/connectors`
- `POST /api/v1/kb/connectors`
- `GET /api/v1/kb/connectors/{connector_id}`
- `PATCH /api/v1/kb/connectors/{connector_id}`
- `DELETE /api/v1/kb/connectors/{connector_id}`
- `GET /api/v1/kb/connectors/{connector_id}/runs`
- `POST /api/v1/kb/connectors/{connector_id}/sync`
- `POST /api/v1/kb/connectors/run-due`

适合场景：

- 需要把“连接源配置”和“执行记录”从一次性接口提升为可治理对象
- 需要为后续定时调度、失败排查和多连接器运营提供统一入口

特点：

- 所有连接器共享统一的 `config + schedule + runs` 模型
- 支持立即执行和执行到期任务两种模式
- 会保存最近运行结果、下次执行时间和历史运行记录

怎么用：

如果你不想每次都手工调用一次性同步接口，可以先创建一个连接器对象，再让系统按计划执行。

创建本地目录连接器示例：

```bash
curl -X POST http://localhost:8300/api/v1/kb/connectors \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "base_id": "<KB_ID>",
    "name": "HR Local Directory",
    "connector_type": "local_directory",
    "config": {
      "source_path": "E:\\corp-docs\\hr",
      "category": "hr-policy",
      "recursive": true,
      "delete_missing": true,
      "max_files": 200
    },
    "schedule": {
      "enabled": true,
      "interval_minutes": 60
    }
  }'
```

手工触发一次：

```bash
curl -X POST http://localhost:8300/api/v1/kb/connectors/<CONNECTOR_ID>/sync \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

执行所有到期任务：

```bash
curl -X POST http://localhost:8300/api/v1/kb/connectors/run-due \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false, "limit": 10}'
```

注册表里最重要的配置项：

- `connector_type`
  当前支持 `local_directory`、`notion`、`web_crawler`、`feishu_document`、`dingtalk_document`、`sql_query`
- `config`
  存业务配置，不存敏感密钥本体
- `schedule.enabled`
  是否进入定时执行
- `schedule.interval_minutes`
  调度间隔，最小 15 分钟

推荐做法：

- 先用一次性同步接口试跑成功
- 再把稳定的同步方案沉淀成连接器注册表对象
- 最后才打开调度执行

#### 4. URL 类连接器（Web / 飞书 / 钉钉）

当前后端已支持以下 `connector_type`：

- `web_crawler`
- `feishu_document`
- `dingtalk_document`

特点：

- 当前落地方式是“按 URL 抓取正文并转成 UTF-8 文本后统一 ingest”
- 可选通过 `header_name + header_value_env` 注入鉴权头
- 适合先接文档页、帮助中心、制度页、开放平台文档等可抓取页面

创建飞书文档连接器示例：

```bash
curl -X POST http://localhost:8300/api/v1/kb/connectors \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "base_id": "<KB_ID>",
    "name": "Feishu Policies",
    "connector_type": "feishu_document",
    "config": {
      "urls": ["https://example.feishu.cn/docx/xxxxx"],
      "category": "feishu-policy",
      "delete_missing": true,
      "header_name": "Authorization",
      "header_value_env": "FEISHU_DOC_AUTH"
    },
    "schedule": {
      "enabled": true,
      "interval_minutes": 120
    }
  }'
```

配置字段说明：

- `urls`
  要抓取的页面 URL 列表，只支持 `http` 或 `https`
- `header_name`
  上游服务要求的鉴权头名称
- `header_value_env`
  存放鉴权头值的环境变量名
- `delete_missing`
  如果某些 URL 不再纳入同步范围，是否同步清理历史文档
- `max_urls`
  单次允许抓取的 URL 数量上限

#### 飞书 / 钉钉接入建议

- 先确认目标链接是否允许服务端访问，而不是只能在浏览器登录态里打开
- 先手工请求一两个 URL，确认返回正文不是登录页或空壳页面
- 优先用专用服务账号或应用 token，不要直接复用个人登录 cookie
- 如果必须走鉴权头，统一把令牌放环境变量，不要把令牌写进连接器配置 JSON

#### 5. SQL 数据连接器

当前后端已支持 `connector_type=sql_query`。

特点：

- 只允许安全的单条 `SELECT` 查询
- 通过 `dsn_env` 读取部署环境中的数据库连接串
- 按记录行生成文档并走统一知识库 ingest 流程
- 适合报表表、制度表、FAQ 表等结构化文本同步

创建 SQL 连接器示例：

```bash
curl -X POST http://localhost:8300/api/v1/kb/connectors \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "base_id": "<KB_ID>",
    "name": "FAQ From Reporting DB",
    "connector_type": "sql_query",
    "config": {
      "dsn_env": "REPORTING_DB_DSN",
      "query": "select id, title, content, updated_at from faq_articles where status = ''published''",
      "id_column": "id",
      "title_column": "title",
      "text_column": "content",
      "updated_at_column": "updated_at",
      "max_rows": 500
    },
    "schedule": {
      "enabled": true,
      "interval_minutes": 180
    }
  }'
```

配置字段说明：

- `dsn_env`
  数据库连接串所在环境变量名
- `query`
  单条 `SELECT` 查询
- `id_column`
  记录唯一标识列
- `title_column`
  文档标题来源列
- `text_column`
  文档正文来源列
- `updated_at_column`
  更新时间列，用于后续增量更新
- `max_rows`
  单次最多同步多少行

接入建议：

- 用只读账号
- 先限制在小表或小结果集上验证
- 先确认 `text_column` 的内容确实适合检索和问答
- 对长文本字段先做清洗，避免把模板噪音、HTML 碎片或无意义日志直接导入知识库

## 系统架构

![Architecture Overview](docs/assets/architecture-overview.svg)

这张图对应的是当前仓库的正式产品化架构表达，不再只是一个开发视角的服务连接图。它把系统拆成四层：

- Experience Layer：前端工作台，承载知识库管理、检索调试、分析看板和聊天交互
- Gateway Layer：统一会话入口、认证、工作流编排、Prompt 模板和 Agent Profile
- Knowledge Layer：知识库、文档、chunk 治理、检索和连接器同步
- Storage and Operations：PostgreSQL、MinIO、Qdrant 以及审计、追踪、成本分析等运维能力

### 每个服务负责什么

- `apps/web`：前端界面，负责登录、上传、检索、问答和查看结果
- `api-gateway`：统一聊天入口、认证、会话管理、工作流编排、审计聚合
- `kb-service`：知识库、文档、上传、检索、单库问答和连接器同步
- `kb-worker`：异步解析文档、OCR、切分、索引、向量化
- `packages/python/shared`：共享鉴权、存储、检索、追踪、模型调用等基础能力

### 文档进入系统后的状态

文档会大致经历以下阶段：

- `uploaded`
- `parsing_fast`
- `fast_index_ready`
- `hybrid_ready`
- `ready`

这意味着系统不是“上传后立刻可用”，而是走一条可观察、可追踪的异步处理链路。

## AI 能力与治理

### 1. 证据化回答

系统尽量基于检索到的内容作答，并返回：

- `citations`
- `grounding_score`
- `evidence_status`

这对非技术用户的意义是：你能看到“它为什么这么回答”。

### 2. 知识治理与检索调试

这次后端增强后，知识库不再只有“上传然后等待检索”这一条链路，还增加了人工治理入口：

- 可以查看文档的 chunk 明细
- 可以手工修正文案、禁用低质量噪音 chunk
- 可以手工拆分/合并切片并重建该文档索引
- 可以通过 `POST /api/v1/kb/retrieve/debug` 只看召回和 rerank 结果，不触发 LLM

这对运营或知识管理员的意义是：能更快定位“为什么没召回”“为什么召回错了”“哪些切片应该被人工修正”。

### 3. 统一聊天与执行模式

统一聊天支持两种主要模式：

- `grounded`：严格基于当前作用域检索结果作答
- `agent`：在统一聊天入口里走更复杂的内部编排，但最终仍然要求 grounded answer
- `v2`：新增基于 LangGraph 的 `thread / run / interrupt` 运行时，支持 checkpoint 恢复、人工澄清（HITL）、`step_events` 与 `verification` 元数据

当前新增的 `v2` 入口：

- `POST /api/v2/chat/threads`
- `POST /api/v2/chat/threads/{thread_id}/runs`
- `POST /api/v2/chat/runs/{run_id}/resume`
- `POST /api/v2/chat/interrupts/{interrupt_id}/submit`

运行时依赖基线：

- `api-gateway`：`langgraph==0.5.4`，`langgraph-checkpoint-postgres==2.0.25`
- `knowledge-base`：`langgraph==0.5.4`
- 若 `langgraph < 0.5`，`langgraph-checkpoint-postgres` 会发出兼容性 `DeprecationWarning`

#### 为什么这次要把编排层改成 LangGraph

这次升级的重点，不是把整个 LangChain 生态从仓库里删除，而是把“编排职责”从分散的 service 逻辑和轻量链式调用里抽出来，交给 LangGraph 做显式状态管理。

在旧的实现里，聊天请求虽然已经具备检索、生成、重试、审计这些能力，但主流程更多依赖命令式函数推进。这样的实现对 happy path 足够直接，但一旦要支持人工澄清、可恢复执行、节点级追踪、运行中断、幂等 resume，就会出现几个典型问题：

1. 状态分散。一次问答的输入、检索结果、生成结果、校验信息和恢复点会散落在多个函数返回值与持久化结构里，后续排障时很难回答“这次 run 现在到底卡在哪个阶段”。
2. 中断不自然。命令式编排可以人为塞一个 `if need_human_review` 分支，但很难把“暂停并等待外部提交”做成统一机制，更难把它和恢复逻辑、幂等逻辑、审计逻辑对齐。
3. 节点边界不清楚。旧模式下更像是“几个大函数串起来”，测试往往只能测整条链，很难把准备阶段、生成阶段、持久化阶段分别验证。
4. 恢复语义不稳定。以前的恢复更偏向“从某个业务 checkpoint 再试一次”，现在则需要更严格的 run 级恢复，即恢复到图的哪个节点、恢复后继续走哪条边，都要有统一语义。

因此，这次调整的本质是：

1. 保留 LangChain 生态里仍然有价值的底层抽象，例如 `Document`、retriever、LLM 调用与共享工具能力。
2. 清掉查询面上“由业务函数自己顺手编排状态机”的模式，让 LangGraph 接管节点、边、checkpoint 与 interrupt。
3. 把 Gateway 和 KB 都改成“状态显式、节点可追踪、失败可恢复、边界可测试”的图运行时。

#### Gateway 的 LangGraph 节点是怎么拆的

Gateway 当前的聊天图定义在 `apps/services/api-gateway/src/app/gateway_graph.py`，入口是 `prepare_turn`，结束于 `persist_turn`。这张图不是为了把业务写得更花哨，而是为了把一次问答拆成四个职责稳定的阶段。

| 节点 | 做什么 | 为什么必须单独成节点 |
| --- | --- | --- |
| `prepare_turn` | 读取会话、规范化请求、解析作用域、拉最近历史、执行检索准备、判断 answer mode，并在必要时构造 `human_review` 载荷 | 这是整条链里最容易分叉的阶段。是否证据不足、是否 scope 为空、是否需要人工澄清，都在这里统一收口 |
| `human_review_turn` | 调用 LangGraph 的 `interrupt(...)` 暂停运行，把结构化澄清问题交给外部；恢复后把人工提交的内容重新写回 payload | 这个节点把“暂停”和“恢复”变成图层级能力，而不是业务层额外维护的一套等待状态 |
| `generate_answer` | 基于已经准备好的上下文调用生成逻辑，产出答案、引用、延迟、verification 信息 | 生成阶段单独隔离后，可以明确回答“是检索准备阶段失败，还是生成阶段失败” |
| `persist_turn` | 将最终问答结果持久化到消息存储，形成用户可见的聊天消息 | 让持久化只发生在最后稳定阶段，避免半途中断时写出不完整消息 |

把这四个节点连起来后，Gateway 图的控制流非常明确：

1. 先进入 `prepare_turn`。
2. 如果 `prepare_turn` 发现当前 scope 为空，或者 agent 模式下证据不足且又不允许常识补充，就走到 `human_review_turn`。
3. 如果没有人工介入需求，就直接走到 `generate_answer`。
4. 生成完成后进入 `persist_turn`，再结束本轮 run。
5. 如果中间走了 `human_review_turn`，在用户提交澄清结果后，图会回到 `prepare_turn` 重新准备，而不是在旧上下文上硬接着跑。

这种设计有一个很重要的工程收益：每个节点都只回答一个问题。

1. `prepare_turn` 只负责把“本轮该怎么答”准备清楚。
2. `human_review_turn` 只负责“是否需要外部人来补充决策”。
3. `generate_answer` 只负责“把证据组织成回答”。
4. `persist_turn` 只负责“把已经稳定的结果写进去”。

这样做之后，排障、测试、审计和恢复都不需要再从一大段 if/else 里猜当前阶段。

#### Gateway 图里的状态到底保存了什么

这次改造的另一个关键点，是把过去隐含在局部变量里的运行态显式放进图状态。当前 `ChatGraphState` 里比较关键的字段有：

1. `payload`：本轮原始请求体，也是 resume 后可能被人工改写的问题来源。
2. `prepared`：准备阶段产物，包括 contextualized question、scope snapshot、history、evidence、answer mode 等。
3. `human_review`：当前是否挂起人工介入，以及挂起时要展示给外部的结构化说明。
4. `response_payload`：生成阶段产出的回答、引用、耗时与检索元数据。
5. `verification`：对回答质量做的轻量校验结果，例如回答里是否真正带了内联引用标记。
6. `step_events`：每个节点执行完都会追加一条事件，方便上层接口直接把运行轨迹返回给调用方。
7. `status` 与 `current_node`：让 run 当前所处位置可以被外部直接读到，而不是靠日志猜。

状态显式化的意义在于：图不再只是“跑一下函数”，而是真正拥有可观察的运行上下文。

#### 中断、恢复和投影为什么要拆成两层

当前 Gateway 查询面有两套持久化对象，但它们的角色已经被重新划分：

1. LangGraph checkpoint 是主状态源。也就是说，真正决定“这个 run 现在卡在哪个节点、恢复后从哪继续”的，是 graph checkpoint。
2. `chat_workflow_runs` 退化为投影层。它继续保留，是为了列表展示、审计查询、运营侧筛选，以及兼容现有 run 查询接口。
3. `chat_graph_interrupts` 专门记录人工介入请求和回复。它解决的是“挂起时要把什么展示给用户”和“恢复时提交了什么”这两个问题，而不是承担主恢复逻辑。

这样拆的好处是：

1. 恢复语义更清楚。恢复依赖 checkpoint，而不是依赖业务表里某个模糊的 stage 字段。
2. 审计更稳定。运营要看 run 列表、状态、节点、interrupt 状态，可以直接读投影表，不必碰底层 checkpoint 结构。
3. 演进空间更大。后续要扩更多节点、更多 interrupt 类型，不需要改动历史 run 的基本查询方式。

#### KB 检索图为什么也要 graph 化

如果只有 Gateway 用 LangGraph，而知识库侧仍然是黑盒函数，那么上层只能知道“我发了一次 retrieve”，却不知道检索内部到底经历了哪些阶段。因此 KB 这次也把 retrieval 编排改成了显式图，定义在 `apps/services/knowledge-base/src/app/retrieve.py`。

当前 KB 检索图的节点虽然只有三个，但边界非常清楚：

| 节点 | 做什么 | 关键价值 |
| --- | --- | --- |
| `prepare_request` | 记录开始时间、标准化 `base_id / question / limit`、执行 query rewrite、解析实际可检索的 document ids | 把原始问题和检索问题区分开，保证后续召回链路都基于同一份 rewrite 结果 |
| `run_signal_retrievers` | 统一执行三类召回：结构检索、全文检索、向量检索，并记录 degraded signals 与 warnings | 让“召回阶段”有独立边界，方便后续继续扩 parallel retriever 或失败降级 |
| `fuse_and_rerank` | 汇总三路结果，做加权 RRF 融合，再执行 rerank，最后包装成统一 `RetrievalResult` | 让融合与重排成为独立的后处理阶段，而不是混在召回逻辑内部 |

这三个节点背后的设计意图是：

1. 改写问题和执行召回不是一回事。改写是查询理解，召回是取证据。
2. 三种检索信号虽然都属于 retrieval，但它们在概念上是同一阶段内部的三个子动作，不需要拆成大量细碎节点来增加图噪音。
3. 融合和重排必须放在召回之后单独表达，因为它决定的是“哪些证据真正进入最终上下文”，这和“召回到了什么”不是同一层含义。

#### KB 图里每一步到底在处理什么

`prepare_request` 处理的是“把一个自然语言问题变成可检索请求”。

1. 它会先做 query rewrite，得到 original query、rewritten query、focus query、rewrite tags、expansion terms。
2. 它会把 document scope 解析成真正允许参与检索的 `doc_ids`。
3. 它还会记录开始时间，为后面计算 `retrieval_ms` 提供基线。

`run_signal_retrievers` 处理的是“从不同角度找证据”。

1. 结构检索偏向标题、章节名和结构化命中，适合制度类文档、目录型文档。
2. 全文检索偏向关键词精确命中，适合专业术语、固定表达、编号条款。
3. 向量检索偏向语义相似，适合用户提问和原文表达不完全一致的情况。

这一步之所以保留三种信号而不是只留向量检索，是因为企业知识问答里，很多问题不是“语义像就够了”，而是需要同时兼顾标题结构、关键术语和语义相近表达。

`fuse_and_rerank` 处理的是“把候选结果变成最终证据集”。

1. 先把三路召回结果映射成统一的 `EvidenceBlock`。
2. 再用加权 RRF 做融合，避免单一信号把结果列表完全主导。
3. 然后把融合后的前部候选送入 rerank。
4. 最终输出 selected candidates、reranked candidates、degraded signals、warnings、retrieval ms 等调试字段。

所以，KB 图真正解决的问题不是“怎么把三次检索写成三行代码”，而是“怎么让一次 retrieval 过程有清楚的阶段边界和可解释的中间产物”。

#### 为什么这次改造可以算更成熟的 Agent 化 RAG

这里说的“成熟”，不是节点数量越多越成熟，而是系统是否具备下面这些工程特征：

1. 有显式状态。当前 run 的输入、证据、答案、校验、人工介入、当前节点都能直接读到。
2. 有显式边。准备、人工介入、生成、持久化之间如何流转，不再靠隐式函数调用关系推断。
3. 有统一恢复点。恢复以 graph checkpoint 为准，不再是“重跑到大概这个阶段”。
4. 有节点级事件。上层 API 可以返回 `step_events`，前端、审计和测试都能复用。
5. 有跨服务一致语义。Gateway 和 KB 都开始返回 `graph` 元数据，后续要做统一 trace 和运行轨迹聚合更容易。
6. 有稳定测试边界。现在可以单独验证 interrupt/resume、retrieval graph、projection 更新，而不必每次都做整链黑盒测试。

如果从工程角度总结，这次不是单纯“接了一个新框架”，而是把查询面从“能跑”升级到“能解释、能恢复、能审计、能演进”。

### 4. 工作流恢复

统一聊天支持失败重试和最小恢复能力。

当前可以做到：

- 失败后查看 `workflow_run`
- 对失败 run 发起 retry
- 从 retrieval 或 generation checkpoint 恢复，而不是每次整轮重跑
- 对于 `v2` LangGraph 运行时，恢复以 graph checkpoint 为主状态源，`workflow_run` 主要承担投影与审计职责

### 5. Agent 工作台与 Prompt 模板

后端已补齐两类可平台化治理的对象：

- Prompt 模板：支持个人模板、公共模板、标签和收藏
- Agent Profile：支持 persona、默认知识库、Prompt 模板挂载和工具开关

当前 Agent Profile 已支持的工具：

- `search_scope`
- `list_scope_documents`
- `search_corpus`
- `calculator`

### 6. 提示词和模型路由

系统支持：

- `prompt registry`
- `model routing`
- route fallback

常见配置入口：

- `PROMPT_REGISTRY_JSON`
- `PROMPT_REGISTRY_PATH`

### 7. 运营分析看板

后端已经提供统一分析接口：

- `GET /api/v1/analytics/dashboard?view=personal|admin&days=14`

当前返回的数据维度包括：

- 问答热点词
- Zero-hit 趋势与高频无命中问题
- 点赞/点踩/标记趋势
- Token 与估算成本统计

其中：

- `view=personal` 适合个人使用分析
- `view=admin` 适合管理员看团队整体情况，需要管理员权限
- `LLM_MODEL_ROUTING_JSON`
- `AI_MODEL_ROUTING_JSON`

### 5. 重排与视觉能力

支持：

- 本地启发式重排
- 外部 cross-encoder rerank
- OCR
- layout-aware visual retrieval

常见配置入口：

- `RERANK_PROVIDER`
- `RERANK_API_BASE_URL`
- `RERANK_API_KEY`
- `RERANK_MODEL`
- `VISION_PROVIDER`
- `VISION_FALLBACK_PROVIDER`
- `VISION_API_BASE_URL`
- `VISION_API_KEY`
- `VISION_MODEL`

### 6. 用户反馈闭环

接口：

- `PUT /api/v1/chat/sessions/{id}/messages/{message_id}/feedback`

用途：

- 用户可以对回答打“好 / 差 / 标记”
- 反馈会绑定当次回答的 `trace_id`
- 同时快照 `prompt_key`、`prompt_version`、`route_key`、`model`、`provider`、`execution_mode`、`answer_mode`、`cost`、`llm_trace`

这使得后续可以分析：

- 哪个提示词版本效果更好
- 哪个模型更稳定
- 哪类问题成本更高

### 7. 安全与背压

系统内置：

- prompt safety 分析
- `unsafe_prompt` 拒答原因
- in-flight 背压保护
- `Retry-After` 提示

背压保护主要覆盖：

- `POST /api/v1/chat/sessions/{id}/messages`
- `POST /api/v1/chat/sessions/{id}/messages/stream`
- `POST /api/v1/kb/query`
- `POST /api/v1/kb/query/stream`

相关配置：

- `GATEWAY_CHAT_MAX_IN_FLIGHT_GLOBAL`
- `GATEWAY_CHAT_MAX_IN_FLIGHT_PER_USER`
- `KB_QUERY_MAX_IN_FLIGHT_GLOBAL`
- `KB_QUERY_MAX_IN_FLIGHT_PER_USER`

## 评测与回归

这个仓库不内置大型真实业务数据集，但已经有一套最小评测闭环。

### 评测脚本

```powershell
python scripts/evaluation/benchmark-local-ingest.py --kb-path <glob-or-file> --kb-path <glob-or-file>
python scripts/evaluation/run-retrieval-ablation.py --fixture <fixture.json>
python scripts/evaluation/compare-embedding-providers.py --fixture <fixture.json>
python scripts/evaluation/eval-long-rag.py --password <pwd> --eval-file <eval.json> --corpus-id kb:<uuid>
python scripts/evaluation/run-eval-suite.py --password <pwd> --config <suite.json>
python scripts/evaluation/check-eval-regression.py --report <suite-report.json>
python scripts/dev/smoke_eval.py --password <pwd> --wait-for-ready
```

### smoke-eval 会做什么

`make smoke-eval` 或 `python scripts/dev/smoke_eval.py` 会自动：

1. 登录本地 gateway
2. 创建 smoke knowledge base
3. 上传内置测试文档
4. 等待 ingest 完成
5. 生成运行时 suite 配置
6. 跑 grounded / agent / refusal 三类 smoke 评测
7. 输出评测报告
8. 运行 regression gate

### 输出产物

- `artifacts/reports/agent_smoke_report.json`
- `artifacts/reports/agent_smoke_report.md`
- `artifacts/reports/agent_smoke_regression_gate.json`
- `artifacts/reports/agent_smoke_regression_gate.md`

### 重点评测字段

- `suite_version`
- `dataset_version`
- `prompt_version`
- `model_version`
- `execution_mode`
- `citation_alignment`
- `faithfulness`
- `correctness`

这些字段适合做：

- 回归检查
- CI 门禁
- 面试展示
- 效果对比

## 开发与运维

### 推荐命令顺序

```powershell
make preflight
make init
make up
make smoke-eval
```

### 常用命令

| 命令 | 用途 |
| --- | --- |
| `make preflight` | 启动前基线检查 |
| `make init` | 初始化数据库、对象存储和 Qdrant |
| `make up` | 启动完整项目 |
| `make down` | 停止本地环境 |
| `make logs` | 查看最近日志 |
| `make logs-follow` | 持续跟随日志 |
| `make export-logs` | 导出日志快照 |
| `make ci` | 运行聚合检查脚本 |
| `make test` | 编译后端并构建前端 |
| `make build` | 构建 Docker 镜像 |
| `make encoding` | 检查文本编码 |
| `make smoke-eval` | 跑本地 smoke 评测 |

### 常见排障思路

#### 1. 如果服务起不来

先看：

- `docker compose ps`
- `http://localhost:8080/readyz`
- `http://localhost:8300/readyz`

#### 2. 如果 Gateway `readyz` 失败

重点检查：

- 数据库连接
- `kb-service` 是否可达
- LLM 配置是否有效

#### 3. 如果 KB Service `readyz` 失败

重点检查：

- 数据库
- MinIO
- Qdrant
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `FASTEMBED_MODEL_NAME`
- `FASTEMBED_SPARSE_MODEL_NAME`

#### 4. 如果向量检索异常

可以尝试：

```powershell
python scripts/dev/reindex-qdrant.py
```

#### 5. 如果 smoke-eval 失败

重点检查：

- `.env` 中的 `ADMIN_EMAIL` 和 `ADMIN_PASSWORD`
- `gateway` 和 `kb-service` 的 `readyz`
- `artifacts/reports/agent_smoke_report.json`
- `artifacts/reports/agent_smoke_regression_gate.json`
- `gateway`、`kb-service`、`kb-worker` 日志

### 常见脚本入口

- `scripts/dev/preflight.ps1`
- `scripts/dev/init.ps1`
- `scripts/dev/up.ps1`
- `scripts/dev/down.ps1`
- `scripts/dev/smoke-eval.ps1`
- `scripts/dev/smoke_eval.py`

## 项目结构

```text
apps/
  services/
    api-gateway/        统一聊天、认证、工作流、审计
    knowledge-base/     知识库、上传、检索、连接器、Worker
  web/                  前端
packages/
  python/shared/        共享鉴权、追踪、存储、检索、模型能力
scripts/
  dev/                  本地开发脚本
  evaluation/           评测与回归脚本
  quality/              质量检查脚本
tests/                  测试
docs/reference/         API 文档
```

## 安全与边界

### 这个项目已经考虑的事情

- 本地默认账号只用于开发环境
- 非本地环境会拒绝不安全默认配置
- 连接器支持软删除，不直接硬删文档记录
- 反馈接口不会在审计日志里回写备注原文
- 统一聊天和问答接口有背压控制
- 返回中带 `trace_id`，便于排障

### 这个项目默认不承诺的事情

- 不自带生产级真实业务语料
- 不默认附带大量演示文档
- 不默认承诺生产 SLA
- Notion 连接器目前不是全量企业级同步方案
- 当前权限模型还不是检索单元级 ACL 下沉

## 常见问题

### 1. 为什么文档已经上传了，但还不能问

最常见原因是文档还没有完成 ingest。系统会按下面的状态推进：

- `uploaded`
- `parsing_fast`
- `fast_index_ready`
- `hybrid_ready`
- `ready`

只有进入 `ready`，检索和问答才最稳定。如果长时间卡住，优先检查：

- `kb-worker` 是否正常运行
- `kb-service` 的 `readyz`
- MinIO 和 Qdrant 是否可用

### 2. 为什么本地目录连接器提示目录不允许

原因通常是 `source_path` 不在 `KB_LOCAL_CONNECTOR_ROOTS` 白名单里。

你应该检查：

- `.env` 是否正确配置了 `KB_LOCAL_CONNECTOR_ROOTS`
- Windows 是否用了分号分隔多个目录
- Linux / macOS 是否用了冒号分隔多个目录
- 你传入的是某个具体业务目录，而不是一个越权目录或盘符根目录

这样设计是为了避免服务进程任意扫描宿主机文件系统。

### 3. 为什么 Notion 同步失败或拿不到内容

最常见是下面几种情况：

- `KB_NOTION_CONNECTOR_ENABLED` 没开
- `KB_NOTION_API_TOKEN` 没配置
- integration 没有被授权到目标页面
- 传入的 `page_id` 不是有效的 32 位十六进制 ID

建议排查顺序：

1. 先确认 `.env` 配置
2. 再确认 Notion integration 是否能访问这个页面
3. 最后再检查 `page_ids` 是否取对

### 4. 为什么 URL / 飞书 / 钉钉连接器同步下来的是空内容或登录页

这通常不是同步接口本身失败，而是上游页面对未登录请求返回了空壳 HTML 或登录页。

你应该先确认：

- 目标 URL 能否被服务端直接访问
- 是否需要 `Authorization` 或其他自定义头
- `header_value_env` 指向的环境变量是否真的存在
- 这个环境变量里的值格式是否符合上游平台要求

### 5. 为什么 SQL 连接器不能直接写数据库地址到请求体里

因为数据库连接串通常包含账号密码，直接写到连接器配置里会带来明显风险：

- 容易被误记录到数据库
- 容易出现在审计、导出或排障输出中
- 不利于后续统一替换和轮换凭据

所以设计上要求你在请求体里写 `dsn_env`，再由服务端去读取环境变量中的真实连接串。

### 6. 为什么检索有命中，但回答仍然不理想

这通常不是单一问题，常见原因包括：

- chunk 切分质量不好
- 文档里有 OCR 噪音
- 同义表达较多，但原文写法和用户提问差异大
- 命中的 chunk 对，但信息不完整

推荐处理顺序：

1. 先用 `POST /api/v1/kb/retrieve/debug` 看召回和 rerank
2. 再查看对应 chunk 明细
3. 必要时手工编辑、拆分、合并或禁用噪音 chunk
4. 最后再重新问答验证

### 7. 为什么建议先 `dry_run` 再正式同步

因为企业数据同步一旦范围选错，最常见的问题不是“同步失败”，而是“同步了太多不该同步的东西”。

`dry_run=true` 可以帮助你先看到：

- 会新建多少文档
- 会更新多少文档
- 会删除多少文档
- 有哪些文件被忽略

这一步非常适合做首次试点和权限边界确认。

## 验证命令

文档改动的最小验证：

```powershell
python scripts/quality/check-encoding.py
docker compose config --quiet
```

完整基线验证：

```powershell
python scripts/quality/check-encoding.py
cd apps/web && npm run build
python -m compileall packages/python apps/services/api-gateway apps/services/knowledge-base
python -m pytest tests -q
docker compose config --quiet
```

LangGraph 运行时的最小回归验证：

```powershell
pytest -q tests/test_backend_infra.py tests/test_chat_workflow_resume_and_budget.py tests/test_langgraph_runtime.py
```

也可以直接运行：

```powershell
powershell -File scripts/quality/ci-check.ps1
```

## 更多说明

- API 文档：[docs/reference/api-specification.md](/E:/Project/rag-qa-system/docs/reference/api-specification.md)
- 协作规范：[AGENTS.md](/E:/Project/rag-qa-system/AGENTS.md)
- 贡献说明：[CONTRIBUTING.md](/E:/Project/rag-qa-system/CONTRIBUTING.md)
- 安全说明：[SECURITY.md](/E:/Project/rag-qa-system/SECURITY.md)
- 开源协议：[LICENSE](/E:/Project/rag-qa-system/LICENSE)
