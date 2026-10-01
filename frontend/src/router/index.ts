import { defineRouter } from '#q-app';
import {
  START_LOCATION,
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
} from 'vue-router';
import routes from './routes';

import { refreshSession } from 'boot/axios';
import { ensureSession, getAccessToken } from 'src/services/session';
import { readCachedPermissions } from 'src/stores/auth';
import { hashUrlToHistory } from 'src/utils/legacyUrl';

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

  router.beforeEach(async (to, from) => {
    // The access token lives in memory: after a reload, or in a new tab, there
    // is none yet while the session may well be alive behind its cookie. Ask
    // for a silent refresh before sending anyone to the login page.
    if (to.meta.requiresAuth && !(await ensureSession(refreshSession))) {
      return { name: 'login', query: { redirect: to.fullPath } };
    }
    // Opening /login directly with a live session lands on the dashboard; the
    // refresh is only tried on that first navigation — once the console runs,
    // reaching /login means the session has just ended.
    if (to.name === 'login') {
      const live =
        from === START_LOCATION ? await ensureSession(refreshSession) : getAccessToken() !== null;
      if (live) return { name: 'dashboard' };
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
