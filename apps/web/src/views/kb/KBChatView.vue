<template>
  <div class="page">
    <section class="page-header kb-header">
      <div>
        <el-tag type="success" effect="dark">企业知识库问答</el-tag>
        <h1>企业库问答工作台</h1>
        <p>这条线路专注精确问答、跨文档汇总、制度提取，不使用小说剧情型策略。</p>
      </div>
      <el-button plain @click="router.push('/workspace/kb/upload')">返回上传线路</el-button>
    </section>

    <section class="grid layout">
      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>问答范围</h2>
              <p>限定知识库与文档范围后再提问。</p>
            </div>
          </div>
        </template>

        <el-form label-position="top">
          <el-form-item label="知识库">
            <el-select v-model="selectedBaseId" placeholder="请选择知识库">
              <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="文档范围">
            <el-select v-model="selectedDocumentIds" multiple collapse-tags collapse-tags-tooltip placeholder="默认检索全部可查文档">
              <el-option
                v-for="document in queryableDocuments"
                :key="document.id"
                :label="`${document.file_name} (${statusMeta(document.status).label})`"
                :value="document.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="问题">
            <el-input
              v-model="question"
              type="textarea"
              :rows="5"
              placeholder="例如：请总结员工报销制度中的审批要求。"
            />
          </el-form-item>
          <div class="shortcut-group">
            <span>快捷提问</span>
            <div class="shortcut-list">
              <el-button v-for="item in shortcuts" :key="item" plain size="small" @click="question = item">{{ item }}</el-button>
            </div>
          </div>
          <div class="actions">
            <el-button type="primary" :loading="asking" @click="ask">提交问题</el-button>
            <el-button plain @click="router.push('/workspace/kb/upload')">继续上传</el-button>
          </div>
        </el-form>
      </el-card>

      <div class="result-column">
        <el-card shadow="hover" class="panel result-panel">
          <template #header>
            <div class="card-head">
              <div>
                <h2>回答结果</h2>
                <p>企业库线路按事实、总结、制度提取三类策略返回。</p>
              </div>
              <el-tag v-if="result" :type="result.evidence_status === 'grounded' ? 'success' : 'warning'" effect="plain">
                {{ result?.evidence_status || '等待提问' }}
              </el-tag>
            </div>
          </template>

          <el-empty v-if="!result" description="选择知识库后开始提问" />
          <div v-else class="answer-panel">
            <div class="meta-row">
              <el-tag v-if="asking" type="warning" effect="plain">流式接收中</el-tag>
              <el-tag type="info" effect="plain">{{ result.strategy_used }}</el-tag>
              <el-tag effect="plain">grounding {{ Number(result.grounding_score || 0).toFixed(2) }}</el-tag>
            </div>
            <p class="answer-text">{{ result.answer || '正在接收问答结果...' }}</p>
            <el-alert
              v-if="result.refusal_reason"
              :title="`拒答原因：${result.refusal_reason}`"
              type="warning"
              :closable="false"
            />
          </div>
        </el-card>

        <el-card shadow="hover" class="panel">
          <CitationList :citations="result?.citations || []" title="证据引用" mode="kb" />
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import CitationList from '@/components/CitationList.vue';
import { listKBDocuments, listKnowledgeBases, queryKB, streamKBQuery } from '@/api/kb';
import { isAbortRequestError } from '@/api/request';
import { applyQueryStreamEvent, createEmptyQueryResult, resolveQueryStreamPayload, type QueryResult } from '@/utils/queryStream';
import { statusMeta } from '@/utils/status';

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

const shortcuts = [
  '这份制度的审批要求是什么？',
  '请总结该知识库内与绩效考核相关的核心规则。',
  '跨文档看，客服升级流程有哪些共同要求？',
  '请抽取该政策中的禁止项与例外项。'
];

const queryableDocuments = computed(() => {
  return documents.value.filter((document) => ['fast_index_ready', 'enhancing', 'ready'].includes(document.status));
});

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
    result.value = await queryKB({
      base_id: selectedBaseId.value,
      question: question.value.trim(),
      document_ids: selectedDocumentIds.value
    }) as unknown as QueryResult;
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
    ElMessage.warning('流式问答失败，已回退为普通查询');
    await askOnce();
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
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 30px;
  border-radius: 28px;
}

.kb-header {
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.2), transparent 30%),
    linear-gradient(135deg, #ffffff, #ecfdf5);
}

.page-header h1 {
  margin: 12px 0 8px;
  font-size: 34px;
}

.page-header p {
  margin: 0;
  line-height: 1.7;
  color: var(--text-regular);
}

.grid.layout {
  display: grid;
  grid-template-columns: 420px minmax(0, 1fr);
  gap: 20px;
}

.panel {
  border-radius: 24px;
  border: none;
}

.panel :deep(.el-card__body) {
  padding: 24px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.card-head h2 {
  margin: 0;
}

.card-head p {
  margin: 6px 0 0;
  color: var(--text-secondary);
}

.shortcut-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 18px;
}

.shortcut-group span {
  font-size: 13px;
  color: var(--text-secondary);
}

.shortcut-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.actions {
  display: flex;
  gap: 12px;
}

.result-column {
  display: grid;
  gap: 20px;
}

.result-panel {
  min-height: 280px;
}

.answer-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.meta-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.answer-text {
  margin: 0;
  line-height: 1.85;
  font-size: 15px;
}

@media (max-width: 1080px) {
  .grid.layout {
    grid-template-columns: 1fr;
  }
}
</style>
