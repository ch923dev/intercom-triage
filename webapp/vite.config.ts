import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'node:path';

// Reference: tasks.md T029. Dev server proxies /api/* to the backend on 4000
// so the SPA can stay on the same origin during local dev. Vitest config
// lives in `vitest.config.ts` (T080) so the dev/build path doesn't drag in
// vitest's nested Vite copy at typecheck time.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
    allowedHosts: ['vertebrae-marmalade-bleep.ngrok-free.dev'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:4000',
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
});
