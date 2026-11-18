import { defineRouter } from '#q-app';
import {
  START_LOCATION,
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
  type RouteLocationNormalized,
} from 'vue-router';
import routes from './routes';
import { documentTitle } from 'src/utils/format';
import { onLocaleChange, t } from 'src/i18n';

/** A route's `meta.title` — a key of the catalogues — in the language shown. */
function pageTitle(key: unknown): string | undefined {
  return typeof key === 'string' && key ? t(key) : undefined;
}

import { refreshSession } from 'boot/axios';
import { ensureSession, getAccessToken } from 'src/services/session';
import { readCachedPermissions, useAuthStore } from 'src/stores/auth';
import { canOpen, firstReadablePage, safeRedirect } from './access';
import { hashUrlToHistory } from 'src/utils/legacyUrl';
import { whenScrollable } from 'src/utils/scrollRestore';
import { installStaleChunkReload } from 'src/utils/staleChunks';

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
    // Back to a page: where it was (audit U10), once its data has made it
    // tall enough to get there. A query change on the same page — a tab, a
    // filter, a page of results — stays put. Anything else starts at the top.
    scrollBehavior: (to, from, saved) => {
      // The first page of the tab — a reload, a pasted link — is shown from
      // the top, as the browser loads it. `saved` is then what history.state
      // kept from the last time this entry was left: not where the reader is.
      if (from === START_LOCATION) return false;
      if (saved) {
        // Held for this very navigation, by the identity of its route: a page
        // that writes its own URL back as it loads (SoftwarePage's load()) has
        // the router call this again for the same route object, and that must
        // not cancel the position — while any real navigation makes another.
        return whenScrollable(saved, { isCurrent: () => router.currentRoute.value === to });
      }
      return to.path === from.path ? false : { left: 0, top: 0 };
    },
    routes,
    history: createHistory(base),
  });

  router.beforeEach(async (to, from) => {
    // The access token lives in memory: after a reload, or in a new tab, there
    // is none yet while the session may well be alive behind its cookie. Ask
    // for a silent refresh before sending anyone to the login page.
    if (to.meta.requiresAuth && !(await ensureSession(refreshSession))) {
      // Inside a running console, no session means it has just ended: the
      // login page says so. On the first page of a tab it is a plain login.
      const ended = from !== START_LOCATION ? { ended: '1' } : {};
      return { name: 'login', query: { redirect: to.fullPath, ...ended } };
    }
    // A session restored by that refresh has no profile yet: load it before
    // the page, which reads its permissions as it loads.
    const auth = useAuthStore();
    if (to.meta.requiresAuth) await auth.ensureProfile();
    // Opening /login directly with a live session goes where the link meant
    // to (`?redirect=`), else home; the refresh is only tried on that first
    // navigation — once the console runs, reaching /login means the session
    // has just ended.
    if (to.name === 'login') {
      const live =
        from === START_LOCATION ? await ensureSession(refreshSession) : getAccessToken() !== null;
      if (live) return safeRedirect(to.query.redirect) ?? '/';
    }
    // Pages behind a permission. The guard only decides what to render — the
    // backend authorizes every call independently, so this cannot be bypassed
    // for real. The profile's set when it is loaded, else what the last
    // profile fetch cached; with neither (the profile could not be read), the
    // page is shown and the layout says the profile is missing.
    const required = to.meta.requiresPermission;
    const permissions = auth.user?.permissions ?? readCachedPermissions();
    const known = Boolean(auth.user) || permissions.length > 0;
    if (known && !canOpen(permissions, required)) {
      // The first page this account may read — « / » included, for an account
      // without machine:read — rather than a dashboard of 403s.
      const landing = firstReadablePage(permissions);
      return landing === to.name ? true : { name: landing };
    }
    return true;
  });

  // One title per page: it is what a screen reader announces on navigation,
  // and what tells twelve open tabs apart. The fiches of a poste and of a room
  // replace it with their name once loaded.
  // The title the router itself last wrote: a change of language rewrites it,
  // and leaves alone one a page put in its place (the poste's name).
  let routeTitle: string | null = null;
  function showRouteTitle(to: RouteLocationNormalized) {
    document.title = documentTitle(pageTitle(to.meta.title));
    routeTitle = document.title;
  }
  router.afterEach((to, from) => {
    // A query change on the same page — a fiche's tab, a filter, a page of
    // results — keeps the title the page set: the poste's name, not « Poste ».
    if (from !== START_LOCATION && to.path === from.path) return;
    showRouteTitle(to);
  });
  onLocaleChange(() => {
    if (typeof document === 'undefined' || document.title !== routeTitle) return;
    showRouteTitle(router.currentRoute.value);
  });

  // A tab opened before a deployment asks for chunks the new build no longer
  // serves: reload it, once, on the page it was going to (audit S34) — and
  // only on proof of a new build; a chunk lost to the network is said instead.
  if (typeof window !== 'undefined') installStaleChunkReload(router);

  return router;
});
