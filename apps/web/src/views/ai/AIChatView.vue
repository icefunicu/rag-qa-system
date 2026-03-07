<template>
  <div class="page">
    <section class="page-header ai-header">
      <div>
        <el-tag type="warning" effect="dark">AI 对话</el-tag>
        <h1>通用模型对话工作台</h1>
        <p>这里不绑定小说或企业知识库，只通过网关调用已配置的大模型。适合通用问答、摘要、改写和方案讨论。</p>
      </div>
      <div class="header-actions">
        <el-button plain @click="router.push('/workspace/entry')">返回入口</el-button>
        <el-button plain @click="clearConversation">清空对话</el-button>
      </div>
    </section>

    <section class="grid layout">
      <el-card shadow="hover" class="panel config-panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>模型配置</h2>
              <p>服务端读取环境变量并代理请求，前端不接触模型密钥。</p>
            </div>
            <el-tag :type="config?.configured ? 'success' : 'warning'" effect="plain">
              {{ config?.configured ? '已配置' : '未配置' }}
            </el-tag>
          </div>
        </template>

        <el-alert
          v-if="config && !config.configured"
          title="AI 对话已恢复，但当前模型尚未配置。请先在 .env 中补齐 AI_BASE_URL / AI_MODEL / AI_API_KEY。"
          type="warning"
          :closable="false"
          class="status-alert"
        />

        <div class="config-grid">
          <div class="config-item">
            <span class="config-label">Provider</span>
            <strong>{{ config?.provider || 'openai-compatible' }}</strong>
          </div>
          <div class="config-item">
            <span class="config-label">Model</span>
            <strong>{{ config?.model || '未设置' }}</strong>
          </div>
          <div class="config-item wide">
            <span class="config-label">Base URL</span>
            <strong>{{ config?.base_url || '未设置' }}</strong>
          </div>
        </div>

        <el-form label-position="top" class="settings-form">
          <el-form-item label="系统提示词">
            <el-input
              v-model="systemPrompt"
              type="textarea"
              :rows="4"
              placeholder="例如：你是一个简洁、可靠的中文助手。"
            />
          </el-form-item>
          <el-form-item label="温度">
            <el-slider v-model="temperature" :min="0" :max="1.5" :step="0.1" show-input />
          </el-form-item>
          <el-form-item label="最大输出 Tokens">
            <el-input-number v-model="maxTokens" :min="128" :max="8192" :step="128" />
          </el-form-item>
        </el-form>

        <div class="shortcut-group">
          <span>快捷问题</span>
          <div class="shortcut-list">
            <el-button v-for="item in shortcuts" :key="item" plain size="small" @click="question = item">{{ item }}</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="panel chat-panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>对话记录</h2>
              <p>AI 对话不附知识库引用，和检索问答严格分开。</p>
            </div>
            <el-tag effect="plain">{{ messages.length }} 条消息</el-tag>
          </div>
        </template>

        <el-empty v-if="messages.length === 0" description="输入第一条消息开始对话" />
        <div v-else class="message-list">
          <article
            v-for="(message, index) in messages"
            :key="`${message.role}-${index}`"
            :class="['message-bubble', message.role]"
          >
            <div class="bubble-head">
              <strong>{{ message.role === 'user' ? '你' : 'AI' }}</strong>
              <div v-if="message.role === 'assistant'" class="bubble-tags">
                <el-tag v-if="message.provider" size="small" effect="plain">{{ message.provider }}</el-tag>
                <el-tag v-if="message.model" size="small" effect="plain">{{ message.model }}</el-tag>
                <el-tag v-if="message.usage?.total_tokens" size="small" effect="plain">
                  tokens {{ message.usage.total_tokens }}
                </el-tag>
              </div>
            </div>
            <p class="bubble-content">{{ message.content }}</p>
            <el-collapse v-if="message.reasoning" class="reasoning-panel">
              <el-collapse-item title="查看推理痕迹" name="reasoning">
                <p class="bubble-reasoning">{{ message.reasoning }}</p>
              </el-collapse-item>
            </el-collapse>
          </article>
          <div ref="endAnchor" />
        </div>

        <div class="composer">
          <el-input
            v-model="question"
            type="textarea"
            :rows="4"
            resize="none"
            placeholder="输入你的问题，按 Ctrl + Enter 或点击发送。"
            @keydown.ctrl.enter.prevent="sendMessage"
          />
          <div class="composer-actions">
            <span class="composer-tip">知识库问答请走企业库线路；这里是纯模型对话。</span>
            <el-button type="primary" :loading="sending" @click="sendMessage">发送</el-button>
          </div>
        </div>
      </el-card>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useRouter } from 'vue-router';
import { getAIConfig, sendAIChat } from '@/api/ai';

interface AIConfig {
  enabled: boolean;
  configured: boolean;
  provider: string;
  model: string;
  base_url: string;
  timeout_seconds: number;
  default_temperature: number;
  default_max_tokens: number;
  has_system_prompt: boolean;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  model?: string;
  provider?: string;
  usage?: {
    total_tokens?: number;
  };
}

const router = useRouter();

const config = ref<AIConfig | null>(null);
const messages = ref<ChatMessage[]>([]);
const question = ref('');
const systemPrompt = ref('');
const temperature = ref(0.7);
const maxTokens = ref(2048);
const sending = ref(false);
const endAnchor = ref<HTMLElement | null>(null);

const shortcuts = [
  '帮我整理这个项目接入 Qwen3.5 的上线检查清单。',
  '把这段需求改写成更明确的开发任务说明。',
  '给我一个三步排查思路，定位上传慢的原因。',
  '帮我把一段会议纪要整理成行动项。'
];

const normalizedMessages = computed(() => {
  return messages.value.map((item) => ({
    role: item.role,
    content: item.content
  }));
});

const scrollToBottom = async () => {
  await nextTick();
  endAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'end' });
};

const loadConfig = async () => {
  const response: any = await getAIConfig();
  config.value = response;
  temperature.value = response.default_temperature || 0.7;
  maxTokens.value = response.default_max_tokens || 2048;
};

const clearConversation = () => {
  messages.value = [];
  question.value = '';
};

const sendMessage = async () => {
  const content = question.value.trim();
  if (!content) {
    ElMessage.warning('请输入消息内容');
    return;
  }

  if (config.value && !config.value.enabled) {
    ElMessage.warning('当前环境已禁用 AI 对话');
    return;
  }

  messages.value.push({
    role: 'user',
    content
  });
  question.value = '';
  await scrollToBottom();

  sending.value = true;
  try {
    const response: any = await sendAIChat({
      messages: normalizedMessages.value,
      system_prompt: systemPrompt.value.trim() || undefined,
      temperature: temperature.value,
      max_tokens: maxTokens.value
    });
    messages.value.push({
      role: 'assistant',
      content: response.answer,
      reasoning: response.reasoning,
      provider: response.provider,
      model: response.model,
      usage: response.usage
    });
    await scrollToBottom();
  } catch (error) {
    const fallback = '模型请求失败，请检查网关日志和 AI 配置。';
    messages.value.push({
      role: 'assistant',
      content: fallback
    });
    await scrollToBottom();
    throw error;
  } finally {
    sending.value = false;
  }
};

onMounted(async () => {
  await loadConfig();
});
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 30px;
  border-radius: 28px;
}

.ai-header {
  background:
    radial-gradient(circle at top left, rgba(249, 115, 22, 0.18), transparent 30%),
    linear-gradient(135deg, #ffffff, #fff7ed);
}

.header-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.page-header h1 {
  margin: 12px 0 8px;
  font-size: 34px;
}

.page-header p {
  margin: 0;
  line-height: 1.7;
  color: var(--text-regular);
  max-width: 760px;
}

.grid.layout {
  display: grid;
  grid-template-columns: 380px minmax(0, 1fr);
  gap: 20px;
}

.panel {
  border-radius: 24px;
  border: none;
}

.panel :deep(.el-card__body) {
  padding: 24px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.card-head h2 {
  margin: 0;
}

.card-head p {
  margin: 6px 0 0;
  color: var(--text-secondary);
}

.status-alert {
  margin-bottom: 18px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.03);
}

.config-item.wide {
  grid-column: 1 / -1;
}

.config-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.settings-form {
  margin-bottom: 20px;
}

.shortcut-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.shortcut-group span {
  font-size: 13px;
  color: var(--text-secondary);
}

.shortcut-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chat-panel {
  display: flex;
  flex-direction: column;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 360px;
  max-height: 560px;
  overflow-y: auto;
  padding-right: 6px;
}

.message-bubble {
  padding: 16px 18px;
  border-radius: 20px;
}

.message-bubble.user {
  align-self: flex-end;
  width: min(90%, 720px);
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.12), rgba(59, 130, 246, 0.08));
}

.message-bubble.assistant {
  align-self: flex-start;
  width: min(90%, 760px);
  background: rgba(15, 23, 42, 0.04);
}

.bubble-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 10px;
}

.bubble-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.bubble-content,
.bubble-reasoning {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.8;
}

.reasoning-panel {
  margin-top: 12px;
}

.composer {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.composer-tip {
  color: var(--text-secondary);
  font-size: 13px;
}

@media (max-width: 1080px) {
  .grid.layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .composer-actions,
  .header-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
