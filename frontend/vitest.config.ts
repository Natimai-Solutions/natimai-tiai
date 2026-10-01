import { fileURLToPath } from 'node:url';
import { quasar, transformAssetUrls } from '@quasar/vite-plugin';
import vue from '@vitejs/plugin-vue';
import { configDefaults, defineConfig } from 'vitest/config';

// Component specs live next to their component; they are the ones that need a
// DOM. Everything else (services, utils, most composables) stays on `node`,
// which is faster and keeps those layers honest about not touching `document`.
const COMPONENT_SPECS = ['src/components/**/*.spec.ts', 'src/pages/**/*.spec.ts'];

export default defineConfig({
  // The same two plugins the app builds with: Vue compiles the SFCs, and
  // Quasar's resolves `<q-btn>` and friends to their components at compile
  // time — so a mounted component renders the real Quasar tree, not stubs.
  plugins: [vue({ template: { transformAssetUrls } }), quasar({ sassVariables: false })],
  resolve: {
    alias: {
      boot: fileURLToPath(new URL('./src/boot', import.meta.url)),
      src: fileURLToPath(new URL('./src', import.meta.url)),
      pages: fileURLToPath(new URL('./src/pages', import.meta.url)),
      layouts: fileURLToPath(new URL('./src/layouts', import.meta.url)),
    },
  },
  // Tests are self-contained: don't inherit the Quasar tsconfig preset.
  // `oxc`, not `esbuild`: Vite 8 transforms with oxc and ignores the esbuild
  // options entirely (it only warns when both are set).
  oxc: {
    tsconfigRaw: '{}',
  },
  test: {
    globals: true,
    // Two projects rather than a per-file environment comment: the rule is
    // "a component spec gets a DOM", and saying it once here means a new
    // component spec cannot forget it. (`environmentMatchGlobs` did this
    // before Vitest 4 removed it.) A composable spec that needs a DOM still
    // says so in its own header, as `useMachineNavigation.spec.ts` does.
    projects: [
      {
        extends: true,
        test: {
          name: 'unit',
          environment: 'node',
          include: ['src/**/*.spec.ts'],
          exclude: [...configDefaults.exclude, ...COMPONENT_SPECS],
        },
      },
      {
        extends: true,
        test: {
          name: 'components',
          environment: 'jsdom',
          include: COMPONENT_SPECS,
          setupFiles: ['src/test/setupComponents.ts'],
        },
      },
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'json-summary'],
      reportsDirectory: './coverage',
      // The tested layers. A components directory joins once every component
      // in it has a spec: measuring all of src/components today would count
      // some thirty untested dialogs and cards, and turn the thresholds from a
      // guard on the tested code into a backlog counter.
      include: [
        'src/composables/**',
        'src/services/**',
        'src/utils/**',
        'src/components/machines-list/**',
      ],
      thresholds: { lines: 80, functions: 80, statements: 80, branches: 70 },
    },
  },
});
