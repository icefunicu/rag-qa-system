# Frontend Source

`apps/web/src/` 是前端源码根目录。

## 目录说明

- `api/`：所有 HTTP 请求封装
- `components/`：可复用展示组件
- `layouts/`：页面布局
- `router/`：路由配置
- `store/`：Pinia 状态管理
- `utils/`：纯工具函数
- `views/`：页面级视图
- `assets/`：静态资源

## 约定

- 页面级业务逻辑优先放在 `views/`
- 可复用 UI 片段放在 `components/`
- 与后端接口相关的代码集中在 `api/`
