<template>
  <div class="login-view">
    <el-form 
      :model="form" 
      :rules="rules" 
      ref="formRef" 
      @keyup.enter="handleLogin" 
      label-position="top"
      class="login-form">
      
      <el-form-item label="Email Address" prop="email">
        <el-input 
          v-model="form.email" 
          placeholder="Enter your email" 
          :prefix-icon="Message" 
          size="large"
          class="custom-input"
        />
      </el-form-item>
      
      <el-form-item label="Password" prop="password">
        <el-input 
          v-model="form.password" 
          type="password" 
          placeholder="Enter your password" 
          :prefix-icon="Lock" 
          show-password 
          size="large"
          class="custom-input"
        />
      </el-form-item>
      
      <!-- Optional: Remember me & Forgot Password Row -->
      <div class="form-actions">
        <el-checkbox v-model="rememberMe">Remember me</el-checkbox>
        <el-link type="primary" underline="never">Forgot password?</el-link>
      </div>

      <el-form-item class="submit-item">
        <el-button type="primary" :loading="loading" @click="handleLogin" size="large" class="submit-btn">
          Sign In
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '@/store/auth';
import { login } from '@/api/auth';
import { ElMessage } from 'element-plus';
import { Lock, Message } from '@element-plus/icons-vue';

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
  email: [{ required: true, message: 'Please input email', trigger: 'blur' }],
  password: [{ required: true, message: 'Please input password', trigger: 'blur' }]
};

const loading = ref(false);

const handleLogin = async () => {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (valid) {
      loading.value = true;
      try {
        const res: any = await login({ email: form.email, password: form.password });
        if (res.access_token) {
          authStore.setAuth(res.access_token, res.user);
          ElMessage.success('Login Successful');
          const redirect = route.query.redirect as string || '/';
          router.push(redirect);
        }
      } finally {
        loading.value = false;
      }
    }
  });
};
</script>

<style scoped>
.login-view {
  width: 100%;
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
