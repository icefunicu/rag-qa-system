import request from './request';

export interface ChatSession {
    id: string;
    title: string;
    created_at: string;
}

export function createSession(title?: string) {
    return request.post<ChatSession>('/chat/sessions', { title });
}

export function getSessions() {
    return request.get<{ items: ChatSession[]; count: number }>('/chat/sessions');
}

export function getSessionMessages(sessionId: string) {
    return request.get<{ items: any[]; count: number }>(`/chat/sessions/${sessionId}/messages`);
}

export interface ChatScope {
    mode: 'single' | 'multi';
    corpus_ids: string[];
    document_ids?: string[];
    allow_common_knowledge: boolean;
}

export interface SendMessageRequest {
    question: string;
    scope: ChatScope;
}

export function sendMessage(sessionId: string, data: SendMessageRequest) {
    return request.post<any>(`/chat/sessions/${sessionId}/messages`, data);
}

// SSE 流式响应类型定义
export interface SSEEvent {
    type: 'sentence' | 'citation' | 'done' | 'error';
    data?: {
        text?: string;
        evidence_type?: string;
        citation_ids?: string[];
        confidence?: number;
        citation_id?: string;
        file_name?: string;
        page_or_loc?: string;
        chunk_id?: string;
        snippet?: string;
    };
    message?: string;
}

export interface StreamResponse {
    content: string;
    references?: any[];
    done: boolean;
}

/**
 * SSE 流式查询（支持断线重连）
 * @param sessionId 会话 ID
 * @param data 请求数据
 * @param maxRetries 最大重试次数（默认 3 次）
 * @param initialRetryDelay 初始重试延迟（毫秒，默认 1000ms）
 * @returns AsyncGenerator<SSEEvent> 流式事件生成器
 */
export async function* sendMessageStream(
    sessionId: string,
    data: SendMessageRequest,
    maxRetries: number = 3,
    initialRetryDelay: number = 1000
): AsyncGenerator<SSEEvent, void, unknown> {
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';
    const url = `${baseUrl}/v1/chat/sessions/${sessionId}/messages/stream`;

    let retryCount = 0;
    let currentDelay = initialRetryDelay;

    while (retryCount <= maxRetries) {
        try {
            // 获取认证 token
            const token = localStorage.getItem('access_token');

            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': token ? `Bearer ${token}` : '',
                },
                body: JSON.stringify(data),
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({ error: '流式请求失败' }));
                throw new Error(error.error || `HTTP ${response.status}`);
            }

            const reader = response.body?.getReader();
            if (!reader) {
                throw new Error('ReadableStream not supported');
            }

            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    // 解码 chunk
                    buffer += decoder.decode(value, { stream: true });

                    // 解析 SSE 事件 (data: {...}\n\n)
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || ''; // 保留不完整的最后一行

                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (!trimmed || trimmed.startsWith(':')) continue; // 跳过注释行

                        if (trimmed.startsWith('data:')) {
                            const jsonStr = trimmed.slice(5).trim();
                            if (jsonStr === '[DONE]') {
                                yield { type: 'done' };
                                return;
                            }

                            try {
                                const event: SSEEvent = JSON.parse(jsonStr);
                                yield event;
                            } catch (e) {
                                console.error('Failed to parse SSE event:', jsonStr, e);
                            }
                        }
                    }
                }
            } finally {
                reader.releaseLock();
            }

            // 成功完成，退出重试循环
            yield { type: 'done' };
            return;

        } catch (error) {
            retryCount++;

            // 达到最大重试次数，抛出错误
            if (retryCount > maxRetries) {
                console.error(`SSE connection failed after ${maxRetries} retries:`, error);
                throw new Error(`网络连接不稳定，已重试${maxRetries}次，请稍后重试`);
            }

            // 计算下次重试延迟（指数退避）
            const retryDelay = currentDelay * Math.pow(2, retryCount - 1);
            console.warn(
                `SSE connection error (attempt ${retryCount}/${maxRetries}), retrying in ${retryDelay}ms...`,
                error
            );

            // 等待后重试
            yield {
                type: 'error',
                message: `网络连接不稳定，${retryDelay / 1000}秒后自动重连...`,
            };

            await new Promise(resolve => setTimeout(resolve, retryDelay));
            currentDelay *= 2; // 指数增长
        }
    }
}
