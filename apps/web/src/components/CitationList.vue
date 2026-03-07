<template>
  <div class="citation-list">
    <div class="section-header">
      <div>
        <h3>{{ title }}</h3>
        <p>所有答案都必须回落到明确引用。</p>
      </div>
      <el-tag type="info" effect="plain">{{ citations.length }} 条引用</el-tag>
    </div>

    <el-empty v-if="!citations.length" description="当前没有可展示的引用" />

    <div v-else class="citation-grid">
      <el-card v-for="citation in citations" :key="citation.unit_id" shadow="hover" class="citation-card">
        <div class="citation-top">
          <div>
            <strong>{{ citation.section_title || '未命名片段' }}</strong>
            <p>{{ citation.char_range || '-' }}</p>
          </div>
          <router-link :to="documentPath(citation.document_id)" class="document-link">
            打开文档
          </router-link>
        </div>
        <p class="quote">{{ citation.quote }}</p>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
interface CitationItem {
  unit_id: string;
  document_id: string;
  section_title: string;
  char_range: string;
  quote: string;
}

const props = defineProps<{
  citations: CitationItem[];
  title?: string;
  mode: 'novel' | 'kb';
}>();

const documentPath = (documentId: string) => {
  if (props.mode === 'novel') {
    return `/workspace/novel/documents/${documentId}`;
  }
  return `/workspace/kb/documents/${documentId}`;
};
</script>

<style scoped>
.citation-list {
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

.citation-grid {
  display: grid;
  gap: 14px;
}

.citation-card {
  border-radius: 18px;
}

.citation-top {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.citation-top p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.document-link {
  color: #2563eb;
  text-decoration: none;
  white-space: nowrap;
}

.quote {
  margin: 16px 0 0;
  line-height: 1.7;
  color: var(--text-regular);
}
</style>
