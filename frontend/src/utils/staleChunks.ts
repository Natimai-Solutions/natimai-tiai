import { Notify } from 'quasar';
import type { Router } from 'vue-router';
import { t } from 'src/i18n';
import layout from 'src/i18n/messages/layout';

/**
 * A console tab opened before a deployment still runs the old build: the
 * pages it has not opened yet are lazy chunks whose hashed names the new
 * build no longer serves, and every navigation to one fails with a 404 until
 * the reader reloads by hand (audit S34). The cure is that reload, done for
 * them — once: if the fresh page fails the same way, the problem is not a
 * stale tab, and reloading again would loop.
 *
 * A chunk also fails to load for reasons a reload makes worse: no network
 * (the reload replaces the whole console with the browser's error page), a
 * server restarting, a file really missing from the build. So the tab is
 * reloaded only on proof of a new build — the server answers, and its
 * index.html no longer names the entry script this tab runs. In every other
 * case the console stays as it is and says the page could not be loaded.
 */

/** When the last reload for a stale chunk happened, per tab. */
export const STALE_CHUNK_RELOAD_KEY = 'tiai.staleChunkReloadAt';
/** A second failure within this window is not a stale tab: no reload then. */
export const STALE_CHUNK_RELOAD_GUARD_MS = 30_000;

/** What the reader is told, in the language shown. */
export function chunkLoadFailedMessage(): string {
  return t('layout.staleChunk.failed');
}

/** Under the message when the browser is offline: what happens on its own. */
export function chunkLoadOfflineCaption(): string {
  return t('layout.staleChunk.offline');
}

/** The message in French, the console's default language (kept for its callers). */
export const CHUNK_LOAD_FAILED_MESSAGE: string = layout.fr.staleChunk.failed;

/** The offline caption in French, the console's default language. */
export const CHUNK_LOAD_OFFLINE_CAPTION: string = layout.fr.staleChunk.offline;

/** The messages browsers give a dynamic import or a preload that failed. */
const CHUNK_ERROR =
  /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS|Loading (CSS )?chunk .* failed/i;

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  return CHUNK_ERROR.test(message);
}

export interface ReloadDeps {
  storage: Pick<Storage, 'getItem' | 'setItem'> | null;
  now: () => number;
  reload: () => void;
}

/**
 * Reload, unless this tab already did so for the same reason a moment ago.
 * True when it reloaded. Without a storage to remember in, it never does:
 * an unguarded reload is the loop this exists to avoid.
 */
export function reloadOnceForStaleChunk(deps: ReloadDeps): boolean {
  if (!deps.storage) return false;
  try {
    const last = Number(deps.storage.getItem(STALE_CHUNK_RELOAD_KEY) ?? '');
    const now = deps.now();
    if (Number.isFinite(last) && last > 0 && now - last < STALE_CHUNK_RELOAD_GUARD_MS) {
      return false;
    }
    deps.storage.setItem(STALE_CHUNK_RELOAD_KEY, String(now));
  } catch {
    // Storage refused (private mode, quota): no memory, so no reload.
    return false;
  }
  deps.reload();
  return true;
}

/**
 * True when `html` is this console's index.html and names another entry
 * script than `entry`, the one this tab runs: a new build has been deployed.
 * A page with no module script at all is not the console's index — a proxy's
 * error page, a captive portal — and proves nothing.
 */
export function indexNamesAnotherBuild(html: string, entry: string): boolean {
  return /<script\b[^>]*\btype=["']?module\b/i.test(html) && !html.includes(entry);
}

/** What the recovery needs from the browser; a spec hands over its own. */
export interface StaleChunkEnv {
  storage: Pick<Storage, 'getItem' | 'setItem'> | null;
  now: () => number;
  /** False when the browser knows it has no network. */
  online: () => boolean;
  /** The entry script this tab runs, as its index.html names it; null if unknown. */
  entryScript: () => string | null;
  /** The index.html the server serves now; null when it cannot be read. */
  fetchIndex: () => Promise<string | null>;
  /** The address of the page shown now. */
  currentHref: () => string;
  /** Load `href` as a whole new document. */
  goTo: (href: string) => void;
  /**
   * Tell the reader the page could not be loaded, until they dismiss it;
   * `retry` is its « Recharger » action. Returns what takes the message down.
   */
  notify: (retry: () => void, offline?: boolean) => () => void;
  /**
   * Call `listener` once, when the browser says it is back online. Returns
   * what cancels the wait. Optional: a spec that does not need it leaves it out.
   */
  whenOnline?: (listener: () => void) => () => void;
  /** Where an error nobody else reports goes. */
  logError: (error: unknown) => void;
}

/** Has the server a newer build than the one this tab runs? */
async function buildChanged(env: StaleChunkEnv): Promise<boolean> {
  const entry = env.entryScript();
  // No entry script to compare with (the dev server): nothing can be proved.
  if (!entry) return false;
  try {
    const html = await env.fetchIndex();
    return html !== null && indexNamesAnotherBuild(html, entry);
  } catch {
    return false;
  }
}

export type ChunkFailureOutcome = 'reloaded' | 'notified';

/**
 * A chunk of the page at `href` could not be loaded. Reload on `href` when a
 * new build explains it; otherwise leave the console alone and say so.
 */
export async function recoverFromChunkFailure(
  href: string,
  env: StaleChunkEnv,
  onNotified: (dismiss: () => void) => void = () => undefined,
  onOffline: (cancel: () => void) => void = () => undefined,
): Promise<ChunkFailureOutcome> {
  const online = env.online();
  if (
    online &&
    (await buildChanged(env)) &&
    reloadOnceForStaleChunk({ storage: env.storage, now: env.now, reload: () => env.goTo(href) })
  ) {
    return 'reloaded';
  }
  // Offline: the browser keeps the failed import for the life of the
  // document, so the page stays unreachable after the network comes back —
  // whatever is clicked. Reloaded once, on the page asked for, as soon as the
  // browser says it is back online.
  if (!online && env.whenOnline) onOffline(env.whenOnline(() => env.goTo(href)));
  onNotified(env.notify(() => env.goTo(href), !online));
  return 'notified';
}

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** The browser's side of the recovery. */
export function browserStaleChunkEnv(): StaleChunkEnv {
  return {
    storage: sessionStore(),
    now: () => Date.now(),
    // `onLine` is only trusted when it says no: true means « a network
    // interface is up », not that the server answers — the fetch tells that.
    online: () => typeof navigator === 'undefined' || navigator.onLine !== false,
    entryScript: () =>
      document.querySelector('script[type="module"][src]')?.getAttribute('src') ?? null,
    fetchIndex: async () => {
      const response = await fetch(`${import.meta.env.BASE_URL ?? '/'}index.html`, {
        cache: 'no-store',
      });
      return response.ok ? await response.text() : null;
    },
    currentHref: () => window.location.href,
    goTo: (href) => {
      const here = new URL(window.location.href);
      const target = new URL(href, here);
      const sameDocument =
        target.origin === here.origin &&
        target.pathname === here.pathname &&
        target.search === here.search;
      if (target.href !== here.href) window.location.assign(target.href);
      // The same address, or one that differs by its fragment only (hash
      // mode): assigning it loads nothing.
      if (sameDocument) window.location.reload();
    },
    whenOnline: (listener) => {
      window.addEventListener('online', listener, { once: true });
      return () => window.removeEventListener('online', listener);
    },
    notify: (retry, offline) =>
      Notify.create({
        type: 'negative',
        message: chunkLoadFailedMessage(),
        ...(offline ? { caption: chunkLoadOfflineCaption() } : {}),
        // Stays until dismissed: the reader may be looking elsewhere when the
        // click on a menu entry does nothing.
        timeout: 0,
        // One message at a time is this module's own business (it takes the
        // previous one down): no « 2 », « 3 » badge counting the clicks.
        group: false,
        actions: [
          { label: t('layout.staleChunk.reload'), color: 'white', handler: retry },
          { label: t('layout.staleChunk.close'), color: 'white' },
        ],
      }),
    logError: (error) => console.error(error),
  };
}

/**
 * Listen for both ways a chunk that cannot be loaded shows: Vite's own
 * preload failure, and a lazy route component that failed to load during a
 * navigation. Either way the recovery targets the page the reader was going
 * to, not the one being left.
 */
export function installStaleChunkReload(
  router: Router,
  env: StaleChunkEnv = browserStaleChunkEnv(),
): void {
  // Where the navigation under way is going: Vite's event does not say.
  let destination: string | null = null;
  // One failed navigation raises both events, with the same error.
  const handled = new WeakSet<object>();
  let recovering = false;
  let dismiss: (() => void) | null = null;
  // The reload waiting for the network, for the latest page asked for only.
  let cancelOnline: (() => void) | null = null;

  function recover(error: unknown, href: string) {
    if (typeof error === 'object' && error !== null) {
      if (handled.has(error)) return;
      handled.add(error);
    }
    if (recovering) return;
    recovering = true;
    void recoverFromChunkFailure(
      href,
      env,
      (close) => {
        // One message, however many clicks on the dead link.
        dismiss?.();
        dismiss = close;
      },
      (cancel) => {
        cancelOnline?.();
        cancelOnline = cancel;
      },
    ).finally(() => {
      recovering = false;
    });
  }

  router.beforeEach((to) => {
    destination = to.fullPath;
  });
  router.afterEach((_to, _from, failure) => {
    destination = null;
    // A page opened after all: the message no longer describes anything.
    if (!failure) {
      dismiss?.();
      dismiss = null;
    }
  });

  window.addEventListener('vite:preloadError', (event) => {
    const error = (event as Event & { payload?: unknown }).payload;
    // Not prevented: the import must still fail for whoever awaits it — the
    // router, for one, which would otherwise render a route with no component.
    if (!isChunkLoadError(error)) return;
    recover(error, destination ? router.resolve(destination).href : env.currentHref());
  });

  router.onError((error, to) => {
    destination = null;
    // Registering a listener silences vue-router's own console.error: every
    // navigation error still has to reach the console.
    env.logError(error);
    if (isChunkLoadError(error)) recover(error, router.resolve(to.fullPath).href);
  });
}
