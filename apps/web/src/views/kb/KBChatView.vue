<template>
  <div class="page-shell">
    <section class="page-hero">
      <div class="hero-copy">
        <span class="hero-kicker">单库调试模式</span>
        <h2 class="hero-title">知识库内独立测试与靶向回答</h2>
        <p class="hero-subtitle">
          在此模式下，系统不会建立持久化会话记录。仅用于快速核验某个刚上传的知识库或调试特定文档的检索表现。如需保存对话上下文，请使用统一问答。
        </p>

        <div class="hero-metrics">
          <div class="hero-metric">
            <strong>{{ bases.length }}</strong>
            <span>知识库</span>
          </div>
          <div class="hero-metric">
            <strong>{{ queryableDocuments.length }}</strong>
            <span>可查询文档</span>
          </div>
          <div class="hero-metric">
            <strong>{{ asking ? '流式生成中' : '就绪' }}</strong>
            <span>响应状态</span>
          </div>
        </div>
      </div>

      <div class="hero-actions">
        <el-button plain @click="router.push('/workspace/kb/upload')">返回治理面板</el-button>
        <el-button type="primary" @click="router.push('/workspace/chat')">前往统一问答</el-button>
      </div>
    </section>

    <section class="page-grid-two kb-chat-layout">
      <el-card class="surface-card">
        <template #header>
          <div class="section-head">
            <div>
              <h3>靶向测试范围</h3>
              <p>选取要调试的特定知识库与文档切片子集。</p>
            </div>
          </div>
        </template>

        <div class="card-stack">
          <div class="metric-grid">
            <div class="metric-card">
              <span>调试目标库</span>
              <strong>{{ selectedBase?.name || '未选择' }}</strong>
            </div>
            <div class="metric-card">
              <span>缩小检索圈</span>
              <strong>{{ selectedDocumentIds.length ? `${selectedDocumentIds.length} 份` : '全部' }}</strong>
            </div>
          </div>

          <el-form label-position="top">
            <el-form-item label="知识库">
              <el-select v-model="selectedBaseId" placeholder="请选择知识库">
                <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
              </el-select>
            </el-form-item>

            <el-form-item label="文档范围 (可选)">
              <el-select
                v-model="selectedDocumentIds"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="默认检索选定库的全部可查文档"
              >
                <el-option
                  v-for="document in queryableDocuments"
                  :key="document.id"
                  :label="`${document.file_name} (${statusMeta(document.status).label})`"
                  :value="document.id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="探测问题">
              <el-input
                v-model="question"
                type="textarea"
                :rows="6"
                class="tech-input-glow"
                placeholder="例如：请抽取出文档中的异常报警处理机制。"
              />
            </el-form-item>
          </el-form>

          <div class="shortcut-list">
            <el-button v-for="item in shortcuts" :key="item" plain size="small" class="pill-btn" @click="question = item">
              {{ item }}
            </el-button>
          </div>

          <div class="kb-chat-actions">
            <el-button v-if="asking" plain @click="stopStreaming">停止生成</el-button>
            <el-button type="primary" :loading="asking" @click="ask">提交探测请求</el-button>
          </div>
        </div>
      </el-card>

      <div class="aside-stack">
        <el-card class="surface-card">
          <template #header>
            <div class="section-head">
              <div>
                <h3>探测响应</h3>
                <p>该视图仅展示最近一次请求的结果。支持流式打印。</p>
              </div>
              <el-tag v-if="result" :type="result.evidence_status === 'grounded' ? 'success' : 'warning'" effect="plain">
                {{ result?.evidence_status || '等待提问' }}
              </el-tag>
            </div>
          </template>

          <el-empty v-if="!result && !asking" description="设置探测参数后发起请求" />
          
          <!-- RAG Waiting Animation -->
          <div v-else-if="asking && !result?.answer" class="rag-thinking-pipeline">
            <div class="rag-step active">
              <el-icon class="is-loading"><Connection /></el-icon>
              <span>建立调试连接...</span>
            </div>
            <div class="rag-step pulse">
              <el-icon><Search /></el-icon>
              <span>跨库执行全双工检索...</span>
            </div>
            <div class="rag-step pending">
              <el-icon><EditPen /></el-icon>
              <span>等待 LLM 首次 token 返回...</span>
            </div>
          </div>

          <div v-if="result" class="result-panel">
            <div class="pill-row">
              <el-tag v-if="asking" type="warning" effect="plain">接收数据流中</el-tag>
              <el-tag type="info" effect="plain">{{ result.strategy_used || 'Standard' }}</el-tag>
              <el-tag effect="plain">证据综合分 {{ Number(result.grounding_score || 0).toFixed(2) }}</el-tag>
            </div>

            <el-alert
              v-if="resultSafetyNotice"
              :title="resultSafetyNotice.title"
              :description="resultSafetyNotice.message"
              :type="resultSafetyNotice.level === 'error' ? 'error' : 'warning'"
              :closable="false"
              show-icon
            />

            <div class="answer-box markdown-body" v-html="renderMarkdown(result.answer)"></div>

            <el-alert
              v-if="result && false"
              :title="`触发安全或策略拦截：${result?.refusal_reason || ''}`"
              type="error"
              :closable="false"
            />
          </div>
        </el-card>

        <el-card class="surface-card">
          <CitationList :citations="result?.citations || []" title="追溯向量空间记录" mode="kb" />
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { Connection, Search, EditPen } from '@element-plus/icons-vue';
import CitationList from '@/components/CitationList.vue';
import { listKBDocuments, listKnowledgeBases, queryKB, streamKBQuery } from '@/api/kb';
import { isAbortRequestError, isHandledRequestError } from '@/api/request';
import { applyQueryStreamEvent, createEmptyQueryResult, resolveQueryStreamPayload, type QueryResult } from '@/utils/queryStream';
import { buildSafetyNotice } from '@/utils/safety';
import { statusMeta } from '@/utils/status';
import { marked } from 'marked';

const router = useRouter();
const route = useRoute();

const bases = ref<any[]>([]);
const documents = ref<any[]>([]);
const selectedBaseId = ref('');
const selectedDocumentIds = ref<string[]>([]);
const question = ref('');
const asking = ref(false);
const result = ref<QueryResult | null>(null);

let currentController: AbortController | null = null;

const renderMarkdown = (text: string) => {
  if (!text) return '';
  const renderer = new marked.Renderer();
  renderer.code = (options: any) => {
    const code = options.text;
    const language = options.lang || 'text';
    return `
      <div class="code-block-wrapper">
        <div class="code-block-header">
          <div class="mac-btns"><span class="mac-close"></span><span class="mac-min"></span><span class="mac-max"></span></div>
          <span class="lang-label">${language}</span>
        </div>
        <pre><code class="language-${language}">${code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</code></pre>
      </div>
    `;
  };
  marked.setOptions({ renderer });
  return marked.parse(text) as string;
};

const shortcuts = [
  '这份制度的审批要求是什么？',
  '请总结该知识库内与绩效考核相关的核心规则。',
  '跨文档看，客服升级流程有哪些共同要求？',
  '请抽取该政策中的禁止项与例外项。'
];

const selectedBase = computed(() => bases.value.find((base) => String(base.id) === String(selectedBaseId.value)) || null);
const resultSafetyNotice = computed(() => buildSafetyNotice({
  answerMode: result.value?.answer_mode,
  evidenceStatus: result.value?.evidence_status,
  refusalReason: result.value?.refusal_reason,
  safety: result.value?.safety
}));

const queryableDocuments = computed(() =>
  documents.value.filter((document) => ['fast_index_ready', 'enhancing', 'ready', 'hybrid_ready'].includes(document.status))
);

const buildPayload = () => ({
  base_id: selectedBaseId.value,
  question: question.value.trim(),
  document_ids: selectedDocumentIds.value
});

const stopStreaming = () => {
  currentController?.abort();
  currentController = null;
  asking.value = false;
};

const loadBases = async () => {
  const res: any = await listKnowledgeBases();
  bases.value = res.items || [];
  if (!selectedBaseId.value && bases.value.length) {
    selectedBaseId.value = String(route.query.baseId || bases.value[0].id);
  }
};

const loadDocuments = async (baseId: string) => {
  const res: any = await listKBDocuments(baseId);
  documents.value = res.items || [];
  const preset = route.query.documentId ? [String(route.query.documentId)] : [];
  if (preset.length) {
    selectedDocumentIds.value = preset.filter((id) => documents.value.some((document) => document.id === id));
  }
};

const askOnce = async () => {
  if (!selectedBaseId.value) {
    ElMessage.warning('请先选择知识库');
    return;
  }
  if (!question.value.trim()) {
    ElMessage.warning('请输入问题');
    return;
  }
  asking.value = true;
  try {
    result.value = (await queryKB(buildPayload())) as unknown as QueryResult;
  } finally {
    asking.value = false;
  }
};

const ask = async () => {
  if (!selectedBaseId.value) {
    ElMessage.warning('请先选择知识库');
    return;
  }
  if (!question.value.trim()) {
    ElMessage.warning('请输入问题');
    return;
  }

  stopStreaming();
  asking.value = true;
  result.value = createEmptyQueryResult();

  const payload = buildPayload();
  const controller = new AbortController();
  currentController = controller;

  try {
    await streamKBQuery(payload, {
      signal: controller.signal,
      onEvent: (event) => {
        result.value = applyQueryStreamEvent(
          result.value || createEmptyQueryResult(),
          event.event,
          resolveQueryStreamPayload(event.data)
        );
      }
    });
  } catch (error) {
    if (isAbortRequestError(error)) {
      return;
    }
    if (isHandledRequestError(error)) {
      result.value = null;
      return;
    }
    ElMessage.warning('流式问答失败，已回退为普通查询');
    await askOnce().catch(() => {
      result.value = null;
    });
  } finally {
    if (currentController === controller) {
      currentController = null;
      asking.value = false;
    }
  }
};

watch(selectedBaseId, (baseId) => {
  stopStreaming();
  result.value = null;
  selectedDocumentIds.value = [];
  if (!baseId) {
    documents.value = [];
    return;
  }
  void loadDocuments(baseId).catch(() => {
    documents.value = [];
  });
});

onMounted(() => {
  void loadBases().catch(() => {
    bases.value = [];
    documents.value = [];
  });
});

onBeforeUnmount(() => {
  stopStreaming();
});
</script>

<style scoped>
.kb-chat-layout {
  align-items: start;
}

.kb-chat-actions {
  display: flex;
  gap: 12px;
}

.result-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.answer-box {
  padding: 24px;
  border-radius: 16px;
  border: 1px solid var(--border-color);
  min-height: 120px;
}

.shortcut-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pill-btn {
  border-radius: 999px;
}

/* RAG Thinking Pipeline Animation */
.rag-thinking-pipeline {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 32px 16px;
  border-radius: 16px;
  background: var(--bg-panel-muted);
  border: 1px dashed var(--border-color);
}

.rag-step {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: var(--text-secondary);
  transition: all 0.3s ease;
}

.rag-step.active {
  color: var(--blue-600);
  font-weight: 600;
}

.rag-step.pulse {
  animation: text-pulse 2s infinite ease-in-out;
  color: var(--blue-600);
}

.rag-step.pending {
  opacity: 0.4;
}

@keyframes text-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; filter: drop-shadow(0 0 8px rgba(37,99,235,0.4)); }
}

/* Markdown overrides for single chat */
:deep(.markdown-body p) {
  margin-bottom: 0.8em;
  color: var(--text-primary);
  line-height: 1.7;
}
:deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}
:deep(.code-block-wrapper) {
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 1em;
  border: 1px solid var(--border-color);
  background: var(--bg-page);
}
:deep(.code-block-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-panel-muted);
  border-bottom: 1px solid var(--border-color);
}
:deep(.mac-btns) {
  display: flex;
  gap: 6px;
}
:deep(.mac-btns span) {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
:deep(.mac-close) { background: #ff5f56; }
:deep(.mac-min) { background: #ffbd2e; }
:deep(.mac-max) { background: #27c93f; }
:deep(.lang-label) {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  text-transform: uppercase;
}
:deep(.markdown-body pre) {
  padding: 12px;
  margin: 0;
  overflow-x: auto;
  font-size: 0.9em;
}

@media (max-width: 768px) {
  .kb-chat-actions {
    flex-direction: column;
  }
}
</style>
