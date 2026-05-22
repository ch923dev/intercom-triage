// ESLint flat config (v9+). Replaces the legacy .eslintrc.* format.
//
// Rule decisions:
//   vue/multi-word-component-names — disabled. The project deliberately uses
//   single-word component names (Topbar, Board, Column, Mono, etc.). Renaming
//   them all would be high-churn with no runtime benefit for an internal tool.

import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import pluginVue from 'eslint-plugin-vue';
import vueParser from 'vue-eslint-parser';
import prettier from 'eslint-config-prettier';

export default [
  // ── Global ignores ───────────────────────────────────────────────────────
  {
    ignores: ['dist/**', 'node_modules/**', '**/*.d.ts', 'coverage/**'],
  },

  // ── JS recommended baseline ──────────────────────────────────────────────
  js.configs.recommended,

  // ── TypeScript recommended (covers .ts files) ────────────────────────────
  ...tseslint.configs.recommended,

  // ── Vue 3 flat-config recommended (covers .vue files) ────────────────────
  ...pluginVue.configs['flat/recommended'],

  // ── File-scope overrides ─────────────────────────────────────────────────
  {
    // All TS + Vue source files under src/, plus the vite config.
    files: ['src/**/*.{ts,vue}', 'vite.config.ts'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        // Use @typescript-eslint/parser for <script lang="ts"> blocks.
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      // ── Vue rule overrides ──────────────────────────────────────────────
      //
      // Project uses single-word component names intentionally — Topbar, Board,
      // Column, Mono, etc. Turning off this stylistic rule avoids high-churn
      // renames for an internal tool.
      'vue/multi-word-component-names': 'off',

      // ── TypeScript rule overrides ───────────────────────────────────────
      //
      // The codebase uses `catch (e)` and immediately casts `(e as Error)`.
      // That is intentional — switching to `unknown` everywhere is low-value
      // churn for an internal tool. Keep at warn, but the `--max-warnings 0`
      // gate means any remaining ones must be fixed or explicitly allowed.
      // (Currently no violations exist after the source fixes below.)
    },
  },

  // ── Prettier integration — must be last ──────────────────────────────────
  // Disables all ESLint rules that would conflict with Prettier's formatting
  // so `npm run lint` and `npm run format` never disagree.
  prettier,
];
