# 贡献指南

感谢你考虑为 RAG-QA System 提交改进。

本仓库是一个由 Go、Python、Vue 和 Docker Compose 组成的多服务项目。为了让改动更容易评审、更安全、更容易回滚，建议所有贡献都保持“小范围、单目标、可验证”。

## 开始之前

- 先阅读 [README.md](README.md) 了解项目概况与启动方式
- 先阅读 [docs/README.md](docs/README.md) 获取文档入口
- 使用 `.env.example` 创建本地 `.env`
- 不要提交任何密钥、`.env` 内容、token、cookie 或私有凭据

## 推荐的本地工作流

### 1. 启动开发环境

```powershell
make up
```

### 2. 保持改动聚焦

请尽量让每个 Pull Request 只解决一个问题，例如：

- 一个缺陷修复
- 一个小型功能
- 一次局部重构
- 一项文档改进

不要把无关清理和行为变化混在同一个 PR 里。

### 3. 执行验证

至少运行与你改动相关的检查。

基础验证命令：

```powershell
python scripts/check_encoding.py
cd services/go-api && go test ./...
cd services/py-rag-service && python -m pytest -q
cd services/py-worker && python -m pytest -q
cd apps/web && npm run build
docker compose config --quiet
```

如果只是文档改动，至少执行：

```powershell
python scripts/check_encoding.py
docker compose config --quiet
```

## 提交信息格式

本仓库使用 Conventional Commits。

示例：

- `feat: add document event polling for uploader`
- `fix: decode gb18030 txt preview correctly`
- `docs: rewrite github-facing readme`

推荐类型：

- `feat`
- `fix`
- `docs`
- `refactor`
- `test`
- `chore`
- `build`
- `ci`

## Pull Request 要求

每个 Pull Request 都应当明确说明：

- `What`：改了什么
- `Why`：为什么要改
- `How to verify`：如何验证，包含命令与预期结果
- `Risk`：已知风险与回滚说明

## 文档同步要求

如果你的改动影响以下任一内容，请在同一个 PR 内同步更新文档：

- API 行为
- 安装或环境变量
- 运行流程
- 日志或排障步骤
- 用户可见行为

## 编码与安全要求

- 优先选择小改动和可回滚方案
- 尽量复用已有工具函数、组件和模式
- 在接口边界处做好输入校验
- 未经明确评审，不要引入破坏性脚本
- 不要打印、提交或回显敏感信息

## 你可以贡献的内容

- 提交缺陷报告
- 改进文档
- 为缺失场景补充测试
- 修复开发体验问题
- 提出小步可落地的产品改进

## 问题咨询

如果你的问题不是明确的缺陷或功能需求，请带着上下文和预期结果提交 Issue，而不是仅给出一句模糊描述。
