# Gateway Service

统一网关服务，负责三类能力：

- 本地登录认证与 JWT 签发
- 小说内核、企业库内核的路由代理
- 通用 AI 对话的服务端模型代理

## 目录说明

- `app/main.py`：FastAPI 入口，暴露认证、AI Chat 和两套代理路由
- `app/ai_client.py`：OpenAI-compatible 模型客户端，负责读取环境变量和调用上游模型
- `Dockerfile`：容器构建配置
- `requirements.runtime.txt`：运行依赖

## 关键环境变量

- `NOVEL_SERVICE_URL`
- `KB_SERVICE_URL`
- `AI_CHAT_ENABLED`
- `AI_PROVIDER`
- `AI_BASE_URL`
- `AI_API_KEY`
- `AI_MODEL`
- `AI_CHAT_TIMEOUT_SECONDS`
- `AI_DEFAULT_TEMPERATURE`
- `AI_DEFAULT_MAX_TOKENS`
- `AI_SYSTEM_PROMPT`
- `AI_EXTRA_BODY_JSON`

## 对外接口

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/ai/config`
- `POST /api/v1/ai/chat`
- `/api/v1/novel/*`
- `/api/v1/kb/*`
