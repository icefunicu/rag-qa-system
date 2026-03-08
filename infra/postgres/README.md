# PostgreSQL Infra

本目录存放 PostgreSQL 相关基础设施文件。

## 文件说明

- `postgres.Dockerfile`：本地开发数据库镜像定义
- `init/000_dual_kernel_bootstrap.sh`：双数据库初始化脚本
- `db-bootstrap`（定义在仓库根目录 `docker-compose.yml`）：每次启动时补齐 `novel_app` 与 `kb_app`，兼容已存在的数据卷
