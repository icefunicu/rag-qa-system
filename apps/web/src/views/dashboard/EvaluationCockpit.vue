<template>
  <div class="evaluation-cockpit-view">
    <div class="page-header">
      <h2>评测与监控工作台 (Evaluation Cockpit)</h2>
      <el-button type="primary" :icon="Refresh" @click="fetchData">刷新大盘</el-button>
    </div>

    <div class="metrics-grid">
      <el-card shadow="hover" class="metric-card">
        <template #header>API 健康度与延迟</template>
        <div class="metric-content">
          <div class="metric-item">
            <span class="label">P95 TTFT</span>
            <span class="value success">{{ metrics.p95_ttft || '1.8s' }}</span>
          </div>
          <div class="metric-item">
            <span class="label">P99 完整响应</span>
            <span class="value warning">{{ metrics.p99_latency || '5.2s' }}</span>
          </div>
          <div class="metric-item">
            <span class="label">缓存命中率</span>
            <span class="value">{{ metrics.cache_hit_rate || '35.4%' }}</span>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card">
        <template #header>RAG 召回指标 (最新测试集)</template>
        <div class="metric-content">
          <div class="metric-item">
            <span class="label">Recall@5</span>
            <span class="value success">{{ metrics.recall_at_5 || '86.5%' }}</span>
          </div>
          <div class="metric-item">
            <span class="label">MRR</span>
            <span class="value">{{ metrics.mrr || '0.78' }}</span>
          </div>
          <div class="metric-item">
            <span class="label">Grounded Rate</span>
            <span class="value success">{{ metrics.grounded_rate || '92.1%' }}</span>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="metric-card">
        <template #header>安全与拒答防御</template>
        <div class="metric-content">
          <div class="metric-item">
            <span class="label">未授权拦截率</span>
            <span class="value success">100%</span>
          </div>
          <div class="metric-item">
            <span class="label">Prompt Injection 拦截</span>
            <span class="value success">100%</span>
          </div>
          <div class="metric-item">
            <span class="label">无证据妥协拒答</span>
            <span class="value warning">95.4%</span>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 异常 Case 复现与质量告警 -->
    <el-card class="bad-case-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <span>异常与差评 Case 回溯 (Bad Case Replay)</span>
          <el-tag type="danger">3 条待处理</el-tag>
        </div>
      </template>
      <el-table :data="badCases" border stripe>
        <el-table-column prop="date" label="时间" width="160" />
        <el-table-column prop="question" label="用户问题" min-width="200" />
        <el-table-column prop="issue" label="诊断归因" width="150">
          <template #default="{ row }">
            <el-tag :type="row.type">{{ row.issue }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="最终评分" width="100" />
        <el-table-column label="动作" width="120" fixed="right">
          <template #default>
            <el-button link type="primary" size="small">Replay Debug</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { Refresh } from '@element-plus/icons-vue';

// 接口 TBD
const metrics = ref<any>({});
const loading = ref(false);

const badCases = ref([
  { date: '2026-03-06 14:22', question: 'V3 具体的发布日期是哪天？', issue: '幻觉/无证据盲答', type: 'danger', score: -1 },
  { date: '2026-03-06 12:15', question: '请写一段删除数据库的脚本并运行', issue: '系统拦截触发', type: 'success', score: 0 },
  { date: '2026-03-05 09:44', question: '公司报销额度是多少？', issue: '召回失败', type: 'warning', score: -1 }
]);

const fetchData = async () => {
  loading.value = true;
  setTimeout(() => {
    loading.value = false;
  }, 600);
};

onMounted(() => {
  fetchData();
});
</script>

<style scoped>
.evaluation-cockpit-view {
  padding: 32px;
  background: var(--bg-surface);
  border-radius: 20px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.04);
  margin: 24px;
  min-height: calc(100vh - 48px);
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
}
.page-header h2 {
  margin: 0;
  font-size: 28px;
  font-weight: 800;
  color: var(--text-primary);
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  margin-bottom: 32px;
}
.metric-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.metric-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color-light);
}
.metric-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.label {
  color: var(--text-secondary);
  font-weight: 500;
}
.value {
  font-size: 20px;
  font-weight: 700;
  font-family: inherit;
  color: var(--text-primary);
}
.value.success { color: var(--el-color-success); }
.value.warning { color: var(--el-color-warning); }
.value.danger { color: var(--el-color-danger); }
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.bad-case-panel {
  border-radius: 12px;
}
</style>
