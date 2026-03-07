<template>
  <div class="page">
    <section class="page-header">
      <div>
        <el-tag type="primary" effect="dark">小说线路</el-tag>
        <h1>小说上传线路</h1>
        <p>只接受 TXT。上传后先进入“快速可查”，随后补全剧情事件与别名增强。</p>
      </div>
      <el-button plain @click="router.push('/workspace/novel/chat')">前往小说问答</el-button>
    </section>

    <section class="grid two-columns">
      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>作品库</h2>
              <p>先创建作品库，再进入专属上传流程。</p>
            </div>
            <el-tag effect="plain">{{ libraries.length }} 个作品库</el-tag>
          </div>
        </template>

        <el-form label-position="top" class="form-grid">
          <el-form-item label="选择作品库">
            <el-select v-model="selectedLibraryId" placeholder="请选择或先创建作品库">
              <el-option
                v-for="library in libraries"
                :key="library.id"
                :label="library.name"
                :value="library.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="新建作品名">
            <el-input v-model="libraryForm.name" placeholder="例如：呢喃诗章" />
          </el-form-item>
          <el-form-item label="作品说明">
            <el-input v-model="libraryForm.description" type="textarea" :rows="3" placeholder="可填写世界观或版本说明" />
          </el-form-item>
          <el-button type="primary" :loading="creatingLibrary" @click="handleCreateLibrary">创建作品库</el-button>
        </el-form>
      </el-card>

      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>上传向导</h2>
              <p>小说与企业库共用网关，但不共用上传表单。</p>
            </div>
            <el-tag type="warning" effect="plain">TXT Only</el-tag>
          </div>
        </template>

        <el-form label-position="top" class="form-grid">
          <el-form-item label="作品标题">
            <el-input v-model="uploadForm.title" placeholder="请输入展示标题" />
          </el-form-item>
          <el-form-item label="卷册信息">
            <el-input v-model="uploadForm.volumeLabel" placeholder="例如：第一卷 / 全本" />
          </el-form-item>
          <el-form-item label="源文件">
            <div class="file-picker">
              <el-button type="primary" plain @click="pickFile">选择 TXT 文件</el-button>
              <span class="file-name">{{ selectedFile?.name || '尚未选择文件' }}</span>
            </div>
            <input ref="fileInputRef" class="hidden-input" type="file" accept=".txt,text/plain" @change="handleFileChange" />
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="uploadForm.spoilerAck">我理解小说问答默认允许剧透直答</el-checkbox>
          </el-form-item>
          <el-button type="primary" :loading="uploading" @click="handleUpload">上传并进入快速索引</el-button>
        </el-form>

        <div class="chapter-preview">
          <div class="preview-head">
            <h3>章节预览</h3>
            <span>{{ chapterPreview.length }} 条</span>
          </div>
          <el-empty v-if="!chapterPreview.length" description="选择 TXT 后将根据标题模式尝试抽取章节预览" />
          <ul v-else>
            <li v-for="item in chapterPreview" :key="item">{{ item }}</li>
          </ul>
        </div>
      </el-card>
    </section>

    <section class="grid two-columns">
      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>当前上传任务</h2>
              <p>上传成功后，快速可查状态即可发起问答。</p>
            </div>
            <el-tag :type="currentStatus.type" effect="plain">{{ currentStatus.label }}</el-tag>
          </div>
        </template>

        <el-empty v-if="!activeDocument" description="尚未创建上传任务" />
        <div v-else class="doc-summary">
          <div class="status-row">
            <strong>{{ activeDocument.title }}</strong>
            <el-tag :type="currentStatus.type">{{ currentStatus.label }}</el-tag>
          </div>
          <p>卷册：{{ activeDocument.volume_label || '未填写' }}</p>
          <p>文件大小：{{ activeDocument.size_bytes || 0 }} bytes</p>
          <div class="status-rail">
            <span :class="{ active: ['uploaded','parsing','fast_index_ready','enhancing','ready'].includes(activeDocument.status) }">已接收</span>
            <span :class="{ active: ['fast_index_ready','enhancing','ready'].includes(activeDocument.status) }">快速可查</span>
            <span :class="{ active: ['ready'].includes(activeDocument.status) }">稳定问答</span>
          </div>
          <div class="action-row">
            <el-button plain @click="openDocument(activeDocument.id)">查看文档详情</el-button>
            <el-button type="primary" @click="goChat">带着这本书提问</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="panel">
        <DocumentEvents
          :items="events"
          title="处理事件"
          description="小说线路独立记录上传、解析、快速可查与增强阶段。"
        />
      </el-card>
    </section>

    <section class="panel list-panel">
      <div class="card-head">
        <div>
          <h2>最近文档</h2>
          <p>当前作品库下的小说文档列表。</p>
        </div>
        <el-button v-if="selectedLibraryId" plain @click="loadDocuments(selectedLibraryId)">刷新</el-button>
      </div>
      <el-empty v-if="!documents.length" description="当前作品库还没有上传记录" />
      <div v-else class="document-list">
        <el-card v-for="document in documents" :key="document.id" shadow="hover" class="document-card">
          <div class="status-row">
            <strong>{{ document.title }}</strong>
            <el-tag :type="statusMeta(document.status).type" effect="plain">{{ statusMeta(document.status).label }}</el-tag>
          </div>
          <p>卷册：{{ document.volume_label || '未填写' }}</p>
          <p>章节：{{ document.chapter_count || 0 }}，场景：{{ document.scene_count || 0 }}，片段：{{ document.passage_count || 0 }}</p>
          <div class="action-row">
            <el-button text @click="openDocument(document.id)">详情</el-button>
            <el-button text type="primary" @click="openInChat(document.id)">问答</el-button>
          </div>
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import DocumentEvents from '@/components/DocumentEvents.vue';
import {
  createNovelLibrary,
  getNovelDocument,
  getNovelDocumentEvents,
  listNovelDocuments,
  listNovelLibraries,
  uploadNovelDocument
} from '@/api/novel';
import { statusMeta } from '@/utils/status';

const router = useRouter();
const route = useRoute();

const libraries = ref<any[]>([]);
const documents = ref<any[]>([]);
const events = ref<any[]>([]);
const selectedLibraryId = ref('');
const selectedFile = ref<File | null>(null);
const chapterPreview = ref<string[]>([]);
const activeDocument = ref<any | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);

const creatingLibrary = ref(false);
const uploading = ref(false);
let pollTimer: number | null = null;

const libraryForm = reactive({
  name: '',
  description: ''
});

const uploadForm = reactive({
  title: '',
  volumeLabel: '',
  spoilerAck: true
});

const currentStatus = computed(() => statusMeta(activeDocument.value?.status));

const clearPoller = () => {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
};

const pickFile = () => {
  fileInputRef.value?.click();
};

const deriveChapterPreview = (text: string) => {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const headings = lines.filter((line) => /^第.{0,12}[章节回卷幕]/.test(line)).slice(0, 12);
  chapterPreview.value = headings.length ? headings : lines.slice(0, 8);
};

const handleFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  selectedFile.value = file;
  chapterPreview.value = [];
  if (!file) {
    return;
  }
  if (!uploadForm.title) {
    uploadForm.title = file.name.replace(/\.[^.]+$/, '');
  }
  const text = await file.text();
  deriveChapterPreview(text);
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
};

const refreshActiveDocument = async (documentId: string) => {
  activeDocument.value = await getNovelDocument(documentId);
  const result: any = await getNovelDocumentEvents(documentId);
  events.value = result.items || [];
};

const pollDocument = async (documentId: string) => {
  await refreshActiveDocument(documentId);
  if (!activeDocument.value || ['ready', 'failed'].includes(activeDocument.value.status)) {
    if (selectedLibraryId.value) {
      await loadDocuments(selectedLibraryId.value);
    }
    clearPoller();
    return;
  }
  pollTimer = window.setTimeout(() => {
    void pollDocument(documentId);
  }, 2000);
};

const handleCreateLibrary = async () => {
  if (!libraryForm.name.trim()) {
    ElMessage.warning('请先填写作品名');
    return;
  }
  creatingLibrary.value = true;
  try {
    const library: any = await createNovelLibrary({
      name: libraryForm.name.trim(),
      description: libraryForm.description.trim()
    });
    libraryForm.name = '';
    libraryForm.description = '';
    await loadLibraries();
    selectedLibraryId.value = library.id;
    ElMessage.success('作品库已创建');
  } finally {
    creatingLibrary.value = false;
  }
};

const handleUpload = async () => {
  if (!selectedLibraryId.value) {
    ElMessage.warning('请先选择作品库');
    return;
  }
  if (!selectedFile.value) {
    ElMessage.warning('请先选择 TXT 文件');
    return;
  }
  if (!uploadForm.title.trim()) {
    ElMessage.warning('请填写作品标题');
    return;
  }
  uploading.value = true;
  try {
    const document: any = await uploadNovelDocument({
      libraryId: selectedLibraryId.value,
      title: uploadForm.title.trim(),
      volumeLabel: uploadForm.volumeLabel.trim(),
      spoilerAck: uploadForm.spoilerAck,
      file: selectedFile.value
    });
    activeDocument.value = document;
    await loadDocuments(selectedLibraryId.value);
    await pollDocument(document.id);
    ElMessage.success('小说文件已接收，正在快速索引');
  } finally {
    uploading.value = false;
  }
};

const openDocument = (documentId: string) => {
  router.push(`/workspace/novel/documents/${documentId}`);
};

const openInChat = (documentId: string) => {
  router.push({
    path: '/workspace/novel/chat',
    query: {
      libraryId: selectedLibraryId.value,
      documentId
    }
  });
};

const goChat = () => {
  if (!activeDocument.value) {
    return;
  }
  openInChat(activeDocument.value.id);
};

watch(selectedLibraryId, (libraryId) => {
  if (!libraryId) {
    documents.value = [];
    return;
  }
  void loadDocuments(libraryId);
});

onMounted(async () => {
  await loadLibraries();
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
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.18), transparent 30%),
    linear-gradient(135deg, #ffffff, #eff6ff);
}

.page-header h1 {
  margin: 12px 0 8px;
  font-size: 34px;
}

.page-header p {
  margin: 0;
  max-width: 760px;
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

.list-panel {
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

.form-grid {
  display: grid;
  gap: 8px;
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
  word-break: break-all;
}

.chapter-preview {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border-color-light);
}

.preview-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.chapter-preview ul {
  margin: 16px 0 0;
  padding-left: 20px;
  line-height: 1.8;
}

.doc-summary {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.status-row,
.action-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.status-rail {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.status-rail span {
  display: inline-flex;
  justify-content: center;
  padding: 10px 12px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.14);
  color: var(--text-secondary);
  font-size: 13px;
}

.status-rail span.active {
  background: rgba(37, 99, 235, 0.14);
  color: #1d4ed8;
}

.document-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
  margin-top: 18px;
}

.document-card {
  border-radius: 20px;
}

@media (max-width: 1080px) {
  .two-columns {
    grid-template-columns: 1fr;
  }
}
</style>
