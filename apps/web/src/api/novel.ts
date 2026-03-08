import request, { streamRequest, type StreamRequestOptions } from './request';

export function listNovelLibraries() {
  return request.get('/novel/libraries');
}

export function createNovelLibrary(data: { name: string; description?: string }) {
  return request.post('/novel/libraries', data);
}

export function listNovelDocuments(libraryId: string) {
  return request.get(`/novel/libraries/${libraryId}/documents`);
}

export function getNovelDocument(documentId: string) {
  return request.get(`/novel/documents/${documentId}`);
}

export function getNovelDocumentEvents(documentId: string) {
  return request.get(`/novel/documents/${documentId}/events`);
}

export async function uploadNovelDocument(payload: {
  libraryId: string;
  title: string;
  volumeLabel?: string;
  spoilerAck?: boolean;
  file: File;
}) {
  const form = new FormData();
  form.append('library_id', payload.libraryId);
  form.append('title', payload.title);
  form.append('volume_label', payload.volumeLabel || '');
  form.append('spoiler_ack', String(Boolean(payload.spoilerAck)));
  form.append('file', payload.file);
  return request.post('/novel/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
}

export function queryNovel(data: {
  library_id: string;
  question: string;
  document_ids?: string[];
  debug?: boolean;
}) {
  return request.post('/novel/query', data);
}

export function streamNovelQuery(data: {
  library_id: string;
  question: string;
  document_ids?: string[];
  debug?: boolean;
}, options?: StreamRequestOptions) {
  return streamRequest('/api/v1/novel/query/stream', data, options);
}
