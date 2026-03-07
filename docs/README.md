# 文档中心

本目录是 RAG-QA System 的正式文档入口。文档目标不是展示概念，而是帮助不同角色在最短时间内完成以下任务：

- 了解系统边界和适用场景
- 在本地拉起并验证完整链路
- 集成 API 或二次开发
- 排查上传、索引、预览和问答问题
- 为外部发布、演示和交付准备材料

## 快速导航

| 文档 | 面向对象 | 用途 |
| --- | --- | --- |
| [产品定义](product-definition.md) | 产品、售前、研发负责人 | 说明系统定位、目标用户、边界与非目标 |
| [架构说明](assets/architecture/architecture-seq.md) | 架构师、后端、运维 | 理解组件职责、数据流和关键时序 |
| [开发脚本与本地工作流](dev-scripts.md) | 开发者 | 本地启动、停止、测试、日志、迁移 |
| [API 总览](API_SPECIFICATION.md) | 前端、后端、集成方 | 快速理解认证方式、资源模型和调用顺序 |
| [OpenAPI 契约](openapi.yaml) | 集成方、工具链 | 机器可读 API 定义 |
| [运行手册](runbook.md) | 运维、开发、值班人员 | 常见故障定位与恢复步骤 |
| [日志与追踪规范](trace-log-spec.md) | 开发、运维 | 统一日志字段、检索关键词和排障方式 |
| [演示脚本](demo-script.md) | 售前、面试、路演 | 5 分钟演示路线与讲解话术 |
| [发布说明](release.md) | 维护者 | 版本记录、发版检查、变更交接 |
| [渠道发布素材](resume-bullets.md) | 运营、作者本人 | GitHub/Gitee/博客/简历可直接复用的文案素材 |
| [Demo 数据集说明](demo-dataset/README.md) | 开发、演示 | 样例文档与评测集的使用方式 |
| [基线报告模板](reports/baseline/summary.md) | 研发、评测 | 记录当前版本的测试方法和结果 |

## 阅读顺序建议

### 第一次接触项目

1. [产品定义](product-definition.md)
2. [架构说明](assets/architecture/architecture-seq.md)
3. [开发脚本与本地工作流](dev-scripts.md)

### 准备接入 API

1. [API 总览](API_SPECIFICATION.md)
2. [OpenAPI 契约](openapi.yaml)
3. [运行手册](runbook.md)

### 准备接手维护

1. [开发脚本与本地工作流](dev-scripts.md)
2. [运行手册](runbook.md)
3. [日志与追踪规范](trace-log-spec.md)
4. [发布说明](release.md)

### 准备对外展示

1. [根 README](../README.md)
2. [演示脚本](demo-script.md)
3. [渠道发布素材](resume-bullets.md)

## 文档约定

- `README.md` 负责对外说明和仓库入口
- `docs/openapi.yaml` 是 API 契约的机器可读版本
- Markdown 文档优先描述“为什么、做什么、怎么验证”
- 若代码行为变化影响接口、部署方式或使用方式，必须同步更新对应文档

## 当前文档边界

以下内容不视为“项目说明文档”，因此不在本索引内展开：

- `docs/呢喃诗章(咸鱼飞行家).txt`：大文本测试样本
- `docs/demo-dataset/**/*.txt|json`：样例数据与评测输入
- 自动生成或第三方依赖目录中的 README
