import axios from 'axios';
import { useAuthStore } from '@/store/auth';
import { ElMessage } from 'element-plus';
import router from '@/router';

export interface RequestConfig {
    skipErrorHandler?: boolean;
}

const request = axios.create({
    baseURL: '/v1',
    timeout: 60000
});

request.interceptors.request.use(config => {
    const authStore = useAuthStore();
    if (authStore.token) {
        config.headers.Authorization = `Bearer ${authStore.token}`;
    }
    return config;
}, error => Promise.reject(error));

request.interceptors.response.use(
    response => response.data,
    error => {
        if ((error.config as RequestConfig | undefined)?.skipErrorHandler) {
            return Promise.reject(error);
        }

        const backendError =
            error.response?.data?.error ||
            error.response?.data?.message ||
            error.response?.data?.detail;

        if (error.response?.status === 401) {
            const authStore = useAuthStore();
            authStore.logout();
            router.push('/login');
            ElMessage.error('登录失效或 Token 无效');
        } else if (error.response?.status === 400) {
            ElMessage.error(String(backendError || '请求参数错误，请检查输入后重试'));
        } else if (error.response?.status === 403) {
            ElMessage.error('权限不足');
        } else if (error.response?.status === 404) {
            ElMessage.error(String(backendError || '资源不存在，请刷新页面后重试'));
        } else if (error.response?.status === 405) {
            ElMessage.error('请求方法不支持，请检查前后端接口配置');
        } else if (error.response?.status === 503) {
            ElMessage.error('入队失败，请重试');
        } else if (backendError) {
            ElMessage.error(String(backendError));
        } else {
            ElMessage.error('请求失败');
        }
        return Promise.reject(error);
    }
);

export default request;
