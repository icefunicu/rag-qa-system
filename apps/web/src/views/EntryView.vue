<template>
  <div class="page">
    <section class="hero">
      <div class="hero-copy">
        <el-tag effect="dark" round>统一网关 / 双内核检索 / 独立 AI 对话</el-tag>
        <h1>同一入口进入三条清晰能力线</h1>
        <p>
          小说和企业库仍然保持各自独立的上传线路、解析策略与问答逻辑；
          同时恢复一个不绑定知识库的 AI 对话工作台，用于直接接入 Qwen3.5 这类通用大模型。
        </p>
      </div>
    </section>

    <section class="entry-grid">
      <el-card shadow="hover" class="entry-card ai-card">
        <div class="entry-badge">AI Chat</div>
        <h2>AI 对话</h2>
        <p>不绑定知识库，直接走模型对话接口。适合草拟内容、头脑风暴、摘要改写和通用问答。</p>
        <ul>
          <li>通过网关服务端代理接入模型，不在前端暴露密钥</li>
          <li>支持 OpenAI-compatible 接口，便于接入 Qwen3.5</li>
          <li>与知识库问答分离，避免无引文回答混入检索结果</li>
        </ul>
        <div class="entry-actions">
          <el-button type="primary" @click="router.push('/workspace/ai/chat')">进入 AI 对话</el-button>
        </div>
      </el-card>

      <el-card shadow="hover" class="entry-card novel-card">
        <div class="entry-badge">Novel Kernel</div>
        <h2>小说上传线路</h2>
        <p>TXT 优先，进入章节预览、剧透提示、快速可查状态与剧情问答工作台。</p>
        <ul>
          <li>优化细节、剧情、人物成长与关系因果</li>
          <li>支持章节预览与快速可查状态展示</li>
          <li>回答默认允许剧透，但必须附引用</li>
        </ul>
        <div class="entry-actions">
          <el-button type="primary" @click="router.push('/workspace/novel/upload')">进入上传</el-button>
          <el-button plain @click="router.push('/workspace/novel/chat')">进入问答</el-button>
        </div>
      </el-card>

      <el-card shadow="hover" class="entry-card kb-card">
        <div class="entry-badge">KB Kernel</div>
        <h2>企业库上传线路</h2>
        <p>支持 txt / pdf / docx 批量导入，进入知识库批处理、状态追踪与企业文档问答工作台。</p>
        <ul>
          <li>优化精确问答、跨文档汇总与制度提取</li>
          <li>支持批量上传与文档分类</li>
          <li>证据不足时明确拒答，不做模型臆测</li>
        </ul>
        <div class="entry-actions">
          <el-button type="primary" @click="router.push('/workspace/kb/upload')">进入上传</el-button>
          <el-button plain @click="router.push('/workspace/kb/chat')">进入问答</el-button>
        </div>
      </el-card>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';

const router = useRouter();
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.hero {
  padding: 36px;
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.18), transparent 32%),
    radial-gradient(circle at bottom right, rgba(15, 118, 110, 0.18), transparent 30%),
    linear-gradient(135deg, #ffffff, #f8fafc);
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.hero-copy {
  max-width: 760px;
}

.hero-copy h1 {
  margin: 16px 0 12px;
  font-size: 44px;
  line-height: 1.1;
}

.hero-copy p {
  margin: 0;
  font-size: 17px;
  line-height: 1.8;
  color: var(--text-regular);
}

.entry-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}

.entry-card {
  border-radius: 28px;
  border: none;
}

.entry-card :deep(.el-card__body) {
  padding: 28px;
}

.entry-badge {
  display: inline-flex;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ai-card {
  background: linear-gradient(180deg, rgba(249, 115, 22, 0.08), #ffffff);
}

.ai-card .entry-badge {
  background: rgba(249, 115, 22, 0.14);
  color: #c2410c;
}

.novel-card {
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.08), #ffffff);
}

.novel-card .entry-badge {
  background: rgba(37, 99, 235, 0.14);
  color: #1d4ed8;
}

.kb-card {
  background: linear-gradient(180deg, rgba(15, 118, 110, 0.08), #ffffff);
}

.kb-card .entry-badge {
  background: rgba(15, 118, 110, 0.14);
  color: #0f766e;
}

.entry-card h2 {
  margin: 18px 0 10px;
  font-size: 30px;
}

.entry-card p {
  margin: 0;
  line-height: 1.7;
  color: var(--text-regular);
}

.entry-card ul {
  margin: 18px 0 0;
  padding-left: 20px;
  color: var(--text-regular);
  line-height: 1.8;
}

.entry-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  flex-wrap: wrap;
}

@media (max-width: 1200px) {
  .entry-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .hero-copy h1 {
    font-size: 34px;
  }
}
</style>
