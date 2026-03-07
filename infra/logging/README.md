# Logging 工具说明

本目录不是完整日志平台，而是本地开发环境下的统一日志入口辅助实现。

## 目标

- 让开发者不用分别打开多个终端看容器日志
- 支持同时查看 Docker 服务和托管前端日志
- 支持按服务、级别和关键词过滤
- 支持导出跨服务日志快照

## 入口命令

```powershell
.\logs.bat
python infra/logging/logs.py
```

推荐优先使用 `.\logs.bat`，因为它已经处理了 Windows 环境下的 Python 编码参数，并优先选择本机可用的 Python 启动器。

## 数据来源

日志查看器会聚合：

- `docker compose logs`
- `logs/dev/frontend.log`

其中前端日志来自 `scripts/dev-up.ps1` 启动的托管开发服务器。

## 常用命令

```powershell
.\logs.bat
.\logs.bat -f
.\logs.bat -s go-api py-worker
.\logs.bat -s frontend -f
.\logs.bat -l ERROR
.\logs.bat --stats
.\logs.bat -k upload
```

## 日志导出

```powershell
.\scripts\aggregate-logs.ps1
.\scripts\aggregate-logs.ps1 -Tail 2000
.\scripts\aggregate-logs.ps1 -Service go-api,py-worker,frontend
```

导出后优先查看：

- `logs/export/combined_<timestamp>.log`

其次再按需查看：

- `logs/export/ALL/*.log`
- `logs/export/ERROR/*.log`
- `logs/export/WARNING/*.log`

## 与其他文档的关系

- 开发命令总览见 [docs/dev-scripts.md](../../docs/dev-scripts.md)
- 日志字段与追踪规范见 [docs/trace-log-spec.md](../../docs/trace-log-spec.md)
- 故障定位步骤见 [docs/runbook.md](../../docs/runbook.md)
