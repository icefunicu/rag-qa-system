import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import {
    getIngestJob,
    getUploadUrl,
    notifyUploadComplete,
    uploadToS3,
    cancelIngestJob,
    type IngestJob,
    type RuntimeProgress,
    type RuntimeProgressDetails,
} from '@/api/documents';
import {
    getDocumentEvents,
    type DocumentEventsResponse,
    type IngestEvent,
} from '@/api/events';

export interface UploadError {
    type: 'file_too_large' | 'timeout' | 'network_error' | 'server_error' | 'unknown';
    message: string;
    statusCode?: number;
    details?: string;
    errorCategory?: string;
    jobId?: string;
    documentId?: string;
}

export interface UploadProgress {
    percent: number;
    loaded: number;
    total: number;
    estimatedRemaining?: number;
}

interface BackendErrorPayload {
    message?: string;
    details?: string;
    statusCode?: number;
    code?: string;
}

interface ResetOptions {
    preserveError?: boolean;
    preserveStatus?: boolean;
}

const numberFormatter = new Intl.NumberFormat('zh-CN');

function extractBackendError(err: any): BackendErrorPayload {
    const payload = err?.response?.data ?? {};
    return {
        message: payload.error || payload.message || payload.detail || payload.error_message,
        details: payload.detail || payload.error_message || payload.message || payload.error,
        statusCode: err?.response?.status || err?.status,
        code: payload.code || err?.code,
    };
}

export function useUploader(corpusId: string, onStateChange?: () => void) {
    const isUploading = ref(false);
    const uploadProgress = ref(0);
    const isPolling = ref(false);
    const pollingProgress = ref(0);
    const currentStatus = ref('');
    const currentStageKey = ref('');
    const currentStage = ref('');
    const currentStageMessage = ref('');
    const lastUpdatedAtText = ref('');
    const activeJobId = ref('');
    const activeDocumentId = ref('');
    const uploadError = ref<UploadError | null>(null);
    const progressInfo = ref<UploadProgress | null>(null);
    const runtimeProgress = ref<RuntimeProgress | null>(null);
    const isCancelling = ref(false);

    const MAX_FILE_SIZE = 500 * 1024 * 1024;
    const MAX_RETRIES = 3;
    const RETRY_DELAY = 1000;

    let pollerId: number | null = null;
    let uploadStartTime = 0;
    let currentUploadUrl: { upload_url: string; storage_key: string } | null = null;
    let currentUploadAbortController: AbortController | null = null;

    function notifyStateChanged() {
        onStateChange?.();
    }

    function stopPolling() {
        if (pollerId !== null) {
            window.clearTimeout(pollerId);
            pollerId = null;
        }
    }

    function formatBytes(bytes: number): string {
        if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        const value = bytes / Math.pow(1024, exp);
        return `${value.toFixed(exp === 0 ? 0 : 2)} ${units[exp]}`;
    }

    function formatTime(seconds: number): string {
        if (!Number.isFinite(seconds) || seconds <= 0) return '0 秒';
        if (seconds < 60) return `${Math.round(seconds)} 秒`;
        if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
        return `${Math.round(seconds / 3600)} 小时`;
    }

    function formatDateTime(value?: string): string {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        return date.toLocaleString();
    }

    function normalizeStage(stage?: string): string {
        return (stage || '').trim().toLowerCase();
    }

    function toPositiveInt(value: unknown): number | null {
        if (typeof value !== 'number' || !Number.isFinite(value)) {
            return null;
        }
        if (value < 0) {
            return null;
        }
        return Math.round(value);
    }

    function getStageLabel(stage?: string): string {
        const labelMap: Record<string, string> = {
            queued: '等待 Worker 接单',
            downloading: '下载源文件',
            parsing: '解析文档',
            chunking: '文本切片',
            embedding: '生成向量',
            indexing: '写入向量索引',
            verifying: '校验索引一致性',
            done: '处理完成',
            failed: '处理失败',
            dead_letter: '处理失败并停止重试',
            cancelled: '已取消',
            running: '处理中',
            pending: '等待中',
        };
        return labelMap[normalizeStage(stage)] || (stage ? `状态：${stage}` : '');
    }

    function translateStageMessage(stage?: string, message?: string): string {
        const normalizedStage = normalizeStage(stage);
        const normalizedMessage = message?.trim();

        if (!normalizedMessage) {
            return '';
        }

        const embeddingMatch = normalizedMessage.match(/^embedding (\d+) chunks/i);
        if (embeddingMatch) {
            return `共 ${numberFormatter.format(Number(embeddingMatch[1]))} 个分片待向量化`;
        }

        const indexingMatch = normalizedMessage.match(/^writing (\d+) vectors to qdrant$/i);
        if (indexingMatch) {
            return `正在写入 ${numberFormatter.format(Number(indexingMatch[1]))} 条向量`;
        }

        if (normalizedStage === 'downloading' && normalizedMessage.toLowerCase().startsWith('downloading ')) {
            return '正在从对象存储拉取原始文件';
        }

        if (normalizedStage === 'parsing' && normalizedMessage.toLowerCase().startsWith('parsing ')) {
            return '正在提取文档正文';
        }

        if (normalizedStage === 'chunking' && normalizedMessage.toLowerCase() === 'splitting into chunks') {
            return '正在按切片策略拆分文本';
        }

        if (normalizedStage === 'verifying' && normalizedMessage.toLowerCase() === 'verifying index consistency') {
            return '正在校对向量库与数据库的一致性';
        }

        if (normalizedStage === 'queued' && normalizedMessage.toLowerCase() === 'job picked up by worker') {
            return 'Worker 已接单，准备开始处理';
        }

        if (normalizedStage === 'done' && normalizedMessage.toLowerCase() === 'ingest completed successfully') {
            return '文档已完成入库';
        }

        return normalizedMessage;
    }

    function buildRuntimeStageMessage(progress?: RuntimeProgress | null): string {
        if (!progress) {
            return '';
        }

        const stage = normalizeStage(progress.stage || progress.status);
        const details = (progress.details ?? {}) as RuntimeProgressDetails;
        const processedChunks = toPositiveInt(details.processed_chunks);
        const totalChunks = toPositiveInt(details.total_chunks);
        const processedBatches = toPositiveInt(details.processed_batches);
        const totalBatches = toPositiveInt(details.total_batches);
        const currentBatch = toPositiveInt(details.current_batch);
        const currentBatchSize = toPositiveInt(details.current_batch_size);
        const totalChunksGenerated = toPositiveInt(details.total_chunks_generated ?? details.total_chunks_count ?? details.total_chunks);
        const vectorCount = toPositiveInt(details.vector_count);
        const chunkCount = toPositiveInt(details.chunk_count);
        const expectedPointCount = toPositiveInt(details.expected_point_count);
        const qdrantPointCount = toPositiveInt(details.qdrant_point_count);
        const dbChunkCount = toPositiveInt(details.db_chunk_count);
        const segmentCount = toPositiveInt(details.segment_count);

        if (stage === 'embedding' && totalChunks && totalBatches) {
            const parts = [
                `已向量化 ${numberFormatter.format(processedChunks ?? 0)} / ${numberFormatter.format(totalChunks)} 个分片`,
                `已完成 ${numberFormatter.format(processedBatches ?? 0)} / ${numberFormatter.format(totalBatches)} 批`,
            ];
            if (currentBatch && currentBatch > (processedBatches ?? 0)) {
                const batchSizeText = currentBatchSize ? `（${numberFormatter.format(currentBatchSize)} 个分片）` : '';
                parts.push(`当前第 ${numberFormatter.format(currentBatch)} 批${batchSizeText}`);
            }
            return parts.join(' · ');
        }

        if (stage === 'chunking' && totalChunksGenerated !== null) {
            return `已生成 ${numberFormatter.format(totalChunksGenerated)} 个分片`;
        }

        if (stage === 'parsing' && segmentCount !== null) {
            return `已提取 ${numberFormatter.format(segmentCount)} 个文本段`;
        }

        if (stage === 'indexing' && vectorCount !== null) {
            const chunksText = chunkCount !== null ? ` / ${numberFormatter.format(chunkCount)} 条分片元数据` : '';
            return `正在写入 ${numberFormatter.format(vectorCount)} 条向量${chunksText}`;
        }

        if (stage === 'verifying' && expectedPointCount !== null) {
            if (qdrantPointCount !== null && dbChunkCount !== null) {
                return `校验 ${numberFormatter.format(qdrantPointCount)} 条向量 / ${numberFormatter.format(dbChunkCount)} 条分片，目标 ${numberFormatter.format(expectedPointCount)}`;
            }
            return `校验目标 ${numberFormatter.format(expectedPointCount)} 条向量`;
        }

        return translateStageMessage(progress.stage || progress.status, progress.message);
    }

    function getRuntimeProgress(job: IngestJob, eventResponse: DocumentEventsResponse | null): RuntimeProgress | null {
        return job.runtime_progress || eventResponse?.job_runtime || null;
    }

    function getLatestEvent(events?: IngestEvent[]): IngestEvent | null {
        if (!events || events.length === 0) {
            return null;
        }
        return events[events.length - 1] ?? null;
    }

    function applyPollingSnapshot(job: IngestJob, eventResponse: DocumentEventsResponse | null, documentId?: string) {
        const latestEvent = getLatestEvent(eventResponse?.items);
        const currentRuntime = getRuntimeProgress(job, eventResponse);
        const runtimeDocumentId = typeof currentRuntime?.details?.document_id === 'string' ? currentRuntime.details.document_id : '';

        runtimeProgress.value = currentRuntime;
        const stage = currentRuntime?.stage || latestEvent?.stage || latestEvent?.status || job.status;
        currentStageKey.value = normalizeStage(stage);
        currentStage.value = getStageLabel(stage);
        currentStageMessage.value = currentRuntime
            ? buildRuntimeStageMessage(currentRuntime)
            : translateStageMessage(stage, latestEvent?.message);
        lastUpdatedAtText.value = formatDateTime(
            currentRuntime?.updated_at || latestEvent?.created_at || eventResponse?.job_updated_at || job.updated_at,
        );
        activeJobId.value = currentRuntime?.job_id || job.id || eventResponse?.job_id || activeJobId.value;
        activeDocumentId.value = documentId || runtimeDocumentId || activeDocumentId.value;
    }

    function buildJobStatus(job: IngestJob): string {
        const progress = Math.max(job.progress || 0, 0);
        const stageText = currentStage.value || getStageLabel(job.status);
        const detailText = currentStageMessage.value;

        switch (job.status) {
            case 'queued':
                return detailText ? `${stageText} · ${detailText}` : '排队中，等待 Worker 处理...';
            case 'running':
                return detailText ? `${stageText} (${progress}%) · ${detailText}` : `${stageText} (${progress}%)`;
            case 'done':
                return '文档处理完成';
            case 'cancelled':
                return '文档处理已取消';
            case 'dead_letter':
            case 'failed':
                return '文档处理失败';
            default:
                return stageText || `状态：${job.status}`;
        }
    }

    function buildUserMessage(error: UploadError): string {
        if (!error.details || error.details === error.message) {
            return error.message;
        }
        return `${error.message}: ${error.details}`;
    }

    function classifyError(err: any, fileSize: number): UploadError {
        const backend = extractBackendError(err);
        const statusCode = backend.statusCode;
        const message = backend.message?.trim();
        const details = backend.details?.trim();
        const isOffline = typeof navigator !== 'undefined' && !navigator.onLine;

        if ((statusCode === 413 || backend.code === 'ERR_REQUEST_TOO_LARGE') && fileSize > 0) {
            return {
                type: 'file_too_large',
                message: '文件过大',
                statusCode: 413,
                details: `当前文件大小为 ${formatBytes(fileSize)}，超过服务端限制`,
            };
        }

        if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
            return {
                type: 'timeout',
                message: '请求超时',
                statusCode,
                details: details || '上传时间过长，请检查网络连接或稍后重试',
            };
        }

        if (err?.code === 'NETWORK_ERROR' || err?.message?.includes('Network Error') || isOffline) {
            return {
                type: 'network_error',
                message: '网络错误',
                statusCode,
                details: details || '请检查网络连接后重试',
            };
        }

        if (statusCode === 401) {
            return {
                type: 'server_error',
                message: '认证失败',
                statusCode,
                details: details || message || '登录已过期，请刷新页面后重试',
            };
        }

        if (statusCode === 403) {
            return {
                type: 'server_error',
                message: '权限不足',
                statusCode,
                details: details || message || '没有上传权限，请联系管理员',
            };
        }

        if (statusCode === 404) {
            return {
                type: 'server_error',
                message: '资源不存在',
                statusCode,
                details: details || message || '目标资源不存在，请刷新后重试',
            };
        }

        if (statusCode === 409) {
            return {
                type: 'server_error',
                message: '上传冲突',
                statusCode,
                details: details || message || '当前文档存在冲突，请刷新列表后重试',
            };
        }

        if (statusCode && statusCode >= 500) {
            return {
                type: 'server_error',
                message: '服务端错误',
                statusCode,
                details: details || message || `服务端返回错误 (${statusCode})，请稍后重试`,
            };
        }

        if (message || details) {
            return {
                type: 'server_error',
                message: message || '上传失败',
                statusCode,
                details: details && details !== message ? details : undefined,
            };
        }

        return {
            type: 'unknown',
            message: '上传失败',
            statusCode,
            details: err?.message || '未知错误',
        };
    }

    function logError(error: UploadError, fileName: string, fileSize: number) {
        console.group(`[Upload Error] ${new Date().toISOString()}`);
        console.error('文件:', fileName);
        console.error('文件大小:', formatBytes(fileSize));
        console.error('错误类型:', error.type);
        console.error('错误信息:', error.message);
        console.error('错误详情:', error.details);
        console.error('错误分类:', error.errorCategory);
        console.error('任务 ID:', error.jobId);
        console.groupEnd();
    }

    function calculateProgress(loaded: number, total: number): UploadProgress {
        const percent = total > 0 ? Math.round((loaded * 100) / total) : 0;
        const elapsedSeconds = Math.max((Date.now() - uploadStartTime) / 1000, 0.001);
        const bytesPerSecond = loaded / elapsedSeconds;
        const remainingBytes = Math.max(total - loaded, 0);
        const estimatedRemaining = bytesPerSecond > 0 ? remainingBytes / bytesPerSecond : undefined;

        return {
            percent,
            loaded,
            total,
            estimatedRemaining,
        };
    }

    function reset(options: ResetOptions = {}) {
        const wasUploading = isUploading.value;

        stopPolling();
        isUploading.value = false;
        isPolling.value = false;
        uploadProgress.value = 0;
        pollingProgress.value = 0;
        progressInfo.value = null;
        currentUploadUrl = null;

        if (!options.preserveStatus) {
            currentStatus.value = '';
            currentStageKey.value = '';
            currentStage.value = '';
            currentStageMessage.value = '';
            lastUpdatedAtText.value = '';
            activeJobId.value = '';
            activeDocumentId.value = '';
            runtimeProgress.value = null;
        }
        if (!options.preserveError) {
            uploadError.value = null;
        }
        if (currentUploadAbortController && wasUploading) {
            currentUploadAbortController.abort('reset');
        }
        currentUploadAbortController = null;
        isCancelling.value = false;
    }

    async function uploadWithRetry(file: File, maxRetries: number): Promise<void> {
        if (!currentUploadUrl) {
            throw new Error('upload url is missing');
        }

        let lastError: any = null;
        for (let attempt = 1; attempt <= maxRetries; attempt += 1) {
            if (isCancelling.value) {
                throw new Error('Cancelled by user');
            }

            currentStatus.value = `上传中... (尝试 ${attempt}/${maxRetries})`;
            currentUploadAbortController = new AbortController();

            try {
                await uploadToS3(
                    currentUploadUrl.upload_url,
                    file,
                    (loaded, total) => {
                        const progress = calculateProgress(loaded, total);
                        uploadProgress.value = progress.percent;
                        progressInfo.value = progress;
                    },
                    currentUploadAbortController,
                );
                currentUploadAbortController = null;
                return;
            } catch (err: any) {
                currentUploadAbortController = null;
                if (err?.code === 'ERR_CANCELED' || err?.message === 'Cancelled by user') {
                    throw err;
                }

                lastError = err;
                if (attempt < maxRetries) {
                    console.warn(`上传失败，${RETRY_DELAY / 1000} 秒后重试 (${attempt}/${maxRetries})`, err);
                    await new Promise<void>(resolve => window.setTimeout(resolve, RETRY_DELAY));
                }
            }
        }

        throw lastError;
    }

    function buildJobFailure(job: IngestJob, documentId?: string): UploadError {
        const isDeadLetter = job.status === 'dead_letter';
        return {
            type: 'server_error',
            message: isDeadLetter ? '文档处理失败，已停止自动重试' : '文档处理失败',
            details: job.error_message || '请打开详情查看处理时间线或查看错误日志',
            errorCategory: job.error_category,
            jobId: job.id,
            documentId,
        };
    }

    function scheduleNextPoll(jobId: string, documentId?: string, delay = 2000) {
        stopPolling();
        pollerId = window.setTimeout(() => {
            void pollJob(jobId, documentId);
        }, delay);
    }

    async function pollJob(jobId: string, documentId?: string) {
        try {
            const [job, eventResponse] = await Promise.all([
                getIngestJob(jobId),
                documentId ? getDocumentEvents(documentId).catch(() => null) : Promise.resolve(null),
            ]);

            applyPollingSnapshot(job, eventResponse, documentId);
            pollingProgress.value = Math.max(job.runtime_progress?.overall_progress || job.progress || 0, 0);

            if (job.status === 'done') {
                currentStatus.value = '文档处理完成';
                ElMessage.success('文档处理完成');
                reset();
                notifyStateChanged();
                return;
            }

            if (job.status === 'cancelled') {
                currentStatus.value = '文档处理已取消';
                ElMessage.info('文档处理已取消');
                reset();
                notifyStateChanged();
                return;
            }

            if (job.status === 'failed' || job.status === 'dead_letter') {
                const error = buildJobFailure(job, documentId);
                uploadError.value = error;
                currentStatus.value = error.message;
                ElMessage({
                    message: buildUserMessage(error),
                    type: 'error',
                    duration: 8000,
                    showClose: true,
                });
                reset({ preserveError: true, preserveStatus: true });
                notifyStateChanged();
                return;
            }

            currentStatus.value = buildJobStatus(job);
            scheduleNextPoll(jobId, documentId);
        } catch (err: any) {
            const error = classifyError(err, 0);
            error.message = '获取任务状态失败';
            error.details = error.details || '请稍后刷新列表查看状态';
            uploadError.value = error;
            currentStatus.value = error.message;
            ElMessage({
                message: buildUserMessage(error),
                type: 'error',
                duration: 6000,
                showClose: true,
            });
            reset({ preserveError: true, preserveStatus: true });
            notifyStateChanged();
        }
    }

    function startPolling(jobId: string, documentId?: string) {
        stopPolling();
        isUploading.value = false;
        isPolling.value = true;
        pollingProgress.value = 0;
        activeJobId.value = jobId;
        activeDocumentId.value = documentId || '';
        currentStageKey.value = 'queued';
        currentStage.value = getStageLabel('queued');
        currentStageMessage.value = '';
        lastUpdatedAtText.value = '';
        runtimeProgress.value = null;
        currentStatus.value = '任务已入队，等待 Worker 开始处理...';
        void pollJob(jobId, documentId);
    }

    async function uploadFile(file: File) {
        reset();

        if (file.size > MAX_FILE_SIZE) {
            const error: UploadError = {
                type: 'file_too_large',
                message: '文件超过限制',
                statusCode: 413,
                details: `文件大小 ${formatBytes(file.size)} 超过最大限制 ${formatBytes(MAX_FILE_SIZE)}`,
            };
            uploadError.value = error;
            currentStatus.value = error.message;
            logError(error, file.name, file.size);
            ElMessage.error(buildUserMessage(error));
            reset({ preserveError: true, preserveStatus: true });
            return;
        }

        try {
            isUploading.value = true;
            uploadProgress.value = 0;
            uploadStartTime = Date.now();
            currentStatus.value = '申请签名...';

            const ext = file.name.split('.').pop()?.toLowerCase() || 'txt';
            const uploadUrl = await getUploadUrl({
                corpus_id: corpusId,
                file_name: file.name,
                file_type: ext,
                size_bytes: file.size,
            });
            currentUploadUrl = uploadUrl;

            currentStatus.value = '上传中...';
            await uploadWithRetry(file, MAX_RETRIES);

            currentStatus.value = '通知网关入库...';
            const notifyRes = await notifyUploadComplete({
                corpus_id: corpusId,
                storage_key: uploadUrl.storage_key,
                file_name: file.name,
                file_type: ext,
                size_bytes: file.size,
            });

            notifyStateChanged();

            if (notifyRes.job_id) {
                startPolling(notifyRes.job_id, notifyRes.document_id);
                return;
            }

            ElMessage.success('上传成功');
            reset();
        } catch (err: any) {
            if (err?.code === 'ERR_CANCELED' || err?.message === 'Cancelled by user') {
                ElMessage.info('已取消上传');
                reset();
                return;
            }

            const error = classifyError(err, file.size);
            uploadError.value = error;
            currentStatus.value = error.message;
            logError(error, file.name, file.size);
            ElMessage({
                message: buildUserMessage(error),
                type: 'error',
                duration: 8000,
                showClose: true,
            });
            reset({ preserveError: true, preserveStatus: true });
        }
    }

    function getProgressText(): string {
        if (!progressInfo.value) {
            return `${uploadProgress.value}%`;
        }

        const { loaded, total, estimatedRemaining } = progressInfo.value;
        let text = `${formatBytes(loaded)} / ${formatBytes(total)} (${uploadProgress.value}%)`;
        if (estimatedRemaining !== undefined) {
            text += ` · 剩余 ${formatTime(estimatedRemaining)}`;
        }
        return text;
    }

    function retryUpload(file: File) {
        void uploadFile(file);
    }

    async function cancelUpload() {
        if (!isUploading.value && !isPolling.value) {
            return;
        }

        isCancelling.value = true;
        currentStatus.value = '正在取消...';

        const jobId = activeJobId.value;
        const wasUploading = isUploading.value;
        const wasPolling = isPolling.value;

        try {
            if (wasUploading && currentUploadAbortController) {
                currentUploadAbortController.abort('Cancelled by user');
                return;
            }

            if (wasPolling && jobId) {
                stopPolling();
                await cancelIngestJob(jobId);
                ElMessage.info('已取消文档处理任务');
                reset();
                notifyStateChanged();
            }
        } catch (err: any) {
            const error = classifyError(err, 0);
            error.message = '取消处理失败';
            error.details = error.details || '请稍后重试';
            uploadError.value = error;
            currentStatus.value = error.message;
            ElMessage.error(buildUserMessage(error));
            reset({ preserveError: true, preserveStatus: true });
            if (jobId) {
                notifyStateChanged();
            }
        } finally {
            if (wasUploading && !wasPolling && !uploadError.value) {
                isCancelling.value = false;
            }
        }
    }

    return {
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
    };
}
