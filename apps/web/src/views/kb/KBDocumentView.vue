<template>
  <div class="page">
    <section class="page-header kb-header">
      <div>
        <el-tag type="success" effect="dark">企业文档详情</el-tag>
        <h1>{{ document?.file_name || '加载中...' }}</h1>
        <p>这里展示企业库专用分段结果，包括 section 与 chunk 统计。</p>
      </div>
      <div class="header-actions">
        <el-button plain @click="router.push('/workspace/kb/upload')">返回上传</el-button>
        <el-button type="primary" @click="goChat">围绕该文档提问</el-button>
      </div>
    </section>

    <section class="grid layout">
      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>基础信息</h2>
              <p>企业库线路保留 section 与 chunk 统计。</p>
            </div>
            <el-tag :type="statusMeta(document?.status).type" effect="plain">{{ statusMeta(document?.status).label }}</el-tag>
          </div>
        </template>

        <el-empty v-if="!document" description="正在加载文档信息" />
        <div v-else class="detail-grid">
          <div class="metric">
            <span>文件类型</span>
            <strong>{{ document.file_type || '-' }}</strong>
          </div>
          <div class="metric">
            <span>Section 数</span>
            <strong>{{ document.section_count || 0 }}</strong>
          </div>
          <div class="metric">
            <span>Chunk 数</span>
            <strong>{{ document.chunk_count || 0 }}</strong>
          </div>
          <div class="metric">
            <span>文件大小</span>
            <strong>{{ document.size_bytes || 0 }} bytes</strong>
          </div>
          <div class="metric">
            <span>分类</span>
            <strong>{{ document.stats_json?.category || '未填写' }}</strong>
          </div>
          <div class="metric">
            <span>哈希</span>
            <strong class="hash">{{ document.content_hash || '-' }}</strong>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="panel">
        <template #header>
          <div class="card-head">
            <div>
              <h2>Section 预览</h2>
              <p>来自快速索引阶段的标题样本。</p>
            </div>
          </div>
        </template>

        <el-empty v-if="!sectionPreview.length" description="当前没有 section 预览" />
        <ul v-else class="preview-list">
          <li v-for="item in sectionPreview" :key="item">{{ item }}</li>
        </ul>
      </el-card>
    </section>

    <el-card shadow="hover" class="panel">
      <DocumentEvents
        :items="events"
        title="处理事件"
        description="事件由企业库内核独立产生，不复用小说线路事件。"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import DocumentEvents from '@/components/DocumentEvents.vue';
import { getKBDocument, getKBDocumentEvents } from '@/api/kb';
import { statusMeta } from '@/utils/status';

const route = useRoute();
const router = useRouter();
const document = ref<any | null>(null);
const events = ref<any[]>([]);

const sectionPreview = computed(() => document.value?.stats_json?.section_preview || []);

const load = async () => {
  const documentId = String(route.params.id);
  document.value = await getKBDocument(documentId);
  const result: any = await getKBDocumentEvents(documentId);
  events.value = result.items || [];
};

const goChat = () => {
  if (!document.value) {
    return;
  }
  router.push({
    path: '/workspace/kb/chat',
    query: {
      baseId: document.value.base_id,
      documentId: document.value.id
    }
  });
};

onMounted(() => {
  void load();
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

.kb-header {
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.2), transparent 30%),
    linear-gradient(135deg, #ffffff, #ecfdf5);
}

.page-header h1 {
  margin: 12px 0 8px;
  font-size: 34px;
}

.page-header p {
  margin: 0;
  line-height: 1.7;
  color: var(--text-regular);
}

.header-actions {
  display: flex;
  gap: 12px;
}

.grid.layout {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
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

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.metric {
  padding: 16px;
  border-radius: 18px;
  background: rgba(248, 250, 252, 0.95);
}

.metric span {
  display: block;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.metric strong {
  word-break: break-all;
}

.hash {
  font-size: 12px;
}

.preview-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
}

@media (max-width: 960px) {
  .grid.layout {
    grid-template-columns: 1fr;
  }

  .header-actions {
    flex-direction: column;
  }
}
</style>
