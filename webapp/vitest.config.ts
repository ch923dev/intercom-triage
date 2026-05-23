import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import path from 'node:path';

// Vitest-only config (tasks.md T080). Kept separate from `vite.config.ts` so
// that the dev/build path doesn't pull vitest's nested Vite types into
// vue-tsc — the two copies of Vite produce a "not assignable" diagnostic when
// `defineConfig` is loaded from `vitest/config` in the shared file.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: false,
    include: ['src/**/*.spec.ts'],
  },
});
