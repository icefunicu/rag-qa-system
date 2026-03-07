# Logging 工具说明

本目录提供本地开发环境下的统一日志入口，覆盖 Docker Compose 服务和托管前端日志。

## 目标

- 不用分别打开多个终端看日志
- 支持按服务、级别、关键字过滤
- 支持导出跨服务日志快照

## 入口命令

```powershell
.\logs.bat
python infra/logging/logs.py
```

## 数据来源

日志查看器会聚合：
- `docker compose logs`
- `logs/dev/frontend.log`

## 常用命令

```powershell
.\logs.bat
.\logs.bat -f
.\logs.bat -s gateway novel-service kb-service
.\logs.bat -s frontend -f
.\logs.bat -l ERROR
.\logs.bat --stats
.\logs.bat -k upload
```

## 日志导出

```powershell
.\scripts\aggregate-logs.ps1
.\scripts\aggregate-logs.ps1 -Tail 2000
.\scripts\aggregate-logs.ps1 -Service gateway,novel-service,frontend
```

## 相关文档

- [docs/dev-scripts.md](../../docs/dev-scripts.md)
- [docs/runbook.md](../../docs/runbook.md)
