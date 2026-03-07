<template>
  <el-drawer
    title="回答详情 (Answer Inspector)"
    :model-value="visible"
    @update:modelValue="$emit('update:visible', $event)"
    direction="rtl"
    size="50%"
    destroy-on-close
  >
    <div v-if="answerData" class="inspector-content">
      <el-tabs v-model="activeTab" class="inspector-tabs">
        <el-tab-pane label="检索与引用 (Citations)" name="citations">
          <div class="citations-panel">
            <template v-if="answerData.citations && answerData.citations.length > 0">
              <el-card 
                v-for="(cit, idx) in answerData.citations" 
                :key="cit.citation_id"
                class="citation-card"
                shadow="hover"
              >
                <div class="citation-header">
                  <span class="citation-badge">[{{ Number(idx) + 1 }}]</span>
                  <span class="citation-file">{{ cit.document_id }}</span>
                </div>
                <div class="citation-body">
                  <p>{{ cit.text }}</p>
                </div>
                <div class="citation-meta">
                  <span>Score: {{ cit.score !== undefined ? cit.score.toFixed(3) : 'N/A' }}</span>
                </div>
              </el-card>
            </template>
            <el-empty v-else description="该回答未基于外部文档引用" />
          </div>
        </el-tab-pane>
        
        <el-tab-pane label="调试信息 (Debug Payload)" name="debug">
          <div class="debug-panel">
            <el-alert
              type="info"
              show-icon
              :closable="false"
              title="原始后端返回层结构"
              style="margin-bottom: 16px;"
            />
            <pre class="json-code">{{ JSON.stringify(answerData, null, 2) }}</pre>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref } from 'vue';

defineProps<{
  visible: boolean;
  answerData: any;
}>();

defineEmits(['update:visible']);

const activeTab = ref('citations');
</script>

<style scoped>
.inspector-content {
  padding: 0 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.inspector-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
}
:deep(.el-tabs__content) {
  flex: 1;
  overflow-y: auto;
}
.citation-card {
  margin-bottom: 16px;
  border-radius: 8px;
}
.citation-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border-color-light);
  padding-bottom: 8px;
}
.citation-badge {
  color: var(--el-color-primary);
  font-weight: bold;
}
.citation-file {
  font-size: 13px;
  color: var(--text-secondary);
  font-family: monospace;
}
.citation-body {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-subtle);
  padding: 12px;
  border-radius: 6px;
}
.citation-meta {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
}
.debug-panel {
  padding-bottom: 24px;
}
.json-code {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 8px;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
}
</style>
