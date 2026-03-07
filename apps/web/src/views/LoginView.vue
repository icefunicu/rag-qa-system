<template>
  <div class="login-view">
    <el-alert
      title="默认账号：admin@local / member@local，默认密码 ChangeMe123!"
      type="info"
      :closable="false"
      class="login-hint"
    />
    <el-form
      :model="form"
      :rules="rules"
      ref="formRef"
      @keyup.enter="handleLogin"
      label-position="top"
      class="login-form"
    >
      <el-form-item label="邮箱" prop="email">
        <el-input
          v-model="form.email"
          placeholder="请输入登录邮箱"
          :prefix-icon="Message"
          size="large"
          class="custom-input"
        />
      </el-form-item>

      <el-form-item label="密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          placeholder="请输入密码"
          :prefix-icon="Lock"
          show-password
          size="large"
          class="custom-input"
        />
      </el-form-item>

      <div class="form-actions">
        <el-checkbox v-model="rememberMe">记住我</el-checkbox>
        <el-link type="primary" underline="never">本地开发环境</el-link>
      </div>

      <el-form-item class="submit-item">
        <el-button type="primary" :loading="loading" @click="handleLogin" size="large" class="submit-btn">
          进入工作台
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { Lock, Message } from '@element-plus/icons-vue';
import { login } from '@/api/auth';
import { useAuthStore } from '@/store/auth';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const formRef = ref();

const form = reactive({
  email: '',
  password: ''
});

const rememberMe = ref(true);

const rules = {
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
};

const loading = ref(false);

const handleLogin = async () => {
  if (!formRef.value) {
    return;
  }
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) {
      return;
    }
    loading.value = true;
    try {
      const res: any = await login({ email: form.email, password: form.password });
      if (res.access_token) {
        authStore.setAuth(res.access_token, res.user);
        ElMessage.success('登录成功');
        const redirect = route.query.redirect as string || '/workspace/entry';
        router.push(redirect);
      }
    } finally {
      loading.value = false;
    }
  });
};
</script>

<style scoped>
.login-view {
  width: 100%;
}

.login-hint {
  margin-bottom: 20px;
  border-radius: 12px;
}

:deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--text-primary);
  padding-bottom: 4px;
}

.form-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  margin-bottom: 24px;
}

.submit-item {
  margin-top: 8px;
  margin-bottom: 0;
}

.submit-btn {
  width: 100%;
  border-radius: 12px;
  font-weight: 600;
  font-size: 16px;
  height: 52px;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: var(--shadow-blue);
  letter-spacing: 0.5px;
}

.submit-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 16px 24px -8px rgba(59, 130, 246, 0.5);
}

.submit-btn:active {
  transform: translateY(0);
}

:deep(.custom-input .el-input__wrapper) {
  border-radius: 12px;
  padding: 8px 16px;
  box-shadow: 0 0 0 1px var(--border-color-light) inset;
  background-color: var(--bg-base);
  transition: all 0.2s ease;
  height: 48px;
}

:deep(.custom-input .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--border-color) inset;
  background-color: var(--bg-surface);
}

:deep(.custom-input .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--el-color-primary) inset;
  background-color: var(--bg-surface);
}

:deep(.custom-input .el-input__prefix-inner) {
  color: var(--text-placeholder);
  font-size: 18px;
}
</style>
