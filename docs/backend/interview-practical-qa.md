# 面试高频问题与项目落地解法

这份文档只描述仓库里已经存在的能力，以及基于当前架构最自然的扩展方向，避免把“可以做”说成“已经做完”。

## 一览

| 主题 | 当前状态 | 可以怎么讲 |
| --- | --- | --- |
| Benchmark | 已落地 | 离线检索、端到端问答、长文 ingest、并发检索分层验证 |
| RAG 解决模型幻觉 | 已落地 | 不是只靠 prompt，而是检索、证据分级、拒答、引用、评测闭环 |
| 长尾效应 | 已落地 | 结构命中 + FTS + 向量检索 + Weighted RRF + rerank |
| 量化加速 | 部分落地 | 当前仓库走轻量 embedding + 外部 LLM；量化是下一步部署策略 |
| 显存优化 | 部分落地 | 当前先做架构级降载，模型级显存治理可继续补强 |
| 处理并发 | 已落地 | 网关异步 fanout、worker 抢占式消费、幂等控制、SSE、指标观测 |

## 1. Benchmark 怎么做

项目里已经保留了 4 类 benchmark / eval 入口，面试时不要只说“跑过 benchmark”，要说清楚测的是什么。

### 1.1 离线检索效果

用途：验证 query rewrite、融合检索、rerank 是否真的提高召回。

```powershell
python scripts/evaluation/run-retrieval-ablation.py --fixture <fixture.json>
```

看这些指标：

- `recall@1`
- `recall@3`
- `mrr`
- `ndcg@3`

适合回答：

- “你怎么证明混合检索比单一向量检索更好？”
- “你怎么验证长尾 query 的召回提升？”

### 1.2 端到端问答效果

用途：验证最终回答是否命中正确证据，以及拒答是否可靠。

```powershell
python scripts/evaluation/run-eval-suite.py --password <password> --config <suite.json>
```

看这些指标：

- `accuracy`
- `mrr`
- `ndcg@5`
- `recall@3`
- `citation precision`
- `refusal precision`
- `refusal recall`
- `p95 latency`

适合回答：

- “你怎么判断 RAG 回答是否靠谱？”
- “你怎么评估拒答机制有没有误伤？”

### 1.3 Ingest 性能

本地解析吞吐：

```powershell
python scripts/evaluation/benchmark-local-ingest.py --kb-path <glob-or-file>
```

长文上传到 ready 的全链路：

```powershell
python scripts/evaluation/benchmark-long-ingest.py --password <password> --corpus-id <id> --file <path>
```

看这些指标：

- `throughput_mib_per_s`
- `fast_index_ready`
- `hybrid_ready`
- `ready`

适合回答：

- “大文件上传和索引耗时怎么量化？”
- “为什么文档状态要拆成 staged ingest？”

### 1.4 并发检索性能

这次补充了一个最小可执行的并发 benchmark 脚本：

```powershell
python scripts/evaluation/benchmark-retrieval-concurrency.py `
  --password <password> `
  --base-id <kb_id> `
  --question "报销审批需要哪些角色签字？" `
  --total-requests 100 `
  --concurrency 16
```

看这些指标：

- `success_rate`
- `throughput_rps`
- `p50 / p95 latency`
- `mean retrieval ms`
- `mean selected candidates`

适合回答：

- “并发上来后，系统先爆在哪里？”
- “你怎么给 fanout / 检索链路做容量基线？”

## 2. RAG 怎么解决模型幻觉

这个项目里，抑制幻觉不是靠一句“请基于知识库回答”，而是 5 层控制一起工作：

1. 先检索再生成：回答前必须先经过 `retrieve -> rerank -> evidence select`。
2. 证据分级：按 `grounded / weak_grounded / refusal` 分类，不满足阈值就不放行强结论。
3. 拒答机制：证据不足时返回 `refusal_reason`，而不是让模型自由补全。
4. 强制引用：grounded 回答要求带 `[1] [2]` 引用标记，并返回 `citations`。
5. 可观测性：响应里保留 `grounding_score`、`retrieval`、`trace_id`，能回放问题到底出在检索还是生成。

面试里建议直接这样说：

> 我们不是把“不要幻觉”写在 prompt 里就结束了，而是把回答资格前移到了检索和证据校验阶段。没有足够证据就拒答，有证据才让模型组织语言。

仓库里对应的验证方式：

```powershell
make smoke-eval
```

或：

```powershell
python scripts/evaluation/run-eval-suite.py --password <password> --config <suite.json>
```

## 3. 长尾效应怎么处理

长尾 query 的问题通常不是“模型不够聪明”，而是检索信号太单一。这个项目的处理思路是把结构化信号和语义信号一起用。

当前链路：

1. 上下文化问题：多轮对话先做 question contextualization。
2. Query rewrite：把原始问题改写成更适合检索的表达。
3. 结构命中：优先命中章节名、标题名、制度名这类显式结构。
4. FTS：兜住关键词、编号、术语、缩写。
5. 向量检索：补语义相近但字面不一致的内容。
6. Weighted RRF：把多路排序信号做稳定融合。
7. 轻量 rerank：最后再按 lexical overlap 做一次校正。

这套方案对这些场景特别有用：

- 制度标题很固定，但用户问法很随意
- 少见术语、编号、缩写、角色名
- 文档中只有一两处出现的长尾知识

面试里不要说“我们用向量库解决了长尾”，更准确的说法是：

> 长尾问题本质上是召回问题，不是单一模型问题，所以我们把结构命中、全文检索和向量检索并行化，再用 Weighted RRF 做融合，避免单一路径漏召回。

## 4. 量化加速怎么回答

这里要实话实说。

当前仓库没有内置“自托管量化大模型推理服务”，所以不能说项目已经完成了 4-bit/8-bit 量化部署。当前的真实做法是：

- embedding 侧默认使用轻量 `FastEmbed` 模型
- 生成侧通过 `OpenAI-compatible` 外部 LLM 接口解耦
- 检索和生成拆成独立服务，避免把重模型塞进核心数据链路

如果面试官继续追问“那你会怎么做量化加速”，建议这样答：

1. 先量化生成模型或 reranker，不先动检索主链路。
2. 采用 `int8` 或 `int4` 量化，换吞吐和显存，但必须保留一套未量化基线。
3. 用同一套 eval case 对比 `accuracy / refusal precision / p95 latency / cost`。
4. 如果量化后拒答变差或 citation 对齐下降，就只对高成本模型做量化，不强推全链路。

一句话总结：

> 量化不是默认开启的“优化开关”，而是一个要拿效果回归来交换吞吐和显存的部署决策。

## 5. 显存优化怎么回答

当前仓库主要做的是架构级降载，而不是把所有显存问题都压给模型。

已经落地的点：

- 文档解析、切片、embedding、向量索引走异步 ingest，不阻塞在线查询
- 在线回答只带 top-k 证据，不把整篇文档塞进 prompt
- 对话历史会做裁剪和压缩，不无界增长
- 检索和生成解耦，可以把 embedding / vector search 放在 CPU 侧
- 小模型 embedding 默认化，避免检索链路先吃掉 GPU

如果面试官问“显存不够怎么办”，可以给出这个顺序：

1. 先减输入：缩短上下文、压缩 history、限制 top-k。
2. 再减模型：先换小 embedding / rerank 模型。
3. 再做部署策略：量化、张量并行、外部推理服务。
4. 最后才是加卡，因为那是最贵的手段。

## 6. 并发怎么处理

并发这块项目里已经有比较完整的工程化设计，面试可以按“入口、处理中台、异步任务、重复请求保护”来讲。

### 6.1 在线检索并发

网关对多 corpus 检索采用异步 fanout，并且用 `Semaphore` 控制同时打到下游的请求数，避免下游服务被一次请求打爆。

可调参数：

- `GATEWAY_RETRIEVAL_FANOUT_LIMIT`

面试话术：

> 不是简单 `gather` 全放开，而是明确做并发上限控制，把单请求的横向 fanout 变成可治理的容量消耗。

### 6.2 Worker 并发

ingest job 不是靠进程内队列，而是走数据库抢占：

- `FOR UPDATE SKIP LOCKED`
- `lease_token`
- `lease_expires_at`
- 重试与 dead-letter

这意味着：

- 多 worker 可以安全并发消费
- 某个 worker 崩了，租约过期后任务会被别的 worker 接管
- 不会因为一个长任务卡住整个 ingest 队列

### 6.3 幂等与重复请求保护

这些接口支持 `Idempotency-Key`：

- 聊天消息创建
- 上传创建
- 上传完成

价值是：

- 前端重试不会重复创建资源
- 网络抖动下不会出现一条消息写两次
- 并发重放时可以明确返回 `409 idempotency_conflict`

### 6.4 流式返回与观测

系统支持 SSE，外加指标：

- `/metrics`
- `rag_gateway_retrieval_fanout_wall_ms`
- `rag_gateway_chat_latency_ms`
- `rag_kb_ingest_phase_duration_ms`

所以并发问题不是“感觉慢”，而是可以拆成：

- fanout 慢
- 下游检索慢
- LLM 慢
- ingest 某一阶段慢

## 7. 目前还建议继续补强的点

如果你想让这个项目在面试里更硬，还可以继续补这 3 类内容：

1. 补真实长尾评测集。
   现在脚本入口齐了，但零数据基线下仍要你自己准备真实 fixture。
2. 补量化 A/B 报告。
   例如同一问题集对比未量化、8-bit、4-bit 的精度和 p95。
3. 补 GPU 资源观测。
   例如把显存、batch size、tokens/s 打到统一报告里，和当前的 latency / retrieval 指标一起看。

## 8. 一段可以直接在面试里说的话

> 这个项目不是只做了一个“能回答问题的 RAG demo”，而是把企业知识库问答拆成了可验证的工程链路：离线检索评测验证召回，端到端 eval 验证 grounded answer 和拒答，ingest benchmark 验证上传到 ready 的时延，并发 benchmark 验证容量上限。幻觉问题主要通过证据分级和拒答来压制，长尾问题主要通过结构命中、FTS、向量检索和 Weighted RRF 融合来解决。量化和显存优化我不会说仓库已经做完，但当前架构已经把它们留在了容易演进的位置。
