<template>
  <div class="page-shell doc-page">
    <PageHeaderCompact :title="document?.file_name || '加载中'">
      <template #actions>
        <el-button plain @click="router.push('/workspace/kb/upload')">返回</el-button>
        <el-button plain :disabled="!document || !canWrite" @click="openEditDrawer">编辑</el-button>
        <el-button plain :disabled="!document" @click="router.push(`/workspace/kb/documents/${document.id}/chunks`)">切片管理</el-button>
        <el-button plain type="danger" :disabled="!document || !canWrite" @click="handleDeleteDocument">删除</el-button>
        <el-button
          v-if="document?.latest_job?.retryable && canManage"
          plain
          type="warning"
          :loading="retryingJob"
          @click="handleRetryIngest"
        >
          重试
        </el-button>
        <el-button type="primary" @click="goChat">提问</el-button>
      </template>
    </PageHeaderCompact>

    <div class="doc-content">
      <div v-if="!document" class="doc-loading">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <span>加载中</span>
      </div>

      <template v-else>
        <div class="doc-info-row">
          <span class="info-item">{{ formatBytes(document.size_bytes) }}</span>
          <span class="info-item">{{ document.stats_json?.category || '-' }}</span>
          <span class="info-item">{{ document.version_label || '未命名版本' }}</span>
          <el-tag :type="statusMeta(document.status).type" size="small" effect="plain">
            {{ statusMeta(document.status).label }}
          </el-tag>
          <el-tag
            :type="document.is_current_version ? 'success' : 'info'"
            size="small"
            effect="plain"
          >
            {{ document.is_current_version ? '当前版本' : '历史版本' }}
          </el-tag>
          <el-tag
            :type="document.effective_now ? 'success' : 'warning'"
            size="small"
            effect="plain"
          >
            {{ document.effective_now ? '当前生效' : '未生效 / 已失效' }}
          </el-tag>
          <el-tag v-if="document.stats_json?.visual_asset_count" type="success" size="small" effect="plain">
            截图 {{ document.stats_json.visual_asset_count }} 张
          </el-tag>
        </div>

        <el-collapse v-model="activeCollapse">
          <el-collapse-item name="versions" title="版本治理">
            <template #title>
              <span>版本治理</span>
              <el-tag size="small" type="warning" style="margin-left: 8px">{{ versionHistory.length }} 个版本</el-tag>
            </template>
            <EnhancedEmpty
              v-if="!versionHistory.length"
              variant="document"
              title="暂无版本记录"
              description="当前文档还没有整理出版本家族信息。"
              class="chunk-empty"
            />
            <div v-else class="version-list">
              <article
                v-for="item in versionHistory"
                :key="item.id"
                class="version-card"
                :class="{ 'version-card--active': String(item.id) === String(selectedVersionId || document.id) }"
              >
                <div class="version-card__header">
                  <strong>{{ item.version_label || `v${item.version_number || 1}` }}</strong>
                  <div class="version-card__tags">
                    <el-tag size="small" effect="plain" :type="item.is_current_version ? 'success' : 'info'">
                      {{ item.is_current_version ? '当前' : '非当前' }}
                    </el-tag>
                    <el-tag size="small" effect="plain" :type="item.effective_now ? 'success' : 'warning'">
                      {{ item.effective_now ? '生效中' : '非生效' }}
                    </el-tag>
                  </div>
                </div>
                <div class="version-card__meta">
                  <span>{{ item.file_name }}</span>
                  <span>状态：{{ item.version_status || '-' }}</span>
                  <span>版本号：{{ item.version_number || 1 }}</span>
                  <span>生效开始：{{ formatDateTime(item.effective_from) }}</span>
                  <span>生效结束：{{ formatDateTime(item.effective_to) }}</span>
                </div>
                <div class="version-card__actions">
                  <el-button size="small" plain @click="inspectVersion(item)">查看内容</el-button>
                  <el-button
                    v-if="String(item.id) !== String(document.id)"
                    size="small"
                    type="primary"
                    plain
                    @click="inspectVersion(item, true)"
                  >
                    对比当前
                  </el-button>
                </div>
              </article>
            </div>
            <div v-if="selectedVersionContent" class="version-inspector">
              <div class="version-inspector__header">
                <div>
                  <strong>{{ selectedVersionContent.version_label || selectedVersionContent.file_name }}</strong>
                  <span class="version-inspector__sub">
                    {{ selectedVersionContent.section_count }} 节 / {{ selectedVersionContent.chunk_count }} 个切片
                  </span>
                </div>
                <el-tag size="small" effect="plain" :type="selectedVersionContent.is_current_version ? 'success' : 'info'">
                  {{ selectedVersionContent.is_current_version ? '当前版本' : '历史版本' }}
                </el-tag>
              </div>
              <el-tabs v-model="versionInspectorTab">
                <el-tab-pane label="版本内容" name="content">
                  <div class="version-sections">
                    <article v-for="section in selectedVersionContent.sections || []" :key="`${section.section_index}:${section.section_title}`" class="version-section">
                      <strong>{{ section.section_title || `Section ${section.section_index + 1}` }}</strong>
                      <pre>{{ section.text_content || '(空)' }}</pre>
                    </article>
                  </div>
                </el-tab-pane>
                <el-tab-pane label="与当前版本差异" name="diff">
                  <EnhancedEmpty
                    v-if="!selectedVersionDiff?.diff?.diff_text"
                    variant="document"
                    title="暂无文本差异"
                    description="当前查看版本与对比目标没有正文差异。"
                    class="chunk-empty"
                  />
                  <template v-else>
                    <div class="version-diff-summary">
                      <span>新增切片：{{ selectedVersionDiff.diff.summary?.added_chunks || 0 }}</span>
                      <span>删除切片：{{ selectedVersionDiff.diff.summary?.removed_chunks || 0 }}</span>
                      <span>修改切片：{{ selectedVersionDiff.diff.summary?.modified_chunks || 0 }}</span>
                      <span>变更章节：{{ selectedVersionDiff.diff.summary?.changed_sections || 0 }}</span>
                    </div>
                    <pre class="version-diff-text">{{ selectedVersionDiff.diff.diff_text }}</pre>
                  </template>
                </el-tab-pane>
              </el-tabs>
            </div>
          </el-collapse-item>

          <el-collapse-item name="chunks" title="知识切片概览">
            <template #title>
              <span>知识切片概览</span>
              <el-tag size="small" type="info" style="margin-left: 8px">{{ sectionPreview.length }} 项</el-tag>
            </template>
            <EnhancedEmpty
              v-if="!sectionPreview.length"
              variant="document"
              title="暂无切片"
              description="文档切片完成后会在这里展示"
              class="chunk-empty"
            />
            <div v-else class="chunk-grid">
              <div v-for="(item, index) in sectionPreview" :key="index" class="chunk-node">
                <span class="chunk-index">#{{ Number(index) + 1 }}</span>
                <span class="chunk-text">{{ String(item).slice(0, 120) }}{{ String(item).length > 120 ? '…' : '' }}</span>
                <span class="chunk-meta">{{ String(item).length }} 字符</span>
              </div>
            </div>
          </el-collapse-item>

          <el-collapse-item name="visuals" title="截图资产">
            <template #title>
              <span>截图资产</span>
              <el-tag size="small" type="success" style="margin-left: 8px">{{ visualAssets.length }} 张</el-tag>
            </template>
            <EnhancedEmpty
              v-if="!visualAssets.length"
              variant="document"
              title="暂无截图资产"
              description="视觉增强完成后会在这里展示文档里的截图"
              class="chunk-empty"
            />
            <div v-else class="visual-grid">
              <article v-for="asset in visualAssets" :key="asset.asset_id" class="visual-card">
                <div class="visual-thumb-wrap">
                  <img
                    v-if="asset.thumbnail_url"
                    :src="asset.thumbnail_url"
                    :alt="asset.file_name || 'visual asset'"
                    class="visual-thumb"
                  />
                  <div v-else class="visual-thumb visual-thumb--empty">无预览</div>
                </div>
                <div class="visual-meta">
                  <strong>{{ asset.file_name || `截图 ${asset.asset_index || ''}` }}</strong>
                  <span>{{ asset.page_number ? `第 ${asset.page_number} 页` : '内嵌图片' }}</span>
                  <span>{{ asset.status || '-' }}</span>
                </div>
              </article>
            </div>
          </el-collapse-item>

          <el-collapse-item name="events" title="处理事件">
            <DocumentEvents :items="events" title="处理事件" description="" />
          </el-collapse-item>
        </el-collapse>
      </template>
    </div>

    <el-drawer
      v-model="editDrawerVisible"
      title="编辑文档"
      size="380px"
      destroy-on-close
      @close="cancelEditDocument"
    >
      <el-form label-position="top" style="padding: 0 16px">
        <el-form-item label="文件名">
          <el-input v-model="documentForm.file_name" placeholder="文件名" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="documentForm.category" placeholder="分类" />
        </el-form-item>
        <el-divider content-position="left">版本治理</el-divider>
        <el-form-item label="版本家族 Key">
          <el-input v-model="documentForm.version_family_key" placeholder="同一份文档不同版本建议保持一致" />
        </el-form-item>
        <el-form-item label="版本标签">
          <el-input v-model="documentForm.version_label" placeholder="例如 v2 / 2026-Q1" />
        </el-form-item>
        <el-form-item label="版本号">
          <el-input-number v-model="documentForm.version_number" :min="1" :max="100000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="版本状态">
          <el-select v-model="documentForm.version_status" style="width: 100%">
            <el-option v-for="item in versionStatusOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="当前版本">
          <el-switch v-model="documentForm.is_current_version" />
        </el-form-item>
        <el-form-item label="生效开始">
          <el-date-picker
            v-model="documentForm.effective_from"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss[Z]"
            placeholder="可选"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="生效结束">
          <el-date-picker
            v-model="documentForm.effective_to"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss[Z]"
            placeholder="可选"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="被当前版本替代的旧文档 ID">
          <el-input v-model="documentForm.supersedes_document_id" placeholder="可选，用于建立新旧版本关系" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!canWrite" @click="saveDocument">保存</el-button>
          <el-button @click="cancelEditDocument">取消</el-button>
        </el-form-item>
      </el-form>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Loading } from '@element-plus/icons-vue';
import DocumentEvents from '@/components/DocumentEvents.vue';
import EnhancedEmpty from '@/components/EnhancedEmpty.vue';
import PageHeaderCompact from '@/components/PageHeaderCompact.vue';
import { useAuthStore } from '@/store/auth';
import {
  deleteKBDocument,
  getKBDocument,
  getKBDocumentEvents,
  getKBDocumentVersionContent,
  getKBDocumentVersionDiff,
  getKBDocumentVersions,
  getKBDocumentVisualAssets,
  retryKBIngestJob,
  updateKBDocument
} from '@/api/kb';
import { formatBytes } from '@/utils/format';
import { statusMeta } from '@/utils/status';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const document = ref<any | null>(null);
const events = ref<any[]>([]);
const visualAssets = ref<any[]>([]);
const versionHistory = ref<any[]>([]);
const selectedVersionId = ref('');
const selectedVersionContent = ref<any | null>(null);
const selectedVersionDiff = ref<any | null>(null);
const versionInspectorTab = ref<'content' | 'diff'>('content');
const retryingJob = ref(false);
const editDrawerVisible = ref(false);
const activeCollapse = ref<string[]>(['versions', 'chunks', 'visuals']);
const versionStatusOptions = ['active', 'draft', 'superseded', 'archived'];

const documentForm = reactive({
  file_name: '',
  category: '',
  version_family_key: '',
  version_label: '',
  version_number: 1,
  version_status: 'active',
  is_current_version: true,
  effective_from: '',
  effective_to: '',
  supersedes_document_id: ''
});

const sectionPreview = computed(() => document.value?.stats_json?.section_preview || []);
const canWrite = computed(() => authStore.hasPermission('kb.write'));
const canManage = computed(() => authStore.hasPermission('kb.manage'));

const syncDocumentForm = () => {
  documentForm.file_name = String(document.value?.file_name || '');
  documentForm.category = String(document.value?.stats_json?.category || '');
  documentForm.version_family_key = String(document.value?.version_family_key || document.value?.id || '');
  documentForm.version_label = String(document.value?.version_label || '');
  documentForm.version_number = Number(document.value?.version_number || 1);
  documentForm.version_status = String(document.value?.version_status || 'active');
  documentForm.is_current_version = Boolean(document.value?.is_current_version);
  documentForm.effective_from = formatDateTimeInput(document.value?.effective_from);
  documentForm.effective_to = formatDateTimeInput(document.value?.effective_to);
  documentForm.supersedes_document_id = String(document.value?.supersedes_document_id || '');
};

const load = async () => {
  const id = String(route.params.id || '');
  document.value = await getKBDocument(id);
  const [eventsResult, visualResult, versionsResult]: any[] = await Promise.all([
    getKBDocumentEvents(id),
    getKBDocumentVisualAssets(id),
    getKBDocumentVersions(id)
  ]);
  events.value = eventsResult.items || [];
  visualAssets.value = visualResult.items || [];
  versionHistory.value = versionsResult.items || [];
  const defaultVersion = versionHistory.value.find((item: any) => String(item.id) === String(document.value?.id || '')) || versionHistory.value[0];
  if (defaultVersion) {
    await inspectVersion(defaultVersion, false);
  }
  syncDocumentForm();
};

const inspectVersion = async (item: any, openDiff: boolean = false) => {
  if (!document.value) return;
  selectedVersionId.value = String(item.id || '');
  versionInspectorTab.value = openDiff ? 'diff' : 'content';
  const [contentResult, diffResult]: any[] = await Promise.all([
    getKBDocumentVersionContent(String(document.value.id), String(item.id)),
    getKBDocumentVersionDiff(String(document.value.id), String(item.id))
  ]);
  selectedVersionContent.value = contentResult.document || null;
  selectedVersionDiff.value = diffResult || null;
};

const goChat = () => {
  if (!document.value) return;
  router.push({
    path: '/workspace/chat',
    query: {
      preset: 'kb',
      baseId: document.value.base_id,
      documentId: document.value.id
    }
  });
};

const openEditDrawer = () => {
  if (!canWrite.value || !document.value) return;
  syncDocumentForm();
  editDrawerVisible.value = true;
};

const cancelEditDocument = () => {
  syncDocumentForm();
  editDrawerVisible.value = false;
};

const saveDocument = async () => {
  if (!canWrite.value || !document.value) return;
  if (!documentForm.file_name.trim()) {
    ElMessage.warning('请填写文件名');
    return;
  }
  document.value = await updateKBDocument(String(document.value.id), {
    file_name: documentForm.file_name.trim(),
    category: documentForm.category.trim(),
    version_family_key: documentForm.version_family_key.trim(),
    version_label: documentForm.version_label.trim(),
    version_number: Number(documentForm.version_number || 1),
    version_status: documentForm.version_status,
    is_current_version: documentForm.is_current_version,
    effective_from: documentForm.effective_from || null,
    effective_to: documentForm.effective_to || null,
    supersedes_document_id: documentForm.supersedes_document_id.trim() || null
  });
  await load();
  editDrawerVisible.value = false;
  ElMessage.success('已更新');
};

const handleRetryIngest = async () => {
  if (!canManage.value || !document.value?.latest_job?.job_id) return;
  retryingJob.value = true;
  try {
    await retryKBIngestJob(String(document.value.latest_job.job_id));
    await load();
    ElMessage.success('已重新入队');
  } finally {
    retryingJob.value = false;
  }
};

const handleDeleteDocument = async () => {
  if (!canWrite.value || !document.value) return;
  try {
    await ElMessageBox.confirm(
      `删除文档「${document.value.file_name}」？此操作不可恢复。`,
      '删除',
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
    );
  } catch {
    return;
  }
  const baseId = String(document.value.base_id || '');
  await deleteKBDocument(String(document.value.id));
  ElMessage.success('已删除');
  router.push({ path: '/workspace/kb/upload', query: baseId ? { baseId } : {} });
};

const formatDateTimeInput = (value: string | Date | null | undefined) => {
  if (!value) return '';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString().slice(0, 19) + 'Z';
};

const formatDateTime = (value: string | Date | null | undefined) => {
  if (!value) return '-';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', { hour12: false });
};

onMounted(() => void load());
</script>

<style scoped>
.doc-page {
  gap: var(--content-gap, 16px);
  overflow: hidden;
}

.doc-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.doc-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px;
  color: var(--text-muted);
}

.doc-info-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  padding: 12px 0;
  margin-bottom: 12px;
}

.info-item {
  font-size: 14px;
  color: var(--text-secondary);
}

.chunk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}

.chunk-node {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-panel-muted);
  font-size: 13px;
}

.chunk-index {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.chunk-text {
  color: var(--text-primary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.chunk-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.chunk-empty {
  padding: 32px 20px !important;
}

.version-list {
  display: grid;
  gap: 12px;
}

.version-card {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-panel);
}

.version-card--active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 25%, transparent);
}

.version-card__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.version-card__tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.version-card__meta {
  display: grid;
  gap: 4px;
  font-size: 13px;
  color: var(--text-secondary);
}

.version-card__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.version-inspector {
  display: grid;
  gap: 12px;
  margin-top: 16px;
  padding: 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-panel-muted);
}

.version-inspector__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.version-inspector__sub {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.version-sections {
  display: grid;
  gap: 12px;
}

.version-section {
  display: grid;
  gap: 8px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-panel);
}

.version-section pre,
.version-diff-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
}

.version-diff-summary {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
}

.visual-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.visual-card {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-panel);
}

.visual-thumb-wrap {
  overflow: hidden;
  border-radius: 8px;
  background: var(--bg-panel-muted);
  border: 1px solid var(--border-color);
}

.visual-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
}

.visual-thumb--empty {
  display: grid;
  place-items: center;
  color: var(--text-muted);
}

.visual-meta {
  display: grid;
  gap: 4px;
  font-size: 13px;
  color: var(--text-secondary);
}

.visual-meta strong {
  color: var(--text-primary);
}
</style>
