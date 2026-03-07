<template>
  <el-container class="chat-view">
    <el-aside width="260px" class="chat-sidebar">
      <ChatSidebar @select-session="handleSessionSelect" />
    </el-aside>
    <el-main class="chat-main">
      <div v-if="!currentSessionId" class="empty-state">
        <el-empty description="请选择或新建一个会话开始对话" />
      </div>
      <div v-else class="chat-box">
        <ChatMessageList :messages="messages" @retry="handleRetry" @inspect="handleInspect" />
        <ChatInputArea @send="handleSend" :disabled="loading" />
      </div>

      <!-- Answer Inspector Drawer -->
      <AnswerInspector 
        v-model:visible="inspectorVisible"
        :answer-data="currentInspectData"
      />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import ChatSidebar from '@/components/ChatSidebar.vue';
import ChatMessageList from '@/components/ChatMessageList.vue';
import ChatInputArea from '@/components/ChatInputArea.vue';
import AnswerInspector from '@/components/AnswerInspector.vue';
import { sendMessage, sendMessageStream, getSessionMessages, type ChatScope, type SSEEvent } from '@/api/chat';

const currentSessionId = ref<string>('');
const messages = ref<any[]>([]);
const loading = ref(false);
const useStreaming = ref(true); // 是否启用流式响应

const inspectorVisible = ref(false);
const currentInspectData = ref<any>(null);

// 错误类型常量
const ErrorType = {
  NETWORK: 'NETWORK_ERROR',
  TIMEOUT: 'TIMEOUT_ERROR',
  RAG_SERVICE: 'RAG_SERVICE_ERROR',
  LLM_TIMEOUT: 'LLM_TIMEOUT_ERROR',
  RETRIEVAL_FAILED: 'RETRIEVAL_FAILED_ERROR',
  NO_EVIDENCE: 'NO_EVIDENCE_ERROR',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  UNAUTHORIZED: 'UNAUTHORIZED_ERROR',
  NOT_FOUND: 'NOT_FOUND_ERROR',
  UNKNOWN: 'UNKNOWN_ERROR',
} as const;

type ErrorType = typeof ErrorType[keyof typeof ErrorType];

// 错误配置
interface ErrorConfig {
  title: string;
  message: string;
  retryable: boolean;
  suggestion?: string;
}

const errorConfig: Record<ErrorType, ErrorConfig> = {
  [ErrorType.NETWORK]: {
    title: '网络连接失败',
    message: '网络连接异常，请检查网络后重试。',
    retryable: true,
    suggestion: '请检查网络连接或刷新页面',
  },
  [ErrorType.TIMEOUT]: {
    title: '请求超时',
    message: '请求超时，服务器响应时间过长。',
    retryable: true,
    suggestion: '网络较慢，建议重试或简化问题',
  },
  [ErrorType.RAG_SERVICE]: {
    title: '检索服务异常',
    message: 'RAG 检索服务暂时不可用，请稍后重试。',
    retryable: true,
    suggestion: '服务可能正在维护，建议稍后重试',
  },
  [ErrorType.LLM_TIMEOUT]: {
    title: 'AI 响应超时',
    message: 'AI 生成答案超时，问题可能过于复杂。',
    retryable: true,
    suggestion: '尝试简化问题或分多次提问',
  },
  [ErrorType.RETRIEVAL_FAILED]: {
    title: '检索失败',
    message: '未能检索到相关文档，请调整检索范围。',
    retryable: true,
    suggestion: '尝试扩大检索范围或更换关键词',
  },
  [ErrorType.NO_EVIDENCE]: {
    title: '未找到依据',
    message: '未在文档中找到相关依据，将基于常识回答。',
    retryable: false,
    suggestion: '答案可能不够准确，建议核实信息',
  },
  [ErrorType.VALIDATION_ERROR]: {
    title: '输入错误',
    message: '输入内容不符合要求，请检查后重试。',
    retryable: false,
    suggestion: '请检查问题格式和检索范围',
  },
  [ErrorType.UNAUTHORIZED]: {
    title: '未授权访问',
    message: '登录已失效，请重新登录。',
    retryable: false,
    suggestion: '请重新登录后再试',
  },
  [ErrorType.NOT_FOUND]: {
    title: '资源不存在',
    message: '请求的资源不存在或已被删除。',
    retryable: false,
    suggestion: '请刷新页面或检查资源 ID',
  },
  [ErrorType.UNKNOWN]: {
    title: '请求失败',
    message: '发生未知错误，请稍后重试。',
    retryable: true,
  },
};

const buildChatErrorMessage = (error: any): { title: string; message: string; retryable: boolean; suggestion?: string } => {
  const status = error?.response?.status;
  const code = error?.response?.data?.code;
  const detail = error?.response?.data?.error || error?.response?.data?.message || error?.message;

  console.error('Chat error:', error); // 详细错误日志

  // 网络错误
  if (!error.response && error.message?.includes('network')) {
    return errorConfig[ErrorType.NETWORK];
  }

  // 超时错误
  if (error.code === 'ECONNABORTED' || error.message?.includes('timeout') || status === 504) {
    return errorConfig[ErrorType.TIMEOUT];
  }

  // 根据错误码细化错误类型
  if (code) {
    switch (code) {
      case 'VALIDATION_ERROR':
        return {
          ...errorConfig[ErrorType.VALIDATION_ERROR],
          message: detail || errorConfig[ErrorType.VALIDATION_ERROR].message,
        };
      case 'LLM_ERROR':
      case 'LLM_TIMEOUT':
        return errorConfig[ErrorType.LLM_TIMEOUT];
      case 'RETRIEVAL_ERROR':
        return errorConfig[ErrorType.RETRIEVAL_FAILED];
      case 'NO_EVIDENCE':
        return errorConfig[ErrorType.NO_EVIDENCE];
      case 'UNAUTHORIZED':
        return errorConfig[ErrorType.UNAUTHORIZED];
      case 'NOT_FOUND':
        return errorConfig[ErrorType.NOT_FOUND];
      case 'RAG_SERVICE_ERROR':
        return errorConfig[ErrorType.RAG_SERVICE];
    }
  }

  // HTTP 状态码错误
  if (status === 400) {
    return {
      title: '请求参数错误',
      message: detail || '请求参数或检索范围不合法，请检查后重试。',
      retryable: false,
    };
  }
  if (status === 401) {
    return errorConfig[ErrorType.UNAUTHORIZED];
  }
  if (status === 404) {
    return errorConfig[ErrorType.NOT_FOUND];
  }
  if (status === 405) {
    return {
      title: '方法不允许',
      message: '接口方法不匹配，请检查前后端路由配置。',
      retryable: false,
    };
  }
  if (status === 500 || status === 502 || status === 503) {
    return errorConfig[ErrorType.RAG_SERVICE];
  }

  // 默认错误
  return {
    title: '请求失败',
    message: detail || '请稍后重试。',
    retryable: true,
  };
};

const handleSessionSelect = async (id: string) => {
  currentSessionId.value = id;
  messages.value = [];
  loading.value = true;
  try {
    const res = await getSessionMessages(id);
    const data = (res as any).items || (res as any).data?.items || [];
    if (data.length > 0) {
      messages.value = data.map((m: any) => {
        if (m.role === 'user') {
          return { role: 'user', content: m.content };
        } else {
          try {
            const data = typeof m.content === 'string' ? JSON.parse(m.content) : m.content;
            return { role: 'assistant', data };
          } catch {
            return { role: 'assistant', data: { content: m.content } };
          }
        }
      });
    }
  } catch (err) {
    console.error('Failed to load history', err);
  } finally {
    loading.value = false;
  }
};

const handleInspect = (messageData: any) => {
  if (!messageData) return;
  currentInspectData.value = messageData;
  inspectorVisible.value = true;
};

const handleSend = async (question: string, scope: ChatScope) => {
  if (!currentSessionId.value) return;

  // 添加用户消息
  messages.value.push({ role: 'user', content: question });

  // 添加助手思考状态
  const assistantMsgIndex = messages.value.length;
  messages.value.push({
    role: 'assistant',
    thinking: true,
    thinkingStep: 0,
    showDetails: false,
  });

  loading.value = true;

  try {
    if (useStreaming.value) {
      // 使用流式响应
      await handleStreamSend(question, scope, assistantMsgIndex);
    } else {
      // 使用传统响应
      await handleNormalSend(question, scope, assistantMsgIndex);
    }
  } catch (err: any) {
    console.error('Send message error:', err);
    messages.value[assistantMsgIndex] = {
      role: 'assistant',
      error: buildChatErrorMessage(err),
    };
  } finally {
    loading.value = false;
  }
};

// 处理流式发送
const handleStreamSend = async (
  question: string,
  scope: ChatScope,
  msgIndex: number
) => {
  try {
    // 更新思考状态：正在检索
    messages.value[msgIndex].thinkingStep = 0;

    const stream = sendMessageStream(currentSessionId.value, { question, scope });

    let fullContent = '';
    const citations: any[] = [];

    for await (const event of stream) {
      const sseEvent = event as SSEEvent;

      if (sseEvent.type === 'sentence') {
        // 更新思考状态：找到文档
        if (messages.value[msgIndex].thinkingStep === 0) {
          messages.value[msgIndex].thinkingStep = 1;
          messages.value[msgIndex].thinking = false;
          messages.value[msgIndex].isStreaming = true;
          messages.value[msgIndex].typedContent = '';
          messages.value[msgIndex].isTyping = true;
        }

        // 逐字显示答案
        if (sseEvent.data?.text) {
          fullContent += sseEvent.data.text;
          await typeText(msgIndex, sseEvent.data.text);
        }
      } else if (sseEvent.type === 'citation') {
        if (sseEvent.data) {
          citations.push(sseEvent.data);
        }
      } else if (sseEvent.type === 'error') {
        throw new Error(sseEvent.message || '流式响应错误');
      } else if (sseEvent.type === 'done') {
        break;
      }
    }

    // 完成流式
    messages.value[msgIndex].isStreaming = false;
    messages.value[msgIndex].isTyping = false;
    messages.value[msgIndex].data = {
      answer_sentences: [{ text: fullContent, evidence_type: 'source', citation_ids: citations.map(c => c.citation_id), confidence: 0.9 }],
      citations: citations,
    };

  } catch (error) {
    throw error;
  }
};

// 处理普通发送
const handleNormalSend = async (
  question: string,
  scope: ChatScope,
  msgIndex: number
) => {
  // 更新思考状态
  messages.value[msgIndex].thinkingStep = 0;
  setTimeout(() => {
    messages.value[msgIndex].thinkingStep = 1;
  }, 1000);
  setTimeout(() => {
    messages.value[msgIndex].thinkingStep = 2;
  }, 2000);

  const res = await sendMessage(currentSessionId.value, { question, scope });

  // 移除思考状态，显示完整答案
  messages.value[msgIndex] = {
    role: 'assistant',
    data: res,
  };
};

// 打字机效果
const typeText = async (msgIndex: number, text: string, speed = 40) => {
  const chars = text.split('');
  const message = messages.value[msgIndex];

  for (const char of chars) {
    message.typedContent = (message.typedContent || '') + char;
    
    // 如果用户滚动，加速显示
    if ((window as any).isScrolling) {
      await new Promise(resolve => setTimeout(resolve, 5));
    } else {
      await new Promise(resolve => setTimeout(resolve, speed));
    }
  }
};

// 重试逻辑
const handleRetry = async (message: any) => {
  const lastUserMessage = messages.value
    .slice(0, messages.value.indexOf(message))
    .reverse()
    .find(msg => msg.role === 'user');

  if (!lastUserMessage) return;

  // 移除错误消息
  messages.value = messages.value.filter(msg => msg !== message);

  // 重新发送
  await handleSend(lastUserMessage.content, {
    mode: 'multi',
    corpus_ids: [], // TODO: 从上下文获取
    allow_common_knowledge: true,
  });
};
</script>

<style scoped>
.chat-view {
  height: 100%;
  background-color: var(--bg-surface);
}
.chat-sidebar {
  border-right: 1px solid var(--border-color-light);
  background: var(--bg-base);
  transition: width 0.3s ease;
}
.chat-main {
  display: flex;
  flex-direction: column;
  padding: 0;
  height: 100%;
  position: relative;
  background: linear-gradient(180deg, var(--bg-surface) 0%, var(--bg-base) 100%);
}
.empty-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.5s ease-out;
}
.chat-box {
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  z-index: 1;
}
</style>
