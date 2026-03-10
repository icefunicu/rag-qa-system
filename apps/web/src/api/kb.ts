import request, { createIdempotencyKey, streamRequest, type StreamRequestOptions } from './request';

export interface UploadPartPayload {
  part_number: number;
  etag: string;
  size_bytes: number;
}

export function listKnowledgeBases() {
  return request.get('/kb/bases');
}

export function getKnowledgeBase(baseId: string) {
  return request.get(`/kb/bases/${baseId}`);
}

export function createKnowledgeBase(data: { name: string; description?: string; category?: string }) {
  return request.post('/kb/bases', data);
}

export function updateKnowledgeBase(baseId: string, data: { name?: string; description?: string; category?: string }) {
  return request.patch(`/kb/bases/${baseId}`, data);
}

export function deleteKnowledgeBase(baseId: string) {
  return request.delete(`/kb/bases/${baseId}`);
}

export function listKBDocuments(baseId: string) {
  return request.get(`/kb/bases/${baseId}/documents`);
}

export function getKBDocument(documentId: string) {
  return request.get(`/kb/documents/${documentId}`);
}

export function updateKBDocument(documentId: string, data: { file_name?: string; category?: string }) {
  return request.patch(`/kb/documents/${documentId}`, data);
}

export function deleteKBDocument(documentId: string) {
  return request.delete(`/kb/documents/${documentId}`);
}

export function getKBDocumentEvents(documentId: string) {
  return request.get(`/kb/documents/${documentId}/events`);
}

export function getKBDocumentVisualAssets(documentId: string) {
  return request.get(`/kb/documents/${documentId}/visual-assets`);
}

export function createKBUpload(data: {
  base_id: string;
  file_name: string;
  file_type: string;
  size_bytes: number;
  category?: string;
}, options: { idempotencyKey?: string } = {}) {
  return request.post('/kb/uploads', data, {
    headers: {
      'Idempotency-Key': options.idempotencyKey || createIdempotencyKey('kb-upload-create')
    }
  });
}

export function getKBUpload(uploadId: string) {
  return request.get(`/kb/uploads/${uploadId}`);
}

export function presignKBUploadParts(uploadId: string, partNumbers: number[]) {
  return request.post(`/kb/uploads/${uploadId}/parts/presign`, {
    part_numbers: partNumbers
  });
}

export function completeKBUpload(
  uploadId: string,
  parts: UploadPartPayload[],
  contentHash = '',
  options: { idempotencyKey?: string } = {}
) {
  return request.post(`/kb/uploads/${uploadId}/complete`, {
    parts,
    content_hash: contentHash
  }, {
    headers: {
      'Idempotency-Key': options.idempotencyKey || createIdempotencyKey('kb-upload-complete')
    }
  });
}

export function getKBIngestJob(jobId: string) {
  return request.get(`/kb/ingest-jobs/${jobId}`);
}

export function retryKBIngestJob(jobId: string) {
  return request.post(`/kb/ingest-jobs/${jobId}/retry`);
}

export function queryKB(data: {
  base_id: string;
  question: string;
  document_ids?: string[];
  debug?: boolean;
}) {
  return request.post('/kb/query', data);
}

export function streamKBQuery(data: {
  base_id: string;
  question: string;
  document_ids?: string[];
  debug?: boolean;
}, options?: StreamRequestOptions) {
  return streamRequest('/api/v1/kb/query/stream', data, options);
}
