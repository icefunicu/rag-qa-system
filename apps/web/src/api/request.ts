import axios from 'axios';
import { ElMessage } from 'element-plus';
import router from '@/router';
import { useAuthStore } from '@/store/auth';

export interface RequestConfig {
  skipErrorHandler?: boolean;
}

export interface StreamEvent<T = unknown> {
  event: string;
  data: T;
  rawData: string;
}

export interface StreamRequestOptions {
  signal?: AbortSignal;
  onEvent?: (event: StreamEvent) => void;
  headers?: Record<string, string>;
}

export interface HandledRequestError extends Error {
  handledByRequestLayer: true;
  status?: number;
  code?: string;
}

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 60000
});

function getBackendError(responseData: unknown): string | undefined {
  if (!responseData || typeof responseData !== 'object') {
    return undefined;
  }

  const payload = responseData as Record<string, unknown>;
  const detail = payload.detail;

  if (typeof payload.error === 'string') {
    return payload.error;
  }
  if (typeof payload.message === 'string') {
    return payload.message;
  }
  if (typeof detail === 'string') {
    return detail;
  }

  return undefined;
}

function getBackendErrorCode(responseData: unknown): string | undefined {
  if (!responseData || typeof responseData !== 'object') {
    return undefined;
  }

  const payload = responseData as Record<string, unknown>;
  const candidates = [
    payload.code,
    payload.error_code,
    payload.error,
    payload.detail,
    payload.message
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.toLowerCase().includes('too_many_inflight_requests')) {
      return 'too_many_inflight_requests';
    }
  }

  return undefined;
}

function handleUnauthorized() {
  const authStore = useAuthStore();
  authStore.logout();
  router.push('/login');
}

function resolveErrorMessage(status?: number, backendError?: string, responseData?: unknown): string {
  const backendCode = getBackendErrorCode(responseData);

  if (status === 401) {
    return '登录已失效，请重新登录。';
  }
  if (status === 400) {
    return String(backendError || '请求参数错误，请检查输入后重试。');
  }
  if (status === 403) {
    return String(backendError || '当前操作无权限执行。');
  }
  if (status === 404) {
    return String(backendError || '请求的资源不存在，请刷新页面后重试。');
  }
  if (status === 405) {
    return '请求方法不被支持，请检查前后端接口配置。';
  }
  if (status === 409) {
    return String(backendError || '请求发生冲突，可能是重复提交，请稍后重试。');
  }
  if (status === 429 && backendCode === 'too_many_inflight_requests') {
    return '当前排队中的问答请求过多，请等待上一条回答完成后再试。';
  }
  if (status === 429) {
    return String(backendError || '当前请求过于频繁，请稍后再试。');
  }
  if (status === 503) {
    return '服务暂时不可用，请稍后重试。';
  }
  if (backendError) {
    return backendError;
  }

  return '请求失败，请稍后重试。';
}

function notifyRequestError(status?: number, responseData?: unknown) {
  const backendError = getBackendError(responseData);
  if (status === 401) {
    handleUnauthorized();
  }
  ElMessage.error(resolveErrorMessage(status, backendError, responseData));
}

function createHandledRequestError(message: string, status?: number, code?: string): HandledRequestError {
  const error = new Error(message) as HandledRequestError;
  error.name = 'HandledRequestError';
  error.handledByRequestLayer = true;
  error.status = status;
  error.code = code;
  return error;
}

request.interceptors.request.use(
  (config) => {
    const authStore = useAuthStore();
    if (authStore.token) {
      config.headers.Authorization = `Bearer ${authStore.token}`;
    }
    return config;
  },
  error => Promise.reject(error)
);

request.interceptors.response.use(
  response => response.data,
  (error) => {
    if ((error.config as RequestConfig | undefined)?.skipErrorHandler) {
      return Promise.reject(error);
    }
    notifyRequestError(error.response?.status, error.response?.data);
    return Promise.reject(error);
  }
);

async function parseErrorPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') || '';
  try {
    if (contentType.includes('application/json')) {
      return await response.json();
    }
    const text = await response.text();
    return text ? { message: text } : null;
  } catch {
    return null;
  }
}

function emitStreamChunk(chunk: string, onEvent: (event: StreamEvent) => void): void {
  const lines = chunk
    .replace(/\r/g, '')
    .split('\n')
    .filter(Boolean);

  let eventName = 'message';
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  const rawData = dataLines.join('\n');
  let data: unknown = rawData;
  if (rawData) {
    try {
      data = JSON.parse(rawData);
    } catch {
      data = rawData;
    }
  }
  onEvent({ event: eventName, data, rawData });
}

export function createIdempotencyKey(scope = 'req'): string {
  const randomPart = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${scope}-${randomPart}`;
}

export async function streamRequest(path: string, body: unknown, options: StreamRequestOptions = {}): Promise<void> {
  const authStore = useAuthStore();
  const headers = new Headers({
    'Content-Type': 'application/json'
  });
  if (authStore.token) {
    headers.set('Authorization', `Bearer ${authStore.token}`);
  }
  Object.entries(options.headers || {}).forEach(([key, value]) => {
    if (value) {
      headers.set(key, value);
    }
  });

  const response = await fetch(path, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: options.signal
  });

  if (!response.ok) {
    const payload = await parseErrorPayload(response);
    const backendError = getBackendError(payload);
    const backendCode = getBackendErrorCode(payload);
    notifyRequestError(response.status, payload);
    throw createHandledRequestError(
      resolveErrorMessage(response.status, backendError, payload),
      response.status,
      backendCode
    );
  }

  if (!response.body || !options.onEvent) {
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let separatorIndex = buffer.indexOf('\n\n');
    while (separatorIndex >= 0) {
      const chunk = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      if (chunk.trim()) {
        emitStreamChunk(chunk, options.onEvent);
      }
      separatorIndex = buffer.indexOf('\n\n');
    }

    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    emitStreamChunk(buffer, options.onEvent);
  }
}

export function isAbortRequestError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export function isHandledRequestError(error: unknown): error is HandledRequestError {
  return error instanceof Error && (error as Partial<HandledRequestError>).handledByRequestLayer === true;
}

export default request;
