<template>
  <div class="citation-list">
    <div class="citation-header">
      <h3 class="citation-title">{{ title || '引用来源' }}</h3>
      <span v-if="citations.length" class="citation-count">{{ citations.length }} 处</span>
    </div>

    <el-empty v-if="!citations.length" description="暂无引用" />

    <div v-else class="citation-grid">
      <article v-for="(citation, index) in citations" :key="citation.unit_id || index" class="citation-card">
        <div class="citation-card-head">
          <div class="citation-title-area">
            <span class="citation-index">{{ index + 1 }}</span>
            <div class="citation-info">
              <strong>{{ citation.section_title || '未命名片段' }}</strong>
              <p>{{ citation.document_title || citation.document_id }}</p>
            </div>
          </div>
          <router-link :to="documentPath(citation)" class="document-link">
            <el-icon><Document /></el-icon> 查看原件
          </router-link>
        </div>

        <div class="pill-row citation-meta">
          <el-tag size="small" effect="plain" type="info" class="meta-tag">
            <el-icon><Files /></el-icon> {{ citation.corpus_type || mode }}
          </el-tag>
          <el-tag size="small" effect="plain" type="info" class="meta-tag">
            <el-icon><Location /></el-icon> {{ citation.char_range || '-' }}
          </el-tag>
          <el-tag v-if="citation.page_number" size="small" effect="plain" type="success" class="meta-tag">
            <el-icon><Picture /></el-icon> 第 {{ citation.page_number }} 页
          </el-tag>

          <div v-if="citation.evidence_path?.final_score !== undefined" class="score-indicator">
            <span class="score-label">相关度</span>
            <div class="score-bar-bg">
              <div
                class="score-bar-fill"
                :style="{ width: `${Math.min(100, Math.max(0, citation.evidence_path.final_score * 100))}%` }"
                :class="getScoreClass(citation.evidence_path.final_score)"
              ></div>
            </div>
            <span class="score-value" :class="getScoreClass(citation.evidence_path.final_score, true)">
              {{ (citation.evidence_path.final_score * 100).toFixed(1) }}%
            </span>
          </div>
        </div>

        <div class="quote-container">
          <div v-if="citation.thumbnail_url" class="visual-preview">
            <img :src="citation.thumbnail_url" :alt="citation.section_title || citation.document_title || 'visual evidence'" />
          </div>
          <el-collapse class="custom-collapse">
            <el-collapse-item name="1">
              <template #title>
                <div class="collapse-title">
                  <el-icon><Reading /></el-icon> 展开引用原文
                </div>
              </template>
              <p class="quote"><mark class="highlight">{{ citation.quote }}</mark></p>
            </el-collapse-item>
          </el-collapse>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Document, Reading, Files, Location, Picture } from '@element-plus/icons-vue';

interface CitationItem {
  unit_id: string;
  document_id: string;
  document_title?: string;
  section_title: string;
  char_range: string;
  quote: string;
  corpus_type?: 'kb';
  evidence_kind?: 'text' | 'visual_ocr';
  source_kind?: string;
  page_number?: number | null;
  asset_id?: string;
  thumbnail_url?: string;
  evidence_path?: {
    final_score?: number;
  };
}

defineProps<{
  citations: CitationItem[];
  title?: string;
  mode: 'kb';
}>();

const documentPath = (citation: CitationItem) => `/workspace/kb/documents/${citation.document_id}`;

const getScoreClass = (score: number, textOnly = false) => {
  if (score >= 0.8) return textOnly ? 'text-high' : 'score-high';
  if (score >= 0.5) return textOnly ? 'text-medium' : 'score-medium';
  return textOnly ? 'text-low' : 'score-low';
};
</script>

<style scoped>
.citation-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.citation-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.citation-title {
  margin: 0;
  font-size: var(--text-body, 0.9375rem);
  font-weight: 600;
  color: var(--text-primary);
}

.citation-count {
  font-size: var(--text-caption, 0.75rem);
  color: var(--text-muted);
  font-weight: 500;
}

.citation-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.citation-card {
  padding: 16px 18px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-color);
  background: var(--bg-panel);
}

.citation-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.citation-title-area {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.citation-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  background: var(--bg-panel-muted);
  color: var(--text-muted);
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-mono);
}

.citation-info strong {
  display: block;
  font-size: 1.05rem;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.citation-info p {
  color: var(--text-secondary);
  font-size: 13px;
}

.document-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-xs);
  background: var(--bg-panel-muted);
  border: 1px solid var(--border-color);
  color: var(--blue-600);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  transition: all 0.2s ease;
}

.document-link:hover {
  background: var(--blue-50);
}

.citation-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px dashed var(--border-color);
}

.score-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.score-label {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
}

.score-bar-bg {
  width: 100px;
  height: 6px;
  background: var(--border-color);
  border-radius: 999px;
  overflow: hidden;
}

.score-bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

.score-high {
  background: #10b981;
}

.score-medium {
  background: #f59e0b;
}

.score-low {
  background: #94a3b8;
}

.text-high {
  color: #10b981;
}

.text-medium {
  color: #f59e0b;
}

.text-low {
  color: #ef4444;
}

.score-value {
  font-size: 12px;
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text-primary);
  min-width: 44px;
  text-align: right;
}

.quote-container {
  display: grid;
  gap: 12px;
}

.visual-preview {
  width: min(240px, 100%);
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border-color);
  background: var(--bg-panel-muted);
}

.visual-preview img {
  display: block;
  width: 100%;
  height: auto;
}

.custom-collapse {
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-top: none;
  border-bottom: none;
}

.custom-collapse :deep(.el-collapse-item__header) {
  background: var(--bg-panel-muted);
  border-bottom: none;
  height: 44px;
  line-height: 44px;
  padding: 0 16px;
  color: var(--text-secondary);
}

.custom-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: none;
  background: transparent;
}

.custom-collapse :deep(.el-collapse-item__content) {
  padding: 0;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
}

.quote {
  padding: 16px;
  background: var(--bg-panel);
  border-top: 1px dashed var(--border-color);
  color: var(--text-regular);
  line-height: 1.75;
  font-size: 14px;
}

@media (max-width: 768px) {
  .citation-card-head {
    flex-direction: column;
  }

  .score-indicator {
    margin-left: 0;
    width: 100%;
    margin-top: 8px;
  }

  .citation-meta {
    flex-wrap: wrap;
  }
}
</style>
