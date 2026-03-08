import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => {
  const envDir = path.resolve(__dirname, '../..');
  const env = loadEnv(mode, envDir, '');
  const gatewayPort = env.GATEWAY_HOST_PORT || '8080';
  const gatewayOrigin = env.VITE_GATEWAY_ORIGIN || `http://localhost:${gatewayPort}`;

  return {
    envDir,
    plugins: [vue()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      }
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            'vue-vendor': ['vue', 'vue-router', 'pinia'],
            'ui-vendor': ['element-plus'],
            'icons-vendor': ['@element-plus/icons-vue'],
            'http-vendor': ['axios']
          }
        }
      }
    },
    server: {
      port: 5173,
      proxy: {
        '/api/v1': {
          target: gatewayOrigin,
          changeOrigin: true
        }
      }
    }
  };
});
