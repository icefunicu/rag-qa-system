import request from './request';
import type { RuntimeProgress } from './documents';

const silentErrorConfig = { skipErrorHandler: true } as any;

export interface IngestEvent {
    id: string;
    document_id: string;
    job_id: string;
    status: string;
    stage?: string;
    message?: string;
    details?: Record<string, unknown>;
    created_at: string;
}

export interface DocumentEventsResponse {
    items: IngestEvent[];
    count: number;
    job_id?: string;
    job_status?: string;
    job_progress?: number;
    job_error_message?: string;
    job_error_category?: string;
    job_updated_at?: string;
    job_runtime?: RuntimeProgress | null;
}

export const getDocumentEvents = (documentId: string, limit = 50) => {
    return request({
        url: `/documents/${documentId}/events`,
        method: 'get',
        params: { limit },
        ...silentErrorConfig
    } as any) as Promise<DocumentEventsResponse>;
};
