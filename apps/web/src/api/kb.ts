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

export function getKBDocumentVersions(documentId: string) {
  return request.get(`/kb/documents/${documentId}/versions`);
}

export function getKBDocumentVersionContent(documentId: string, versionId: string, includeDisabled: boolean = true) {
  return request.get(`/kb/documents/${documentId}/versions/${versionId}/content`, {
    params: { include_disabled: includeDisabled }
  });
}

export function getKBDocumentVersionDiff(documentId: string, versionId: string, compareToDocumentId?: string) {
  return request.get(`/kb/documents/${documentId}/versions/${versionId}/diff`, {
    params: { compare_to_document_id: compareToDocumentId || '' }
  });
}

export function updateKBDocument(documentId: string, data: {
  file_name?: string;
  category?: string;
  version_family_key?: string;
  version_label?: string;
  version_number?: number;
  version_status?: string;
  is_current_version?: boolean;
  effective_from?: string | null;
  effective_to?: string | null;
  supersedes_document_id?: string | null;
}) {
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
  version_family_key?: string;
  version_label?: string;
  version_number?: number;
  version_status?: string;
  is_current_version?: boolean;
  effective_from?: string | null;
  effective_to?: string | null;
  supersedes_document_id?: string | null;
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

export function syncLocalDirectory(data: {
  base_id: string;
  source_path: string;
  category?: string;
  recursive?: boolean;
  delete_missing?: boolean;
  dry_run?: boolean;
  max_files?: number;
}) {
  return request.post('/kb/connectors/local-directory/sync', data);
}

export function syncNotion(data: {
  base_id: string;
  page_ids: string[];
  category?: string;
  delete_missing?: boolean;
  dry_run?: boolean;
  max_pages?: number;
}) {
  return request.post('/kb/connectors/notion/sync', data);
}

// ---- Chunk Management ----
export function getKBChunks(documentId: string, includeDisabled: boolean = false) {
  return request.get(`/kb/documents/${documentId}/chunks`, { params: { include_disabled: includeDisabled } });
}

export function updateKBChunk(chunkId: string, data: { text_content?: string, disabled?: boolean, disabled_reason?: string, manual_note?: string }) {
  return request.patch(`/kb/chunks/${chunkId}`, data);
}

export function splitKBChunk(chunkId: string, parts: string[]) {
  return request.post(`/kb/chunks/${chunkId}/split`, { parts });
}

export function mergeKBChunks(chunkIds: string[], separator: string = '\n\n') {
  return request.post(`/kb/chunks/merge`, { chunk_ids: chunkIds, separator });
}

// ---- Retrieval Debugger ----
export function retrieveDebugKB(data: { query: string; base_id?: string; document_ids?: string[]; top_k?: number; [key: string]: any }) {
  return request.post('/kb/retrieve/debug', data);
}

// ---- Connectors ----
export function listConnectors(baseId?: string) {
  return request.get('/kb/connectors', { params: { base_id: baseId } });
}

export function createConnector(data: { base_id: string; name: string; connector_type: string; config: any; schedule?: any }) {
  return request.post('/kb/connectors', data);
}

export function getConnector(connectorId: string) {
  return request.get(`/kb/connectors/${connectorId}`);
}

export function updateConnector(connectorId: string, data: any) {
  return request.patch(`/kb/connectors/${connectorId}`, data);
}

export function deleteConnector(connectorId: string) {
  return request.delete(`/kb/connectors/${connectorId}`);
}

export function getConnectorRuns(connectorId: string) {
  return request.get(`/kb/connectors/${connectorId}/runs`);
}

export function syncConnector(connectorId: string, dryRun: boolean = false) {
  return request.post(`/kb/connectors/${connectorId}/sync`, { dry_run: dryRun });
}

export function runDueConnectors(limit: number = 10, dryRun: boolean = false) {
  return request.post('/kb/connectors/run-due', { limit, dry_run: dryRun });
}
