# 2026-03 LangChain 深度集成说明

## 目标

本轮改造把项目从“局部使用 LangChain”推进到“检索、问答、评测、运行脚本都围绕 LangChain 主链路组织”的状态。

## 当前状态

### KB 侧

- Qdrant 主集成切到 `langchain-qdrant`
- 向量写入统一走 LangChain `Document`
- 检索主路径统一回到 LangChain `Document`，再映射回既有 `EvidenceBlock`
- `retrieve.py` 内部改成 `StructureRetriever + FTSRetriever + Qdrant hybrid retriever + fusion/rerank runnable`

### Gateway 侧

- 回答生成统一走 LangChain prompt / runnable
- 统一聊天新增 `execution_mode`
- `execution_mode=agent` 时使用 LangChain tool calling 做受限检索编排
- Agent 最多 3 轮工具调用，且必须严格受当前 `scope` 限制

## Agent 工具集

当前只开放 3 个工具：

- `search_scope(question, limit)`
- `list_scope_documents(corpus_id)`
- `search_corpus(corpus_id, question, document_ids, limit)`

约束：

- 不允许超出当前 scope
- 不新增新的公共 API
- 最终答案仍走 grounded answer 链

## 本地运行

推荐命令：

```powershell
make preflight
make init
make up
make smoke-eval
```

说明：

- `make init` 和 `make up` 现在都会先保证 `qdrant` 已启动
- `make smoke-eval` 会覆盖 grounded / agent / refusal 三类最小验证

## 兼容性

对外保持不变：

- `/api/v1/kb/retrieve`
- `/api/v1/kb/query`
- `/api/v1/kb/query/stream`
- `/api/v1/chat/*`

兼容点：

- 响应结构不变
- SSE 主顺序不变
- `EvidenceBlock` 结构不变

新增点：

- 统一聊天请求和响应新增 `execution_mode`
- `agent` 模式的 `strategy_used` 为 `agent_grounded_qa`
