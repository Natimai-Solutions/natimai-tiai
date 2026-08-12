import { defineRouter } from '#q-app/wrappers';
import {
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
} from 'vue-router';
import routes from './routes';

// Source of truth for "logged in" in the guard (kept in sync by the auth store).
const TOKEN_KEY = 'tiai_token';
const ROLE_KEY = 'tiai_role';

export default defineRouter(() => {
  const createHistory = process.env.SERVER
    ? createMemoryHistory
    : process.env.VUE_ROUTER_MODE === 'history'
      ? createWebHistory
      : createWebHashHistory;

  const router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    history: createHistory(process.env.VUE_ROUTER_BASE),
  });

  router.beforeEach((to) => {
    const isAuthed = !!localStorage.getItem(TOKEN_KEY);
    if (to.meta.requiresAuth && !isAuthed) {
      return { name: 'login', query: { redirect: to.fullPath } };
    }
    if (to.name === 'login' && isAuthed) {
      return { name: 'dashboard' };
    }
    // Admin-only pages. The guard only decides what to render — the backend
    // authorizes every call independently, so this cannot be bypassed for real.
    if (to.meta.requiresAdmin && localStorage.getItem(ROLE_KEY) !== 'admin') {
      return { name: 'dashboard' };
    }
    return true;
  });

  return router;
});
