# Web Console

`apps/web` 是统一前端，基于 `Vue 3 + TypeScript + Vite + Element Plus`。

## 职责

- 登录与权限展示
- AI 对话工作台
- 小说上传、问答、文档详情
- 企业库上传、问答、文档详情

## 路由结构

| 路由 | 说明 |
| --- | --- |
| `/login` | 登录页 |
| `/workspace/entry` | 统一入口页 |
| `/workspace/ai/chat` | AI 对话工作台 |
| `/workspace/novel/upload` | 小说上传线路 |
| `/workspace/novel/chat` | 小说问答页 |
| `/workspace/novel/documents/:id` | 小说文档详情 |
| `/workspace/kb/upload` | 企业库上传线路 |
| `/workspace/kb/chat` | 企业库问答页 |
| `/workspace/kb/documents/:id` | 企业库文档详情 |

## 与后端的边界

- 前端只通过 `gateway` 的 `/api/v1/*` 接口访问后端
- 不直接访问数据库或本地 blob 存储
- 小说、企业库、AI 对话虽然共用一个前端壳层，但在信息架构上是三条独立工作线

## 本地开发

```powershell
make up
```

单独调试：

```powershell
cd apps/web
npm install
npm run dev
```

生产构建：

```powershell
cd apps/web
npm run build
```
