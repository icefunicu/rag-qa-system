<template>
  <div class="corpus-detail">
    <div class="page-header">
      <div class="header-left">
        <el-button :icon="Back" circle @click="$router.push('/dashboard/corpora')" />
        <h2>知识库文档管理 {{ corpusId }}</h2>
      </div>
    </div>

    <div class="content-grid">
      <div class="upload-column">
        <el-card class="upload-card">
          <template #header>
            <div class="card-header">
              <span>上传新文档</span>
            </div>
          </template>
          <DocumentUploader :corpusId="corpusId" @uploaded="fetchDocuments" />
        </el-card>
      </div>

      <div class="list-column">
        <el-card class="list-card">
          <template #header>
            <div class="card-header">
              <div class="header-left-actions">
                <span>文档列表</span>
                <el-button 
                  v-if="selectedDocuments.length > 0" 
                  type="danger" 
                  size="small" 
                  plain
                  style="margin-left: 12px;"
                  @click="confirmBatchDelete"
                >
                  批量删除 ({{ selectedDocuments.length }})
                </el-button>
              </div>
              <el-button link type="primary" @click="fetchDocuments">刷新</el-button>
            </div>
          </template>

          <el-table :data="documents" v-loading="loading" border style="width: 100%" @selection-change="handleSelectionChange">
            <el-table-column type="selection" width="55" />
            <el-table-column prop="id" label="ID" min-width="280" />
            <el-table-column prop="file_name" label="文件名" min-width="220" />
            <el-table-column prop="file_type" label="类型" width="100">
              <template #default="scope">
                <el-tag>{{ scope.row.file_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="120">
              <template #default="scope">
                {{ formatSize(scope.row.size_bytes) }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="120">
              <template #default="scope">
                <el-tag :type="getStatusType(scope.row.status)" :effect="['failed', 'cancelled'].includes(scope.row.status) ? 'dark' : 'light'">
                  {{ scope.row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180">
              <template #default="scope">
                {{ formatDateTime(scope.row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="320" fixed="right">
              <template #default="scope">
                <el-button type="primary" link @click="openDetail(scope.row)">详情</el-button>
                <el-button type="success" link @click="openPreview(scope.row)">在线查看</el-button>
                <el-button
                  type="warning"
                  link
                  :disabled="!canEdit(scope.row)"
                  @click="openEdit(scope.row)"
                >
                  在线修改
                </el-button>
                <el-button
                  v-if="canCancel(scope.row)"
                  type="warning"
                  link
                  :loading="cancellingDocumentId === scope.row.id"
                  @click="cancelDocumentIngest(scope.row)"
                >
                  取消处理
                </el-button>
                <el-button
                  type="danger"
                  link
                  :disabled="canCancel(scope.row)"
                  @click="confirmDelete(scope.row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </div>

    <el-dialog v-model="detailVisible" title="文档详情" width="800px" destroy-on-close>
      <div v-loading="detailLoading || logsLoading">
        <el-tabs v-model="activeDetailTab" @tab-change="handleDetailTabChange">
          <el-tab-pane label="基本信息" name="info">
            <el-descriptions v-if="detailData" :column="1" border style="margin-bottom: 24px;">
              <el-descriptions-item label="文档 ID">{{ detailData.id }}</el-descriptions-item>
              <el-descriptions-item label="知识库 ID">{{ detailData.corpus_id }}</el-descriptions-item>
              <el-descriptions-item label="文件名">{{ detailData.file_name }}</el-descriptions-item>
              <el-descriptions-item label="文件类型">{{ detailData.file_type }}</el-descriptions-item>
              <el-descriptions-item label="文件大小">{{ formatSize(detailData.size_bytes) }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ detailData.status }}</el-descriptions-item>
              <el-descriptions-item label="创建者">{{ detailData.created_by ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.created_at) }}</el-descriptions-item>
            </el-descriptions>

            <el-card v-if="detailJobRuntime" class="detail-runtime-card" shadow="never">
              <div class="detail-runtime-header">
                <div>
                  <div class="detail-runtime-title">{{ getRuntimeStageLabel(detailJobRuntime.stage || detailJobRuntime.status) }}</div>
                  <div v-if="detailRuntimeDescription" class="detail-runtime-description">{{ detailRuntimeDescription }}</div>
                </div>
                <div class="detail-runtime-actions">
                  <el-tag type="warning">{{ detailJobRuntime.overall_progress }}%</el-tag>
                  <el-button
                    v-if="detailData && canCancel(detailData)"
                    type="warning"
                    plain
                    size="small"
                    :loading="cancellingDocumentId === detailData.id"
                    @click="cancelDocumentIngest(detailData)"
                  >
                    取消处理
                  </el-button>
                </div>
              </div>
              <el-progress :percentage="detailRuntimePercent" status="warning" :stroke-width="18" />
            </el-card>

            <div>
              <h4 style="margin-bottom: 16px;">Ingest Timeline (处理轨迹)</h4>
              <el-timeline v-if="detailEvents && detailEvents.length > 0">
                <el-timeline-item
                  v-for="(ev, index) in detailEvents"
                  :key="index"
                  :type="getEventTagType(ev.status || ev.stage)"
                  :timestamp="formatDateTime(ev.created_at)"
                  placement="top"
                >
                  <el-card shadow="hover">
                    <h4>{{ ev.status || ev.stage }}</h4>
                    <p v-if="ev.message" style="margin-top: 8px; color: var(--text-secondary); font-size: 13px;">{{ ev.message }}</p>
                    <div v-if="ev.details" style="margin-top: 8px; font-size: 12px; background: var(--bg-surface-hover); padding: 8px; border-radius: 4px; overflow-x: auto;">
                      <pre style="margin: 0; white-space: pre-wrap;">{{ JSON.stringify(ev.details, null, 2) }}</pre>
                    </div>
                  </el-card>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-else description="暂无轨迹记录" :image-size="60" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="后端日志" name="logs">
            <div class="logs-toolbar">
              <el-button size="small" type="primary" :icon="Refresh" @click="fetchLogs" :loading="logsLoading">刷新日志</el-button>
              <span class="logs-hint">按当前文档 ID 和任务 ID 过滤。最多显示最后 200 行。</span>
            </div>
            <div class="logs-viewer">
              <template v-if="logsLines && logsLines.length > 0">
                <div 
                  v-for="(line, idx) in logsLines" 
                  :key="idx" 
                  class="log-line"
                  :class="getLogLineClass(line)"
                >
                  {{ line }}
                </div>
              </template>
              <el-empty v-else description="未找到相关后端日志" :image-size="60" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="在线查看" width="980px" destroy-on-close>
      <div v-loading="previewLoading">
        <template v-if="previewData">
          <div class="preview-info-bar">
            <el-tag type="info">文件大小：{{ formatSize(previewData.document.size_bytes ?? 0) }}</el-tag>
            <el-tag :type="getFileSizeTagType(fileSizeCategory)" style="margin-left: 8px;">
              {{ fileSizeCategoryText }}
            </el-tag>
            <el-tag
              v-if="isTextualPreviewMode(previewData.preview_mode) && previewData.detected_encoding"
              type="info"
              style="margin-left: 8px;"
            >
              编码：{{ previewData.detected_encoding }}
            </el-tag>
          </div>

          <el-alert
            v-if="isTextualPreviewMode(previewData.preview_mode)"
            :type="previewData.preview_mode === 'text' ? 'success' : 'warning'"
            :closable="false"
            show-icon
            :title="getPreviewAlertTitle(previewData)"
            :description="getPreviewAlertDescription(previewData)"
            class="preview-alert"
          />

          <el-alert
            v-else
            type="info"
            :closable="false"
            show-icon
            title="当前文档使用预签名 URL 预览"
            class="preview-alert"
          />

          <template v-if="isTextualPreviewMode(previewData.preview_mode)">
            <el-input
              :model-value="previewData.text ?? ''"
              type="textarea"
              :rows="22"
              readonly
              v-loading="previewLoading"
            />
          </template>

          <div v-else class="preview-url-mode">
            <div class="preview-toolbar">
              <el-button type="primary" @click="openPreviewInNewTab">新窗口打开</el-button>
              <span class="preview-expire-text">
                预览链接有效期 {{ previewData.expires_in_seconds ?? 0 }} 秒
              </span>
            </div>
            <iframe
              v-if="previewData.view_url"
              :src="previewData.view_url"
              class="preview-frame"
              title="文档预览"
            />
            <el-empty v-else description="预览链接不可用" />
          </div>
        </template>
      </div>
    </el-dialog>

    <el-dialog v-model="editVisible" title="在线修改（仅 TXT）" width="980px" destroy-on-close>
      <div v-loading="editLoading">
        <template v-if="editDocument">
          <el-alert
            type="warning"
            show-icon
            :closable="false"
            title="保存后将自动触发文档重新入库与向量索引重建。"
            class="preview-alert"
          />
          <el-input
            v-model="editContent"
            type="textarea"
            :rows="22"
            maxlength="1048576"
            show-word-limit
            placeholder="请输入文档内容"
          />
        </template>
      </div>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="editSubmitting"
          :disabled="!editContent.trim()"
          @click="submitEdit"
        >
          保存并重建索引
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="deleteVisible" title="确认删除" width="500px" destroy-on-close>
      <el-alert
        type="error"
        show-icon
        :closable="false"
        title="删除后不可恢复"
        class="delete-alert"
      />
      <div class="delete-content">
        <p>确定要删除以下文档吗？</p>
        <p class="delete-filename"><strong>{{ deleteDocument?.file_name }}</strong></p>
        <p class="delete-warning">此操作将同时删除：</p>
        <ul class="delete-list">
          <li>文档文件本身</li>
          <li>关联的向量索引</li>
          <li>所有相关的元数据</li>
        </ul>
      </div>
      <template #footer>
        <el-button @click="deleteVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="deleting"
          @click="executeDelete"
        >
          确认删除
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchDeleteVisible" title="确认批量删除" width="540px" destroy-on-close>
      <el-alert
        type="error"
        show-icon
        :closable="false"
        title="批量删除后不可恢复"
        class="delete-alert"
      />
      <div class="delete-content">
        <p>确定要删除以下 <strong>{{ selectedDocuments.length }}</strong> 个文档吗？</p>
        <div class="batch-delete-list">
          <p v-for="doc in selectedDocuments" :key="doc.id" class="delete-filename">
            • {{ doc.file_name }}
          </p>
        </div>
        <p class="delete-warning" style="margin-top: 12px;">此操作将同时彻底清理所有关联的向量索引、S3文件对象和元数据。</p>
      </div>
      <template #footer>
        <el-button @click="batchDeleteVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="deleting"
          @click="executeBatchDelete"
        >
          确认批量删除
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import { Back, Refresh } from '@element-plus/icons-vue';
import DocumentUploader from '@/components/DocumentUploader.vue';
import {
  getDocumentDetail,
  getDocumentPreview,
  listCorpusDocuments,
  updateDocumentContent,
  deleteDocument as deleteDocumentApi,
  cancelIngestJob,
  batchDeleteDocuments,
  getAdminLogs,
  type CorpusDocument,
  type DocumentPreviewResponse,
  type RuntimeProgress
} from '@/api/documents';
import { getDocumentEvents, type DocumentEventsResponse } from '@/api/events';

const SIZE_THRESHOLD_SMALL = 1024 * 1024;
const SIZE_THRESHOLD_LARGE = 10 * 1024 * 1024;

const route = useRoute();
const corpusId = computed(() => String(route.params.id ?? ''));
const loading = ref(false);
const documents = ref<CorpusDocument[]>([]);
let autoRefreshTimer: number | null = null;

const detailVisible = ref(false);
const detailLoading = ref(false);
const detailData = ref<CorpusDocument | null>(null);
const detailEvents = ref<Record<string, any>[]>([]);
const detailJobRuntime = ref<RuntimeProgress | null>(null);
const activeDetailTab = ref('info');
const logsLoading = ref(false);
const logsLines = ref<string[]>([]);
let detailRefreshTimer: number | null = null;

const previewVisible = ref(false);
const previewLoading = ref(false);
const previewData = ref<DocumentPreviewResponse | null>(null);
const fileSizeCategory = ref<'small' | 'medium' | 'large'>('small');

const editVisible = ref(false);
const editLoading = ref(false);
const editSubmitting = ref(false);
const editDocument = ref<CorpusDocument | null>(null);
const editContent = ref('');

const deleteVisible = ref(false);
const deleting = ref(false);
const deleteDocument = ref<CorpusDocument | null>(null);
const cancellingDocumentId = ref('');

const selectedDocuments = ref<CorpusDocument[]>([]);
const batchDeleteVisible = ref(false);

const fetchDocuments = async () => {
  loading.value = true;
  try {
    const res = await listCorpusDocuments(corpusId.value);
    documents.value = res.items ?? [];
  } finally {
    loading.value = false;
    syncAutoRefresh();
  }
};

const stopAutoRefresh = () => {
  if (autoRefreshTimer !== null) {
    window.clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
};

const syncAutoRefresh = () => {
  const hasPendingDocuments = documents.value.some(doc => ['uploaded', 'indexing'].includes(doc.status));
  if (!hasPendingDocuments) {
    stopAutoRefresh();
    return;
  }

  if (autoRefreshTimer !== null) {
    return;
  }

  autoRefreshTimer = window.setInterval(() => {
    if (!loading.value) {
      void fetchDocuments();
    }
  }, 3000);
};

const formatDateTime = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
};

const formatSize = (sizeBytes: number) => {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) {
    return '0 B';
  }
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  }
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
};

const getStatusType = (status: CorpusDocument['status'] | string) => {
  switch (status) {
    case 'ready':
      return 'success';
    case 'failed':
      return 'danger';
    case 'cancelled':
      return 'info';
    case 'indexing':
      return 'warning';
    case 'uploaded':
      return 'info';
    default:
      return '';
  }
};

const getBackendErrorMessage = (error: any, fallback: string) => {
  return error?.response?.data?.error || error?.response?.data?.message || error?.message || fallback;
};

const canCancel = (doc?: Pick<CorpusDocument, 'status'> | null) => {
  const status = (doc?.status || '').toLowerCase();
  return status === 'uploaded' || status === 'indexing';
};

const canEdit = (doc: CorpusDocument) => doc.file_type === 'txt' && doc.size_bytes <= SIZE_THRESHOLD_SMALL;

const isTextualPreviewMode = (mode?: DocumentPreviewResponse['preview_mode']) => mode === 'text' || mode === 'partial';

const getPreviewAlertTitle = (preview: DocumentPreviewResponse) => {
  if (preview.preview_mode === 'text') {
    return '已加载完整内容，可在线查看与编辑';
  }
  if (preview.truncated) {
    return `当前仅展示已解码的前 ${formatSize(preview.max_partial_bytes ?? 0)}`;
  }
  return '文件较大，已按检测编码加载完整内容（只读）';
};

const getPreviewAlertDescription = (preview: DocumentPreviewResponse) => {
  if (preview.preview_mode === 'text') {
    return preview.detected_encoding ? `检测编码：${preview.detected_encoding}` : '';
  }
  if (preview.truncated) {
    return `原文件大小 ${formatSize(preview.document.size_bytes ?? 0)}，为保证浏览器可用性，仅返回前 ${formatSize(preview.max_partial_bytes ?? 0)} 的 UTF-8 预览。`;
  }
  return `原文件超过在线编辑上限 ${formatSize(preview.max_inline_bytes ?? 0)}，因此关闭在线编辑，仅提供只读预览。`;
};

const fileSizeCategoryText = computed(() => {
  switch (fileSizeCategory.value) {
    case 'small':
      return '小文件 (< 1MB)';
    case 'medium':
      return '中等文件 (1MB - 10MB)';
    case 'large':
      return '大文件 (> 10MB)';
    default:
      return '';
  }
});

const getFileSizeTagType = (category: 'small' | 'medium' | 'large') => {
  switch (category) {
    case 'small':
      return 'success';
    case 'medium':
      return 'warning';
    case 'large':
      return 'danger';
    default:
      return 'info';
  }
};

const categorizeFileSize = (sizeBytes: number): 'small' | 'medium' | 'large' => {
  if (sizeBytes < SIZE_THRESHOLD_SMALL) {
    return 'small';
  } else if (sizeBytes < SIZE_THRESHOLD_LARGE) {
    return 'medium';
  } else {
    return 'large';
  }
};

const getRuntimeStageLabel = (stage?: string) => {
  switch ((stage || '').toLowerCase()) {
    case 'queued':
      return '等待 Worker 接单';
    case 'downloading':
      return '下载源文件';
    case 'parsing':
      return '解析文档';
    case 'chunking':
      return '文本切片';
    case 'embedding':
      return '生成向量';
    case 'indexing':
      return '写入向量索引';
    case 'verifying':
      return '校验索引一致性';
    case 'done':
      return '处理完成';
    case 'dead_letter':
      return '重试耗尽';
    case 'failed':
      return '处理失败';
    default:
      return stage || '处理中';
  }
};

const detailRuntimeDescription = computed(() => {
  const details = detailJobRuntime.value?.details ?? {};
  if (typeof details.total_chunks === 'number' && typeof details.total_batches === 'number') {
    const parts = [
      `${details.processed_chunks ?? 0}/${details.total_chunks} 分片`,
      `${details.processed_batches ?? 0}/${details.total_batches} 批`,
    ];
    if (typeof details.current_batch === 'number' && details.current_batch > (details.processed_batches ?? 0)) {
      parts.push(
        `当前第 ${details.current_batch} 批${typeof details.current_batch_size === 'number' ? `（${details.current_batch_size} 分片）` : ''}`,
      );
    }
    return parts.join(' · ');
  }

  if (typeof details.vector_count === 'number') {
    return typeof details.chunk_count === 'number'
      ? `${details.vector_count} 条向量 / ${details.chunk_count} 条分片`
      : `${details.vector_count} 条向量`;
  }

  return detailJobRuntime.value?.message || '';
});

const detailRuntimePercent = computed(() => {
  const details = detailJobRuntime.value?.details ?? {};
  if (typeof details.stage_progress_percent === 'number' && Number.isFinite(details.stage_progress_percent)) {
    return Math.max(0, Math.min(100, Math.round(details.stage_progress_percent)));
  }
  if (typeof detailJobRuntime.value?.overall_progress === 'number') {
    return Math.max(0, Math.min(100, Math.round(detailJobRuntime.value.overall_progress)));
  }
  return 0;
});

const stopDetailAutoRefresh = () => {
  if (detailRefreshTimer !== null) {
    window.clearInterval(detailRefreshTimer);
    detailRefreshTimer = null;
  }
};

const syncDetailAutoRefresh = () => {
  const runtimeStatus = (detailJobRuntime.value?.status || '').toLowerCase();
  const documentStatus = (detailData.value?.status || '').toLowerCase();
  const hasPendingJob = ['queued', 'running'].includes(runtimeStatus) || ['uploaded', 'indexing'].includes(documentStatus);

  if (!detailVisible.value || !hasPendingJob) {
    stopDetailAutoRefresh();
    return;
  }

  if (detailRefreshTimer !== null) {
    return;
  }

  detailRefreshTimer = window.setInterval(() => {
    if (!detailLoading.value && detailData.value?.id) {
      void loadDetailData(detailData.value.id, false);
    }
  }, 2500);
};

const loadDetailData = async (documentId: string, showLoading = true) => {
  if (showLoading) {
    detailLoading.value = true;
  }

  try {
    const emptyEvents: DocumentEventsResponse = { items: [], count: 0, job_runtime: null };
    const [detailRes, eventsRes] = await Promise.all([
      getDocumentDetail(documentId),
      getDocumentEvents(documentId).catch(() => emptyEvents),
    ]);
    detailData.value = detailRes;
    detailEvents.value = eventsRes.items || [];
    detailJobRuntime.value = eventsRes.job_runtime || null;
  } finally {
    if (showLoading) {
      detailLoading.value = false;
    }
    syncDetailAutoRefresh();
  }
};

const openDetail = async (doc: CorpusDocument) => {
  detailVisible.value = true;
  detailLoading.value = true;
  detailData.value = null;
  detailEvents.value = [];
  detailJobRuntime.value = null;
  activeDetailTab.value = 'info';
  logsLines.value = [];
  await loadDetailData(doc.id);
};

const handleDetailTabChange = (name: string) => {
  if (name === 'logs' && logsLines.value.length === 0) {
    fetchLogs();
  }
};

const fetchLogs = async () => {
  if (!detailData.value) return;
  logsLoading.value = true;
  logsLines.value = [];
  try {
    const keyword = detailData.value.id; // 可以按 document_id 过滤
    const res = await getAdminLogs({ keyword, tail: 200 });
    logsLines.value = res.lines || [];
  } catch (error: any) {
    if (error?.response?.status === 409 && deleteDocument.value) {
      ElMessage.warning('该文档仍在处理中，请先点击“取消处理”再删除');
      return;
    }
    ElMessage.error('获取后端日志失败');
  } finally {
    logsLoading.value = false;
  }
};

const getLogLineClass = (line: string) => {
  const lower = line.toLowerCase();
  if (lower.includes('error') || lower.includes('failed') || lower.includes('catastrophic')) {
    return 'log-error';
  }
  if (lower.includes('warn') || lower.includes('retry')) {
    return 'log-warn';
  }
  if (lower.includes('info') || lower.includes('success')) {
    return 'log-info';
  }
  return '';
};

const getEventTagType = (status: string) => {
  switch (status.toLowerCase()) {
    case 'done':
    case 'ready':
      return 'success';
    case 'failed':
    case 'dead_letter':
      return 'danger';
    case 'queued':
    case 'downloading':
    case 'parsing':
    case 'chunking':
    case 'embedding':
    case 'processing':
    case 'indexing':
    case 'verifying':
      return 'warning';
    default:
      return 'info';
  }
};

const openPreview = async (doc: CorpusDocument) => {
  previewVisible.value = true;
  previewLoading.value = true;
  previewData.value = null;
  fileSizeCategory.value = 'small';
  
  try {
    previewData.value = await getDocumentPreview(doc.id);
    
    const sizeBytes = previewData.value.document.size_bytes ?? doc.size_bytes ?? 0;
    fileSizeCategory.value = categorizeFileSize(sizeBytes);
  } catch (error) {
    ElMessage.error('获取预览失败');
    console.error(error);
  } finally {
    previewLoading.value = false;
  }
};

watch(previewVisible, (newVal) => {
  if (!newVal) {
    previewData.value = null;
    fileSizeCategory.value = 'small';
  }
});

watch(detailVisible, (newVal) => {
  if (!newVal) {
    stopDetailAutoRefresh();
    detailJobRuntime.value = null;
  }
});

const openPreviewInNewTab = () => {
  const url = previewData.value?.view_url;
  if (!url) {
    ElMessage.warning('预览链接不可用');
    return;
  }
  window.open(url, '_blank', 'noopener');
};

const openEdit = async (doc: CorpusDocument) => {
  if (!canEdit(doc)) {
    ElMessage.warning('仅 txt 文档支持在线修改');
    return;
  }

  editVisible.value = true;
  editLoading.value = true;
  editDocument.value = null;
  editContent.value = '';

  try {
    const [detail, preview] = await Promise.all([
      getDocumentDetail(doc.id),
      getDocumentPreview(doc.id)
    ]);
    if (preview.preview_mode !== 'text') {
      ElMessage.error('当前文档不支持在线编辑');
      editVisible.value = false;
      return;
    }

    editDocument.value = detail;
    editContent.value = preview.text ?? '';
  } finally {
    editLoading.value = false;
  }
};

const submitEdit = async () => {
  if (!editDocument.value) {
    return;
  }

  const nextContent = editContent.value;
  if (!nextContent.trim()) {
    ElMessage.warning('内容不能为空');
    return;
  }

  editSubmitting.value = true;
  try {
    await updateDocumentContent(editDocument.value.id, nextContent);
    ElMessage.success('内容已更新，已提交重建索引任务');
    editVisible.value = false;
    await fetchDocuments();
  } finally {
    editSubmitting.value = false;
  }
};

const resolveActiveJobId = async (documentId: string) => {
  const eventsRes = await getDocumentEvents(documentId);
  return eventsRes.job_runtime?.job_id || eventsRes.job_id || eventsRes.items?.[eventsRes.items.length - 1]?.job_id || '';
};

const cancelDocumentIngest = async (doc: CorpusDocument) => {
  if (!canCancel(doc)) {
    ElMessage.warning('当前文档没有可取消的处理任务');
    return;
  }

  cancellingDocumentId.value = doc.id;
  try {
    const jobId = await resolveActiveJobId(doc.id);
    if (!jobId) {
      ElMessage.warning('未找到可取消的任务，请刷新后重试');
      return;
    }

    await cancelIngestJob(jobId);
    ElMessage.success('已取消文档处理任务');

    if (deleteDocument.value?.id === doc.id) {
      deleteVisible.value = false;
    }

    await fetchDocuments();
    if (detailVisible.value && detailData.value?.id === doc.id) {
      await loadDetailData(doc.id, false);
    }
  } catch (error) {
    ElMessage.error(getBackendErrorMessage(error, '取消处理失败，请稍后重试'));
    console.error(error);
  } finally {
    cancellingDocumentId.value = '';
  }
};
const confirmDelete = (doc: CorpusDocument) => {
  deleteDocument.value = doc;
  deleteVisible.value = true;
};

const executeDelete = async () => {
  if (!deleteDocument.value) {
    return;
  }

  deleting.value = true;
  try {
    await deleteDocumentApi(deleteDocument.value.id);
    ElMessage.success('文档已删除');
    deleteVisible.value = false;
    await fetchDocuments();
  } catch (error: any) {
    if (error?.response?.status === 409 && deleteDocument.value) {
      ElMessage.warning('该文档仍在处理中，请先取消处理再删除');
      return;
    }
    ElMessage.error(getBackendErrorMessage(error, '删除失败，请稍后重试'));
    console.error(error);
  } finally {
    deleting.value = false;
  }
};
watch(deleteVisible, (newVal) => {
  if (!newVal) {
    deleteDocument.value = null;
  }
});

const handleSelectionChange = (selection: CorpusDocument[]) => {
  selectedDocuments.value = selection;
};

const confirmBatchDelete = () => {
  if (selectedDocuments.value.length === 0) return;
  batchDeleteVisible.value = true;
};

const executeBatchDelete = async () => {
  if (selectedDocuments.value.length === 0) return;
  
  deleting.value = true;
  try {
    const ids = selectedDocuments.value.map(d => d.id);
    await batchDeleteDocuments(ids);
    ElMessage.success(`已成功删除 ${ids.length} 个文档`);
    batchDeleteVisible.value = false;
    selectedDocuments.value = [];
    await fetchDocuments();
  } catch (error) {
    ElMessage.error('批量删除失败，请稍后重试');
    console.error(error);
  } finally {
    deleting.value = false;
  }
};

onMounted(() => {
  fetchDocuments();
});

onBeforeUnmount(() => {
  stopAutoRefresh();
  stopDetailAutoRefresh();
});
</script>

<style scoped>
.corpus-detail {
  padding: 24px;
  margin: 16px;
  background-color: var(--bg-surface);
  border-radius: 16px;
  box-shadow: var(--shadow-sm);
  min-height: calc(100vh - 32px);
}

.page-header {
  margin-bottom: 28px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.5px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}

.upload-column,
.list-column {
  min-width: 0;
}

.upload-column {
  position: sticky;
  top: 24px;
}

.upload-card {
  border-radius: 16px;
  border: 1px solid var(--border-color-light);
  box-shadow: var(--shadow-sm);
}

.list-card {
  border-radius: 16px;
  border: 1px solid var(--border-color-light);
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: var(--text-primary);
}

.header-left-actions {
  display: flex;
  align-items: center;
}

.preview-alert {
  margin-bottom: 12px;
  border-radius: 8px;
}

.detail-runtime-card {
  margin-bottom: 16px;
  border-radius: 12px;
  border: 1px solid var(--border-color-light);
  background: var(--bg-base);
}

.detail-runtime-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.detail-runtime-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.detail-runtime-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-runtime-description {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.preview-info-bar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  gap: 8px;
}

.preview-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 12px;
  padding: 12px 0;
  border-top: 1px solid var(--border-color-light);
}

.preview-url-mode {
  width: 100%;
}

.preview-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.preview-expire-text {
  font-size: 13px;
  color: var(--text-secondary);
}

.preview-frame {
  width: 100%;
  height: 620px;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  box-shadow: var(--shadow-sm);
}

.delete-alert {
  margin-bottom: 16px;
  border-radius: 8px;
}

.delete-content {
  padding: 8px 0;
}

.delete-content p {
  margin: 8px 0;
  color: var(--text-primary);
}

.delete-filename {
  font-size: 16px;
  color: var(--text-primary);
  word-break: break-all;
}

.delete-warning {
  color: var(--text-secondary);
  font-size: 14px;
}

.batch-delete-list {
  max-height: 150px;
  overflow-y: auto;
  background-color: var(--bg-surface-hover);
  padding: 8px 12px;
  border-radius: 6px;
  margin-top: 8px;
  font-size: 13px;
  border: 1px solid var(--border-color-light);
}

.delete-list {
  margin: 8px 0;
  padding-left: 20px;
  color: var(--text-secondary);
}

.delete-list li {
  margin: 4px 0;
}

.logs-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.logs-hint {
  font-size: 13px;
  color: var(--text-secondary);
}

.logs-viewer {
  background-color: var(--bg-surface-hover);
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  padding: 12px;
  height: 480px;
  overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, builtin, monospace;
  font-size: 13px;
  line-height: 1.5;
}

.log-line {
  word-break: break-all;
  white-space: pre-wrap;
  color: var(--text-regular);
  padding: 2px 0;
  border-bottom: 1px solid transparent;
}

.log-line:hover {
  background-color: rgba(0, 0, 0, 0.02);
}

.log-error {
  color: var(--el-color-danger);
  font-weight: 500;
}

.log-warn {
  color: var(--el-color-warning);
}

.log-info {
  color: var(--el-color-success);
}

:deep(.el-table) {
  border-radius: 8px;
}
:deep(.el-table th.el-table__cell) {
  background-color: var(--bg-base);
  color: var(--text-secondary);
  font-weight: 600;
}

@media (max-width: 1400px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .upload-column {
    position: static;
  }

  .upload-card {
    margin-bottom: 24px;
  }
}
</style>
