<template>
  <div class="page-shell upload-page">
    <PageHeaderCompact :title="selectedBase?.name || '知识库治理'">
      <template #actions>
        <el-button type="primary" @click="router.push('/workspace/chat')">问答</el-button>
        <el-button plain :disabled="!canWrite" @click="pickFiles">上传</el-button>
        <el-button plain :disabled="!canWrite" @click="openBaseDrawer('create')">新建</el-button>
      </template>
    </PageHeaderCompact>

    <div class="upload-layout">
      <div class="upload-left">
        <div class="kb-select-row">
          <el-select
            v-model="selectedBaseId"
            placeholder="选择知识库"
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="base in bases"
              :key="base.id"
              :label="base.name"
              :value="base.id"
            />
          </el-select>
          <el-button
            v-if="selectedBase && canWrite"
            plain
            size="small"
            @click="openBaseDrawer('edit')"
          >
            编辑
          </el-button>
        </div>

        <div class="upload-section">
          <el-form label-position="top" label-width="auto">
            <el-form-item label="文档分类">
              <el-input
                v-model="uploadForm.category"
                placeholder="例如：客服 FAQ"
                size="small"
              />
            </el-form-item>
            <el-divider content-position="left">版本治理（可选）</el-divider>
            <el-form-item label="版本家族 Key">
              <el-input
                v-model="uploadForm.version_family_key"
                placeholder="例如：expense-policy"
                size="small"
              />
            </el-form-item>
            <el-form-item label="版本标签">
              <el-input
                v-model="uploadForm.version_label"
                placeholder="例如：2026-Q1 / v2"
                size="small"
              />
            </el-form-item>
            <el-form-item label="版本号">
              <el-input-number v-model="uploadForm.version_number" :min="1" :max="100000" style="width: 100%" />
            </el-form-item>
            <el-form-item label="版本状态">
              <el-select v-model="uploadForm.version_status" size="small" style="width: 100%">
                <el-option label="active" value="active" />
                <el-option label="draft" value="draft" />
                <el-option label="superseded" value="superseded" />
                <el-option label="archived" value="archived" />
              </el-select>
            </el-form-item>
            <el-form-item label="设为当前版本">
              <el-switch v-model="uploadForm.is_current_version" />
            </el-form-item>
            <el-form-item label="生效开始">
              <el-date-picker
                v-model="uploadForm.effective_from"
                type="datetime"
                value-format="YYYY-MM-DDTHH:mm:ss[Z]"
                placeholder="可选"
                size="small"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="生效结束">
              <el-date-picker
                v-model="uploadForm.effective_to"
                type="datetime"
                value-format="YYYY-MM-DDTHH:mm:ss[Z]"
                placeholder="可选"
                size="small"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="替代旧文档 ID">
              <el-input
                v-model="uploadForm.supersedes_document_id"
                placeholder="可选，导入新版本时填写"
                size="small"
              />
            </el-form-item>
          </el-form>

          <div
            class="dropzone"
            @click="canWrite && pickFiles()"
            @dragover.prevent
            @drop.prevent="handleDrop"
          >
            <el-icon :size="32"><UploadFilled /></el-icon>
            <span>点击或拖拽文件</span>
            <span class="dropzone-hint">TXT / PDF / DOCX / PNG / JPG / JPEG</span>
          </div>
          <input
            ref="fileInputRef"
            type="file"
            accept=".txt,.pdf,.docx,.png,.jpg,.jpeg"
            multiple
            class="hidden-input"
            @change="handleFileChange"
          />

          <div v-if="selectedFiles.length" class="file-list">
            <div
              v-for="file in selectedFiles"
              :key="fileFingerprint(file)"
              class="file-row"
            >
              <span class="file-name">{{ file.name }}</span>
              <el-progress
                :percentage="Math.round((uploadProgress[fileFingerprint(file)] || 0) * 100)"
                :status="(uploadProgress[fileFingerprint(file)] || 0) === 1 ? 'success' : ''"
                style="flex: 1; min-width: 0"
              />
            </div>
          </div>

          <el-button
            type="primary"
            :loading="uploading"
            :disabled="!canWrite || !selectedBaseId || !selectedFiles.length"
            class="upload-btn"
            @click="handleUpload"
          >
            <el-icon><VideoPlay /></el-icon> 开始上传
          </el-button>
        </div>
      </div>

      <div class="upload-right">
        <div class="doc-list-header">
          <span>文档列表</span>
          <span class="doc-count">{{ latestDocuments.length }} 份</span>
        </div>
        <div class="doc-list-scroll">
          <EnhancedEmpty
            v-if="!latestDocuments.length"
            variant="document"
            title="暂无文档"
            description="上传文档后将在此展示"
            class="doc-empty"
          />
          <div v-else class="doc-list">
            <button
              v-for="doc in latestDocuments"
              :key="doc.id"
              type="button"
              class="doc-item"
              @click="openDocument(doc.id)"
            >
              <span class="doc-name">{{ doc.file_name }}</span>
              <el-tag :type="statusMeta(doc.status).type" size="small" effect="plain">
                {{ statusMeta(doc.status).label }}
              </el-tag>
              <div class="doc-actions">
                <el-button text type="primary" size="small" @click.stop="openInChat(doc.id)">提问</el-button>
                <el-button text type="danger" size="small" :disabled="!canWrite" @click.stop="handleDeleteDocument(doc)">删除</el-button>
              </div>
            </button>
          </div>
        </div>

        <el-collapse v-model="eventsCollapse">
          <el-collapse-item name="events">
            <template #title>
              <span class="collapse-title">处理事件</span>
            </template>
            <DocumentEvents :items="events" title="" description="" />
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>

    <el-drawer
      v-model="baseDrawerVisible"
      :title="baseFormMode === 'edit' ? '编辑知识库' : '新建知识库'"
      size="400px"
      destroy-on-close
      @close="cancelEditBase"
    >
      <el-form label-position="top" style="padding: 0 16px">
        <el-form-item label="名称">
          <el-input v-model="baseForm.name" placeholder="例如：运营制度库" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="baseForm.category" placeholder="例如：制度 / FAQ" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input
            v-model="baseForm.description"
            type="textarea"
            :rows="3"
            placeholder="选填"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="creatingBase" :disabled="!canWrite" @click="handleSubmitBase">
            {{ baseFormMode === 'edit' ? '保存' : '创建' }}
          </el-button>
          <el-button v-if="baseFormMode === 'edit'" @click="cancelEditBase">取消</el-button>
          <el-button
            v-if="baseFormMode === 'edit' && selectedBase && canWrite"
            type="danger"
            plain
            @click="handleDeleteBase"
          >
            删除知识库
          </el-button>
        </el-form-item>
      </el-form>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { UploadFilled, VideoPlay } from '@element-plus/icons-vue';
import DocumentEvents from '@/components/DocumentEvents.vue';
import EnhancedEmpty from '@/components/EnhancedEmpty.vue';
import PageHeaderCompact from '@/components/PageHeaderCompact.vue';
import { useAuthStore } from '@/store/auth';
import {
  completeKBUpload,
  createKBUpload,
  createKnowledgeBase,
  deleteKBDocument,
  deleteKnowledgeBase,
  getKBDocumentEvents,
  getKBIngestJob,
  getKBUpload,
  listKBDocuments,
  listKnowledgeBases,
  presignKBUploadParts,
  updateKnowledgeBase
} from '@/api/kb';
import { createIdempotencyKey } from '@/api/request';
import { uploadMultipartFile } from '@/utils/multipartUpload';
import { statusMeta } from '@/utils/status';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const bases = ref<any[]>([]);
const selectedBaseId = ref('');
const selectedFiles = ref<File[]>([]);
const latestDocuments = ref<any[]>([]);
const events = ref<any[]>([]);
const uploadProgress = ref<Record<string, number>>({});
const fileInputRef = ref<HTMLInputElement | null>(null);

const creatingBase = ref(false);
const uploading = ref(false);
const baseFormMode = ref<'create' | 'edit'>('create');
const eventsCollapse = ref<string[]>([]);
const baseDrawerVisible = ref(false);
let pollTimer: number | null = null;

const baseForm = reactive({
  name: '',
  description: '',
  category: ''
});

const uploadForm = reactive({
  category: '',
  version_family_key: '',
  version_label: '',
  version_number: 1,
  version_status: 'active',
  is_current_version: true,
  effective_from: '',
  effective_to: '',
  supersedes_document_id: ''
});

const fileFingerprint = (file: File) => `${file.name}:${file.size}:${file.lastModified}`;
const canWrite = computed(() => authStore.hasPermission('kb.write'));
const selectedBase = computed(() => bases.value.find((b) => String(b.id) === String(selectedBaseId.value)) || null);

const clearPoller = () => {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
};

const loadBases = async () => {
  const res: any = await listKnowledgeBases();
  bases.value = res.items || [];
  const preferredBaseId = String(route.query.baseId || '');
  const nextSelected =
    bases.value.find((b) => String(b.id) === String(selectedBaseId.value))?.id
    || bases.value.find((b) => String(b.id) === preferredBaseId)?.id
    || bases.value[0]?.id
    || '';
  selectedBaseId.value = String(nextSelected || '');
};

const loadDocuments = async (baseId: string) => {
  const res: any = await listKBDocuments(baseId);
  latestDocuments.value = res.items || [];
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

const pickFiles = () => {
  if (!canWrite.value) return;
  fileInputRef.value?.click();
};

const handleFileChange = (e: Event) => {
  addFiles(Array.from((e.target as HTMLInputElement).files || []));
};

const handleDrop = (e: DragEvent) => {
  const files = Array.from(e.dataTransfer?.files || []);
  if (files.length) addFiles(files);
};

const addFiles = (files: File[]) => {
  const valid = files.filter((f) => {
    const ext = f.name.split('.').pop()?.toLowerCase();
    return ['txt', 'pdf', 'docx', 'png', 'jpg', 'jpeg'].includes(String(ext || ''));
  });
  if (valid.length < files.length) ElMessage.warning('已过滤不支持格式');
  selectedFiles.value = [...selectedFiles.value, ...valid];
};

const resetBaseForm = () => {
  baseForm.name = '';
  baseForm.description = '';
  baseForm.category = '';
};

const fillBaseForm = (base: any) => {
  baseForm.name = String(base?.name || '');
  baseForm.description = String(base?.description || '');
  baseForm.category = String(base?.category || '');
};

const openBaseDrawer = (mode: 'create' | 'edit') => {
  baseFormMode.value = mode;
  if (mode === 'edit' && selectedBase.value) {
    fillBaseForm(selectedBase.value);
  } else {
    resetBaseForm();
  }
  baseDrawerVisible.value = true;
};

const cancelEditBase = () => {
  baseFormMode.value = 'create';
  resetBaseForm();
  baseDrawerVisible.value = false;
};

const handleSubmitBase = async () => {
  if (!canWrite.value || !baseForm.name.trim()) {
    ElMessage.warning('请填写名称');
    return;
  }
  creatingBase.value = true;
  try {
    if (baseFormMode.value === 'edit' && selectedBaseId.value) {
      await updateKnowledgeBase(selectedBaseId.value, {
        name: baseForm.name.trim(),
        description: baseForm.description.trim(),
        category: baseForm.category.trim()
      });
      await loadBases();
      ElMessage.success('已更新');
    } else {
      const base: any = await createKnowledgeBase({
        name: baseForm.name.trim(),
        description: baseForm.description.trim(),
        category: baseForm.category.trim()
      });
      resetBaseForm();
      await loadBases();
      selectedBaseId.value = String(base.id || '');
      ElMessage.success('已创建');
    }
    baseDrawerVisible.value = false;
  } finally {
    creatingBase.value = false;
  }
};

const handleDeleteBase = async () => {
  if (!canWrite.value || !selectedBase.value) return;
  try {
    await ElMessageBox.confirm(
      `将删除知识库「${selectedBase.value.name}」及其全部文档，此操作不可恢复。`,
      '删除知识库',
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
    );
  } catch {
    return;
  }
  const id = String(selectedBaseId.value);
  await deleteKnowledgeBase(id);
  cancelEditBase();
  if (String(route.query.baseId || '') === id) {
    router.replace({ path: route.path, query: { ...route.query, baseId: undefined } });
  }
  await loadBases();
  if (selectedBaseId.value) {
    await loadDocuments(selectedBaseId.value);
    await refreshEventFocus();
  } else {
    latestDocuments.value = [];
    events.value = [];
  }
  ElMessage.success('已删除');
};

const pollJobs = async (jobIds: string[]) => {
  const snapshots = await Promise.all(jobIds.map((id) => getKBIngestJob(id)));
  const done = snapshots.every((j: any) =>
    ['ready', 'failed', 'dead_letter', 'done'].includes(String(j.document_status || j.status))
  );
  if (selectedBaseId.value) await loadDocuments(selectedBaseId.value);
  await refreshEventFocus();
  if (done) {
    clearPoller();
    return;
  }
  pollTimer = window.setTimeout(() => void pollJobs(jobIds), 2000);
};

const uploadSingleFile = async (file: File) => {
  const fp = fileFingerprint(file);
  const createKey = createIdempotencyKey(`kb-upload-create:${selectedBaseId.value}:${fp}`);
  const completeKey = createIdempotencyKey(`kb-upload-complete:${selectedBaseId.value}:${fp}`);
  const result = await uploadMultipartFile({
    file,
    resumeKey: `kb-upload:${selectedBaseId.value}:${fp}`,
    controller: {
      createUpload: () =>
        createKBUpload(
          {
            base_id: selectedBaseId.value,
            file_name: file.name,
            file_type: file.name.split('.').pop()?.toLowerCase() || 'txt',
            size_bytes: file.size,
            category: uploadForm.category.trim(),
            version_family_key: uploadForm.version_family_key.trim() || undefined,
            version_label: uploadForm.version_label.trim() || undefined,
            version_number: Number(uploadForm.version_number || 1),
            version_status: uploadForm.version_status || undefined,
            is_current_version: uploadForm.is_current_version,
            effective_from: uploadForm.effective_from || null,
            effective_to: uploadForm.effective_to || null,
            supersedes_document_id: uploadForm.supersedes_document_id.trim() || null
          },
          { idempotencyKey: createKey }
        ) as Promise<any>,
      getUpload: (uploadId: string) => getKBUpload(uploadId) as Promise<any>,
      presignParts: (uploadId: string, partNumbers: number[]) =>
        presignKBUploadParts(uploadId, partNumbers) as Promise<any>,
      completeUpload: (uploadId: string, parts: any) =>
        completeKBUpload(uploadId, parts, '', { idempotencyKey: completeKey }) as Promise<any>
    },
    onProgress: ({ ratio }) => {
      uploadProgress.value = { ...uploadProgress.value, [fp]: ratio };
    }
  });
  uploadProgress.value = { ...uploadProgress.value, [fp]: 1 };
  return result.result;
};

const handleUpload = async () => {
  if (!canWrite.value || !selectedBaseId.value || !selectedFiles.value.length) return;
  uploading.value = true;
  try {
    const completed = [];
    for (const file of selectedFiles.value) {
      completed.push(await uploadSingleFile(file));
    }
    await loadDocuments(selectedBaseId.value);
    await refreshEventFocus();
    await pollJobs(completed.map((r: any) => String(r.job_id)));
    selectedFiles.value = [];
    uploadProgress.value = {};
    fileInputRef.value && (fileInputRef.value.value = '');
    ElMessage.success('上传完成，后台正在索引');
  } finally {
    uploading.value = false;
  }
};

const openDocument = (id: string) => router.push(`/workspace/kb/documents/${id}`);

const openInChat = (documentId: string) => {
  router.push({
    path: '/workspace/chat',
    query: { preset: 'kb', baseId: selectedBaseId.value, documentId }
  });
};

const handleDeleteDocument = async (doc: any) => {
  if (!canWrite.value) return;
  try {
    await ElMessageBox.confirm(`删除文档「${doc.file_name}」？`, '删除', {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消'
    });
  } catch {
    return;
  }
  await deleteKBDocument(String(doc.id));
  if (selectedBaseId.value) {
    await loadDocuments(selectedBaseId.value);
    await refreshEventFocus();
  }
  ElMessage.success('已删除');
};

watch(selectedBaseId, (id) => {
  if (!id) {
    latestDocuments.value = [];
    events.value = [];
    return;
  }
  void loadDocuments(id).then(() => refreshEventFocus());
});

onMounted(async () => {
  await loadBases();
  if (selectedBaseId.value) {
    await loadDocuments(selectedBaseId.value);
    await refreshEventFocus();
  }
});

onBeforeUnmount(clearPoller);
</script>

<style scoped>
.upload-page {
  gap: var(--content-gap, 20px);
  overflow: hidden;
}

.upload-layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 360px) minmax(0, 1fr);
  gap: var(--section-gap, 24px);
}

.upload-left {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.kb-select-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.kb-select-row .el-select {
  flex: 1;
}

.upload-section {
  padding: 20px;
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px 24px;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-panel-muted);
  cursor: pointer;
  transition: border-color var(--transition-base), background var(--transition-base);
}

.dropzone:hover {
  border-color: var(--blue-600);
  background: var(--blue-50);
}

.dropzone .el-icon {
  color: var(--text-muted);
}

.dropzone:hover .el-icon {
  color: var(--blue-600);
}

.dropzone-hint {
  font-size: var(--text-caption, 0.75rem);
  color: var(--text-muted);
}

.hidden-input {
  display: none;
}

.file-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.file-name {
  flex-shrink: 0;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-body, 0.9375rem);
}

.upload-btn {
  margin-top: 14px;
  width: 100%;
}

.upload-right {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
}

.doc-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-color);
  font-size: var(--text-body, 0.9375rem);
  font-weight: 600;
}

.doc-count {
  font-size: var(--text-caption, 0.75rem);
  color: var(--text-muted);
  font-weight: 500;
}

.doc-list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.doc-empty {
  padding: 40px 20px !important;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.doc-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-panel-muted);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--transition-base), background var(--transition-base);
}

.doc-item:hover {
  border-color: var(--border-strong);
  background: var(--bg-panel);
}

.doc-name {
  font-size: var(--text-body, 0.9375rem);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
}

.doc-actions {
  display: flex;
  gap: 10px;
}

.collapse-title {
  font-size: var(--text-body, 0.9375rem);
  color: var(--text-secondary);
  font-weight: 500;
}

@media (max-width: 900px) {
  .upload-layout {
    grid-template-columns: 1fr;
  }
}
</style>
