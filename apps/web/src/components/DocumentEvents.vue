<template>
  <div class="events-block">
    <div class="section-header">
      <div>
        <h3>{{ title }}</h3>
        <p>{{ description }}</p>
      </div>
      <el-tag type="info" effect="plain">{{ items.length }} 条事件</el-tag>
    </div>

    <el-empty v-if="!items.length" description="还没有事件记录" />

    <el-timeline v-else>
      <el-timeline-item
        v-for="item in items"
        :key="`${item.created_at}-${item.stage}`"
        :timestamp="formatDateTime(item.created_at)"
        placement="top"
      >
        <el-card shadow="never" class="event-card">
          <div class="event-head">
            <strong>{{ stageLabel(item.stage) }}</strong>
            <el-tag :type="statusMeta(item.stage).type" effect="plain">{{ item.stage }}</el-tag>
          </div>
          <p class="event-message">{{ item.message }}</p>
          <pre v-if="item.details_json" class="event-details">{{ pretty(item.details_json) }}</pre>
        </el-card>
      </el-timeline-item>
    </el-timeline>
  </div>
</template>

<script setup lang="ts">
import { statusMeta } from '@/utils/status';
import { formatDateTime } from '@/utils/time';

interface EventItem {
  stage: string;
  message: string;
  created_at: string;
  details_json?: unknown;
}

defineProps<{
  items: EventItem[];
  title?: string;
  description?: string;
}>();

const STAGE_LABELS: Record<string, string> = {
  uploaded: '已接收',
  parsing: '解析中',
  fast_index_ready: '快速可查',
  enhancing: '深度增强',
  ready: '已完成',
  failed: '失败'
};

const stageLabel = (stage: string) => STAGE_LABELS[stage] || stage;

const pretty = (value: unknown) => JSON.stringify(value, null, 2);
</script>

<style scoped>
.events-block {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.section-header h3 {
  margin: 0;
  font-size: 18px;
}

.section-header p {
  margin: 6px 0 0;
  color: var(--text-secondary);
}

.event-card {
  border-radius: 16px;
}

.event-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.event-message {
  margin: 12px 0 0;
  line-height: 1.7;
}

.event-details {
  margin: 12px 0 0;
  padding: 12px;
  overflow: auto;
  border-radius: 12px;
  background: #0f172a;
  color: #dbeafe;
  font-size: 12px;
}
</style>
