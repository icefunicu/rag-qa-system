<template>
  <div class="page-shell chat-page">
    <section class="chat-workspace">
      <aside class="session-sidebar">
        <button type="button" class="new-chat-btn" @click="startDraftSession">
          <el-icon><Plus /></el-icon>
          <span>新对话</span>
        </button>
        <div v-if="!sessions.length" class="session-empty">
          <span>暂无历史对话</span>
        </div>
        <div v-else class="session-list">
          <button
            v-for="session in sessions"
            :key="session.id"
            type="button"
            class="session-item"
            :class="{ active: session.id === activeSessionId }"
            @click="selectSession(session)"
          >
            <el-icon class="session-icon"><ChatLineRound /></el-icon>
            <span class="session-title">{{ session.title || '未命名对话' }}</span>
          </button>
        </div>
        <div v-if="sessions.length" class="session-actions">
          <el-button v-if="activeSessionId" text size="small" @click="renameActiveSession">重命名</el-button>
          <el-button v-if="activeSessionId" text size="small" type="danger" @click="handleDeleteSession">删除</el-button>
        </div>
      </aside>

      <main class="chat-main">
        <header class="chat-header">
          <span class="chat-title">{{ activeSessionTitle }}</span>
          <el-popover placement="bottom-start" :width="320" trigger="click">
            <template #reference>
              <button type="button" class="scope-chip">
                <el-icon><Aim /></el-icon>
                <span>{{ currentScopeSummary }}</span>
              </button>
            </template>
            <div class="scope-popover">
              <div class="scope-popover-title">检索范围</div>
              <el-form label-position="top" size="default">
                <el-form-item label="范围模式">
                  <el-radio-group v-model="scopeMode" size="small" @change="handleScopeModeChange">
                    <el-radio-button value="single">单库</el-radio-button>
                    <el-radio-button value="multi">多库</el-radio-button>
                    <el-radio-button value="all">全库</el-radio-button>
                  </el-radio-group>
                </el-form-item>
                <el-form-item label="知识库">
                  <el-select
                    v-model="selectedCorpusIds"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    filterable
                    placeholder="选择知识库"
                    size="small"
                    style="width: 100%"
                    @change="handleCorpusChange"
                  >
                    <el-option
                      v-for="corpus in kbCorpora"
                      :key="corpus.corpus_id"
                      :label="`${corpus.name} (${corpus.queryable_document_count}/${corpus.document_count})`"
                      :value="corpus.corpus_id"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="限定文档">
                  <el-select
                    v-model="selectedDocumentIds"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    filterable
                    :disabled="!documentOptions.length"
                    placeholder="可选"
                    size="small"
                    style="width: 100%"
                  >
                    <el-option
                      v-for="doc in documentOptions"
                      :key="doc.document_id"
                      :label="`${doc.display_name} (${statusMeta(doc.status).label})`"
                      :value="doc.document_id"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="回答策略">
                  <el-switch
                    v-model="allowCommonKnowledge"
                    inline-prompt
                    :active-value="true"
                    :inactive-value="false"
                    active-text="常识兜底"
                    inactive-text="严格证据"
                    @change="handleScopeModeChange"
                  />
                </el-form-item>
              </el-form>
              <p class="scope-summary">{{ selectedCorpusSummary }}</p>
              <p class="scope-summary">
                {{ allowCommonKnowledge ? '未命中知识库证据时，可退回通用知识回答；回答会标注风险提示。' : '仅当知识库有足够证据时才回答，并展示证据片段与引用。' }}
              </p>
            </div>
          </el-popover>
          <el-popover placement="bottom-start" :width="280" trigger="click">
            <template #reference>
              <button type="button" class="scope-chip">
                <el-icon><Setting /></el-icon>
                <span>{{ executionMode === 'agent' ? '智能体模式' : '标准问答' }}</span>
              </button>
            </template>
            <div class="scope-popover">
              <div class="scope-popover-title">执行模式</div>
              <el-radio-group v-model="executionMode" size="small" @change="handleExecutionModeChange">
                <el-radio-button value="grounded">标准模式</el-radio-button>
                <el-radio-button value="agent">智能体 (Agent)</el-radio-button>
              </el-radio-group>
              <p class="scope-summary" style="margin-top: 12px;">
                {{ executionMode === 'agent' ? '允许助手多步思考、分解问题并多次检索，适合解决复杂问题。' : '基于检索到的片段直接生成回答，速度较快。' }}
              </p>
            </div>
          </el-popover>
        </header>

        <div ref="messageListRef" class="message-list">
          <div v-if="!messages.length" class="message-empty">
            <div class="welcome-state">
              <p class="welcome-text">输入问题开始对话</p>
              <div class="suggested-chips">
                <button
                  v-for="prompt in suggestedQuestions"
                  :key="prompt"
                  type="button"
                  class="suggest-chip"
                  @click="applyPrompt(prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
            </div>
          </div>

          <template v-else>
            <transition-group name="chat-fade">
              <article
                v-for="message in messages"
                :key="message.id"
                class="message-row"
                :class="message.role"
              >
                <div class="avatar-wrap">
                  <el-avatar v-if="message.role === 'user'" :size="36" class="avatar user">
                    <el-icon><User /></el-icon>
                  </el-avatar>
                  <el-avatar v-else :size="36" class="avatar assistant">
                    <el-icon><Platform /></el-icon>
                  </el-avatar>
                </div>
                <div class="message-block">
                  <div class="message-bubble" :class="message.role">
                    <div v-if="message.role === 'assistant'" class="bubble-meta">
                      <span class="assistant-name">RAG 助手</span>
                      <span v-if="message.answer_mode" class="mode-tag">{{ answerModeLabel(message.answer_mode) }}</span>
                      <span v-if="message.execution_mode === 'agent'" class="mode-tag agent-tag">智能体模式</span>
                      <span v-if="message.model" class="model-tag">{{ message.model }}</span>
                    </div>
                    <div
                      v-if="message.role === 'assistant' && message.safety_notice"
                      class="answer-safety"
                      :class="`is-${message.safety_notice.level}`"
                    >
                      <strong>{{ message.safety_notice.title }}</strong>
                      <span>{{ message.safety_notice.message }}</span>
                    </div>
                    <div v-if="false" class="answer-warning">
                      常识兜底回答，不保证与当前知识库或业务规则完全一致，请人工核实。
                    </div>
                    <div v-if="message.role === 'assistant' && message.streaming && !message.content" class="rag-thinking">
                      <el-icon class="is-loading"><Connection /></el-icon>
                      <span>正在检索并生成回答...</span>
                    </div>
                    <div v-else class="message-content markdown-body" v-html="renderMarkdown(message.content)"></div>
                    <div v-if="message.role === 'assistant'" class="rag-meta">
                      <span v-if="message.retrieval">检索 {{ message.retrieval.aggregate?.retrieval_ms || 0 }}ms</span>
                      <span v-if="message.retrieval?.aggregate?.selected_candidates">
                        · 召回 {{ message.retrieval.aggregate.selected_candidates }} 条
                      </span>
                      <span v-if="message.workflow_run" class="workflow-link">
                        <a href="#" @click.prevent="showWorkflow(message.workflow_run)">
                          <el-icon><Link /></el-icon> 查看执行轨迹
                        </a>
                      </span>
                    </div>
                  </div>
                  <div v-if="message.role === 'assistant' && (message.citations?.length || 0) > 0" class="inline-citations">
                    <CitationList :citations="message.citations" title="引用来源" mode="kb" />
                  </div>
                </div>
              </article>

              <article v-if="asking && !hasStreamingAssistant" key="typing" class="message-row assistant">
                <div class="avatar-wrap">
                  <el-avatar :size="36" class="avatar assistant">
                    <el-icon><Platform /></el-icon>
                  </el-avatar>
                </div>
                <div class="message-block">
                  <div class="message-bubble assistant typing">
                    <div class="rag-thinking">
                      <el-icon class="is-loading"><Connection /></el-icon>
                      <span>正在检索并生成回答…</span>
                    </div>
                  </div>
                </div>
              </article>
            </transition-group>
          </template>
        </div>

        <div class="composer-bar">
          <el-input
            v-model="question"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="输入消息…  Ctrl+Enter 发送"
            resize="none"
            @keydown.ctrl.enter.prevent="ask"
            class="composer-input"
          />
          <div class="composer-toolbar">
            <button
              v-for="prompt in suggestedQuestions.slice(0, 2)"
              :key="`q-${prompt}`"
              type="button"
              class="quick-chip"
              @click="applyPrompt(prompt)"
            >
              {{ prompt }}
            </button>
            <el-button type="primary" :loading="asking" circle class="send-btn" @click="ask">
              <el-icon><Position /></el-icon>
            </el-button>
          </div>
        </div>
      </main>

      <el-drawer
        v-model="workflowDrawerVisible"
        title="执行轨迹 (Workflow Run)"
        size="50%"
        :destroy-on-close="true"
      >
        <div v-if="workflowRunDetail" class="workflow-detail">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="Run ID">{{ workflowRunDetail.id }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="workflowRunDetail.status === 'completed' ? 'success' : (workflowRunDetail.status === 'failed' ? 'danger' : 'info')" size="small">
                {{ workflowRunDetail.status }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="执行模式">{{ workflowRunDetail.execution_mode }}</el-descriptions-item>
            <el-descriptions-item label="Trace ID" v-if="workflowRunDetail.trace_id">{{ workflowRunDetail.trace_id }}</el-descriptions-item>
            <el-descriptions-item label="重试自" v-if="workflowRunDetail.retried_from_run_id">{{ workflowRunDetail.retried_from_run_id }}</el-descriptions-item>
            <el-descriptions-item label="耗时 (LLM)" v-if="workflowRunDetail.llm_trace?.duration_ms">
              {{ workflowRunDetail.llm_trace.duration_ms }} ms
            </el-descriptions-item>
            <el-descriptions-item label="路由策略 (Route Key)" v-if="workflowRunDetail.llm_trace?.route_key">
              <el-tag size="small" type="info">{{ workflowRunDetail.llm_trace.route_key }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <div class="workflow-section">
            <h4>LLM Trace</h4>
            <pre class="json-viewer">{{ JSON.stringify(workflowRunDetail.llm_trace || {}, null, 2) }}</pre>
          </div>
          <div class="workflow-section" v-if="workflowRunDetail.tool_calls?.length">
            <h4>Tool Calls</h4>
            <pre class="json-viewer">{{ JSON.stringify(workflowRunDetail.tool_calls || [], null, 2) }}</pre>
          </div>
          <div class="workflow-section">
            <h4>Workflow State</h4>
            <pre class="json-viewer">{{ JSON.stringify(workflowRunDetail.workflow_state || {}, null, 2) }}</pre>
          </div>
          <div class="workflow-actions" v-if="workflowRunDetail.status === 'failed'">
            <el-button type="primary" :loading="retrying" @click="retryWorkflow(workflowRunDetail.id)">重试该执行</el-button>
          </div>
        </div>
        <div v-else v-loading="loadingWorkflow" style="min-height: 200px;"></div>
      </el-drawer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import CitationList from '@/components/CitationList.vue';
import { Position, User, Platform, Connection, Plus, ChatLineRound, Aim, Setting, Link } from '@element-plus/icons-vue';
import { marked } from 'marked';
import {
  createChatSession,
  deleteChatSession,
  defaultChatScope,
  listChatCorpora,
  listChatCorpusDocuments,
  listChatMessages,
  listChatSessions,
  streamChatMessage,
  updateChatSession,
  getWorkflowRun,
  retryWorkflowRun,
  type ChatScope
} from '@/api/chat';
import { createIdempotencyKey, isAbortRequestError, isHandledRequestError } from '@/api/request';
import { statusMeta } from '@/utils/status';
import { buildSafetyNotice } from '@/utils/safety';

const route = useRoute();

const corpora = ref<any[]>([]);
const sessions = ref<any[]>([]);
const messages = ref<any[]>([]);
const documentsByCorpus = ref<Record<string, any[]>>({});
const messageListRef = ref<HTMLElement | null>(null);

const activeSessionId = ref('');
const question = ref('');
const asking = ref(false);
let currentController: AbortController | null = null;

const scopeMode = ref<'single' | 'multi' | 'all'>('all');
const selectedCorpusIds = ref<string[]>([]);
const selectedDocumentIds = ref<string[]>([]);
const allowCommonKnowledge = ref(false);
const executionMode = ref<'grounded' | 'agent'>('grounded');

const workflowDrawerVisible = ref(false);
const workflowRunDetail = ref<any>(null);
const loadingWorkflow = ref(false);
const retrying = ref(false);

const suggestedQuestions = [
  '报销审批需要哪些角色签字？',
  '试用期请假流程与正式员工有哪些区别？',
  '跨文档看，客服升级流程有哪些共性要求？'
];

const renderMarkdown = (text: string) => {
  if (!text) return '';
  const renderer = new marked.Renderer();
  renderer.code = (options: any) => {
    const code = options.text;
    const language = options.lang || 'text';
    return `
      <div class="code-block-wrapper">
        <span class="code-lang">${language}</span>
        <pre><code class="language-${language}">${code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</code></pre>
      </div>
    `;
  };
  marked.setOptions({ renderer });
  return marked.parse(text) as string;
};

const kbCorpora = computed(() => corpora.value.filter((item) => item.corpus_type === 'kb'));

const documentOptions = computed(() => {
  const ids = new Set(selectedCorpusIds.value);
  return Object.values(documentsByCorpus.value)
    .flat()
    .filter((item: any) => ids.has(item.corpus_id) && item.query_ready);
});

const activeSessionTitle = computed(() => {
  if (!activeSessionId.value) {
    return '新会话';
  }
  const session = sessions.value.find((item) => item.id === activeSessionId.value);
  return session?.title || '未命名会话';
});

const currentScopeSummary = computed(() => summarizeScope(buildScope()));
const hasStreamingAssistant = computed(() => messages.value.some((item: any) => item.role === 'assistant' && item.streaming));

function attachMessageSafety(message: any) {
  if (!message || message.role !== 'assistant') {
    return message;
  }

  return {
    ...message,
    safety_notice: buildSafetyNotice({
      answerMode: message.answer_mode,
      evidenceStatus: message.evidence_status,
      refusalReason: message.refusal_reason,
      safety: message.safety
    })
  };
}

const selectedCorpusSummary = computed(() => {
  if (scopeMode.value === 'all' && !selectedCorpusIds.value.length) {
    return '当前未手动限制知识库，默认在全部可用知识库内检索。';
  }

  const names = selectedCorpusIds.value
    .map((id) => kbCorpora.value.find((item) => item.corpus_id === id)?.name)
    .filter(Boolean)
    .join('、');

  if (!names) {
    return '尚未选择知识库。';
  }

  if (!selectedDocumentIds.value.length) {
    return `已选择 ${names}，当前未缩圈到具体文档。`;
  }

  return `已选择 ${names}，并限制到 ${selectedDocumentIds.value.length} 个具体文档。`;
});

function answerModeLabel(mode: string | undefined) {
  if (mode === 'grounded') {
    return '证据回答';
  }
  if (mode === 'weak_grounded') {
    return '保守回答';
  }
  if (mode === 'common_knowledge') {
    return '常识兜底';
  }
  if (mode === 'refusal') {
    return '证据不足';
  }
  if (mode === 'hybrid') {
    return '混合回答';
  }
  if (mode === 'summary') {
    return '总结回答';
  }
  return '标准回答';
}

function buildScope(): ChatScope {
  return {
    mode: scopeMode.value,
    corpus_ids: [...selectedCorpusIds.value],
    document_ids: [...selectedDocumentIds.value],
    allow_common_knowledge: allowCommonKnowledge.value
  };
}

function summarizeScope(scope: Partial<ChatScope> | Record<string, any>): string {
  const mode = String(scope.mode || 'all');
  const corporaCount = Array.isArray(scope.corpus_ids) ? scope.corpus_ids.length : 0;
  const docsCount = Array.isArray(scope.document_ids) ? scope.document_ids.length : 0;

  if (mode === 'single') {
    return `单库 · ${corporaCount} 个知识库 · ${docsCount} 个文档`;
  }

  if (mode === 'multi') {
    return `多库 · ${corporaCount} 个知识库 · ${docsCount} 个文档`;
  }

  return docsCount ? `全库 · 已缩圈 ${docsCount} 个文档` : '全库 · 全部可查文档';
}

async function loadCorpora() {
  const res: any = await listChatCorpora();
  corpora.value = res.items || [];
}

async function loadSessions() {
  const res: any = await listChatSessions();
  sessions.value = res.items || [];
}

async function ensureDocuments(corpusIds: string[]) {
  const targets = corpusIds.filter((corpusId) => !documentsByCorpus.value[corpusId]);
  if (!targets.length) {
    return;
  }

  const results = await Promise.all(targets.map((corpusId) => listChatCorpusDocuments(corpusId)));
  targets.forEach((corpusId, index) => {
    documentsByCorpus.value[corpusId] = (results[index] as any).items || [];
  });
}

function applyScope(scope: Partial<ChatScope> | Record<string, any> | null | undefined) {
  const normalized = {
    ...defaultChatScope(),
    ...(scope || {})
  };

  scopeMode.value = normalized.mode as 'single' | 'multi' | 'all';
  selectedCorpusIds.value = [...(normalized.corpus_ids || [])];
  selectedDocumentIds.value = [...(normalized.document_ids || [])];
  allowCommonKnowledge.value = Boolean(normalized.allow_common_knowledge);
}

async function selectSession(session: any) {
  stopStreaming();
  activeSessionId.value = String(session.id || '');
  applyScope(session.scope_json || defaultChatScope());
  executionMode.value = session.execution_mode === 'agent' ? 'agent' : 'grounded';
  await ensureDocuments(selectedCorpusIds.value);
  const res: any = await listChatMessages(activeSessionId.value);
  messages.value = (res.items || []).map((item: any) => attachMessageSafety(item));
}

function startDraftSession() {
  stopStreaming();
  activeSessionId.value = '';
  messages.value = [];
  question.value = '';
  applyScope(defaultChatScope());
  executionMode.value = 'grounded';
}

async function renameActiveSession() {
  if (!activeSessionId.value) {
    ElMessage.warning('请先选择会话');
    return;
  }

  const currentTitle = activeSessionTitle.value === '未命名会话' ? '' : activeSessionTitle.value;
  let value = '';
  try {
    const promptResult = await ElMessageBox.prompt('输入新的会话标题，便于后续查找和切换。', '重命名会话', {
      inputValue: currentTitle,
      confirmButtonText: '保存',
      cancelButtonText: '取消'
    });
    value = promptResult.value;
  } catch {
    return;
  }

  const nextTitle = value.trim();
  if (!nextTitle) {
    ElMessage.warning('会话标题不能为空');
    return;
  }

  await updateChatSession(activeSessionId.value, { title: nextTitle });
  await loadSessions();
  ElMessage.success('会话标题已更新');
}

async function handleDeleteSession() {
  if (!activeSessionId.value) {
    ElMessage.warning('请先选择会话');
    return;
  }

  try {
    await ElMessageBox.confirm('删除后该会话及全部消息将不可恢复。', '删除会话', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消'
    });
  } catch {
    return;
  }

  const removedSessionId = activeSessionId.value;
  await deleteChatSession(removedSessionId);
  await loadSessions();

  const nextSession = sessions.value.find((item) => String(item.id) !== removedSessionId);
  if (nextSession) {
    await selectSession(nextSession);
  } else {
    startDraftSession();
  }
  ElMessage.success('会话已删除');
}

async function ensureSession(): Promise<string> {
  if (activeSessionId.value) {
    return activeSessionId.value;
  }

  const res: any = await createChatSession({
    scope: buildScope(),
    execution_mode: executionMode.value
  });

  activeSessionId.value = String(res.session_id || '');
  await loadSessions();
  return activeSessionId.value;
}

async function handleScopeModeChange() {
  if (scopeMode.value === 'single' && selectedCorpusIds.value.length > 1) {
    selectedCorpusIds.value = selectedCorpusIds.value.slice(0, 1);
  }

  if (scopeMode.value === 'all' && !selectedCorpusIds.value.length) {
    selectedDocumentIds.value = [];
  }

  await ensureDocuments(selectedCorpusIds.value);
  if (activeSessionId.value) {
    await updateChatSession(activeSessionId.value, { scope: buildScope() });
  }
}

async function handleExecutionModeChange() {
  if (activeSessionId.value) {
    await updateChatSession(activeSessionId.value, { execution_mode: executionMode.value });
    await loadSessions();
  }
}

async function handleCorpusChange() {
  if (scopeMode.value === 'single' && selectedCorpusIds.value.length > 1) {
    selectedCorpusIds.value = selectedCorpusIds.value.slice(-1);
  }

  await ensureDocuments(selectedCorpusIds.value);
  const validDocumentIds = new Set(documentOptions.value.map((item: any) => item.document_id));
  selectedDocumentIds.value = selectedDocumentIds.value.filter((item) => validDocumentIds.has(item));
  if (activeSessionId.value) {
    await updateChatSession(activeSessionId.value, { scope: buildScope() });
  }
}

async function applyRoutePreset() {
  const preset = String(route.query.preset || '');
  const baseId = String(route.query.baseId || '');
  const documentId = String(route.query.documentId || '');
  if (preset === 'kb' && baseId) {
    applyScope({
      mode: 'single',
      corpus_ids: [`kb:${baseId}`],
      document_ids: documentId ? [documentId] : []
    });
    await ensureDocuments(selectedCorpusIds.value);
  }
}

function applyPrompt(prompt: string) {
  question.value = prompt;
}

function stopStreaming() {
  currentController?.abort();
  currentController = null;
  messages.value = messages.value
    .filter((item: any) => !(item?.streaming && item.role === 'assistant' && !String(item.content || item.answer || '').trim()))
    .map((item: any) => item?.streaming ? attachMessageSafety({ ...item, streaming: false }) : item);
  asking.value = false;
}

function scrollMessagesToBottom() {
  const target = messageListRef.value;
  if (!target) {
    return;
  }
  target.scrollTop = target.scrollHeight;
}

function updateStreamingAssistant(messageId: string, updater: (current: any) => any) {
  const index = messages.value.findIndex((item: any) => item.id === messageId);
  if (index < 0) {
    return;
  }
  messages.value[index] = attachMessageSafety(updater({ ...messages.value[index] }));
  void nextTick().then(() => {
    scrollMessagesToBottom();
  });
}

function applyChatStreamEvent(messageId: string, eventName: string, payload: Record<string, any>) {
  if (eventName === 'metadata') {
    updateStreamingAssistant(messageId, (current) => ({
      ...current,
      answer_mode: String(payload.answer_mode || current.answer_mode || ''),
      execution_mode: String(payload.execution_mode || current.execution_mode || ''),
      evidence_status: String(payload.evidence_status || current.evidence_status || ''),
      grounding_score: Number(payload.grounding_score ?? current.grounding_score ?? 0),
      refusal_reason: String(payload.refusal_reason || current.refusal_reason || ''),
      safety: payload.safety ?? current.safety ?? null,
      retrieval: payload.retrieval || current.retrieval || null,
      strategy_used: String(payload.strategy_used || current.strategy_used || ''),
      workflow_run: payload.workflow_run || current.workflow_run || null
    }));
    return;
  }

  if (eventName === 'citation') {
    updateStreamingAssistant(messageId, (current) => {
      const citations = Array.isArray(current.citations) ? [...current.citations] : [];
      const citationKey = `${String(payload.unit_id || '')}:${String(payload.char_range || '')}`;
      const exists = citations.some((item: any) => `${String(item.unit_id || '')}:${String(item.char_range || '')}` === citationKey);
      if (!exists) {
        citations.push(payload);
      }
      return {
        ...current,
        citations
      };
    });
    return;
  }

  if (eventName === 'answer') {
    updateStreamingAssistant(messageId, (current) => ({
      ...current,
      content: String(payload.answer || current.content || ''),
      answer: String(payload.answer || current.answer || ''),
      grounding_score: Number(payload.grounding_score ?? current.grounding_score ?? 0),
      refusal_reason: String(payload.refusal_reason || current.refusal_reason || ''),
      safety: payload.safety ?? current.safety ?? null
    }));
    return;
  }

  if (eventName === 'message') {
    updateStreamingAssistant(messageId, (current) => ({
      ...current,
      ...payload,
      id: String(payload.id || current.id),
      content: String(payload.content || payload.answer || current.content || ''),
      answer: String(payload.answer || current.answer || ''),
      citations: Array.isArray(payload.citations) ? payload.citations : (current.citations || []),
      safety: payload.safety ?? current.safety ?? null,
      retrieval: payload.retrieval || current.retrieval || null,
      latency: payload.latency || current.latency || null,
      cost: payload.cost || current.cost || null,
      usage: payload.usage || current.usage || {},
      workflow_run: payload.workflow_run || current.workflow_run || null,
      streaming: false
    }));
    return;
  }

  if (eventName === 'done') {
    updateStreamingAssistant(messageId, (current) => ({
      ...current,
      streaming: false
    }));
    return;
  }

  if (eventName === 'error') {
    updateStreamingAssistant(messageId, (current) => ({
      ...current,
      streaming: false
    }));
    throw new Error(String(payload.detail || 'stream chat failed'));
  }
}

async function ask() {
  if (asking.value) {
    return;
  }
  if (!question.value.trim()) {
    ElMessage.warning('请输入问题');
    return;
  }

  if (scopeMode.value !== 'all' && !selectedCorpusIds.value.length) {
    ElMessage.warning('请先选择知识库范围');
    return;
  }

  stopStreaming();
  asking.value = true;
  try {
    const sessionId = await ensureSession();
    const currentQuestion = question.value.trim();
    const streamMessageId = `local-assistant-${Date.now()}`;

    messages.value.push({
      id: `local-user-${Date.now()}`,
      role: 'user',
      content: currentQuestion
    });

    question.value = '';
    messages.value.push(attachMessageSafety({
      id: streamMessageId,
      session_id: sessionId,
      role: 'assistant',
      content: '',
      answer: '',
      answer_mode: '',
      execution_mode: executionMode.value,
      evidence_status: 'streaming',
      grounding_score: 0,
      refusal_reason: '',
      citations: [],
      evidence_path: [],
      retrieval: null,
      latency: null,
      cost: null,
      provider: '',
      model: '',
      usage: {},
      safety: null,
      streaming: true
    }));
    await nextTick();
    scrollMessagesToBottom();

    const idempotencyKey = createIdempotencyKey(`chat:${sessionId}`);
    const controller = new AbortController();
    currentController = controller;
    await streamChatMessage(sessionId, {
      question: currentQuestion,
      scope: buildScope(),
      execution_mode: executionMode.value
    }, {
      idempotencyKey,
      signal: controller.signal,
      onEvent: (event) => {
        if (!event.data || typeof event.data !== 'object') {
          return;
        }
        applyChatStreamEvent(streamMessageId, event.event, event.data as Record<string, any>);
      }
    });

    await loadSessions();
  } catch (error: any) {
    if (isAbortRequestError(error)) {
      return;
    }
    messages.value = messages.value.filter((item: any) => !(item?.streaming && item.role === 'assistant' && !String(item.content || item.answer || '').trim()));
    if (isHandledRequestError(error)) {
      return;
    }
    ElMessage.error('统一问答流式输出失败，请重试');
    return;
  } finally {
    currentController = null;
    messages.value = messages.value.map((item: any) => item?.streaming ? attachMessageSafety({ ...item, streaming: false }) : item);
    asking.value = false;
  }
}

async function showWorkflow(workflowInfo: any) {
  if (!workflowInfo || !workflowInfo.id) return;
  workflowRunDetail.value = null;
  workflowDrawerVisible.value = true;
  loadingWorkflow.value = true;
  try {
    const res: any = await getWorkflowRun(workflowInfo.id);
    workflowRunDetail.value = res;
  } catch (e) {
    ElMessage.error('获取执行轨迹失败');
    workflowDrawerVisible.value = false;
  } finally {
    loadingWorkflow.value = false;
  }
}

async function retryWorkflow(runId: string) {
  try {
    retrying.value = true;
    await retryWorkflowRun(runId);
    ElMessage.success('已发起重试，请查看新消息');
    workflowDrawerVisible.value = false;
    // reload messages
    if (activeSessionId.value) {
      const res: any = await listChatMessages(activeSessionId.value);
      messages.value = (res.items || []).map((item: any) => attachMessageSafety(item));
      await nextTick();
      scrollMessagesToBottom();
    }
  } catch (e) {
    ElMessage.error('重试失败');
  } finally {
    retrying.value = false;
  }
}

watch(
  () => messages.value.length,
  async () => {
    await nextTick();
    scrollMessagesToBottom();
  }
);

onMounted(async () => {
  await loadCorpora();
  await loadSessions();
  await applyRoutePreset();

  if (route.query.sessionId) {
    const session = sessions.value.find((item) => item.id === route.query.sessionId);
    if (session) {
      await selectSession(session);
      return;
    }
  }

  if (sessions.value.length) {
    await selectSession(sessions.value[0]);
  }
});

onBeforeUnmount(() => {
  stopStreaming();
});
</script>

<style scoped>
.chat-page {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  padding-bottom: 0;
}

.chat-workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 0;
  overflow: hidden;
  background: var(--bg-panel);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-color);
}

.session-sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color);
  background: var(--bg-panel-muted);
}

.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: 14px;
  padding: 12px 18px;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  color: var(--blue-600);
  font-size: var(--text-body, 0.9375rem);
  font-weight: 500;
  cursor: pointer;
  transition: border-color var(--transition-base), background var(--transition-base);
}

.new-chat-btn:hover {
  border-color: var(--blue-600);
  background: var(--blue-50);
}

.session-empty {
  padding: 28px 18px;
  font-size: var(--text-body, 0.9375rem);
  color: var(--text-muted);
  text-align: center;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-base);
  position: relative;
}

.session-item:hover {
  background: var(--bg-panel);
}

.session-item.active {
  background: var(--blue-50);
  color: var(--blue-700);
  padding-left: 18px;
}

.session-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  background: var(--blue-600);
  border-radius: 0 2px 2px 0;
}

.session-icon {
  flex-shrink: 0;
  font-size: 16px;
}

.session-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.session-actions {
  padding: 8px 12px;
  border-top: 1px solid var(--border-color);
  display: flex;
  gap: 8px;
}

.chat-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.chat-title {
  font-size: var(--text-h2, 1.125rem);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.scope-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-panel-muted);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}

.scope-chip:hover {
  border-color: var(--blue-600);
  color: var(--blue-600);
}

.scope-chip span {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
  white-space: nowrap;
}

.scope-popover-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}

.scope-popover .scope-summary {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px 28px 20px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.message-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 240px;
}

.welcome-state {
  text-align: center;
  max-width: 480px;
}

.welcome-text {
  font-size: var(--text-h2, 1.125rem);
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 24px;
  letter-spacing: -0.02em;
}

.suggested-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
}

.suggest-chip {
  padding: 12px 18px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--bg-panel);
  color: var(--text-primary);
  font-size: var(--text-body, 0.9375rem);
  font-weight: 500;
  cursor: pointer;
  transition: border-color var(--transition-base), background var(--transition-base);
}

.suggest-chip:hover {
  border-color: var(--blue-600);
  background: var(--blue-50);
  color: var(--blue-700);
}

.message-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.message-row.user {
  flex-direction: row-reverse;
}

.avatar-wrap {
  flex-shrink: 0;
}

.avatar.user {
  background: var(--blue-600);
  color: #fff;
}

.avatar.assistant {
  background: var(--bg-panel-muted);
  color: var(--blue-600);
  border: 1px solid var(--border-color);
}

.message-block {
  max-width: 75%;
  min-width: 0;
}

.message-bubble {
  padding: 14px 18px;
  border-radius: var(--radius-md);
  line-height: 1.65;
}

.message-bubble.user {
  background: var(--blue-600);
  color: #fff;
  border-top-right-radius: 6px;
}

.message-bubble.assistant {
  background: var(--bg-panel-muted);
  border: 1px solid var(--border-color);
  border-top-left-radius: 6px;
}

.bubble-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.answer-safety {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  display: grid;
  gap: 4px;
  font-size: 12px;
  line-height: 1.5;
}

.answer-safety.is-warning {
  border: 1px solid rgba(217, 119, 6, 0.24);
  background: rgba(245, 158, 11, 0.12);
  color: #92400e;
}

.answer-safety.is-error {
  border: 1px solid rgba(220, 38, 38, 0.2);
  background: rgba(254, 226, 226, 0.75);
  color: #991b1b;
}

.answer-warning {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(217, 119, 6, 0.24);
  background: rgba(245, 158, 11, 0.12);
  color: #92400e;
  font-size: 12px;
  line-height: 1.5;
}

.assistant-name {
  font-weight: 600;
}

.mode-tag {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  font-size: 11px;
}

.agent-tag {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.3);
  color: #059669;
}

.model-tag {
  padding: 2px 6px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.18);
  color: var(--blue-700);
  font-size: 11px;
}

.message-content {
  font-size: 15px;
  color: var(--text-primary);
}

.message-bubble.user .message-content {
  color: #fff;
}

.rag-meta {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-color);
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  gap: 12px;
  align-items: center;
}

.workflow-link a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--blue-600);
  text-decoration: none;
}
.workflow-link a:hover {
  text-decoration: underline;
}

.inline-citations {
  margin-top: 12px;
}

.inline-citations :deep(.citation-list) {
  gap: 12px;
}

.inline-citations :deep(.citation-card) {
  padding: 12px 16px;
}

.chat-fade-enter-active,
.chat-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.chat-fade-enter-from,
.chat-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

.composer-bar {
  flex-shrink: 0;
  padding: 16px 22px 22px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-panel);
}

.composer-bar .composer-input :deep(.el-textarea__inner) {
  border-radius: var(--radius-md);
  padding: 14px 18px;
  font-size: var(--text-body, 0.9375rem);
  border: 1px solid var(--border-color);
  line-height: 1.6;
}

.composer-bar .composer-input:focus-within :deep(.el-textarea__inner) {
  border-color: var(--blue-600);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 12px;
}

.quick-chip {
  padding: 8px 14px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-caption, 0.75rem);
  font-weight: 500;
  cursor: pointer;
  transition: border-color var(--transition-base), color var(--transition-base), background var(--transition-base);
}

.quick-chip:hover {
  border-color: var(--blue-600);
  color: var(--blue-600);
  background: var(--blue-50);
}

.composer-bar .send-btn {
  flex-shrink: 0;
}

.workflow-detail {
  padding: 0 20px 20px;
}
.workflow-section {
  margin-top: 20px;
}
.workflow-section h4 {
  margin-bottom: 10px;
  color: var(--text-primary);
  font-size: 14px;
}
.json-viewer {
  background: var(--bg-panel-muted);
  border: 1px solid var(--border-color);
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
  font-family: var(--font-mono);
}
.workflow-actions {
  margin-top: 20px;
  text-align: right;
}

/* Markdown Base Styles (scoped to .markdown-body inside bubble) */
:deep(.markdown-body p) {
  margin-bottom: 0.8em;
}
:deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}
:deep(.markdown-body code:not(pre code)) {
  background-color: rgba(126, 142, 161, 0.15);
  padding: 0.2em 0.4em;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.9em;
}
:deep(.message-row.user .markdown-body code:not(pre code)) {
  background-color: rgba(0, 0, 0, 0.2);
  color: #fff;
}
:deep(.code-block-wrapper) {
  border-radius: var(--radius-xs);
  overflow: hidden;
  margin-bottom: 1em;
  border: 1px solid var(--border-color);
  background: var(--bg-panel-muted);
}
:deep(.code-lang) {
  display: block;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border-color);
}
:deep(.markdown-body pre) {
  padding: 12px;
  margin: 0;
  overflow-x: auto;
  font-size: 0.9em;
}
:deep(.message-row.user .code-block-wrapper) {
  background: rgba(0,0,0,0.15);
  border-color: rgba(255,255,255,0.2);
}
:deep(.message-row.user .code-lang) {
  background: rgba(0,0,0,0.2);
  border-bottom-color: rgba(255,255,255,0.1);
  color: rgba(255,255,255,0.8);
}
:deep(.markdown-body ul), :deep(.markdown-body ol) {
  padding-left: 1.5em;
  margin-bottom: 1em;
}
:deep(.markdown-body li) {
  margin-bottom: 0.3em;
}
:deep(.markdown-body h1), :deep(.markdown-body h2), :deep(.markdown-body h3) {
  margin-top: 1.2em;
  margin-bottom: 0.6em;
  font-weight: 600;
  color: var(--text-primary);
}
:deep(.message-row.user .markdown-body h1), 
:deep(.message-row.user .markdown-body h2), 
:deep(.message-row.user .markdown-body h3) {
  color: #fff;
}
:deep(.markdown-body a) {
  color: var(--blue-600);
  text-decoration: underline;
}
:deep(.message-row.user .markdown-body a) {
  color: #93c5fd;
}

.rag-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
}

@media (max-width: 900px) {
  .chat-workspace {
    grid-template-columns: 1fr;
  }

  .session-sidebar {
    max-height: 120px;
    flex-direction: row;
    flex-wrap: wrap;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
  }

  .new-chat-btn {
    margin: 8px;
  }

  .session-list {
    flex-direction: row;
    overflow-x: auto;
    padding: 0 8px 8px;
  }

  .session-item .session-title {
    max-width: 80px;
  }
}

@media (max-width: 768px) {
  .message-block {
    max-width: 90%;
  }
}
</style>
