# RAG-P MVP

超大文件 RAG 系统 MVP（单租户私有部署，500MB/文件）。

## 当前阶段
- 已落地 Phase 1 基础骨架：
  - `go-api`（REST API、登录与角色、资料/文档/任务/会话接口）
  - `py-rag-service`（RAG 服务占位接口）
  - `py-worker`（异步 Worker 占位进程）
  - `docker-compose.yml`（PostgreSQL/Redis/Qdrant/MinIO 与应用编排）
  - PostgreSQL 初始化 schema

## 目录结构
- `go-api/`: Go API 网关
- `py-rag-service/`: Python RAG 服务
- `py-worker/`: Python Worker
- `infra/postgres/init/`: 数据库初始化脚本
- `AGENTS.md`: 协作规范与开发进度看板

## 快速启动
1. 复制环境变量模板：
   - `cp .env.example .env`（Windows PowerShell 可手动复制）
2. 启动服务：
   - `docker compose up -d --build`
3. 健康检查：
   - `GET http://localhost:8080/healthz`
   - `GET http://localhost:8000/healthz`

## 主要接口（Phase 1）
- `POST /v1/auth/login`
- `POST /v1/corpora`
- `GET /v1/corpora`
- `POST /v1/documents/upload`
- `GET /v1/ingest-jobs/{job_id}`
- `POST /v1/chat/sessions`
- `POST /v1/chat/sessions/{session_id}/messages`

## 开发命令
- `make test`
- `make build`
- `make up`
- `make down`

## 说明
- 当前 `documents/upload` 为元数据入队接口（文件直传 S3 将在后续阶段补齐）。
- 当前 `py-rag-service` 返回占位回答，检索/重排/引用对齐在 Phase 2/3 实现。

