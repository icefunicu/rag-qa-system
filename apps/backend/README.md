# Backend Apps

`apps/backend/` 存放三个独立后端服务。

## 目录说明

- `gateway/`：统一认证、JWT、路由聚合
- `novel-service/`：小说上传、解析、索引、问答
- `kb-service/`：企业库上传、解析、索引、问答

## 服务内约定

- `app/`：运行时代码
- `migrations/`：数据库初始化或迁移脚本
- `Dockerfile`：该服务镜像构建入口
- `requirements.runtime.txt`：运行时依赖
