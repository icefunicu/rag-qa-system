<template>
  <div class="document-uploader">
    <el-upload
      class="upload-demo"
      drag
      action="#"
      :auto-upload="false"
      :show-file-list="false"
      :on-change="handleChange"
      :disabled="isUploading || isPolling"
    >
      <el-icon class="el-icon--upload"><upload-filled /></el-icon>
      <div class="el-upload__text">
        拖拽文件到此处，或 <em>点击上传</em>
      </div>
      <template #tip>
        <div class="el-upload__tip">
          支持 txt / pdf / docx，大小不超过 500MB
        </div>
      </template>
    </el-upload>

    <div v-if="isUploading || isPolling || uploadError" class="progress-container">
      <div class="status-header">
        <el-icon v-if="uploadError" class="status-icon error"><circle-close /></el-icon>
        <el-icon v-else-if="isPolling && pollingProgress === 100" class="status-icon success"><circle-check /></el-icon>
        <el-icon v-else class="status-icon loading"><loading /></el-icon>
        <span class="status-text">{{ currentStatus }}</span>
      </div>

      <el-progress
        v-if="isUploading"
        :percentage="uploadProgress"
        :status="uploadError ? 'exception' : (uploadProgress === 100 ? 'success' : undefined)"
        :format="getProgressText"
        :stroke-width="20"
      />

      <el-progress
        v-if="isPolling"
        :percentage="pollingProgress"
        :status="pollingProgress === 100 ? 'success' : 'warning'"
        :format="formatPollingProgress"
        :stroke-width="20"
      />

      <el-progress
        v-if="stageProgressPercent !== null"
        class="stage-progress"
        :percentage="stageProgressPercent"
        status="warning"
        :format="formatStageProgress"
        :stroke-width="14"
      />

      <div v-if="isPolling || (uploadError && activeJobId)" class="steps-container">
        <el-steps :active="activeStep" :process-status="uploadError ? 'error' : 'process'" align-center>
          <el-step title="排队等待" />
          <el-step title="下载源文件" />
          <el-step title="解析与切片" />
          <el-step title="生成向量" />
          <el-step title="索引与校验" />
          <el-step title="处理完成" />
        </el-steps>
      </div>

      <div v-if="currentStage || activeJobId || activeDocumentId || lastUpdatedAtText" class="runtime-meta">
        <div v-if="currentStage" class="meta-row">
          <span class="meta-label">当前阶段</span>
          <span class="meta-value">
            {{ currentStage }}
            <template v-if="currentStageMessage"> · {{ currentStageMessage }}</template>
          </span>
        </div>
        <div v-if="runtimeProgressSummary" class="meta-row">
          <span class="meta-label">阶段进度</span>
          <span class="meta-value">{{ runtimeProgressSummary }}</span>
        </div>
        <div v-if="runtimeProviderText" class="meta-row">
          <span class="meta-label">运行模型</span>
          <span class="meta-value">{{ runtimeProviderText }}</span>
        </div>
        <div v-if="lastUpdatedAtText" class="meta-row">
          <span class="meta-label">最近更新</span>
          <span class="meta-value">{{ lastUpdatedAtText }}</span>
        </div>
        <div v-if="activeJobId" class="meta-row">
          <span class="meta-label">任务 ID</span>
          <code class="meta-code">{{ activeJobId }}</code>
        </div>
        <div v-if="activeDocumentId" class="meta-row">
          <span class="meta-label">文档 ID</span>
          <code class="meta-code">{{ activeDocumentId }}</code>
        </div>
        <div v-if="uploadError?.errorCategory" class="meta-row">
          <span class="meta-label">错误分类</span>
          <code class="meta-code">{{ uploadError.errorCategory }}</code>
        </div>
      </div>

      <el-alert
        v-if="isPolling || uploadError"
        class="timeline-hint"
        type="info"
        :closable="false"
        show-icon
        title="查看处理轨迹"
        description="下方文档列表可点击“详情”查看 Ingest Timeline；本地开发环境可直接执行下方命令筛日志。"
      />

      <div v-if="(isPolling || uploadError) && logCommands.length" class="log-hints">
        <div class="log-hints-title">本地日志排障命令</div>
        <code v-for="command in logCommands" :key="command" class="log-command">{{ command }}</code>
        <div class="log-hints-note">导出的汇总日志默认位于 <code>logs/export/combined_*.log</code>。</div>
      </div>

      <div v-if="uploadError" class="error-details">
        <el-alert
          :title="uploadError.message"
          :description="uploadError.details"
          type="error"
          :closable="true"
          @close="handleErrorClose"
          show-icon
        />
        <el-button
          v-if="isUploading || isPolling"
          type="info"
          size="small"
          @click="handleCancel"
          :loading="isCancelling"
        >
          <el-icon><circle-close /></el-icon>
          取消处理
        </el-button>
        <el-button
          v-if="uploadError"
          type="primary"
          size="small"
          @click="handleRetry"
          :loading="isUploading"
        >
          <el-icon><refresh /></el-icon>
          重试上传
        </el-button>
      </div>

      <div v-else-if="isUploading || isPolling" class="actions-row">
        <el-button
          type="info"
          size="small"
          @click="handleCancel"
          :loading="isCancelling"
        >
          <el-icon><circle-close /></el-icon>
          取消处理
        </el-button>
      </div>

      <div v-if="isUploading && progressInfo?.estimatedRemaining" class="time-remaining">
        预计剩余时间：{{ formatTime(progressInfo.estimatedRemaining) }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { UploadFilled, CircleClose, CircleCheck, Loading, Refresh } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import type { RuntimeProgressDetails } from '@/api/documents';
import { useUploader } from '@/composables/useUploader';

const props = defineProps<{ corpusId: string }>();
const emit = defineEmits(['uploaded']);

const handleSuccess = () => {
  emit('uploaded');
};

const {
  activeDocumentId,
  activeJobId,
  currentStageKey,
  currentStage,
  currentStageMessage,
  uploadFile,
  retryUpload,
  isUploading,
  uploadProgress,
  isPolling,
  pollingProgress,
  currentStatus,
  lastUpdatedAtText,
  uploadError,
  progressInfo,
  runtimeProgress,
  getProgressText,
  cancelUpload,
  isCancelling,
} = useUploader(props.corpusId, handleSuccess);

let currentFile: File | null = null;

const handleChange = async (uploadFileObj: any) => {
  if (uploadFileObj && uploadFileObj.raw) {
    currentFile = uploadFileObj.raw;
    const ext = uploadFileObj.name.split('.').pop()?.toLowerCase();
    if (!['txt', 'pdf', 'docx'].includes(ext)) {
      ElMessage.error('仅支持 txt、pdf、docx 格式');
      return;
    }
    await uploadFile(uploadFileObj.raw);
  }
};

const activeStep = computed(() => {
  const stage = (currentStageKey.value || '').toLowerCase();
  if (!stage) return 0;
  if (stage.includes('download')) return 1;
  if (stage.includes('pars') || stage.includes('chunk')) return 2;
  if (stage.includes('embed')) return 3;
  if (stage.includes('index') || stage.includes('verify')) return 4;
  if (stage.includes('done')) return 6;
  return 0;
});

const runtimeDetails = computed<RuntimeProgressDetails>(() => runtimeProgress.value?.details ?? {});

const stageProgressPercent = computed<number | null>(() => {
  if ((currentStageKey.value || '').toLowerCase() !== 'embedding') {
    return null;
  }

  const explicit = runtimeDetails.value.stage_progress_percent;
  if (typeof explicit === 'number' && Number.isFinite(explicit)) {
    return Math.max(0, Math.min(100, Math.round(explicit)));
  }

  const processedChunks = runtimeDetails.value.processed_chunks;
  const totalChunks = runtimeDetails.value.total_chunks;
  if (typeof processedChunks !== 'number' || typeof totalChunks !== 'number' || totalChunks <= 0) {
    return null;
  }

  return Math.max(0, Math.min(100, Math.round((processedChunks / totalChunks) * 100)));
});

const runtimeProgressSummary = computed(() => {
  const details = runtimeDetails.value;
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

  return '';
});

const runtimeProviderText = computed(() => {
  const provider = runtimeDetails.value.provider;
  const model = runtimeDetails.value.model;
  if (typeof provider === 'string' && typeof model === 'string' && provider && model) {
    return `${provider} / ${model}`;
  }
  return '';
});

const handleErrorClose = () => {
  uploadError.value = null;
};

const handleRetry = () => {
  if (currentFile) {
    retryUpload(currentFile);
  }
};

const handleCancel = () => {
  void cancelUpload();
};

const logCommands = computed(() => {
  const commands: string[] = [];

  if (activeJobId.value) {
    commands.push(`.\\logs.bat -f -s go-api py-worker -k ${activeJobId.value}`);
  }

  if (activeDocumentId.value) {
    commands.push(`.\\logs.bat -f -s go-api py-worker -k ${activeDocumentId.value}`);
  }

  commands.push('.\\scripts\\aggregate-logs.ps1 -Service go-api,py-worker,frontend');
  return commands;
});

const formatPollingProgress = (percentage: number) => {
  return currentStage.value ? `${percentage}% · ${currentStage.value}` : `${percentage}%`;
};

const formatStageProgress = (percentage: number) => {
  return runtimeProgressSummary.value ? `${percentage}% · ${runtimeProgressSummary.value}` : `${percentage}%`;
};

const formatTime = (seconds: number): string => {
  if (seconds < 60) return `${Math.round(seconds)}秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟`;
  return `${Math.round(seconds / 3600)}小时`;
};
</script>

<style scoped>
.document-uploader {
  margin-bottom: 16px;
}

:deep(.el-upload-dragger) {
  border-radius: 12px;
  background-color: var(--bg-base);
  border: 2px dashed var(--border-color);
  transition: all var(--el-transition-duration);
}

:deep(.el-upload-dragger:hover) {
  border-color: var(--el-color-primary);
  background-color: var(--el-color-primary-light-9);
}

.progress-container {
  margin-top: 20px;
  padding: 20px;
  background-color: var(--bg-base);
  border: 1px solid var(--border-color-light);
  border-radius: 12px;
}

.steps-container {
  margin-top: 24px;
  margin-bottom: 8px;
  padding: 0 10px;
}

.stage-progress {
  margin-top: 10px;
}

.status-header {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  gap: 8px;
}

.status-icon {
  font-size: 18px;
}

.status-icon.loading {
  color: var(--el-color-primary);
  animation: rotate 1.5s linear infinite;
}

.status-icon.success {
  color: var(--el-color-success);
}

.status-icon.error {
  color: var(--el-color-danger);
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.status-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-regular);
  flex: 1;
}

.error-details {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.actions-row {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.runtime-meta {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background-color: var(--bg-surface-hover);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meta-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  font-size: 13px;
  line-height: 1.5;
}

.meta-label {
  flex: 0 0 72px;
  color: var(--text-secondary);
}

.meta-value {
  color: var(--text-regular);
  word-break: break-word;
}

.meta-code {
  font-size: 12px;
  color: var(--text-primary);
  background-color: var(--bg-base);
  border: 1px solid var(--border-color-light);
  border-radius: 6px;
  padding: 2px 6px;
  word-break: break-all;
}

.timeline-hint {
  margin-top: 12px;
}

.log-hints {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background-color: var(--bg-surface-hover);
  border: 1px dashed var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.log-hints-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.log-command {
  display: block;
  font-size: 12px;
  line-height: 1.5;
  padding: 6px 8px;
  border-radius: 8px;
  color: var(--text-primary);
  background-color: var(--bg-base);
  border: 1px solid var(--border-color-light);
  word-break: break-all;
}

.log-hints-note {
  font-size: 12px;
  color: var(--text-secondary);
}

:deep(.el-alert) {
  padding: 12px 16px;
}

:deep(.el-alert__title) {
  font-size: 14px;
}

:deep(.el-alert__description) {
  font-size: 13px;
  margin-top: 4px;
}

.time-remaining {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
}

:deep(.el-progress-bar) {
  border-radius: 4px;
}

:deep(.el-progress__text) {
  font-size: 12px !important;
}
</style>
