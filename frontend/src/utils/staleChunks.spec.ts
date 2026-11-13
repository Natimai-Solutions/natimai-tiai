import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Router } from 'vue-router';
import {
  STALE_CHUNK_RELOAD_GUARD_MS,
  STALE_CHUNK_RELOAD_KEY,
  installStaleChunkReload,
  isChunkLoadError,
  reloadOnceForStaleChunk,
} from './staleChunks';

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
  };
}

describe('isChunkLoadError', () => {
  it('recognises a lazy chunk that could not be fetched, in each browser’s words', () => {
    for (const message of [
      'Failed to fetch dynamically imported module: https://tiai/assets/MachinesPage-1a2b.js',
      'error loading dynamically imported module',
      'Importing a module script failed.',
      'Unable to preload CSS for /assets/MachinesPage-1a2b.css',
    ]) {
      expect(isChunkLoadError(new Error(message))).toBe(true);
    }
  });

  it('leaves every other navigation error alone', () => {
    expect(isChunkLoadError(new Error('Request failed with status code 500'))).toBe(false);
    expect(isChunkLoadError(null)).toBe(false);
  });
});

describe('reloadOnceForStaleChunk (audit S34)', () => {
  it('reloads, and remembers when', () => {
    const storage = memoryStorage();
    const reload = vi.fn();

    expect(reloadOnceForStaleChunk({ storage, now: () => 1_000_000, reload })).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(storage.getItem(STALE_CHUNK_RELOAD_KEY)).toBe('1000000');
  });

  it('does not reload again right after a reload: that would loop', () => {
    const storage = memoryStorage({ [STALE_CHUNK_RELOAD_KEY]: '1000000' });
    const reload = vi.fn();

    const again = reloadOnceForStaleChunk({
      storage,
      now: () => 1_000_000 + STALE_CHUNK_RELOAD_GUARD_MS - 1,
      reload,
    });

    expect(again).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it('reloads again for a later deployment', () => {
    const storage = memoryStorage({ [STALE_CHUNK_RELOAD_KEY]: '1000000' });
    const reload = vi.fn();

    reloadOnceForStaleChunk({
      storage,
      now: () => 1_000_000 + STALE_CHUNK_RELOAD_GUARD_MS + 1,
      reload,
    });

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('never reloads without a storage to remember it in', () => {
    const reload = vi.fn();
    expect(reloadOnceForStaleChunk({ storage: null, now: () => 1, reload })).toBe(false);

    const refusing = {
      getItem: () => null,
      setItem: () => {
        throw new Error('QuotaExceededError');
      },
    };
    expect(reloadOnceForStaleChunk({ storage: refusing, now: () => 1, reload })).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});

describe('installStaleChunkReload', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function fakeWindow() {
    const target = new EventTarget();
    const location = { reload: vi.fn(), assign: vi.fn() };
    vi.stubGlobal('window', {
      addEventListener: target.addEventListener.bind(target),
      dispatchEvent: target.dispatchEvent.bind(target),
      sessionStorage: memoryStorage(),
      location,
    });
    return { target, location };
  }

  function fakeRouter() {
    let handler: ((error: unknown, to: { fullPath: string }) => void) | null = null;
    const router = {
      onError: (cb: typeof handler) => {
        handler = cb;
      },
      resolve: (path: string) => ({ href: `/console${path}` }),
    };
    return {
      router: router as unknown as Router,
      fail: (e: unknown, to: string) => handler!(e, { fullPath: to }),
    };
  }

  it('reloads on Vite’s preload error, once, and keeps the error from surfacing', () => {
    const { target, location } = fakeWindow();
    installStaleChunkReload(fakeRouter().router);

    const first = new Event('vite:preloadError', { cancelable: true });
    target.dispatchEvent(first);
    const second = new Event('vite:preloadError', { cancelable: true });
    target.dispatchEvent(second);

    expect(location.reload).toHaveBeenCalledTimes(1);
    expect(first.defaultPrevented).toBe(true);
    expect(second.defaultPrevented).toBe(false);
  });

  it('reloads on the page being opened when its chunk fails to load', () => {
    const { location } = fakeWindow();
    const { router, fail } = fakeRouter();
    installStaleChunkReload(router);

    fail(new Error('Request failed with status code 500'), '/software');
    expect(location.assign).not.toHaveBeenCalled();

    fail(new TypeError('Failed to fetch dynamically imported module: /assets/x.js'), '/software');
    expect(location.assign).toHaveBeenCalledWith('/console/software');
  });
});
