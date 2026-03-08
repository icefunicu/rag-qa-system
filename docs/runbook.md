# 运行手册

本手册面向本地开发、演示环境维护和日常排障，默认前提是仓库已切换到双内核架构。

## 统一排障原则

1. 先确认是小说线路还是企业库线路出问题。
2. 先看状态，再看日志。
3. 优先做可回滚的恢复动作，不直接清数据库或删卷。

## 第一响应检查

```powershell
docker compose ps
.\logs.bat -l ERROR -s gateway novel-service kb-service
```

确认：
- `postgres` 是否在线
- `gateway` 是否能返回 `/healthz`
- `novel-service` 与 `kb-service` 是否健康
- 前端是否仍能访问 `http://localhost:5173`

## 场景 1：小说上传后一直停留在处理中

现象：
- 文档状态长时间停留在 `uploaded` 或 `parsing`
- 事件时间线没有继续推进

排查：

```powershell
.\logs.bat -f -s gateway novel-service
```

正常状态流：
- `uploaded`
- `parsing`
- `fast_index_ready`
- `enhancing`
- `ready`

恢复建议：
- 重新上传单个小说 TXT
- 检查 `data/novel/<document_id>/` 是否已写入源文件
- 检查 `.env` 中数据库连接是否正确

## 场景 2：企业库上传后解析失败

现象：
- 批量上传中的某个文档状态进入 `failed`
- 事件中只看到 `uploaded`

排查：

```powershell
.\logs.bat -f -s gateway kb-service
```

重点确认：
- 文件类型是否在 `txt / pdf / docx` 范围内
- `kb-service` 是否能读取 `data/kb/<document_id>/source.*`
- PostgreSQL 是否已创建 `kb_app`

## 场景 3：登录返回 401

排查顺序：
1. 确认请求走的是 `POST /api/v1/auth/login`
2. 核对 `.env` 中本地账号字段是否存在
3. 查看 `gateway` 日志

```powershell
.\logs.bat -f -s gateway -k auth
```

## 场景 4：问答返回拒答或无证据

排查顺序：
1. 文档是否已进入 `fast_index_ready` 或 `ready`
2. 请求是否传入正确的 `library_id` 或 `base_id`
3. 查看对应服务日志

```powershell
.\logs.bat -f -s novel-service
.\logs.bat -f -s kb-service
```

## 场景 5：网关返回 502 或 503

排查：

```powershell
docker compose ps
.\logs.bat -f -s gateway novel-service kb-service
```

重点确认：
- `NOVEL_SERVICE_URL`、`KB_SERVICE_URL` 是否与 compose 服务名一致
- 下游服务是否已通过健康检查
- 端口是否仍然是 `8100 / 8300`，或是否被 `.env` 中的 `NOVEL_HOST_PORT / KB_HOST_PORT` 覆盖
- Windows 如仍报端口不可绑定，可执行 `netsh interface ipv4 show excludedportrange protocol=tcp` 检查是否命中保留区间

## 场景 6：数据库初始化异常

排查：

```powershell
docker compose logs postgres --tail 200
docker compose config --quiet
```

当前数据库初始化只负责：
- 创建 `novel_app`
- 创建 `kb_app`

## 日志导出

```powershell
.\scripts\aggregate-logs.ps1
.\scripts\aggregate-logs.ps1 -Service gateway,novel-service,kb-service,frontend
```

优先查看：
- `logs/export/combined_<timestamp>.log`
- `logs/export/summary_<timestamp>.txt`

## 安全恢复建议

可以安全尝试的动作：
- 重启单个容器
- 重新登录
- 重新上传单个文档
- 导出日志快照
- 重跑前端构建与 compose 配置检查

需要谨慎的动作：
- 手动修改数据库记录
- 直接删除数据卷
- 手动改写 `data/novel` 或 `data/kb` 中的文件
