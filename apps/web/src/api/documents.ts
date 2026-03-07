import request from './request';
import axios from 'axios';

const silentErrorConfig = { skipErrorHandler: true } as any;

export interface CorpusDocument {
    id: string;
    corpus_id: string;
    file_name: string;
    file_type: 'txt' | 'pdf' | 'docx';
    size_bytes: number;
    status: 'uploaded' | 'indexing' | 'ready' | 'failed' | 'cancelled';
    created_at: string;
    created_by?: string;
}

export interface UploadUrlRequest {
    corpus_id: string;
    file_name: string;
    file_type: string;
    size_bytes: number;
}

export interface UploadUrlResponse {
    upload_url: string;
    storage_key: string;
}

export interface IngestJob {
    id: string;
    document_id?: string;
    status: 'queued' | 'running' | 'done' | 'failed' | 'dead_letter' | 'cancelled';
    progress: number;
    error_message?: string;
    error_category?: string;
    created_at?: string;
    updated_at?: string;
    runtime_progress?: RuntimeProgress | null;
}

export interface RuntimeProgressDetails {
    processed_chunks?: number;
    total_chunks?: number;
    processed_batches?: number;
    total_batches?: number;
    current_batch?: number;
    current_batch_size?: number;
    stage_progress_percent?: number;
    total_chunks_generated?: number;
    total_chunks_count?: number;
    vector_count?: number;
    chunk_count?: number;
    expected_point_count?: number;
    qdrant_point_count?: number;
    db_chunk_count?: number;
    segment_count?: number;
    batch_size?: number;
    batch_max_chars?: number;
    provider?: string;
    model?: string;
    file_type?: string;
    storage_key?: string;
    error_category?: string;
    retry_count?: number;
    max_retries?: number;
    document_id?: string;
    embedding_dim?: number;
    [key: string]: unknown;
}

export interface RuntimeProgress {
    job_id: string;
    status: string;
    overall_progress: number;
    stage: string;
    message?: string;
    updated_at?: string;
    details?: RuntimeProgressDetails;
}

export interface DocumentPreviewResponse {
    document: CorpusDocument;
    preview_mode: 'text' | 'partial' | 'url';
    editable: boolean;
    content_type: string;
    size_bytes?: number;
    text?: string;
    view_url?: string;
    max_inline_bytes?: number;
    max_partial_bytes?: number;
    expires_in_seconds?: number;
    warning?: string;
    detected_encoding?: string;
    truncated?: boolean;
}

export interface UpdateDocumentContentResponse {
    document_id: string;
    job_id: string;
    status: 'queued';
    message: string;
}

export async function listCorpusDocuments(corpusId: string): Promise<{ items: CorpusDocument[]; count: number }> {
    const res = await request.get(`/corpora/${corpusId}/documents`);
    return res as unknown as { items: CorpusDocument[]; count: number };
}

export async function getDocumentDetail(documentId: string): Promise<CorpusDocument> {
    const res = await request.get(`/documents/${documentId}`);
    return res as unknown as CorpusDocument;
}

export async function getDocumentPreview(documentId: string): Promise<DocumentPreviewResponse> {
    const res = await request.get(`/documents/${documentId}/preview`);
    return res as unknown as DocumentPreviewResponse;
}

export async function updateDocumentContent(documentId: string, content: string): Promise<UpdateDocumentContentResponse> {
    const res = await request.put(`/documents/${documentId}/content`, { content });
    return res as unknown as UpdateDocumentContentResponse;
}

export async function getUploadUrl(data: UploadUrlRequest): Promise<UploadUrlResponse> {
    const res = await request.post('/documents/upload-url', data, silentErrorConfig);
    return res as unknown as UploadUrlResponse;
}

export function uploadToS3(
    url: string,
    file: File,
    onProgress?: (loaded: number, total: number) => void,
    abortController?: AbortController
) {
    return axios.put(url, file, {
        headers: {
            'Content-Type': file.type || 'application/octet-stream'
        },
        signal: abortController?.signal,
        onUploadProgress: (progressEvent: any) => {
            if (progressEvent.total && onProgress) {
                onProgress(progressEvent.loaded, progressEvent.total);
            }
        }
    });
}

export async function notifyUploadComplete(data: {
    corpus_id: string;
    storage_key: string;
    file_name: string;
    file_type: string;
    size_bytes: number;
}): Promise<{ job_id: string; document_id: string }> {
    const res = await request.post('/documents/upload', data, silentErrorConfig);
    return res as unknown as { job_id: string; document_id: string };
}

export async function getIngestJob(job_id: string): Promise<IngestJob> {
    const res = await request.get(`/ingest-jobs/${job_id}`, silentErrorConfig);
    return res as unknown as IngestJob;
}

export function deleteDocument(documentId: string) {
    return request.delete(`/documents/${documentId}`);
}

export function cancelIngestJob(jobId: string) {
    return request.post(`/ingest-jobs/${jobId}/cancel`);
}

export function batchDeleteDocuments(documentIds: string[]) {
    return request.post('/documents/batch-delete', { document_ids: documentIds });
}

export async function getAdminLogs(params?: { service?: string; keyword?: string; tail?: number }): Promise<{ lines: string[] }> {
    const res = await request.get('/admin/logs', { params });
    return res as unknown as { lines: string[] };
}
