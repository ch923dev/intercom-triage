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
    // Node ≥22 ships an experimental global `localStorage` that is
    // non-functional without `--localstorage-file`; happy-dom's GlobalWindow
    // adopts it (observed on Node 25.9), so every spec touching localStorage
    // fails with "localStorage.clear is not a function". Strip it from the
    // worker processes so happy-dom installs its own working storage.
    poolOptions: {
      threads: { execArgv: ['--no-experimental-webstorage'] },
      forks: { execArgv: ['--no-experimental-webstorage'] },
    },
  },
});
