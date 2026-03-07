<template>
  <div class="chat-message-list">
    <div 
      v-for="(msg, index) in messages" 
      :key="index"
      :class="['message-row', msg.role]"
    >
      <div class="avatar">
        <el-icon v-if="msg.role === 'user'"><User /></el-icon>
        <el-icon v-else><Service /></el-icon>
      </div>
      <div class="content">
        <template v-if="msg.role === 'user'">
          {{ msg.content }}
        </template>
        <template v-else>
          <div v-if="msg.error" class="error-text">
            <div class="error-header">
              <el-icon><Warning /></el-icon>
              <span>{{ msg.error.title || '错误' }}</span>
            </div>
            <div class="error-body">{{ msg.error.message }}</div>
            <div v-if="msg.error.retryable" class="error-actions">
              <el-button type="primary" size="small" @click="handleRetry(msg)">重试</el-button>
            </div>
          </div>
          <div v-else-if="msg.thinking" class="thinking-state">
            <div class="thinking-steps">
              <el-timeline>
                <el-timeline-item 
                  v-for="step in thinkingSteps" 
                  :key="step.key"
                  :timestamp="step.timestamp"
                  :type="msg.thinkingStep >= step.index ? 'primary' : 'info'"
                  :hollow="msg.thinkingStep < step.index"
                >
                  {{ step.text }}
                  <span v-if="step.detail && msg.thinkingStep === step.index" class="step-detail">
                    {{ step.detail }}
                  </span>
                </el-timeline-item>
              </el-timeline>
            </div>
            <div v-if="msg.showDetails && msg.retrievedChunks" class="chunk-details">
              <el-collapse>
                <el-collapse-item title="查看检索到的文档片段" name="1">
                  <div v-for="(chunk, idx) in msg.retrievedChunks" :key="idx" class="chunk-item">
                    <div class="chunk-header">
                      <el-tag size="small" type="info">{{ chunk.file_name }}</el-tag>
                      <span class="chunk-score">相关性：{{ (chunk.score * 100).toFixed(1) }}%</span>
                    </div>
                    <div class="chunk-text">{{ chunk.snippet }}</div>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
          <div v-else-if="msg.data" class="assistant-response">
            <div v-if="msg.isStreaming" class="streaming-indicator">
              <span class="typing-dot"></span>
              <span class="typing-dot"></span>
              <span class="typing-dot"></span>
            </div>
            <div v-if="msg.typedContent" class="typed-content">
              {{ msg.typedContent }}
              <span v-if="msg.isTyping" class="typing-cursor">|</span>
            </div>
            <RagMessageRenderer v-else :answer="msg.data" />
            
            <div v-if="!msg.isStreaming && msg.data" class="msg-actions">
              <el-button link type="primary" size="small" @click="$emit('inspect', msg.data)">
                查看详情 / Debug
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { User, Service, Warning } from '@element-plus/icons-vue';
import RagMessageRenderer from './RagMessageRenderer.vue';

interface ThinkingStep {
  key: string;
  index: number;
  text: string;
  timestamp: string;
  detail?: string;
}

const props = defineProps<{ messages: any[] }>();
const emit = defineEmits<{
  (e: 'retry', message: any): void;
  (e: 'inspect', answerData: any): void;
}>();

const thinkingSteps = ref<ThinkingStep[]>([
  { key: 'searching', index: 0, text: '正在检索文档...', timestamp: '', detail: '' },
  { key: 'found', index: 1, text: '找到相关文档', timestamp: '', detail: '' },
  { key: 'generating', index: 2, text: '生成答案中...', timestamp: '', detail: '' },
]);

// 打字机效果
const isScrolling = ref(false);

const handleRetry = (message: any) => {
  emit('retry', message);
};

// Using a local variable for scroll lock instead of window object to prevent global state pollution
let typingScrollTimeout: number | undefined;

// 检测用户滚动（用于加速打字机效果）
const handleScroll = () => {
  isScrolling.value = true;
  clearTimeout(typingScrollTimeout);
  typingScrollTimeout = window.setTimeout(() => {
    isScrolling.value = false;
  }, 200);
};

onMounted(() => {
  window.addEventListener('scroll', handleScroll, { passive: true });
});

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll);
  clearTimeout(typingScrollTimeout);
});
</script>

<style scoped>
.chat-message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 40px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.message-row {
  display: flex;
  gap: 16px;
  animation: slideUpFade 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  margin-bottom: 8px;
}
.message-row.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 44px;
  height: 44px;
  border-radius: 16px;
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--text-secondary);
  flex-shrink: 0;
  border: 1px solid rgba(0,0,0,0.05);
}
.message-row.user .avatar {
  background: linear-gradient(135deg, var(--el-color-primary-light-3) 0%, var(--el-color-primary) 100%);
  color: white;
  border: none;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}
.content {
  max-width: 75%;
  padding: 18px 22px;
  border-radius: 20px;
  background: var(--bg-surface);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
  line-height: 1.6;
  font-size: 15px;
  color: var(--text-primary);
  border: 1px solid rgba(0,0,0,0.04);
}
.message-row.user .content {
  background: linear-gradient(135deg, var(--el-color-primary) 0%, var(--el-color-primary-dark-2) 100%);
  color: white;
  border: none;
  border-bottom-right-radius: 6px;
  box-shadow: 0 8px 20px rgba(59, 130, 246, 0.2);
}
.message-row:not(.user) .content {
  border-top-left-radius: 6px;
}

/* 错误样式 */
.error-text {
  color: var(--el-color-danger);
}
.error-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  margin-bottom: 8px;
  font-size: 14px;
}
.error-body {
  margin-bottom: 12px;
  line-height: 1.5;
}
.error-actions {
  display: flex;
  gap: 8px;
}

/* 思考中状态 */
.thinking-state {
  min-width: 300px;
}
.thinking-steps {
  margin-bottom: 12px;
}
.step-detail {
  display: block;
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-secondary);
}

/* 文档片段详情 */
.chunk-details {
  margin-top: 12px;
}
.chunk-item {
  padding: 12px;
  background: var(--bg-subtle);
  border-radius: 8px;
  margin-bottom: 8px;
}
.chunk-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.chunk-score {
  font-size: 12px;
  color: var(--text-secondary);
}
.chunk-text {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
}

/* 流式指示器 */
.streaming-indicator {
  display: inline-flex;
  gap: 4px;
  margin-bottom: 8px;
}
.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  animation: typing 1.4s infinite;
}
.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

/* 打字机效果 */
.typed-content {
  display: inline;
}
.typing-cursor {
  display: inline-block;
  animation: blink 1s step-end infinite;
  color: var(--el-color-primary);
  font-weight: bold;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.assistant-response {
  min-height: 24px;
}
.msg-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
  border-top: 1px dashed var(--border-color-light);
  padding-top: 8px;
}
</style>
