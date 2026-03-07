import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/store/auth';

const routes = [
  {
    path: '/',
    redirect: '/entry'
  },
  {
    path: '/entry',
    redirect: '/workspace/entry'
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
    path: '/workspace',
    name: 'WorkspaceRoot',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: 'entry',
        name: 'EntryView',
        component: () => import('@/views/EntryView.vue')
      },
      {
        path: 'ai/chat',
        name: 'AIChatView',
        component: () => import('@/views/ai/AIChatView.vue')
      },
      {
        path: 'novel/upload',
        name: 'NovelUploadView',
        component: () => import('@/views/novel/NovelUploadView.vue')
      },
      {
        path: 'novel/chat',
        name: 'NovelChatView',
        component: () => import('@/views/novel/NovelChatView.vue')
      },
      {
        path: 'novel/documents/:id',
        name: 'NovelDocumentView',
        component: () => import('@/views/novel/NovelDocumentView.vue')
      },
      {
        path: 'kb/upload',
        name: 'KBUploadView',
        component: () => import('@/views/kb/KBUploadView.vue')
      },
      {
        path: 'kb/chat',
        name: 'KBChatView',
        component: () => import('@/views/kb/KBChatView.vue')
      },
      {
        path: 'kb/documents/:id',
        name: 'KBDocumentView',
        component: () => import('@/views/kb/KBDocumentView.vue')
      }
    ]
  },
  {
    path: '/chat',
    redirect: '/workspace/ai/chat'
  },
  {
    path: '/dashboard/:pathMatch(.*)*',
    redirect: '/workspace/entry'
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
    return { path: '/workspace/entry' };
  }
});

export default router;
