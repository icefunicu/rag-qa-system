import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/store/auth';

const routes = [
    {
        path: '/',
        redirect: '/chat'
    },
    {
        path: '/login',
        name: 'Login',
        component: () => import('@/layouts/AuthLayout.vue'),
        children: [
            {
                path: '',
                name: 'LoginView',
                component: () => import('@/views/LoginView.vue')
            }
        ]
    },
    {
        path: '/chat',
        name: 'ChatRoot',
        component: () => import('@/layouts/MainLayout.vue'),
        meta: { requiresAuth: true },
        children: [
            {
                path: '',
                name: 'ChatHome',
                component: () => import('@/views/chat/ChatView.vue')
            }
        ]
    },
    {
        path: '/dashboard',
        name: 'DashboardRoot',
        component: () => import('@/layouts/MainLayout.vue'),
        meta: { requiresAuth: true, requiresAdmin: true },
        children: [
            {
                path: 'corpora',
                name: 'CorporaList',
                component: () => import('@/views/dashboard/CorporaList.vue')
            },
            {
                path: 'corpus/:id',
                name: 'CorpusDetail',
                component: () => import('@/views/dashboard/CorpusDetail.vue')
            },
            {
                path: 'evaluation',
                name: 'EvaluationCockpit',
                component: () => import('@/views/dashboard/EvaluationCockpit.vue')
            }
        ]
    }
];

const router = createRouter({
    history: createWebHistory(),
    routes
});

router.beforeEach((to) => {
    const authStore = useAuthStore();

    if (to.meta.requiresAuth && !authStore.token) {
        return { path: '/login', query: { redirect: to.fullPath } };
    }

    if (to.meta.requiresAdmin && !authStore.isAdmin()) {
        return { path: '/chat' };
    }
});

export default router;
