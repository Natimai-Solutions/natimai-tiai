import type { Router } from 'vue-router';

/**
 * A console tab opened before a deployment still runs the old build: the
 * pages it has not opened yet are lazy chunks whose hashed names the new
 * build no longer serves, and every navigation to one fails with a 404 until
 * the reader reloads by hand (audit S34). The cure is that reload, done for
 * them — once: if the fresh page fails the same way, the problem is not a
 * stale tab, and reloading again would loop.
 */

/** When the last reload for a stale chunk happened, per tab. */
export const STALE_CHUNK_RELOAD_KEY = 'tiai.staleChunkReloadAt';
/** A second failure within this window is not a stale tab: no reload then. */
export const STALE_CHUNK_RELOAD_GUARD_MS = 30_000;

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

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * Listen for both ways a stale chunk shows: Vite's own preload failure, and a
 * lazy route component that failed to load during a navigation — reloaded on
 * the page the reader was going to.
 */
export function installStaleChunkReload(router: Router): void {
  window.addEventListener('vite:preloadError', (event) => {
    const reloaded = reloadOnceForStaleChunk({
      storage: sessionStore(),
      now: () => Date.now(),
      reload: () => window.location.reload(),
    });
    // Reloading: the error would only reach the console on its way out.
    if (reloaded) event.preventDefault();
  });
  router.onError((error, to) => {
    if (!isChunkLoadError(error)) return;
    reloadOnceForStaleChunk({
      storage: sessionStore(),
      now: () => Date.now(),
      reload: () => window.location.assign(router.resolve(to.fullPath).href),
    });
  });
}
