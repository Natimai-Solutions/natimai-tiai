import { fileURLToPath } from 'node:url';

import { defineConfig } from '#q-app';

export default defineConfig(() => {
  return {
    boot: ['pinia', 'axios'],
    css: ['app.scss'],
    extras: ['material-icons'],

    build: {
      // app-vite 3 a ramené les alias par défaut au seul `@` → src/. Les
      // conventions du projet sont rétablies ici plutôt que réécrites sur les
      // 56 imports concernés : elles sont orthogonales à la montée de version,
      // et `build.alias` est prévu pour ça — il alimente Vite comme les
      // `paths` du tsconfig généré.
      alias: {
        src: fileURLToPath(new URL('./src', import.meta.url)),
        boot: fileURLToPath(new URL('./src/boot', import.meta.url)),
        pages: fileURLToPath(new URL('./src/pages', import.meta.url)),
        layouts: fileURLToPath(new URL('./src/layouts', import.meta.url)),
      },
      target: { browser: ['es2022'], node: 'node22' },
      typescript: { strict: true, vueShim: true },
      vueRouterMode: 'history',
      // API base URL injected at build time (overridable via env), read as
      // `import.meta.env.API_BASE_URL`. `defineEnv` and not `env`: since
      // app-vite 3, `build.env` only configures the prefixes of .env files,
      // and nothing replaces `process.env.*` in client code any more.
      defineEnv: {
        API_BASE_URL: process.env.API_BASE_URL || '/api/v1',
      },
    },

    devServer: {
      port: 9000,
      open: true,
      proxy: {
        '/api': { target: 'http://localhost:8000', changeOrigin: true },
      },
    },

    framework: {
      plugins: ['Notify', 'Dialog'],
    },
  };
});
