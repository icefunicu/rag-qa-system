# 基线报告模板

本文件是基线测试记录模板，用于沉淀“某一天、某个版本、某套配置”下的系统表现。

当前仓库不再保留未经验证的性能数字。只有在真实执行测试并保存结果后，才应在此写入具体指标。

## 报告元信息

| 字段 | 值 |
| --- | --- |
| 日期 | `YYYY-MM-DD` |
| 提交 / 版本 | `<git commit / release tag>` |
| 测试环境 | `local / staging / other` |
| 数据集 | `docs/demo-dataset/...` |
| 记录人 | `<name>` |

## 测试范围

勾选本次实际执行的内容：

- [ ] Go API 单元测试
- [ ] Python RAG Service 单元测试
- [ ] Python Worker 单元测试
- [ ] 前端构建
- [ ] 文档上传链路验证
- [ ] 文本预览验证
- [ ] 流式问答验证
- [ ] 反馈接口验证

## 验证命令

```powershell
python scripts/check_encoding.py
cd services/go-api && go test ./...
cd services/py-rag-service && python -m pytest -q
cd services/py-worker && python -m pytest -q
cd apps/web && npm run build
docker compose config --quiet
```

如果有额外性能或评测脚本，也应在此追加。

## 结果记录

### 功能性结论

- 文档上传：
- 文档入库：
- 文档预览：
- 普通问答：
- 流式问答：
- 删除与重试：

### 质量指标

只有执行过真实测量时才填写：

| 指标 | 结果 | 备注 |
| --- | --- | --- |
| 上传成功率 |  |  |
| 入库成功率 |  |  |
| 首字延迟 TTFT |  |  |
| 平均问答耗时 |  |  |
| 错误率 |  |  |

## 发现的问题

| 编号 | 问题 | 影响 | 建议 |
| --- | --- | --- | --- |
| 1 |  |  |  |

## 结论

示例模板：

> 本次基线验证覆盖了上传、入库、预览和问答主链路。所有基础测试通过，但尚未执行完整性能压测，因此当前结果仅可用于功能性验收，不应用于对外宣传性能指标。
