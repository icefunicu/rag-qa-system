# Scripts

`scripts/` 按职责拆分，避免所有脚本平铺在根目录。

## 目录说明

- `dev/`：开发环境启动、停止、前端托管
- `quality/`：编码检查、构建校验、CI 汇总
- `observability/`：日志导出与观测辅助
- `evals/`：评测与基准脚本

## 常用入口

```powershell
.\scripts\dev\up.ps1
.\scripts\dev\down.ps1 -Force
.\scripts\quality\ci-check.ps1
.\scripts\observability\aggregate-logs.ps1
```
