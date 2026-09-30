import { defineRouter } from '#q-app';
import {
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
} from 'vue-router';
import routes from './routes';

import { readCachedPermissions } from 'src/stores/auth';
import { hashUrlToHistory } from 'src/utils/legacyUrl';

// Source of truth for "logged in" in the guard (kept in sync by the auth store).
const TOKEN_KEY = 'tiai_token';

export default defineRouter(() => {
  // Read from `import.meta.env`, where app-vite 3 defines them. The former
  // `process.env.*` reads were no longer replaced: the dev server threw on
  // them, and the build quietly fell back to hash mode — which broke every
  // console link the server mails (/reset-password, /machines/<id>, /tasks).
  const history = import.meta.env.QUASAR_VUE_ROUTER_MODE === 'history';
  const base = import.meta.env.QUASAR_VUE_ROUTER_BASE;
  const createHistory = import.meta.env.QUASAR_SERVER
    ? createMemoryHistory
    : history
      ? createWebHistory
      : createWebHashHistory;

  if (history && typeof window !== 'undefined') {
    const rewritten = hashUrlToHistory(window.location.hash, base ?? '/');
    if (rewritten) window.history.replaceState(null, '', rewritten);
  }

  const router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    history: createHistory(base),
  });

  router.beforeEach((to) => {
    const isAuthed = !!localStorage.getItem(TOKEN_KEY);
    if (to.meta.requiresAuth && !isAuthed) {
      return { name: 'login', query: { redirect: to.fullPath } };
    }
    if (to.name === 'login' && isAuthed) {
      return { name: 'dashboard' };
    }
    // Pages behind a permission. The guard only decides what to render — the
    // backend authorizes every call independently, so this cannot be bypassed
    // for real. The cached set is what the last profile fetch wrote.
    const required = to.meta.requiresPermission;
    if (typeof required === 'string' && !readCachedPermissions().includes(required)) {
      return { name: 'dashboard' };
    }
    return true;
  });

  return router;
});
