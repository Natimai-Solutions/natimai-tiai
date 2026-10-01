// ESLint — the console's correctness rules, beside Prettier (format) and
// vue-tsc (types). Flat config.
//
// What it is for: the mistakes neither of the other two catch — a Vue
// template that mutates a prop, a `v-for` without a key, a promise left
// floating, a variable declared and never used. The type-aware rules
// (`recommendedTypeChecked`) are what catch the floating promise: they read
// the TypeScript program, which is why linting takes a few seconds more. Formatting is Prettier's
// alone: `eslint-config-prettier` comes last and switches off every rule that
// would argue with it.
import pluginVue from 'eslint-plugin-vue';
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript';
import prettier from 'eslint-config-prettier';
import tseslint from 'typescript-eslint';
import globals from 'globals';

export default defineConfigWithVueTs(
  {
    ignores: [
      'dist/**',
      '.quasar/**',
      'coverage/**',
      'node_modules/**',
      'src-*/**',
      // Playwright's own report and traces.
      'playwright-report/**',
      'test-results/**',
    ],
  },
  pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommendedTypeChecked,
  {
    languageOptions: {
      globals: { ...globals.browser },
    },
    rules: {
      // Unused bindings are dead code or a forgotten wire; a leading
      // underscore marks the ones kept on purpose (a positional parameter).
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // The console's component names are French nouns of one word in places
      // (pages, a few cards): the rule's multi-word convention is for
      // libraries sharing a namespace, not an application.
      'vue/multi-word-component-names': 'off',
    },
  },
  {
    // In a single-file component the linter sees the script through the Vue
    // parser, with less type information than vue-tsc: an assertion it calls
    // unnecessary there can be the one vue-tsc needs. vue-tsc is the judge.
    files: ['**/*.vue'],
    rules: { '@typescript-eslint/no-unnecessary-type-assertion': 'off' },
  },
  {
    files: ['**/*.spec.ts'],
    rules: {
      // A spec mounts small throwaway components of its own beside the one
      // it tests: the one-component-per-file rule is for application code.
      'vue/one-component-per-file': 'off',
      // `expect(api.get).toHaveBeenCalled…` passes a method unbound on
      // purpose, and an async mock with nothing to await is still the
      // honest shape of what it replaces.
      '@typescript-eslint/unbound-method': 'off',
      '@typescript-eslint/require-await': 'off',
    },
  },
  {
    // Build, lint and end-to-end configuration: run by Node, outside the
    // application's TypeScript project, so the type-aware rules have no
    // program to read them with.
    files: ['*.config.{ts,js}', 'e2e/**/*.ts'],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: {
      ...tseslint.configs.disableTypeChecked.languageOptions,
      globals: { ...globals.node },
    },
  },
  prettier,
);
