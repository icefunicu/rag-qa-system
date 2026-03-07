# Web Console

`apps/web` 是 RAG-QA System 的前端控制台，基于 Vue 3、TypeScript、Vite 和 Element Plus 构建。

它承担三类职责：

- 登录与权限边界展示
- 聊天与会话交互
- 管理员侧的知识库、文档和评测页面

## 页面结构

| 路由 | 说明 | 角色 |
| --- | --- | --- |
| `/login` | 登录页 | 所有人 |
| `/chat` | 聊天主页 | 已登录用户 |
| `/dashboard/corpora` | 知识库列表 | Admin |
| `/dashboard/corpus/:id` | 某个知识库的文档管理页 | Admin |
| `/dashboard/evaluation` | 评测页面 | Admin |

## 与后端的交互边界

- 默认通过 `/v1` 调用 Go API
- 不直接请求 Qdrant、Redis 或 PostgreSQL
- 文档上传采用“先申请预签名 URL，再直传对象存储，再通知 Go API”的方式
- 上传完成后轮询任务状态与事件接口，用于展示阶段、进度和错误

## 本地开发

### 推荐方式

由仓库根目录统一启动：

```powershell
make up
```

### 单独调试前端

```powershell
cd apps/web
npm install
npm run dev
```

### 生产构建

```powershell
cd apps/web
npm run build
```

## 开发关注点

### 认证

- Token 存储在前端状态中
- 路由守卫负责区分已登录与 Admin 权限

### 上传体验

上传组件会展示：

- 当前阶段
- 最近更新时间
- `jobID`
- `documentID`
- 建议的日志排障命令

### 预览体验

- 小型 TXT：完整文本预览，可在线编辑
- 较大 TXT：只读或部分预览，并展示检测编码
- PDF / DOCX：通过预签名 URL 预览

## 构建与发布注意事项

- 发布前至少执行 `npm run build`
- 如果接口前缀或域名变化，请同步检查 `src/api/request.ts` 与 Vite 代理配置
- 如修改了页面信息架构，请同步更新根 README 与 `docs/README.md`
