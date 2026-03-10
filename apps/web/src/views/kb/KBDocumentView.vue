<template>
  <div class="page-shell doc-page">
    <PageHeaderCompact :title="document?.file_name || '加载中'">
      <template #actions>
        <el-button plain @click="router.push('/workspace/kb/upload')">返回</el-button>
        <el-button plain :disabled="!document || !canWrite" @click="openEditDrawer">编辑</el-button>
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
          <el-tag :type="statusMeta(document.status).type" size="small" effect="plain">
            {{ statusMeta(document.status).label }}
          </el-tag>
          <el-tag v-if="document.stats_json?.visual_asset_count" type="success" size="small" effect="plain">
            截图 {{ document.stats_json.visual_asset_count }} 张
          </el-tag>
        </div>

        <el-collapse v-model="activeCollapse">
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
const retryingJob = ref(false);
const editDrawerVisible = ref(false);
const activeCollapse = ref<string[]>(['chunks', 'visuals']);

const documentForm = reactive({
  file_name: '',
  category: ''
});

const sectionPreview = computed(() => document.value?.stats_json?.section_preview || []);
const canWrite = computed(() => authStore.hasPermission('kb.write'));
const canManage = computed(() => authStore.hasPermission('kb.manage'));

const syncDocumentForm = () => {
  documentForm.file_name = String(document.value?.file_name || '');
  documentForm.category = String(document.value?.stats_json?.category || '');
};

const load = async () => {
  const id = String(route.params.id || '');
  document.value = await getKBDocument(id);
  const [eventsResult, visualResult]: any[] = await Promise.all([
    getKBDocumentEvents(id),
    getKBDocumentVisualAssets(id)
  ]);
  events.value = eventsResult.items || [];
  visualAssets.value = visualResult.items || [];
  syncDocumentForm();
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
    category: documentForm.category.trim()
  });
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
