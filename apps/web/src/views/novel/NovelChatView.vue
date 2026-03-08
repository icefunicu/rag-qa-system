<template>
  <div class="page">
    <section class="page-header spoiler-header">
      <div>
        <el-tag type="danger" effect="dark">可能剧透</el-tag>
        <h1>小说问答工作台</h1>
        <p>这条线路专门处理人物细节、剧情发展、关系因果、人物成长与设定主题。</p>
      </div>
      <el-button plain @click="router.push('/workspace/novel/upload')">返回上传线路</el-button>
    </section>

    <section class="grid layout">
      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>问答范围</h2>
              <p>先选择作品库，再限定问答文档。</p>
            </div>
          </div>
        </template>

        <el-form label-position="top">
          <el-form-item label="作品库">
            <el-select v-model="selectedLibraryId" placeholder="请选择作品库">
              <el-option v-for="library in libraries" :key="library.id" :label="library.name" :value="library.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="文档范围">
            <el-select v-model="selectedDocumentIds" multiple collapse-tags collapse-tags-tooltip placeholder="默认检索当前作品库全部可查文档">
              <el-option
                v-for="document in queryableDocuments"
                :key="document.id"
                :label="`${document.title} (${statusMeta(document.status).label})`"
                :value="document.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="问题">
            <el-input
              v-model="question"
              type="textarea"
              :rows="5"
              placeholder="例如：夏德第一次见到露维娅时发生了什么？"
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
            <el-button plain @click="router.push('/workspace/novel/upload')">继续上传</el-button>
          </div>
        </el-form>
      </el-card>

      <div class="result-column">
        <el-card shadow="hover" class="panel result-panel">
          <template #header>
            <div class="card-head">
              <div>
                <h2>回答结果</h2>
                <p>小说线路默认直答，但必须展示证据。</p>
              </div>
              <el-tag v-if="result" :type="result.evidence_status === 'grounded' ? 'success' : 'warning'" effect="plain">
                {{ result?.evidence_status || '等待提问' }}
              </el-tag>
            </div>
          </template>

          <el-empty v-if="!result" description="选择作品库后开始提问" />
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
          <CitationList :citations="result?.citations || []" title="证据引用" mode="novel" />
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
import { listNovelDocuments, listNovelLibraries, queryNovel, streamNovelQuery } from '@/api/novel';
import { isAbortRequestError } from '@/api/request';
import { applyQueryStreamEvent, createEmptyQueryResult, resolveQueryStreamPayload, type QueryResult } from '@/utils/queryStream';
import { statusMeta } from '@/utils/status';

const router = useRouter();
const route = useRoute();

const libraries = ref<any[]>([]);
const documents = ref<any[]>([]);
const selectedLibraryId = ref('');
const selectedDocumentIds = ref<string[]>([]);
const question = ref('');
const asking = ref(false);
const result = ref<QueryResult | null>(null);

let currentController: AbortController | null = null;

const shortcuts = [
  '第1章主要讲了什么？',
  '主角第一次获得关键线索是在什么时候？',
  'A 和 B 的关系为什么会变化？',
  '某件遗物在剧情里起了什么作用？',
  '这条设定线索在故事中如何被反复强调？'
];

const queryableDocuments = computed(() => {
  return documents.value.filter((document) => ['fast_index_ready', 'enhancing', 'ready'].includes(document.status));
});

const buildPayload = () => ({
  library_id: selectedLibraryId.value,
  question: question.value.trim(),
  document_ids: selectedDocumentIds.value
});

const stopStreaming = () => {
  currentController?.abort();
  currentController = null;
  asking.value = false;
};

const loadLibraries = async () => {
  const res: any = await listNovelLibraries();
  libraries.value = res.items || [];
  if (!selectedLibraryId.value && libraries.value.length) {
    selectedLibraryId.value = String(route.query.libraryId || libraries.value[0].id);
  }
};

const loadDocuments = async (libraryId: string) => {
  const res: any = await listNovelDocuments(libraryId);
  documents.value = res.items || [];
  const preset = route.query.documentId ? [String(route.query.documentId)] : [];
  if (preset.length) {
    selectedDocumentIds.value = preset.filter((id) => documents.value.some((document) => document.id === id));
  }
};

const askOnce = async () => {
  if (!selectedLibraryId.value) {
    ElMessage.warning('请先选择作品库');
    return;
  }
  if (!question.value.trim()) {
    ElMessage.warning('请输入问题');
    return;
  }
  asking.value = true;
  try {
    result.value = await queryNovel({
      library_id: selectedLibraryId.value,
      question: question.value.trim(),
      document_ids: selectedDocumentIds.value
    }) as unknown as QueryResult;
  } finally {
    asking.value = false;
  }
};

const ask = async () => {
  if (!selectedLibraryId.value) {
    ElMessage.warning('请先选择作品库');
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
    await streamNovelQuery(payload, {
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

watch(selectedLibraryId, (libraryId) => {
  stopStreaming();
  result.value = null;
  selectedDocumentIds.value = [];
  if (!libraryId) {
    documents.value = [];
    return;
  }
  void loadDocuments(libraryId).catch(() => {
    documents.value = [];
  });
});

onMounted(() => {
  void loadLibraries().catch(() => {
    libraries.value = [];
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

.spoiler-header {
  background:
    radial-gradient(circle at top left, rgba(239, 68, 68, 0.16), transparent 28%),
    linear-gradient(135deg, #ffffff, #fff1f2);
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
