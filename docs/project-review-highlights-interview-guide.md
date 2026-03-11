# RAG-QA System 项目审阅与面试资料总表

更新时间：2026-03-11

适用对象：
- 需要快速梳理这个仓库的项目亮点、技术难点、技术选型和工程化价值的人
- 需要把仓库内容转成面试可讲材料、项目复盘材料、简历扩展材料的人

重要说明：
- 本文结论基于仓库代码、配置、脚本、测试与文档交叉审阅整理，不基于猜测。
- 本文不虚构线上真实指标。凡是仓库中没有直接给出生产数据的地方，统一按“代码能力、测试覆盖、可验证工程设计”来表述。
- 若后续需要用于简历中的量化表达，建议再补充真实运行数据，例如吞吐、召回、延迟、错误率、成本趋势。

---

## 1. 项目一句话定位

这不是一个“上传文档后调一下大模型接口”的轻量 Demo，而是一个围绕企业知识库问答场景构建的、具备完整前后端、检索链路、异步入库、工作流恢复、连接器同步、治理调试、运营分析、评测回归和 CI 验证能力的本地化 RAG 平台原型。

如果用面试里的业务语言来讲，这个项目的核心目标是：

1. 把企业内部文档、页面、目录、外部系统内容沉淀成可检索知识库。
2. 把问答从“纯模型输出”改造成“检索证据驱动 + 引用可追踪 + 安全可控”的系统。
3. 把 AI 能力做成一个工程化平台，而不是一次性脚本。

---

## 2. 先说结论：这个项目最值得讲的总体价值

从代码层面看，这个项目最强的地方不是某一个单点算法，而是“把很多 AI 应用里最容易被忽略的非功能性要求补齐了”。

具体来说，项目不只做了“能回答”：

1. 做了上传会话、分片上传、断点续传和幂等控制，说明作者考虑了大文件和弱网络场景。
2. 做了知识库异步入库 Worker、重试和租约机制，说明作者考虑了长任务和失败恢复。
3. 做了多信号检索、查询改写、RRF 融合、重排和调试接口，说明作者不满足于“向量搜一下就完事”。
4. 做了视觉资源抽取、OCR、缩略图和视觉区域切块，说明作者考虑了真实文档并不都是纯文本。
5. 做了工作流运行记录、失败重试和 resume checkpoint，说明作者不是把问答当成一次黑盒 RPC，而是当成可恢复工作流。
6. 做了 prompt safety、证据注入检测、拒答/降级策略，说明作者考虑了 RAG 系统里“恶意证据”和“提示注入”。
7. 做了成本统计、Token 统计、预算控制、运营看板，说明作者在意 AI 应用上线后的真实运营成本。
8. 做了连接器体系，支持本地目录、Notion、URL 页面、飞书/钉钉文档、SQL 查询，说明作者理解知识来源不是单一上传。
9. 做了前端工作台、检索调试台、切片治理、工作流轨迹查看、Prompt/Agent 管理，说明作者把系统设计成平台而不是单接口。
10. 做了 smoke eval、ablation、safety regression、embedding benchmark、CI 构建，说明作者把质量保障纳入研发主链路。

一句更适合面试的总结是：

“这个项目的亮点不是只把 RAG 跑起来，而是把 RAG 从一个功能点做成了一个可治理、可恢复、可观测、可评测、可扩展的平台雏形。”

---

## 3. 系统架构总览

从仓库结构看，系统基本分为五层：

1. 用户交互层：`apps/web`
2. 网关编排层：`apps/services/api-gateway`
3. 知识库能力层：`apps/services/knowledge-base`
4. 共享基础能力层：`packages/python/shared`
5. 运维与质量保障层：`docker-compose.yml`、`scripts/*`、`tests/*`、`.github/workflows/ci.yml`

可以按“请求流”来理解：

1. 用户在前端上传文档、配置知识库、选择检索范围、发起问答。
2. Gateway 负责鉴权、会话管理、Scope 解析、跨知识库 fanout、Agent/Prompt 配置拼装、工作流记录、成本和审计。
3. KB Service 负责知识库 CRUD、上传会话、入库任务、检索、连接器同步、视觉资源查询、分析数据聚合。
4. KB Worker 负责真正的文档解析、切片、OCR、缩略图生成、向量写入和失败重试。
5. Shared 包把跨服务共用的能力统一起来，比如 tracing、idempotency、retrieval、rerank、prompt safety、metrics、auth、model routing。

这个拆分在面试里非常加分，因为它说明作者知道：

1. 问答编排和知识入库是两种不同生命周期的任务。
2. 面向用户的低延迟接口和后台长耗时任务应该解耦。
3. 检索、模型调用、安全、追踪这些横切关注点不应该散落在各个服务里。

---

## 4. 项目亮点清单（15 条，均可展开）

下面每一条都尽量写成“你在面试里能直接说”的版本。

### 亮点 1：这是一个完整的全链路 RAG 系统，而不是单服务 Demo

可说点：
- 仓库同时包含前端工作台、API Gateway、Knowledge Base Service、异步 Worker、共享基础包、运维脚本、评测脚本和自动化测试。
- 这说明项目不是只追求“模型回答出来”，而是把数据进入系统、被治理、被检索、被分析、被评测的完整闭环都做了。
- 面试时可以强调这是“产品化雏形”而不是“技术实验脚本”。

代码证据：
- `apps/web`
- `apps/services/api-gateway/src/app/main.py`
- `apps/services/knowledge-base/src/app/main.py`
- `apps/services/knowledge-base/src/app/worker.py`
- `packages/python/shared/*`
- `docker-compose.yml`

### 亮点 2：前后端边界清晰，Gateway 和 KB Service 职责拆分合理

可说点：
- Gateway 主要负责用户身份、会话、Scope、工作流、LLM 调用、Agent 模式、运营分析汇总。
- KB Service 主要负责知识库、文档、检索、入库、连接器和资源层能力。
- 这种拆分减少了服务间职责污染，也便于后续独立扩展吞吐与部署策略。

代码证据：
- `apps/services/api-gateway/src/app/gateway_chat_routes.py`
- `apps/services/api-gateway/src/app/gateway_platform_routes.py`
- `apps/services/knowledge-base/src/app/kb_upload_routes.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `apps/services/knowledge-base/src/app/kb_connector_routes.py`

### 亮点 3：问答流程不是一次性请求，而是可追踪、可重试、可恢复的工作流

可说点：
- Gateway 为问答记录 workflow run，保存 workflow state、tool calls、LLM trace、resume checkpoint。
- 失败后不是只能“整轮重来”，而是支持从 retrieval 完成后或 generation 完成后恢复。
- 这对于真实生产中的网络波动、上游超时、消息持久化失败很重要。

代码证据：
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `apps/services/api-gateway/src/app/gateway_workflows.py`
- `apps/services/api-gateway/src/app/gateway_chat_routes.py`
- `tests/test_chat_workflow_resume_and_budget.py`
- `tests/test_backend_infra.py`

### 亮点 4：上传链路做了 multipart、断点续传和幂等

可说点：
- 前端不是直接把整文件塞给后端，而是通过 upload session + presign parts + complete 的形式走对象存储分片上传。
- 前端用 `localStorage` 记录 resume key，可以在刷新或中断后复用上传会话。
- 后端在上传创建和完成阶段都加了幂等保护，避免重复提交造成重复 document 或 job。

代码证据：
- `apps/web/src/utils/multipartUpload.ts`
- `apps/web/src/views/kb/KBUploadView.vue`
- `apps/services/knowledge-base/src/app/kb_upload_routes.py`
- `packages/python/shared/idempotency.py`
- `tests/test_visual_stack.py`
- `scripts/evaluation/verify-multipart-resume.py`

### 亮点 5：知识入库不是“一次解析完再开放”，而是分阶段可用

可说点：
- Worker 先完成基础文本解析和 FTS 后，就能让文档提前进入 `query_ready` 窗口。
- 后续再补视觉资源处理、section 向量、chunk 向量，最终进入 `hybrid_ready` 和 `ready`。
- 这是一种很典型的产品思维：尽快让用户可问，而不是等全部增强任务跑完。

代码证据：
- `apps/services/knowledge-base/src/app/worker.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `docs/reference/api-specification.md`

### 亮点 6：检索链路不是单信号，而是结构检索 + 全文检索 + 向量检索 + 融合 + 重排

可说点：
- 项目先做 query rewrite，再分别跑 structure、FTS、vector 三路检索，再通过 weighted RRF 融合，然后再做 rerank。
- 这种设计比单纯 ANN 检索更接近真实企业文档场景，尤其对结构化制度文档、章节标题、表格截图很有效。
- 项目还暴露了检索调试接口，便于诊断 zero-hit、低质量召回和排序问题。

代码证据：
- `apps/services/knowledge-base/src/app/retrieve.py`
- `packages/python/shared/query_rewrite.py`
- `packages/python/shared/retrieval.py`
- `packages/python/shared/rerank.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `apps/web/src/views/kb/RetrievalDebuggerView.vue`

### 亮点 7：支持视觉文档处理，不只盯纯文本

可说点：
- Worker 会抽取图片/PDF 页面的视觉资源，生成缩略图，并对视觉资源做 OCR。
- OCR 结果不仅能作为整体文本入索引，还会根据 layout 区域进一步生成 `visual_region` 切片。
- 对于表格、票据、截图、扫描件这类企业常见材料，这个能力非常实用。

代码证据：
- `apps/services/knowledge-base/src/app/worker.py`
- `apps/services/knowledge-base/src/app/vision.py`
- `apps/services/knowledge-base/src/app/kb_visual_routes.py`
- `tests/test_visual_stack.py`
- `tests/test_ai_platform_capabilities.py`

### 亮点 8：Agent 模式不是无限制自治，而是“受约束工具调用”

可说点：
- Agent 有明确工具预算：最大 tool calls、最大证据数、最大文档数。
- Agent 工具集也被 Agent Profile 限制，只能在当前 scope 内搜索、列文档、查单库、做简单计算。
- 这种设计避免把 Agent 变成不可控黑盒，同时保留复杂问题分步求解能力。

代码证据：
- `apps/services/api-gateway/src/app/gateway_agent.py`
- `apps/services/api-gateway/src/app/gateway_platform_routes.py`
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `tests/test_platform_and_connector_extensions.py`
- `tests/test_backend_infra.py`

### 亮点 9：Prompt Template 和 Agent Profile 做成平台能力，而不是写死在代码里

可说点：
- 用户可以管理 Prompt Template，也可以配置 Agent persona、默认知识库、启用工具、绑定模板。
- 这说明项目从一开始就在做“AI 平台化”，而不是“把系统 prompt 写死在函数里”。
- 后续如果做多业务域、多角色助手，就很容易演化。

代码证据：
- `apps/services/api-gateway/src/app/gateway_platform_routes.py`
- `apps/services/api-gateway/src/app/gateway_platform_store.py`
- `apps/web/src/views/platform/PromptTemplateView.vue`
- `apps/web/src/views/platform/AgentProfileView.vue`
- `tests/test_ai_platform_capabilities.py`
- `tests/test_platform_and_connector_extensions.py`

### 亮点 10：安全不是事后补丁，而是回答链路内建能力

可说点：
- 项目会扫描用户问题、历史消息、检索证据中的提示注入特征。
- 对高风险输入不是简单报错，而是区分 fallback 和 refuse 两种策略。
- 这对 RAG 尤其关键，因为恶意内容可能来自知识库文档本身。

代码证据：
- `packages/python/shared/prompt_safety.py`
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `tests/test_safety_guardrails.py`

### 亮点 11：系统考虑了 backpressure 和请求幂等，不是“能跑就行”

可说点：
- KB Query 和 Gateway Chat 都使用 inflight limiter，限制全局和单用户并发。
- 对高成本接口会返回明确的 429，并带 `Retry-After`。
- 对消息发送、重试、上传完成这类接口做了 idempotency，减少重复调用副作用。

代码证据：
- `packages/python/shared/inflight_limiter.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `apps/services/api-gateway/src/app/gateway_idempotency.py`
- `tests/test_safety_guardrails.py`
- `tests/test_backend_infra.py`

### 亮点 12：系统具备成本意识和运营分析能力

可说点：
- Gateway 会统计 prompt/completion token 和 estimated cost。
- 支持 session cost budget 超限阻断，避免长对话无限烧钱。
- 前端和接口层都支持 analytics dashboard，能看漏斗、zero-hit、满意度、热点词、成本走势。

代码证据：
- `apps/services/api-gateway/src/app/gateway_pricing.py`
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `apps/services/api-gateway/src/app/gateway_analytics_routes.py`
- `apps/web/src/views/EntryView.vue`
- `tests/test_gateway_pricing.py`
- `tests/test_chat_workflow_resume_and_budget.py`

### 亮点 13：连接器体系较完整，说明项目不局限于手工上传

可说点：
- 已支持本地目录、Notion、URL 页面、飞书文档、钉钉文档、SQL 查询等多类数据源。
- 连接器支持 schedule、dry run、delete missing、run record。
- 这说明项目在往“企业知识接入平台”方向发展，而不是“上传文件网站”。

代码证据：
- `apps/services/knowledge-base/src/app/kb_connector_routes.py`
- `apps/services/knowledge-base/src/app/kb_local_sync.py`
- `apps/services/knowledge-base/src/app/kb_notion_sync.py`
- `apps/services/knowledge-base/src/app/kb_url_sync.py`
- `apps/services/knowledge-base/src/app/kb_sql_sync.py`
- `tests/test_kb_local_sync.py`
- `tests/test_kb_notion_sync.py`
- `tests/test_platform_and_connector_extensions.py`

### 亮点 14：前端不是简单表单页，而是完整的运营与治理工作台

可说点：
- 前端包含统一聊天、知识库管理、多源同步、检索调试、切片治理、Prompt 管理、Agent 管理、审计日志、业务概览等页面。
- 聊天页支持 scope 控制、execution mode 切换、SSE 流式输出、引用展示、工作流轨迹查看、反馈提交。
- 上传页支持大文件上传进度、文档事件查看、知识库 CRUD。

代码证据：
- `apps/web/src/router/index.ts`
- `apps/web/src/views/chat/UnifiedChatView.vue`
- `apps/web/src/views/kb/KBUploadView.vue`
- `apps/web/src/views/kb/RetrievalDebuggerView.vue`
- `apps/web/src/views/platform/PromptTemplateView.vue`
- `apps/web/src/views/platform/AgentProfileView.vue`
- `apps/web/src/views/EntryView.vue`

### 亮点 15：质量保障链条非常完整，具备“研究 + 工程 + 运营”三层验证

可说点：
- 有单元/集成测试，覆盖安全、工作流恢复、成本预算、视觉处理、连接器、模型路由、运维校验等。
- 有离线评测和 ablation：检索消融、embedding provider 对比、安全回归、长文 eval、smoke eval。
- 有 CI：编码检查、Python compile、pytest、前端构建、docker compose config、在线 smoke。

代码证据：
- `tests/*`
- `scripts/evaluation/run-retrieval-ablation.py`
- `scripts/evaluation/compare-embedding-providers.py`
- `scripts/evaluation/run-safety-regression.py`
- `scripts/dev/smoke_eval.py`
- `.github/workflows/ci.yml`

### 专项补充：如果面试官追问 benchmark、幻觉、长尾、量化/显存、并发，可以这样讲

这一段专门回答几个在 RAG 面试里特别容易被追问的问题。重点是基于仓库里已经落地的代码能力来讲，不把没做的事情说成做过。

#### 1. Benchmark 是怎么做的

可以这样讲：
- 项目不是只做功能演示，而是把 benchmark 和回归脚本放进了仓库与 CI。
- 检索侧有 retrieval ablation，比对 `fusion_only`、`rewrite_plus_fusion`、`rewrite_plus_fusion_plus_rerank` 三种配置，用 `recall@1`、`recall@3`、`mrr`、`ndcg@3` 看 query rewrite 和 rerank 是否真的提升排序质量。
- 效果侧有长文 eval，单独统计 `correctness`、`faithfulness`、`citation_alignment`、`refusal precision/recall`、`latency`，避免只看“答得像不像”。
- 数据处理侧有 local ingest benchmark，统计解析耗时、chunk 数和吞吐；embedding 侧还有 provider benchmark，比对不同 embedding backend 的召回质量。
- CI 里直接跑 encoding、compile、pytest、retrieval ablation smoke、embedding benchmark smoke、local ingest benchmark smoke 和在线 smoke eval，说明这些不是一次性脚本，而是进入了质量门禁。

更适合面试的一句话：

“这个项目的 benchmark 不是单一准确率，而是把检索质量、回答可信度、拒答质量、解析吞吐和回归门禁拆开验证。” 

证据：
- `scripts/evaluation/run-retrieval-ablation.py`
- `scripts/evaluation/eval-long-rag.py`
- `scripts/evaluation/benchmark-local-ingest.py`
- `scripts/evaluation/compare-embedding-providers.py`
- `scripts/evaluation/run-eval-suite.py`
- `scripts/observability/rag-daily-report.py`
- `.github/workflows/ci.yml`

#### 2. 模型幻觉问题是怎么压的

可以这样讲：
- 项目没有把“减少幻觉”完全寄托在模型本身，而是先把回答模式拆成 `grounded`、`weak_grounded`、`common_knowledge`、`refusal`。
- 当检索证据不足时，不让模型强答，而是走保守回答或者直接拒答；当允许 common knowledge 时，也会强制加免责声明，明确告诉用户这不是知识库证据回答。
- grounded prompt 明确要求“只能依据提供证据回答”“不得引入证据外事实”“必须带引用标记”，并且在输出后还会补 citation marker。
- 仓库不仅实现了控制逻辑，还在评测脚本里单独统计 `faithfulness` 和 `citation_alignment`，把“有没有幻觉”从主观印象变成可比较指标。
- 对提示注入、越权指令、绕过引用的请求，还会在生成前做 prompt safety 扫描，高风险时直接跳过 LLM，避免被脏证据或恶意输入带偏。

更适合面试的一句话：

“这个项目控制幻觉的核心不是调低 temperature，而是证据分级、引用约束、无证据拒答和评测里的 faithfulness/citation alignment 闭环。” 

证据：
- `packages/python/shared/grounded_answering.py`
- `packages/python/shared/prompt_safety.py`
- `apps/services/api-gateway/src/app/gateway_answering.py`
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `scripts/evaluation/eval-long-rag.py`
- `tests/test_safety_guardrails.py`

#### 3. 长尾效应是怎么处理的

这里要诚实一点讲：
- 仓库里没有单独名为“长尾效应治理”的专项模块，也没有 head / torso / tail 分桶报表。
- 但它确实实现了一组能间接缓解长尾 query 的设计。

可以这样讲：
- 先做 query rewrite，从问题里抽实体、章节提示、关键词扩展，减少用户口语化表达、短问句和追问上下文导致的召回失败。
- 检索不是单路向量搜索，而是 structure、FTS、vector 三路召回。这样低频术语可以被关键词命中，结构性问题可以被标题/章节命中，语义相近问题可以被向量命中。
- 多路结果再走 weighted RRF 融合和 rerank，降低单一路径 miss 时整题失效的概率。
- 文档侧还做了 OCR 和 visual region 切块，意味着表格截图、扫描件、页眉页脚这类原本更容易成为长尾 bad case 的内容也能被召回。
- 前端有 retrieval debugger，脚本里有 retrieval ablation，所以即使没有“长尾专项平台”，也能把尾部 bad case 暴露出来并验证优化有没有生效。

更适合面试的一句话：

“项目没有单独做长尾分桶运营，但用 query rewrite、混合检索、RRF 融合、rerank 和视觉 OCR，把很多长尾 query 的召回问题提前在架构层做了兜底。” 

证据：
- `packages/python/shared/query_rewrite.py`
- `apps/services/knowledge-base/src/app/retrieve.py`
- `packages/python/shared/retrieval.py`
- `packages/python/shared/rerank.py`
- `apps/services/knowledge-base/src/app/vision.py`
- `apps/web/src/views/kb/RetrievalDebuggerView.vue`
- `scripts/evaluation/run-retrieval-ablation.py`

#### 4. 量化加速是怎么做的

这一点要明确边界：
- 目前仓库里没有直接实现大模型量化推理。
- 没看到 `bitsandbytes`、`AWQ`、`GPTQ`、`GGUF`、`4bit/8bit` 之类量化落地，也没有本仓库自带的大模型推理服务。

更准确的说法是：
- 这个仓库把 LLM 调用抽象在 OpenAI-compatible / LangChain 封装后面，并通过 model routing 做路由与 fallback，推理服务可以外置。
- 真正的模型量化如果要做，通常会落在外部推理层，而不是当前仓库内部。
- 当前仓库更偏向“把应用层和推理层解耦”，而不是“在仓库内部做量化内核优化”。

面试里推荐这样回答：

“这个仓库没有直接写模型量化，但把应用编排和模型推理解耦了。如果后续接 vLLM、TGI、LMDeploy 或量化模型服务，改动主要集中在外部推理层和路由配置，不会大改业务链路。” 

证据：
- `packages/python/shared/langchain_chat.py`
- `packages/python/shared/llm_settings.py`
- `packages/python/shared/model_routing.py`
- `apps/services/api-gateway/src/app/ai_client.py`
- `apps/services/api-gateway/src/app/langchain_client.py`

#### 5. 显存优化是怎么做的

这一点也要和量化一样分清楚：
- 仓库里没有直接实现 KV cache 管理、paged attention、tensor parallel、显存卸载、显存水位控制这类典型推理层显存优化。
- 因为当前仓库主要聚焦在 RAG 平台层，不负责自研模型 serving。

但可以讲的资源控制点有：
- embedding 层提供本地轻量 backend 和外部 provider 两种模式，适合在开发、离线评测、低资源环境下切换。
- embedding batch size、FastEmbed batch size、FastEmbed threads 都做成了环境变量，允许按机器资源调节吞吐和内存占用。
- Worker 在 section/chunk 写入和向量索引阶段采用分批处理，而不是整文档一次性全量塞入，降低长文档处理时的资源峰值。

更适合面试的一句话：

“显存优化不是这个仓库的主战场；它真正做的是通过轻量 embedding、本地/外部 provider 切换、批量参数和分阶段入库，把资源占用控制在平台层可调范围内。” 

证据：
- `packages/python/shared/embeddings.py`
- `packages/python/shared/qdrant_store.py`
- `apps/services/knowledge-base/src/app/vector_store.py`
- `apps/services/knowledge-base/src/app/worker.py`
- `.env.example`

#### 6. 并发和高负载是怎么处理的

可以这样讲：
- 在线问答链路用 `InflightLimiter` 限制全局和单用户并发，超限直接返回 `429` 和 `Retry-After`，这是典型的 backpressure 设计。
- Gateway 在多知识库 scope 下会并发 fanout 检索，但用 `asyncio.Semaphore` 控制 fanout 并发度，避免 scope 一大就把下游 KB 服务打爆。
- 流式回答用队列和异步任务把上游 token 流和下游 SSE 输出解耦，流式取消时会释放 inflight slot，避免并发泄漏。
- 文档上传在前端支持 multipart 并发上传与断点续传；长耗时入库则完全拆到 Worker。
- Worker 通过数据库租约、`FOR UPDATE SKIP LOCKED`、重试退避、dead letter 来处理多实例竞争、任务失败和恢复问题，保证长任务不是“抢到就算运气”。

更适合面试的一句话：

“项目把并发分成两类处理：前台问答用限流和背压兜住突发流量，后台入库用租约、重试和 dead letter 兜住长任务稳定性。” 

证据：
- `packages/python/shared/inflight_limiter.py`
- `apps/services/api-gateway/src/app/gateway_chat_routes.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `apps/services/api-gateway/src/app/gateway_retrieval.py`
- `apps/web/src/utils/multipartUpload.ts`
- `apps/services/knowledge-base/src/app/worker.py`
- `tests/test_safety_guardrails.py`
- `tests/test_backend_infra.py`

---

## 5. 技术难点与解决办法（15 条）

这一节最适合面试时回答“你做这个项目最难的地方是什么”。每条都按照“难点 - 为什么难 - 解决思路 - 可复用价值”的结构来写。

### 难点 1：企业文档问答不能只靠向量检索

为什么难：
- 企业制度文档常常是章节化结构，问题会直接指向“第几章”“审批流程”“费用上限”等结构线索。
- 只做向量检索容易漏掉结构命中的内容，尤其在中文长文档场景里更明显。

解决办法：
- 项目实现了 structure、FTS、vector 三路召回。
- 用 `query_rewrite` 把问题中的实体、章节和关键词抽出来。
- 用 weighted RRF 融合，再通过 rerank 提高最终排序质量。

可复用价值：
- 这是典型的“先保证 recall，再优化 precision”的检索架构，适合制度、手册、客服、法务类文档。

证据：
- `apps/services/knowledge-base/src/app/retrieve.py`
- `packages/python/shared/query_rewrite.py`
- `packages/python/shared/retrieval.py`
- `packages/python/shared/rerank.py`

### 难点 2：检索链路需要可解释，否则很难调优

为什么难：
- RAG 问题很多时候不是模型回答错，而是召回错、排序错、切片错。
- 如果接口只返回答案，不返回检索细节，后续几乎没法定位问题。

解决办法：
- 项目提供 `/api/v1/kb/retrieve/debug`，直接返回 rank、score、signal_scores、rerank_score、trace_id。
- 前端还做了 Retrieval Debugger 页面，可直观看到 Top K 结果和分数。

可复用价值：
- 这让系统具备了“检索可观测性”，对模型调优、数据治理和支持排障都很重要。

证据：
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `apps/web/src/views/kb/RetrievalDebuggerView.vue`

### 难点 3：文档入库耗时长，不能让用户一直等待

为什么难：
- 文档解析、OCR、向量化、Qdrant 写入都可能比较慢。
- 如果必须等所有阶段完成才开放查询，用户体验会很差。

解决办法：
- Worker 把入库拆成 parsing_fast、fast_index_ready、visual_pending、hybrid_ready、ready 等阶段。
- 当基础文本切片就绪后，先开放 `query_ready`。
- 后续增强过程继续异步跑完。

可复用价值：
- 这是典型的“增量可用”设计，非常适合大文件、批量导入和弱算力环境。

证据：
- `apps/services/knowledge-base/src/app/worker.py`
- `docs/reference/api-specification.md`

### 难点 4：扫描件、图片、截图里的知识怎么进入检索链路

为什么难：
- 现实世界的知识库并不都是 txt、docx；很多内容是截图、票据、扫描 PDF。
- 如果只提取整页文本，会丢失布局信号，且可用性差。

解决办法：
- 抽取 visual assets，生成原图和缩略图。
- 对视觉资源跑 OCR。
- 把 OCR 结果转成 `visual_ocr` 单元，还把 region/layout 转成 `visual_region` 单元。

可复用价值：
- 这让系统从“文本知识库”升级成“多模态文档知识库”的雏形。

证据：
- `apps/services/knowledge-base/src/app/worker.py`
- `apps/services/knowledge-base/src/app/vision.py`
- `tests/test_visual_stack.py`
- `tests/test_ai_platform_capabilities.py`

### 难点 5：大文件上传与不稳定网络下如何保证可靠性

为什么难：
- 大文件直传容易失败，上传一半断掉会带来糟糕体验。
- 如果刷新页面后会话丢失，还要重新上传，成本很高。

解决办法：
- 后端创建 upload session，返回 multipart 上传上下文。
- 前端按 part 分片上传，实时汇总 progress。
- resume key 存本地，未完成上传可以恢复。

可复用价值：
- 这是典型的大文件上传工程化方案，适用于文档平台、素材平台、知识库平台。

证据：
- `apps/web/src/utils/multipartUpload.ts`
- `apps/services/knowledge-base/src/app/kb_upload_routes.py`
- `scripts/evaluation/verify-multipart-resume.py`

### 难点 6：问答过程中失败，如何避免重复跑整条链路

为什么难：
- 问答链路中既有检索，也有生成，也有持久化。
- 如果 persistence 阶段失败，但 retrieval 和 generation 已经成功，整条重跑会造成浪费。

解决办法：
- Gateway 在 workflow state 里存 resume checkpoint。
- 检索成功后可从 generation 恢复。
- 生成成功后可从 persist_message 恢复。

可复用价值：
- 降低重复成本，尤其适合高成本模型调用和复杂 Agent 流程。

证据：
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `apps/services/api-gateway/src/app/gateway_chat_routes.py`
- `tests/test_chat_workflow_resume_and_budget.py`

### 难点 7：如何防止重复提交导致重复消息、重复上传、重复执行

为什么难：
- 浏览器重试、用户连点、网络抖动、上游超时都会导致重复请求。
- AI 场景下重复执行通常意味着重复花钱和重复写数据。

解决办法：
- 统一实现 idempotency key 和 request hash。
- 状态区分 processing、succeeded、failed，可重放成功结果。
- 上传完成、消息发送、工作流重试都套用了这一机制。

可复用价值：
- 这是把 AI 接口从“幂等性弱”的实验代码提升到“可投入业务接口”的关键一步。

证据：
- `packages/python/shared/idempotency.py`
- `apps/services/api-gateway/src/app/gateway_idempotency.py`
- `apps/services/knowledge-base/src/app/kb_api_support.py`

### 难点 8：高成本问答接口如何做背压保护

为什么难：
- 如果多个用户同时提交长问答，模型、检索和数据库压力都会飙升。
- 没有限流时，最终结果往往是整体雪崩，而不是单请求失败。

解决办法：
- 用 `InflightLimiter` 同时限制 global limit 和 per-user limit。
- 达到阈值就返回 429 和 `Retry-After`。
- 同时记录审计事件和 metrics。

可复用价值：
- 背压保护是 AI 系统工程化里非常容易被忽略但极其重要的一环。

证据：
- `packages/python/shared/inflight_limiter.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `tests/test_safety_guardrails.py`

### 难点 9：提示注入不只来自用户，也可能来自知识库内容

为什么难：
- RAG 的特殊风险在于“证据”本身可能含有恶意指令。
- 如果把检索出的文档直接拼 Prompt，很容易把恶意文本当指令执行。

解决办法：
- 同时扫描 question、history、evidence 三类来源。
- 将风险等级分成 low、medium、high。
- 高风险时根据是否有证据决定 fallback 还是 refuse。

可复用价值：
- 这是一个真正理解 RAG 安全边界的人会做的设计。

证据：
- `packages/python/shared/prompt_safety.py`
- `tests/test_safety_guardrails.py`

### 难点 10：多知识库 fanout 时，单个上游失败不能拖垮整轮问答

为什么难：
- 一个问答范围可能包含多个 corpus。
- 某个知识库检索失败不一定意味着整个回答都必须失败。

解决办法：
- Gateway 对每个 corpus 并发检索。
- 对单服务失败返回 failed service 记录。
- 只要还有有效 evidence，就走 partial failure 路径而不是全量失败。

可复用价值：
- 这是多数据源检索系统常见但很实用的容错设计。

证据：
- `apps/services/api-gateway/src/app/gateway_retrieval.py`
- `tests/test_backend_infra.py`

### 难点 11：AI 成本不可控，如何在系统层面设预算

为什么难：
- 长会话、多轮追问、Agent 模式工具调用都会抬升成本。
- 如果没有预算保护，项目越成功，成本问题越快暴露。

解决办法：
- 对 chat session 聚合 estimated cost。
- 超出预算直接拒绝继续生成。
- 记录预算拒绝审计事件，便于运营侧观察。

可复用价值：
- 这体现了 AI 应用不是只有模型效果，还要考虑单位交付成本。

证据：
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `apps/services/api-gateway/src/app/gateway_pricing.py`
- `tests/test_chat_workflow_resume_and_budget.py`

### 难点 12：不同模型、不同路由如何平滑切换且允许降级

为什么难：
- grounded、agent、common knowledge 可能适合不同模型参数。
- 上游模型失败时，如果没有 fallback route，只能整轮失败。

解决办法：
- `LLM_MODEL_ROUTING_JSON` 支持 route_key、fallback_route_key、provider、model、temperature、max_tokens 等配置。
- 执行层按 route plan 逐步回退。

可复用价值：
- 让模型切换从“改代码”变成“改配置”。

证据：
- `packages/python/shared/llm_settings.py`
- `packages/python/shared/model_routing.py`
- `packages/python/shared/prompt_registry.py`
- `tests/test_ai_platform_capabilities.py`

### 难点 13：连接器同步不只是抓取，还要处理更新、跳过和软删除

为什么难：
- 企业知识源是变化的，如果只会“新增导入”，知识库会越来越脏。
- 真正难的是识别 create、update、skip、soft delete。

解决办法：
- 本地目录同步会规划 create/update/skip/soft delete。
- notion/url/sql 同步也支持 dry run 和 delete_missing。
- 连接器 run 会保留执行记录和最后结果。

可复用价值：
- 这让知识库具备长期维护能力，而不是一次性导入工具。

证据：
- `apps/services/knowledge-base/src/app/kb_local_sync.py`
- `apps/services/knowledge-base/src/app/kb_notion_sync.py`
- `apps/services/knowledge-base/src/app/kb_url_sync.py`
- `apps/services/knowledge-base/src/app/kb_sql_sync.py`
- `tests/test_kb_local_sync.py`
- `tests/test_kb_notion_sync.py`

### 难点 14：仪表盘数据可能部分不可用，但页面不能整体崩

为什么难：
- analytics 往往汇总多个来源，某个来源挂掉并不代表整个 dashboard 应该 500。
- 如果处理不好，前端会频繁白屏。

解决办法：
- Gateway analytics 接口允许 degraded sections。
- KB analytics 不可用时，仍可返回整体 200，并附带 data_quality / degraded 信息。
- 前端有“部分数据降级”的 UI 设计。

可复用价值：
- 体现了平台型产品的稳态设计。

证据：
- `apps/services/api-gateway/src/app/gateway_analytics_routes.py`
- `apps/web/src/views/EntryView.vue`
- `docs/reference/api-specification.md`

### 难点 15：如何证明系统不是“感觉靠谱”，而是“被验证过”

为什么难：
- AI 项目最常见问题是能演示，但无法稳定验证。
- 没有测试和评测，项目很难在面试里证明工程成熟度。

解决办法：
- 仓库加入 pytest 覆盖关键功能。
- 加入 retrieval ablation、embedding benchmark、safety regression、smoke eval。
- CI 自动跑构建、测试、在线 smoke 和 compose 校验。

可复用价值：
- 这是从“个人实验项目”跨到“团队可维护项目”的关键。

证据：
- `tests/*`
- `scripts/evaluation/*`
- `.github/workflows/ci.yml`

---

## 6. 技术选型及原因（18 条）

这一节适合回答“为什么这么选，不选别的”的问题。重点不是背名词，而是说出选型和需求之间的对应关系。

### 选型 1：Vue 3

原因：
- 前端页面较多，但交互复杂度主要集中在表单、工作台和管理页面，Vue 3 的 SFC 模式非常适合这类中后台。
- 对于个人或小团队而言，Vue 的心智负担较低，便于快速搭建完整工作台。

证据：
- `apps/web/package.json`
- `apps/web/src/main.ts`

### 选型 2：TypeScript

原因：
- 前端涉及聊天消息、工作流、引用、知识库、上传会话、反馈、连接器等多类数据结构。
- 使用 TS 有助于控制接口演进成本，减少前后端联调中的“字段拼写错误”和弱类型问题。

证据：
- `apps/web/package.json`
- `apps/web/src/api/*`

### 选型 3：Vite

原因：
- 适合本地开发效率优先的前端工程，构建和热更新速度快。
- 对 Vue 3 支持成熟。

证据：
- `apps/web/package.json`
- `apps/web/vite.config.ts`

### 选型 4：Element Plus

原因：
- 项目是典型平台型中后台，不是营销官网。
- Element Plus 能快速提供 Drawer、Popover、Form、Table、Collapse、Upload 等复杂组件。

证据：
- `apps/web/package.json`
- `apps/web/src/main.ts`

### 选型 5：Pinia

原因：
- 项目共享状态主要集中在鉴权信息，不需要更重的状态架构。
- Pinia 对 Vue 3 组合式 API 友好，足够支撑当前复杂度。

证据：
- `apps/web/package.json`
- `apps/web/src/store/auth.ts`

### 选型 6：Vue Router

原因：
- 系统包含多个工作台页面、权限路由、登录跳转和 workspace 结构。
- 使用路由守卫可自然承载登录态和权限控制。

证据：
- `apps/web/src/router/index.ts`

### 选型 7：FastAPI

原因：
- 需要快速构建结构清晰的 API，且兼顾 Pydantic 校验、异步接口和 SSE。
- FastAPI 在这类“接口多、数据结构明确、文档友好”的项目中性价比很高。

证据：
- `apps/services/api-gateway/src/app/main.py`
- `apps/services/knowledge-base/src/app/main.py`

### 选型 8：PostgreSQL

原因：
- 项目除了业务数据，还需要会话、审计、工作流、反馈、连接器 run、分析聚合等结构化存储。
- PostgreSQL 同时支持 JSONB、事务和全文检索，非常适合这种混合场景。

证据：
- `docker-compose.yml`
- `apps/services/api-gateway/database/migrations/*`
- `apps/services/knowledge-base/database/migrations/*`
- `apps/services/knowledge-base/src/app/retrieve.py`

### 选型 9：Qdrant

原因：
- RAG 场景需要向量检索，而 Qdrant 对语义检索和本地部署都比较友好。
- 与 FastEmbed、LangChain 生态结合方便。

证据：
- `docker-compose.yml`
- `apps/services/knowledge-base/requirements.runtime.txt`
- `packages/python/shared/qdrant_store.py`

### 选型 10：MinIO / 对象存储

原因：
- 原始文档、分片上传、视觉资源、缩略图都不适合直接塞数据库。
- 对象存储天然适合 multipart、presign 和大文件管理。

证据：
- `docker-compose.yml`
- `packages/python/shared/storage.py`
- `apps/services/knowledge-base/src/app/kb_upload_routes.py`

### 选型 11：LangChain Core / OpenAI Compatible 接口

原因：
- 项目需要在 grounded、agent、common knowledge 多种模式之间复用模型封装。
- 通过 compatible 接口和路由配置，后续替换模型供应商成本更低。

证据：
- `apps/services/api-gateway/requirements.runtime.txt`
- `packages/python/shared/langchain_chat.py`
- `packages/python/shared/llm_settings.py`
- `packages/python/shared/model_routing.py`

### 选型 12：FastEmbed + 本地 embedding 兜底

原因：
- 为了避免完全依赖外部 embedding 服务，项目提供本地 embedding 和 provider 对比能力。
- 对本地开发、离线评测和成本控制更友好。

证据：
- `docker-compose.yml`
- `apps/services/knowledge-base/requirements.runtime.txt`
- `packages/python/shared/embeddings.py`
- `scripts/evaluation/compare-embedding-providers.py`

### 选型 13：RapidOCR + Pillow + 文档解析库

原因：
- 企业知识库不可避免包含图片、扫描件、PDF、DOCX。
- OCR 和视觉资源处理是提升覆盖率的关键，而不是可选项。

证据：
- `apps/services/knowledge-base/requirements.runtime.txt`
- `apps/services/knowledge-base/src/app/vision.py`
- `apps/services/knowledge-base/src/app/worker.py`

### 选型 14：Prometheus 指标

原因：
- 项目包含长链路、异步任务、限流、成本、检索和模型调用，单靠日志不够。
- 指标能帮助定位吞吐、耗时和异常分布。

证据：
- `packages/python/shared/metrics.py`
- `apps/services/knowledge-base/src/app/worker.py`
- `apps/services/api-gateway/src/app/gateway_runtime.py`

### 选型 15：PyJWT 与角色/权限模型

原因：
- 系统不只是单人本地工具，而是有 platform_admin、kb_admin、kb_editor、kb_viewer、audit_viewer 等角色。
- 权限应该落在系统边界，而不是只靠前端隐藏按钮。

证据：
- `apps/services/api-gateway/requirements.runtime.txt`
- `packages/python/shared/auth.py`
- `apps/web/src/store/auth.ts`

### 选型 16：Docker Compose

原因：
- 本项目有 PostgreSQL、MinIO、Qdrant、Gateway、KB Service、KB Worker 等多个组件。
- 对本地开发和 CI 来说，Compose 是最直接的可复制环境编排方式。

证据：
- `docker-compose.yml`
- `Makefile`
- `scripts/dev/*.ps1`

### 选型 17：Pytest + 离线评测脚本

原因：
- 传统测试能验证代码正确性，但对检索质量和安全回归不够。
- 所以项目同时保留 pytest 和评测脚本，两条线一起跑。

证据：
- `tests/*`
- `scripts/evaluation/*`

### 选型 18：GitHub Actions

原因：
- 需要自动执行编码检查、构建、测试、smoke 和 compose 配置校验。
- 这保证每次提交至少经过基本工程门禁。

证据：
- `.github/workflows/ci.yml`

---

## 7. 面试最可能问到的实战问题与参考回答（30 题）

说明：
- 这一节不是标准答案，而是“回答思路”。
- 重点是把问题回答成“有工程判断的人说的话”，而不是“背概念”。

### 架构与边界类

#### 问题 1：为什么要拆成 Gateway 和 Knowledge Base Service，而不是一个大服务全做？

回答思路：
- 因为两者职责完全不同。
- Gateway 面向用户交互和会话编排，更偏同步、低延迟、权限和工作流。
- KB Service 面向知识数据管理、检索和入库，更偏数据生命周期和异步任务。
- 这种拆分可以让问答和入库各自扩展，也能避免模型调用逻辑和知识库底层实现耦合在一起。

证据：
- `apps/services/api-gateway/src/app/main.py`
- `apps/services/knowledge-base/src/app/main.py`

#### 问题 2：为什么还要有 `packages/python/shared` 这一层？

回答思路：
- 因为 tracing、auth、idempotency、retrieval、rerank、prompt safety、metrics 这些都是跨服务横切逻辑。
- 如果散落在两个服务里，会出现重复实现和行为漂移。
- 抽成 shared 后，测试也更集中，边界更清晰。

证据：
- `packages/python/shared/*`

#### 问题 3：你如何定义这个项目不是 Demo，而是平台雏形？

回答思路：
- 看是否具备平台型能力：多数据源接入、权限、治理调试、工作流恢复、运营分析、评测、CI。
- 这个项目这些能力都具备了，所以它已经超出“单功能 Demo”。

证据：
- `apps/web/src/router/index.ts`
- `apps/services/knowledge-base/src/app/kb_connector_routes.py`
- `apps/services/api-gateway/src/app/gateway_platform_routes.py`
- `scripts/evaluation/*`

### 检索与 RAG 类

#### 问题 4：为什么不直接用向量检索？

回答思路：
- 企业文档很多问题带有明显结构线索，如章节名、审批节点、制度标题。
- 纯向量检索在这类问题上经常不稳定。
- 所以用 structure + FTS + vector 的混合召回，再做融合和重排。

证据：
- `apps/services/knowledge-base/src/app/retrieve.py`

#### 问题 5：你为什么要做 query rewrite？

回答思路：
- 用户问题往往带有问句词、口语化表达、上下文省略。
- query rewrite 会提取实体、章节提示、关键词扩展，让检索更稳。
- 这一步不一定追求很复杂，但对中文检索效果往往有明显帮助。

证据：
- `packages/python/shared/query_rewrite.py`
- `tests/test_shared_stack.py`

#### 问题 6：为什么融合算法选 RRF，而不是简单加权求和？

回答思路：
- 不同信号的原始分数不可直接比较，量纲差异很大。
- RRF 更关注排名位置，天然适合多路召回融合。
- 在工程上更稳定，也更容易解释和调参。

证据：
- `packages/python/shared/retrieval.py`
- `apps/services/knowledge-base/src/app/retrieve.py`

#### 问题 7：为什么重排层既有 heuristic，也支持 external cross-encoder？

回答思路：
- 工程里不能假设外部 reranker 永远可用。
- heuristic 是零依赖兜底，external cross-encoder 是高质量增强。
- 项目通过 provider 配置实现有则更好、无则不死。

证据：
- `packages/python/shared/rerank.py`
- `tests/test_ai_platform_capabilities.py`

#### 问题 8：检索问题怎么排查？

回答思路：
- 首先看 query rewrite 输出。
- 再看 structure/FTS/vector 各自候选数。
- 再看 fusion 后 final_score 和 rerank_score。
- 如果还不够，就看 chunk 质量和文档切片策略。

证据：
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `apps/web/src/views/kb/RetrievalDebuggerView.vue`

#### 问题 9：为什么你会把 visual OCR 内容也纳入检索，而不是只当附件展示？

回答思路：
- 因为很多真实企业知识就藏在截图、扫描件、表格里。
- 如果不入索引，用户会觉得“明明上传了，为什么问不到”。
- 所以不仅存图，还要把 OCR 和 region 转成可检索单元。

证据：
- `apps/services/knowledge-base/src/app/worker.py`

### 工作流与可靠性类

#### 问题 10：为什么要做 workflow run，而不是只在 chat_messages 里存结果？

回答思路：
- 结果只能说明输出了什么，workflow run 才能说明中间发生了什么。
- 对复杂问答、Agent 工具调用、失败恢复来说，中间状态非常关键。
- workflow run 也是后续做 AIOps、故障定位和执行回放的基础。

证据：
- `apps/services/api-gateway/src/app/gateway_chat_routes.py`
- `apps/services/api-gateway/src/app/gateway_workflows.py`

#### 问题 11：resume checkpoint 解决了什么具体问题？

回答思路：
- 它解决的是“部分阶段已成功但最终失败”的重跑浪费。
- 例如 retrieval 已完成，generation 也成功了，但持久化失败，这时只恢复最后一步即可。
- 这直接减少模型成本和平均恢复时间。

证据：
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `tests/test_chat_workflow_resume_and_budget.py`

#### 问题 12：为什么上传和消息发送都要幂等？

回答思路：
- 因为前端重试、浏览器重发、用户双击都是高概率事件。
- AI 请求幂等失败的代价不只是脏数据，还有重复 token 成本。
- 所以幂等是成本控制的一部分，不只是接口规范。

证据：
- `apps/services/api-gateway/src/app/gateway_idempotency.py`
- `apps/services/knowledge-base/src/app/kb_upload_routes.py`

#### 问题 13：为什么你还做了 inflight limiter，不只靠网关超时？

回答思路：
- 超时是事后失败，限流是事前保护。
- 高成本链路一旦并发堆积，超时往往会放大问题，而不是解决问题。
- inflight limiter 可以在系统进入雪崩前主动拒绝。

证据：
- `packages/python/shared/inflight_limiter.py`
- `tests/test_safety_guardrails.py`

#### 问题 14：Worker 为什么要有 lease 机制和 retry backoff？

回答思路：
- 因为异步任务可能进程崩掉、执行超时或中途宕机。
- lease 用于抢占和恢复“僵尸任务”，backoff 用于避免失败后热循环打满系统。
- 这是一套典型的长任务可靠消费设计。

证据：
- `apps/services/knowledge-base/src/app/worker.py`
- `tests/test_backend_infra.py`

### 安全与治理类

#### 问题 15：RAG 场景下为什么提示注入更难？

回答思路：
- 因为恶意内容不仅来自用户，也可能来自检索到的文档本身。
- 如果系统把文档内容直接拼进 prompt，模型会把它误当规则。
- 所以安全扫描必须覆盖 question、history、evidence 三个来源。

证据：
- `packages/python/shared/prompt_safety.py`

#### 问题 16：为什么 high risk 有时 fallback，有时 refuse？

回答思路：
- 如果已有证据且问题本身是业务相关，完全拒绝会损伤可用性。
- 所以在有证据时可以降级为 `weak_grounded`，保守回答并降低 grounding score。
- 没证据时则直接拒答。

证据：
- `packages/python/shared/prompt_safety.py`
- `tests/test_safety_guardrails.py`

#### 问题 17：权限控制为什么不只放前端做？

回答思路：
- 前端权限只是用户体验控制，真正边界必须在后端。
- 项目里路由守卫和后端 `require_permission` / `require_kb_permission` 是双保险。

证据：
- `apps/web/src/router/index.ts`
- `apps/services/api-gateway/src/app/gateway_audit_support.py`
- `apps/services/knowledge-base/src/app/kb_api_support.py`

#### 问题 18：为什么默认账号密码在本地允许，但非本地环境要阻止？

回答思路：
- 本地开发需要低门槛启动，但默认凭证进入非本地环境就是安全事故。
- 所以代码里对 auth configuration 做了环境敏感校验。

证据：
- `packages/python/shared/auth.py`
- `tests/test_backend_infra.py`

### 成本与运营类

#### 问题 19：为什么要把 token、cost、feedback、zero-hit 都纳入 dashboard？

回答思路：
- 因为 AI 系统是否可运营，不只是看回答数量。
- 需要同时看成本、质量、知识覆盖和用户反馈，才能知道问题出在模型、检索还是数据。

证据：
- `apps/services/api-gateway/src/app/gateway_analytics_routes.py`
- `apps/web/src/views/EntryView.vue`

#### 问题 20：session budget 为什么放在服务层而不是前端提醒？

回答思路：
- 前端提醒不可靠，无法防并发请求和脚本调用。
- 成本预算属于系统约束，必须放在后端才能真正生效。

证据：
- `apps/services/api-gateway/src/app/gateway_chat_service.py`

### Agent 与平台能力类

#### 问题 21：为什么 Agent 要限制工具调用次数？

回答思路：
- Agent 能力越强，成本和不可控性越高。
- 限制工具轮次和证据规模，是在效果和稳定性之间做取舍。
- 这也是生产型 Agent 和演示型 Agent 的差异。

证据：
- `apps/services/api-gateway/src/app/gateway_agent.py`

#### 问题 22：为什么要把 Prompt Template 和 Agent Profile 产品化？

回答思路：
- 因为不同业务线、不同角色、不同语气风格不能都写死在代码里。
- 把这层抽出来后，运营、产品、算法都能参与迭代，而不必每次改代码发版。

证据：
- `apps/services/api-gateway/src/app/gateway_platform_routes.py`
- `apps/web/src/views/platform/*`

#### 问题 23：Agent 为什么还要受 scope 约束？

回答思路：
- 因为 Agent 的核心风险之一是越权。
- 即使工具能力很强，也不能绕过用户当前可见知识范围。
- 所以 search_scope、search_corpus 等工具都要以内层 scope 为边界。

证据：
- `apps/services/api-gateway/src/app/gateway_agent.py`
- `apps/services/api-gateway/src/app/gateway_scope.py`

### 前端与体验类

#### 问题 24：聊天页为什么要同时显示 answer mode、execution mode、model、workflow trace？

回答思路：
- 因为 AI 产品调试成本高，前端如果不暴露这些上下文，问题很难定位。
- 用户、运营、开发都需要知道这次回答是 grounded、weak_grounded、refusal 还是 agent。

证据：
- `apps/web/src/views/chat/UnifiedChatView.vue`

#### 问题 25：前端为什么要自己实现 SSE 解析层？

回答思路：
- 因为需要统一处理 metadata、citation、answer、done 等多类事件。
- 同时也要处理错误、取消、流中断和自定义 headers。

证据：
- `apps/web/src/api/request.ts`
- `apps/services/api-gateway/src/app/gateway_chat_routes.py`

#### 问题 26：上传为什么不直接用浏览器原生表单上传？

回答思路：
- 因为本项目要支持大文件、恢复上传、展示精细进度，还要对接对象存储的 presign part。
- 原生简单表单做不到这些工程需求。

证据：
- `apps/web/src/utils/multipartUpload.ts`
- `apps/web/src/views/kb/KBUploadView.vue`

### 运维与质量类

#### 问题 27：你是怎么验证检索优化有没有真的变好？

回答思路：
- 不是只看一两个手工例子，而是跑离线 fixture。
- 比较 fusion_only、rewrite_plus_fusion、rewrite_plus_fusion_plus_rerank 的 recall@1、MRR、NDCG@3。

证据：
- `scripts/evaluation/run-retrieval-ablation.py`

#### 问题 28：你是怎么验证安全策略没有回归的？

回答思路：
- 用固定 fixture 跑 safety regression。
- 关注 blocked、warned、allowed、reason_codes、source_types 等结果，而不是只看 HTTP 是否 200。

证据：
- `scripts/evaluation/run-safety-regression.py`
- `tests/test_safety_guardrails.py`

#### 问题 29：为什么 CI 里还要跑 backend smoke，而不是只跑 pytest？

回答思路：
- pytest 证明单元逻辑没坏，但不代表多容器集成链路没问题。
- smoke 会真的拉起 postgres/minio/qdrant/kb-service/kb-worker/gateway，再走一次上传和问答。

证据：
- `.github/workflows/ci.yml`
- `scripts/dev/smoke_eval.py`

#### 问题 30：如果让你继续迭代这个项目，你优先做什么？

回答思路：
- 第一类是补真实线上指标和 benchmark 报表，形成“效果/成本/稳定性”三维基线。
- 第二类是做增量索引与 connector 统一调度中心。
- 第三类是把检索调试、chunk 治理和 prompt/agent 管理进一步联动，形成真正的平台闭环。

可结合当前仓库现状讲：
- 现在代码和测试已经把框架打好了，下一步最值得做的是“让数据闭环和治理闭环更强”。

---

## 8. 如果你要把这个项目讲成 STAR，可以怎么讲

### STAR 版本 1：偏工程化平台

S：
- 企业知识库问答常见问题是文档来源杂、检索不稳、答案不可追踪、上传和同步不可靠，很多项目只能做单点演示。

T：
- 搭建一个完整的企业级 RAG 问答平台原型，要求覆盖上传入库、检索问答、Agent 执行、多源同步、治理调试、分析和质量保障。

A：
- 将系统拆分为前端工作台、API Gateway、KB Service、Worker 和 shared 基础包。
- 实现混合检索、视觉 OCR、工作流恢复、幂等控制、并发背压、Prompt 安全、连接器同步和运营分析能力。
- 构建 pytest、offline eval、safety regression、CI smoke 等验证体系。

R：
- 项目具备了从知识接入、索引构建、问答生成到分析回归的完整闭环。
- 能够作为 RAG 产品原型、AI 应用后端模板和面试展示项目使用。
- 从工程完整度上显著区别于只调用模型接口的简单 Demo。

### STAR 版本 2：偏 RAG 技术深度

S：
- 单纯向量检索在中文制度文档、扫描件和多知识库场景中效果不稳定，且问题难排查。

T：
- 设计一套更适合真实企业文档场景的检索与回答链路，同时提升可解释性和可调优性。

A：
- 引入 query rewrite、structure/FTS/vector 多信号召回、weighted RRF 融合和 rerank。
- 为图片/PDF 增加视觉资源抽取、OCR 和布局区域切块。
- 暴露 retrieval debug 接口，并在前端做可视化调试页面。

R：
- 系统从“黑盒问答”升级成“可诊断、可优化、可治理”的 RAG 链路。
- 后续无论做召回调优、切片治理还是知识盲区分析，都有了抓手。

### STAR 版本 3：偏稳定性与可靠性

S：
- AI 应用常见问题是上传中断、请求重复、模型超时、工作流失败后只能整轮重跑，导致体验差且成本高。

T：
- 提升系统端到端可靠性，降低用户侧失败感知和系统侧重复成本。

A：
- 设计 multipart 上传、上传恢复、幂等保护。
- 为问答链路加入 workflow run 和 resume checkpoint。
- 为高成本接口加入 inflight limiter 和 session cost budget。
- 为后台入库任务加入 lease、retry 和 dead-letter 视角。

R：
- 系统在大文件上传、长任务执行和多阶段问答恢复方面具备较强韧性。
- 相比普通 AI Demo，更接近可持续运行的业务系统。

---

## 9. 面试时最能打动人的 12 句总结话术

1. 这个项目不是“调个模型接口”，而是完整把知识接入、入库、检索、回答、反馈、分析和回归都做了。
2. 我最重视的不是把 RAG 跑起来，而是把它做成可治理、可恢复、可观测的系统。
3. 检索链路我没有只押注向量，而是做了结构、全文、向量三路召回和融合重排。
4. 我专门考虑了视觉文档场景，把 OCR 和布局区域都转成了可检索单元。
5. 问答失败时我没有选择粗暴重试，而是做了 workflow checkpoint 和 resume。
6. 上传链路支持 multipart 和断点续传，这是为了贴近真实大文件场景。
7. Agent 模式不是完全放开，而是做了工具预算和 scope 约束，控制风险和成本。
8. 我把 Prompt Template 和 Agent Profile 产品化了，方便不同业务场景复用。
9. 我把提示注入防护放进了回答主链路，而且会扫描用户、历史和证据三个来源。
10. 我把成本、满意度、zero-hit 和热点词放进了 dashboard，因为 AI 系统上线后最重要的是运营闭环。
11. 我做了离线评测、安全回归和 smoke CI，不想让项目停留在“看起来能用”。
12. 这个项目最能证明我的不是某个库会不会用，而是我能把 AI 能力做成一个有工程纪律的系统。

---

## 10. 项目仍可继续加强的地方

这一节也建议在面试里主动说，体现判断力。

1. 仓库目前具备大量工程能力，但缺少真实线上指标，后续最值得补的是真实业务流量下的吞吐、延迟和成本曲线。
2. 检索链路已有 ablation 和 benchmark，但还可以进一步引入更丰富的业务评测集和人工标注集。
3. 连接器已具备雏形，但还可以增加统一调度中心、失败告警和增量同步策略。
4. 视觉处理已具备 OCR 和 layout 区域能力，但可以继续往表格结构化抽取方向增强。
5. 当前使用 Docker Compose 做本地编排，若要继续产品化，可增加更系统的容器化部署与配置分层方案。
6. 运营分析已覆盖漏斗、zero-hit、满意度和成本，但还可以加入 prompt/template/profile 维度分析。
7. 现在的平台能力更偏单租户/单组织本地原型，若走企业级路线，还可以加强租户隔离与更细粒度 RBAC。
8. 现有前端已经具备工作台属性，下一步可以把 chunk 治理、检索调试和效果回归联动起来。

---

## 10.1 补充：企业级文档版本治理能力

这是这次补漏后非常值得讲的新能力，因为它直接回应了企业用户在制度、合同、流程、FAQ 等知识场景里的真实问题：同一份文档会迭代，旧版不能立刻删掉，但系统默认又必须知道“现在应该优先信哪一版”。

### 这项能力为什么有价值

1. 企业知识不是静态的，制度、合同模板、审批流程、客户话术都会持续变化。
2. 很多组织必须同时保留旧版和新版，原因包括审计追溯、历史问责、合规取证和跨时间查询。
3. 如果系统只会“覆盖旧文档”，就失去了追溯能力。
4. 如果系统只会“新旧都放着一起检索”，默认回答就可能混入过期规则。
5. 真正可用的企业知识库必须把“版本并存”和“默认选谁”同时解决。

### 这次补齐后的亮点

1. 给知识库文档增加了 `version_family_key`、`version_label`、`version_number`、`version_status`、`is_current_version`、`effective_from`、`effective_to`、`supersedes_document_id` 等版本治理字段。
2. 默认检索不再简单扫全库，而是只检索“当前生效版本”。
3. 如果显式传 `document_ids`，系统仍允许你强制查询旧版本，满足追溯分析场景。
4. 同一版本家族切换 current 时，服务端会自动收敛冲突，把旧 current 版本降为 `superseded`。
5. 未来生效版本不能直接抢占 current，避免默认检索在正式切换日前出现空窗。
6. 文档详情页新增了版本治理面板，可以直接看当前版本、历史版本、历史正文和版本差异。
7. API 文档明确了默认版本选择规则，避免前后端各自理解不一致。
8. 上传接口支持在导入阶段直接声明版本元数据，而不是只能先传再人工补录。
9. 如果上传时声明了 `supersedes_document_id`，系统会自动继承版本家族并递增版本号。
10. 连接器同步检测到内容变化时，不再原地覆盖旧文档，而是自动创建新版本。
11. 连接器定时任务不是常驻空转，只有真的配置了启用调度的连接器时才启动 runner，更节约资源。
12. 对聊天范围选择也补了展示细节，文档名会带上版本标签和 current 标识，减少人工误选。

### 面试里可以怎么讲这个难点

你可以这样表达：

“企业知识库最大的坑之一不是检索算法本身，而是文档版本治理。因为现实里旧制度不能删，新制度又要立刻成为默认依据。如果没有版本家族、current 标识和生效窗口，系统要么只能覆盖旧文档，要么会把新旧版本一起检索，导致答案混入过期规则。这个项目后来把版本元数据、默认选择规则、手动追溯能力和连接器增量版本化一起补齐了，才更接近真实企业落地要求。”

### 补充后的高频面试问答

#### 问题 31：为什么企业知识库一定要做文档版本治理？

- 因为企业文档会持续迭代，但旧版本又常常不能删除。
- 没有版本治理时，系统默认回答很容易混入过时规则。
- 所以必须同时支持“版本并存”和“默认只查当前有效版本”。

#### 问题 32：旧版本和新版本并存时，你们默认怎么选？

- 默认不传 `document_ids` 时，只检索 `query_ready + active + is_current_version + 生效窗口命中` 的版本。
- 这样普通用户拿到的是当前有效答案。
- 如果运营或法务要追溯旧版，可以显式传 `document_ids` 指向历史文档。

#### 问题 33：为什么不能简单用上传时间最新的文档当默认版本？

- 上传时间最新不等于业务上最新有效。
- 可能存在预发布文档、未来生效文档、回滚文档、补录旧版本文档。
- 所以要把“版本状态”和“生效时间”单独建模，不能偷懒只看 `created_at`。

#### 问题 34：为什么要区分 `version_status` 和 `is_current_version`？

- `version_status` 表示生命周期，例如草稿、有效、已替代、已归档。
- `is_current_version` 表示默认检索应该优先选谁。
- 两者拆开后，系统才能表达“这个版本是 active，但还没切成默认 current”这类治理过程。

#### 问题 35：为什么还要做 `effective_from` / `effective_to`？

- 很多制度会提前录入，但下周或下个月才正式生效。
- 如果没有生效窗口，系统会在错误时间引用新规则。
- 所以 current 之外还要再叠一层时间窗口判断。

#### 问题 36：显式指定旧版本文档会不会破坏默认规则？

- 不会，显式 `document_ids` 是有意覆盖默认规则。
- 默认规则服务于日常问答，显式选择服务于审计、追溯和差异分析。
- 这两种需求都是真实存在的，所以系统必须同时支持。

#### 问题 37：如果业务问“新版到底改了什么”，你们怎么支撑？

- 系统不仅保留历史版本，还能直接返回历史版本正文。
- 同时提供版本 diff，能统计新增、删除、修改了多少切片和章节。
- 这样业务、法务、运营不需要人工逐页对比 PDF，也能快速确认变更点。

#### 问题 38：为什么连接器定时任务要做成“按需启动”？

- 如果系统里根本没有启用调度的连接器，常驻轮询就是纯浪费。
- 所以 scheduler 只有在存在 `schedule_enabled=true` 的连接器时才会启动。
- 连接器被禁用、删除或全部关闭调度后，runner 会自动停掉，减少空转资源占用。

## 11. 证据索引

以下文件最值得重点阅读，也是本文主要判断依据。

### 核心后端

- `apps/services/api-gateway/src/app/main.py`
- `apps/services/api-gateway/src/app/gateway_chat_routes.py`
- `apps/services/api-gateway/src/app/gateway_chat_service.py`
- `apps/services/api-gateway/src/app/gateway_agent.py`
- `apps/services/api-gateway/src/app/gateway_retrieval.py`
- `apps/services/api-gateway/src/app/gateway_platform_routes.py`
- `apps/services/api-gateway/src/app/gateway_analytics_routes.py`
- `apps/services/api-gateway/src/app/gateway_idempotency.py`

### 核心知识库服务

- `apps/services/knowledge-base/src/app/main.py`
- `apps/services/knowledge-base/src/app/worker.py`
- `apps/services/knowledge-base/src/app/retrieve.py`
- `apps/services/knowledge-base/src/app/kb_upload_routes.py`
- `apps/services/knowledge-base/src/app/kb_query_routes.py`
- `apps/services/knowledge-base/src/app/kb_connector_routes.py`
- `apps/services/knowledge-base/src/app/kb_local_sync.py`
- `apps/services/knowledge-base/src/app/kb_notion_sync.py`
- `apps/services/knowledge-base/src/app/kb_url_sync.py`
- `apps/services/knowledge-base/src/app/kb_sql_sync.py`

### 共享基础能力

- `packages/python/shared/query_rewrite.py`
- `packages/python/shared/retrieval.py`
- `packages/python/shared/rerank.py`
- `packages/python/shared/prompt_safety.py`
- `packages/python/shared/model_routing.py`
- `packages/python/shared/llm_settings.py`
- `packages/python/shared/prompt_registry.py`
- `packages/python/shared/inflight_limiter.py`
- `packages/python/shared/idempotency.py`
- `packages/python/shared/tracing.py`
- `packages/python/shared/metrics.py`
- `packages/python/shared/auth.py`

### 前端

- `apps/web/src/router/index.ts`
- `apps/web/src/store/auth.ts`
- `apps/web/src/views/chat/UnifiedChatView.vue`
- `apps/web/src/views/kb/KBUploadView.vue`
- `apps/web/src/views/kb/RetrievalDebuggerView.vue`
- `apps/web/src/views/platform/PromptTemplateView.vue`
- `apps/web/src/views/platform/AgentProfileView.vue`
- `apps/web/src/views/EntryView.vue`
- `apps/web/src/utils/multipartUpload.ts`
- `apps/web/src/api/request.ts`

### 运维与质量

- `docker-compose.yml`
- `Makefile`
- `.github/workflows/ci.yml`
- `scripts/dev/smoke_eval.py`
- `scripts/evaluation/run-retrieval-ablation.py`
- `scripts/evaluation/run-safety-regression.py`
- `scripts/observability/rag-daily-report.py`
- `tests/test_backend_infra.py`
- `tests/test_chat_workflow_resume_and_budget.py`
- `tests/test_safety_guardrails.py`
- `tests/test_ai_platform_capabilities.py`
- `tests/test_platform_and_connector_extensions.py`
- `tests/test_kb_local_sync.py`
- `tests/test_kb_notion_sync.py`
- `tests/test_visual_stack.py`

---

## 12. 最后给一句总评

如果只看“功能数量”，这个项目已经足够丰富；但真正有价值的是，它在 RAG 项目里少见地把可靠性、安全性、可恢复性、可观测性、治理能力和评测链路一起做出来了。

因此，这个仓库最适合被定义为：

“一个面向企业知识库问答场景的、工程化程度较高的全链路 RAG 平台原型。”
