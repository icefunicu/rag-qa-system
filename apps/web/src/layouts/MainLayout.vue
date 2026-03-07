<template>
  <el-container class="main-layout">
    <el-aside width="260px" class="app-sidebar">
      <div class="sidebar-header">
        <div class="logo-circle-mini">
          <el-icon :size="20" color="var(--el-color-primary)"><Platform /></el-icon>
        </div>
        <h2>RAG-P QA</h2>
      </div>
      
      <div class="sidebar-menu-container">
        <el-menu :default-active="$route.path" router class="app-menu" :popper-offset="16">
          <el-menu-item index="/chat" class="menu-item-custom">
            <el-icon><ChatDotRound /></el-icon>
            <template #title>对话聊天</template>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin()" index="/dashboard/corpora" class="menu-item-custom">
            <el-icon><Files /></el-icon>
            <template #title>知识库管理</template>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin()" index="/dashboard/evaluation" class="menu-item-custom">
            <el-icon><DataLine /></el-icon>
            <template #title>评测与监控</template>
          </el-menu-item>
        </el-menu>
      </div>

      <div class="sidebar-footer">
        <el-dropdown trigger="click" @command="handleCommand" placement="top-start" class="user-dropdown">
          <div class="user-profile">
            <el-avatar :size="36" class="user-avatar">{{ userInitial }}</el-avatar>
            <div class="user-info">
              <span class="user-name">{{ authStore.user?.email?.split('@')[0] || 'User' }}</span>
              <span class="user-role">{{ authStore.isAdmin() ? 'Administrator' : 'Member' }}</span>
            </div>
            <el-icon class="dropdown-icon"><MoreFilled /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-aside>
    
    <el-container class="main-content-wrapper">
      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade-transform" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/store/auth';
import { useRouter } from 'vue-router';
import { ChatDotRound, Files, DataLine, Platform, MoreFilled, SwitchButton } from '@element-plus/icons-vue';
import { computed } from 'vue';

const authStore = useAuthStore();
const router = useRouter();

const userInitial = computed(() => {
  const email = authStore.user?.email || '?';
  return email.charAt(0).toUpperCase();
});

const handleCommand = (command: string) => {
  if (command === 'logout') {
    authStore.logout();
    router.push('/login');
  }
};
</script>

<style scoped>
.main-layout {
  height: 100vh;
  background-color: var(--bg-base);
}

.app-sidebar {
  background-color: var(--bg-sidebar);
  border-right: 1px solid var(--border-color-light);
  display: flex;
  flex-direction: column;
  box-shadow: 4px 0 24px rgba(0, 0, 0, 0.02);
  z-index: 10;
  transition: width 0.3s ease;
}

.sidebar-header {
  height: 72px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.logo-circle-mini {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, var(--el-color-primary) 0%, var(--el-color-primary-light-3) 100%);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 12px;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.logo-circle-mini :deep(.el-icon) {
  color: #fff !important;
}

.sidebar-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.3px;
}

.sidebar-menu-container {
  flex: 1;
  padding: 20px 16px;
  overflow-y: auto;
}

.app-menu {
  border-right: none;
  background-color: transparent;
}

.menu-item-custom {
  height: 48px;
  line-height: 48px;
  margin-bottom: 8px;
  border-radius: 12px;
  color: var(--text-regular);
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.menu-item-custom:hover {
  background-color: var(--bg-base);
  color: var(--text-primary);
  transform: translateX(4px);
}

.menu-item-custom.is-active {
  background-color: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1);
}

/* User Profile Footer */
.sidebar-footer {
  padding: 16px;
  border-top: 1px solid var(--border-color-light);
  background: linear-gradient(to top, var(--bg-surface) 50%, transparent);
}

.user-dropdown {
  width: 100%;
}

.user-profile {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.user-profile:hover {
  background-color: var(--bg-base);
  border-color: var(--border-color-light);
  box-shadow: 0 2px 6px rgba(0,0,0,0.02);
}

.user-avatar {
  background: linear-gradient(135deg, var(--el-color-primary-light-3) 0%, var(--el-color-primary) 100%);
  color: white;
  font-weight: 600;
  margin-right: 12px;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.25);
}

.user-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
}

.user-role {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.dropdown-icon {
  color: var(--text-placeholder);
}

.main-content-wrapper {
  background-color: var(--bg-base);
  position: relative;
}

.app-main {
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* Page Transitions */
.fade-transform-enter-active,
.fade-transform-leave-active {
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

.fade-transform-enter-from {
  opacity: 0;
  transform: translateY(15px);
}

.fade-transform-leave-to {
  opacity: 0;
  transform: translateY(-15px);
}

/* 响应式移动端适配补充 */
@media screen and (max-width: 768px) {
  .app-sidebar {
    width: 60px !important;
  }
  .sidebar-header h2 {
    display: none;
  }
  .menu-item-custom :deep(.el-menu-item__title) {
    display: none;
  }
  .user-info {
    display: none;
  }
  .logo-circle-mini {
    margin-right: 0;
  }
}
</style>
