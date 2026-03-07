import request from '@/api/request';

export interface AIChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface AIChatPayload {
  messages: AIChatMessage[];
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
}

export function getAIConfig() {
  return request.get('/ai/config');
}

export function sendAIChat(payload: AIChatPayload) {
  return request.post('/ai/chat', payload);
}
