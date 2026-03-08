import request, { streamRequest, type StreamRequestOptions } from './request';

export function listKnowledgeBases() {
  return request.get('/kb/bases');
}

export function createKnowledgeBase(data: { name: string; description?: string; category?: string }) {
  return request.post('/kb/bases', data);
}

export function listKBDocuments(baseId: string) {
  return request.get(`/kb/bases/${baseId}/documents`);
}

export function getKBDocument(documentId: string) {
  return request.get(`/kb/documents/${documentId}`);
}

export function getKBDocumentEvents(documentId: string) {
  return request.get(`/kb/documents/${documentId}/events`);
}

export async function uploadKBDocuments(payload: {
  baseId: string;
  category?: string;
  files: File[];
}) {
  const form = new FormData();
  form.append('base_id', payload.baseId);
  form.append('category', payload.category || '');
  for (const file of payload.files) {
    form.append('files', file);
  }
  return request.post('/kb/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
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
