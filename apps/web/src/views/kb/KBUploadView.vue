<template>
  <div class="page">
    <section class="page-header kb-header">
      <div>
        <el-tag type="success" effect="dark">企业库线路</el-tag>
        <h1>企业知识库上传线路</h1>
        <p>支持 txt / pdf / docx 批量导入。与小说线路分开校验、分开状态、分开问答。</p>
      </div>
      <el-button plain @click="router.push('/workspace/kb/chat')">前往企业库问答</el-button>
    </section>

    <section class="grid two-columns">
      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>知识库</h2>
              <p>企业库上传只能进入企业知识库内核。</p>
            </div>
            <el-tag effect="plain">{{ bases.length }} 个知识库</el-tag>
          </div>
        </template>

        <el-form label-position="top">
          <el-form-item label="选择知识库">
            <el-select v-model="selectedBaseId" placeholder="请选择或先创建知识库">
              <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="新建知识库名称">
            <el-input v-model="baseForm.name" placeholder="例如：运营制度库" />
          </el-form-item>
          <el-form-item label="分类">
            <el-input v-model="baseForm.category" placeholder="例如：制度 / 培训 / 合同" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="baseForm.description" type="textarea" :rows="3" placeholder="描述该知识库的用途" />
          </el-form-item>
          <el-button type="primary" :loading="creatingBase" @click="handleCreateBase">创建知识库</el-button>
        </el-form>
      </el-card>

      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>批量上传</h2>
              <p>支持多文件同批导入，并保留文档分类。</p>
            </div>
            <el-tag type="success" effect="plain">TXT / PDF / DOCX</el-tag>
          </div>
        </template>

        <el-form label-position="top">
          <el-form-item label="文档分类">
            <el-input v-model="uploadForm.category" placeholder="例如：人事制度 / 客服 FAQ" />
          </el-form-item>
          <el-form-item label="选择文件">
            <div class="file-picker">
              <el-button type="primary" plain @click="pickFiles">选择文件</el-button>
              <span class="file-name">{{ selectedFiles.length ? `${selectedFiles.length} 个文件待上传` : '尚未选择文件' }}</span>
            </div>
            <input ref="fileInputRef" class="hidden-input" type="file" accept=".txt,.pdf,.docx" multiple @change="handleFileChange" />
          </el-form-item>
          <div class="selected-files">
            <el-empty v-if="!selectedFiles.length" description="选择文件后将在这里展示批处理清单" />
            <ul v-else>
              <li v-for="file in selectedFiles" :key="file.name">{{ file.name }} · {{ file.size }} bytes</li>
            </ul>
          </div>
          <el-button type="primary" :loading="uploading" @click="handleUpload">批量上传并启动索引</el-button>
        </el-form>
      </el-card>
    </section>

    <section class="grid two-columns">
      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>最近批次</h2>
              <p>企业库线路按文档逐个追踪状态。</p>
            </div>
          </div>
        </template>

        <el-empty v-if="!latestDocuments.length" description="当前没有上传批次" />
        <div v-else class="document-list">
          <el-card v-for="document in latestDocuments" :key="document.id" shadow="hover" class="document-card">
            <div class="status-row">
              <strong>{{ document.file_name }}</strong>
              <el-tag :type="statusMeta(document.status).type" effect="plain">{{ statusMeta(document.status).label }}</el-tag>
            </div>
            <p>类型：{{ document.file_type }}</p>
            <p>分段：{{ document.section_count || 0 }} 节，{{ document.chunk_count || 0 }} chunk</p>
            <div class="action-row">
              <el-button text @click="openDocument(document.id)">详情</el-button>
              <el-button text type="primary" @click="openInChat(document.id)">问答</el-button>
            </div>
          </el-card>
        </div>
      </el-card>

      <el-card shadow="hover" class="panel">
        <DocumentEvents
          :items="events"
          title="处理事件"
          description="企业库线路独立记录上传、解析、快速可查与增强阶段。"
        />
      </el-card>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import DocumentEvents from '@/components/DocumentEvents.vue';
import {
  createKnowledgeBase,
  getKBDocument,
  getKBDocumentEvents,
  listKBDocuments,
  listKnowledgeBases,
  uploadKBDocuments
} from '@/api/kb';
import { statusMeta } from '@/utils/status';

const router = useRouter();
const route = useRoute();

const bases = ref<any[]>([]);
const selectedBaseId = ref('');
const selectedFiles = ref<File[]>([]);
const latestDocuments = ref<any[]>([]);
const events = ref<any[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);

const creatingBase = ref(false);
const uploading = ref(false);
let pollTimer: number | null = null;

const baseForm = reactive({
  name: '',
  description: '',
  category: ''
});

const uploadForm = reactive({
  category: ''
});

const clearPoller = () => {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
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
  latestDocuments.value = res.items || [];
};

const pickFiles = () => {
  fileInputRef.value?.click();
};

const handleFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement;
  selectedFiles.value = Array.from(input.files || []);
};

const handleCreateBase = async () => {
  if (!baseForm.name.trim()) {
    ElMessage.warning('请先填写知识库名称');
    return;
  }
  creatingBase.value = true;
  try {
    const base: any = await createKnowledgeBase({
      name: baseForm.name.trim(),
      description: baseForm.description.trim(),
      category: baseForm.category.trim()
    });
    baseForm.name = '';
    baseForm.description = '';
    baseForm.category = '';
    await loadBases();
    selectedBaseId.value = base.id;
    ElMessage.success('知识库已创建');
  } finally {
    creatingBase.value = false;
  }
};

const refreshEventFocus = async () => {
  if (!latestDocuments.value.length) {
    events.value = [];
    return;
  }
  const focus = latestDocuments.value[0];
  const result: any = await getKBDocumentEvents(focus.id);
  events.value = result.items || [];
};

const pollDocuments = async (documentIds: string[]) => {
  const snapshots = await Promise.all(documentIds.map((id) => getKBDocument(id)));
  const completed = snapshots.every((document: any) => ['ready', 'failed'].includes(String(document.status)));
  if (selectedBaseId.value) {
    await loadDocuments(selectedBaseId.value);
  }
  await refreshEventFocus();
  if (completed) {
    clearPoller();
    return;
  }
  pollTimer = window.setTimeout(() => {
    void pollDocuments(documentIds);
  }, 2000);
};

const handleUpload = async () => {
  if (!selectedBaseId.value) {
    ElMessage.warning('请先选择知识库');
    return;
  }
  if (!selectedFiles.value.length) {
    ElMessage.warning('请先选择文件');
    return;
  }
  uploading.value = true;
  try {
    const result: any = await uploadKBDocuments({
      baseId: selectedBaseId.value,
      category: uploadForm.category.trim(),
      files: selectedFiles.value
    });
    const items = result.items || [];
    await loadDocuments(selectedBaseId.value);
    await refreshEventFocus();
    await pollDocuments(items.map((item: any) => item.id));
    ElMessage.success('企业文档已接收，正在索引');
  } finally {
    uploading.value = false;
  }
};

const openDocument = (documentId: string) => {
  router.push(`/workspace/kb/documents/${documentId}`);
};

const openInChat = (documentId: string) => {
  router.push({
    path: '/workspace/kb/chat',
    query: {
      baseId: selectedBaseId.value,
      documentId
    }
  });
};

watch(selectedBaseId, (baseId) => {
  if (!baseId) {
    latestDocuments.value = [];
    return;
  }
  void loadDocuments(baseId);
});

onMounted(async () => {
  await loadBases();
});

onBeforeUnmount(() => {
  clearPoller();
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
  color: var(--text-regular);
  line-height: 1.7;
}

.grid {
  display: grid;
  gap: 20px;
}

.two-columns {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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
  align-items: flex-start;
}

.card-head h2 {
  margin: 0;
}

.card-head p {
  margin: 6px 0 0;
  color: var(--text-secondary);
}

.file-picker {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hidden-input {
  display: none;
}

.file-name {
  color: var(--text-secondary);
}

.selected-files {
  margin-bottom: 18px;
}

.selected-files ul {
  margin: 0;
  padding-left: 20px;
  line-height: 1.8;
}

.document-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.document-card {
  border-radius: 20px;
}

.status-row,
.action-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

@media (max-width: 1080px) {
  .two-columns {
    grid-template-columns: 1fr;
  }
}
</style>
