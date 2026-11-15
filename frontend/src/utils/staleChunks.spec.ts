// @vitest-environment jsdom
// (`quasar`, imported for its Notify plugin, needs a window to load.)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Notify } from 'quasar';
import type { Router } from 'vue-router';
import {
  CHUNK_LOAD_FAILED_MESSAGE,
  STALE_CHUNK_RELOAD_GUARD_MS,
  STALE_CHUNK_RELOAD_KEY,
  browserStaleChunkEnv,
  indexNamesAnotherBuild,
  installStaleChunkReload,
  isChunkLoadError,
  reloadOnceForStaleChunk,
  type StaleChunkEnv,
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

const ENTRY = '/assets/index-OLD11111.js';
const SAME_BUILD = `<!doctype html><html><head><script type="module" crossorigin src="${ENTRY}"></script></head><body><div id=q-app></div></body></html>`;
const NEW_BUILD = SAME_BUILD.replace('OLD11111', 'NEW22222');
const CHUNK_ERROR = () =>
  new TypeError('Failed to fetch dynamically imported module: /assets/SoftwarePage-1a2b.js');

describe('indexNamesAnotherBuild', () => {
  it('tells a new build by the entry script its index.html names', () => {
    expect(indexNamesAnotherBuild(NEW_BUILD, ENTRY)).toBe(true);
    expect(indexNamesAnotherBuild(SAME_BUILD, ENTRY)).toBe(false);
  });

  it('proves nothing from a page that is not the console’s index', () => {
    expect(indexNamesAnotherBuild('<html><body>502 Bad Gateway</body></html>', ENTRY)).toBe(false);
  });
});

describe('installStaleChunkReload', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** A window that only carries events: everything else comes through `env`. */
  function fakeWindow() {
    const target = new EventTarget();
    vi.stubGlobal('window', {
      addEventListener: target.addEventListener.bind(target),
      dispatchEvent: target.dispatchEvent.bind(target),
    });
    return target;
  }

  type Guard = (to: { fullPath: string }, from?: unknown, failure?: unknown) => void;

  function fakeRouter() {
    const hooks: { before: Guard[]; after: Guard[]; error: Guard[] } = {
      before: [],
      after: [],
      error: [],
    };
    const router = {
      beforeEach: (cb: Guard) => void hooks.before.push(cb),
      afterEach: (cb: Guard) => void hooks.after.push(cb),
      onError: (cb: (error: unknown, to: { fullPath: string }) => void) =>
        void hooks.error.push((to, _from, error) => cb(error, to)),
      resolve: (path: string) => ({ href: `/console${path}` }),
    };
    return {
      router: router as unknown as Router,
      /** A navigation starts. */
      start: (to: string) => hooks.before.forEach((cb) => cb({ fullPath: to })),
      /** A navigation ends, on a page or on a failure the router reports as such. */
      end: (to: string, failure?: unknown) =>
        hooks.after.forEach((cb) => cb({ fullPath: to }, undefined, failure)),
      /** A navigation throws. */
      fail: (error: unknown, to: string) =>
        hooks.error.forEach((cb) => cb({ fullPath: to }, undefined, error)),
    };
  }

  function fakeEnv(over: Partial<StaleChunkEnv> = {}) {
    const dismiss = vi.fn();
    const notify = vi.fn((retry: () => void) => {
      void retry;
      return dismiss;
    });
    const env = {
      storage: memoryStorage(),
      now: () => 1_000_000,
      online: () => true,
      entryScript: () => ENTRY as string | null,
      fetchIndex: vi.fn(() => Promise.resolve<string | null>(NEW_BUILD)),
      currentHref: () => 'https://tiai/console/machines',
      goTo: vi.fn(),
      logError: vi.fn(),
      ...over,
      notify,
    };
    return { env, dismiss };
  }

  /** Let the check of the server's index.html run to its end. */
  async function settle() {
    for (let k = 0; k < 10; k++) await Promise.resolve();
  }

  function preloadError(target: EventTarget, payload: unknown) {
    const event = Object.assign(new Event('vite:preloadError', { cancelable: true }), { payload });
    target.dispatchEvent(event);
    return event;
  }

  it('reloads once, on the page being opened, when the server has a new build', async () => {
    const target = fakeWindow();
    const { router, start, fail } = fakeRouter();
    const { env } = fakeEnv();
    installStaleChunkReload(router, env);

    // What a click on « Logiciels » does in a tab left open over a
    // deployment: Vite's event first, then the router's error, same error.
    const error = CHUNK_ERROR();
    start('/software');
    const event = preloadError(target, error);
    fail(error, '/software');
    await settle();

    expect(env.fetchIndex).toHaveBeenCalledTimes(1);
    expect(env.goTo).toHaveBeenCalledTimes(1);
    // The destination, not the page being left.
    expect(env.goTo).toHaveBeenCalledWith('/console/software');
    expect(env.notify).not.toHaveBeenCalled();
    // The import must still fail for the router: the event is left alone.
    expect(event.defaultPrevented).toBe(false);
  });

  it('does not reload when the browser is offline, and says the page could not be loaded', async () => {
    fakeWindow();
    const { router, start, fail } = fakeRouter();
    const { env } = fakeEnv({ online: () => false });
    installStaleChunkReload(router, env);

    start('/software');
    fail(CHUNK_ERROR(), '/software');
    await settle();

    expect(env.goTo).not.toHaveBeenCalled();
    // Not even asked: offline, the answer is known.
    expect(env.fetchIndex).not.toHaveBeenCalled();
    expect(env.notify).toHaveBeenCalledTimes(1);

    // « Recharger » goes to the page that was asked for.
    env.notify.mock.calls[0]![0]();
    expect(env.goTo).toHaveBeenCalledWith('/console/software');
  });

  it('does not reload when the server still serves the same build', async () => {
    fakeWindow();
    const { router, fail } = fakeRouter();
    const { env } = fakeEnv({
      fetchIndex: vi.fn(() => Promise.resolve<string | null>(SAME_BUILD)),
    });
    installStaleChunkReload(router, env);

    fail(CHUNK_ERROR(), '/software');
    await settle();

    expect(env.fetchIndex).toHaveBeenCalledTimes(1);
    expect(env.goTo).not.toHaveBeenCalled();
    expect(env.notify).toHaveBeenCalledTimes(1);
  });

  it('does not reload when the server cannot be reached or the build cannot be told', async () => {
    for (const over of [
      { fetchIndex: vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) },
      { fetchIndex: vi.fn(() => Promise.resolve<string | null>(null)) },
      { entryScript: () => null },
    ]) {
      fakeWindow();
      const { router, fail } = fakeRouter();
      const { env } = fakeEnv(over);
      installStaleChunkReload(router, env);

      fail(CHUNK_ERROR(), '/software');
      await settle();

      expect(env.goTo).not.toHaveBeenCalled();
      expect(env.notify).toHaveBeenCalledTimes(1);
    }
  });

  it('reloads once per 30 s: a chunk still missing after the reload is said, not reloaded again', async () => {
    fakeWindow();
    const { router, fail } = fakeRouter();
    let now = 1_000_000;
    const { env } = fakeEnv({ now: () => now });
    installStaleChunkReload(router, env);

    fail(CHUNK_ERROR(), '/software');
    await settle();
    expect(env.goTo).toHaveBeenCalledTimes(1);

    now += STALE_CHUNK_RELOAD_GUARD_MS - 1;
    fail(CHUNK_ERROR(), '/software');
    await settle();
    expect(env.goTo).toHaveBeenCalledTimes(1);
    expect(env.notify).toHaveBeenCalledTimes(1);

    now += 2;
    fail(CHUNK_ERROR(), '/software');
    await settle();
    expect(env.goTo).toHaveBeenCalledTimes(2);
  });

  it('logs a navigation error that is not a chunk, and reloads nothing', async () => {
    const target = fakeWindow();
    const { router, fail } = fakeRouter();
    const { env } = fakeEnv();
    installStaleChunkReload(router, env);

    const error = new Error('Request failed with status code 500');
    fail(error, '/software');
    // Vite raises its event for any rejected import: a module that throws as
    // it evaluates is not a chunk that could not be fetched.
    preloadError(target, new TypeError('x is not a function'));
    preloadError(target, undefined);
    await settle();

    expect(env.logError).toHaveBeenCalledWith(error);
    expect(env.fetchIndex).not.toHaveBeenCalled();
    expect(env.goTo).not.toHaveBeenCalled();
    expect(env.notify).not.toHaveBeenCalled();
  });

  it('logs the chunk error too: the router no longer does once it has a listener', async () => {
    fakeWindow();
    const { router, fail } = fakeRouter();
    const { env } = fakeEnv();
    installStaleChunkReload(router, env);

    const error = CHUNK_ERROR();
    fail(error, '/software');
    await settle();

    expect(env.logError).toHaveBeenCalledWith(error);
  });

  it('recovers on the current page when a chunk fails outside a navigation', async () => {
    const target = fakeWindow();
    const { router, start, end } = fakeRouter();
    const { env } = fakeEnv();
    installStaleChunkReload(router, env);

    // A navigation that ended is no longer where the reader is going.
    start('/software');
    end('/software');
    preloadError(target, CHUNK_ERROR());
    await settle();

    expect(env.goTo).toHaveBeenCalledWith('https://tiai/console/machines');
  });

  it('targets the page being opened from Vite’s event alone', async () => {
    const target = fakeWindow();
    const { router, start } = fakeRouter();
    const { env } = fakeEnv();
    installStaleChunkReload(router, env);

    start('/software');
    preloadError(target, CHUNK_ERROR());
    await settle();

    expect(env.goTo).toHaveBeenCalledWith('/console/software');
  });

  it('shows one message however many times the dead link is clicked, and takes it down once a page opens', async () => {
    fakeWindow();
    const { router, fail, end } = fakeRouter();
    const { env, dismiss } = fakeEnv({ online: () => false });
    installStaleChunkReload(router, env);

    fail(CHUNK_ERROR(), '/software');
    await settle();
    fail(CHUNK_ERROR(), '/software');
    await settle();
    expect(env.notify).toHaveBeenCalledTimes(2);
    // The first message was taken down for the second.
    expect(dismiss).toHaveBeenCalledTimes(1);

    // A navigation the router gave up on is not a page opened.
    end('/machines', new Error('Navigation aborted'));
    expect(dismiss).toHaveBeenCalledTimes(1);
    end('/machines');
    expect(dismiss).toHaveBeenCalledTimes(2);
  });
});

describe('browserStaleChunkEnv', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubBrowser(href: string) {
    const location = { href, reload: vi.fn(), assign: vi.fn() };
    vi.stubGlobal('window', { location, sessionStorage: memoryStorage() });
    return location;
  }

  it('trusts navigator.onLine only when it says no', () => {
    stubBrowser('https://tiai/machines');
    vi.stubGlobal('navigator', { onLine: false });
    expect(browserStaleChunkEnv().online()).toBe(false);
    vi.stubGlobal('navigator', { onLine: true });
    expect(browserStaleChunkEnv().online()).toBe(true);
  });

  it('reads the entry script from the document', () => {
    stubBrowser('https://tiai/machines');
    const querySelector = vi.fn(() => ({ getAttribute: () => ENTRY }));
    vi.stubGlobal('document', { querySelector });
    expect(browserStaleChunkEnv().entryScript()).toBe(ENTRY);
    expect(querySelector).toHaveBeenCalledWith('script[type="module"][src]');
  });

  it('asks the server for its index.html, past every cache', async () => {
    stubBrowser('https://tiai/machines');
    const fetch = vi.fn(() =>
      Promise.resolve({ ok: true, text: () => Promise.resolve(NEW_BUILD) }),
    );
    vi.stubGlobal('fetch', fetch);

    expect(await browserStaleChunkEnv().fetchIndex()).toBe(NEW_BUILD);
    expect(fetch).toHaveBeenCalledWith('/index.html', { cache: 'no-store' });

    // A 502 page from the proxy is not the console's index.
    fetch.mockResolvedValueOnce({ ok: false, text: () => Promise.resolve('<html>') });
    expect(await browserStaleChunkEnv().fetchIndex()).toBeNull();
  });

  it('loads another page by its address, and the same page by a reload', () => {
    const location = stubBrowser('https://tiai/machines?page=2');
    const env = browserStaleChunkEnv();

    env.goTo('/software');
    expect(location.assign).toHaveBeenCalledWith('https://tiai/software');
    expect(location.reload).not.toHaveBeenCalled();

    location.assign.mockClear();
    env.goTo('https://tiai/machines?page=2');
    expect(location.assign).not.toHaveBeenCalled();
    expect(location.reload).toHaveBeenCalledTimes(1);

    // Hash mode: an address that differs by its fragment loads nothing alone.
    env.goTo('/machines?page=2#/software');
    expect(location.assign).toHaveBeenCalledWith('https://tiai/machines?page=2#/software');
    expect(location.reload).toHaveBeenCalledTimes(2);
  });

  it('says the page could not be loaded in a notification that stays, with « Recharger »', () => {
    stubBrowser('https://tiai/machines');
    const close = vi.fn();
    // `Notify.create` only exists once Quasar has installed the plugin, which
    // the app does before its router: stand in for it here.
    const create = vi.fn((options: unknown) => {
      void options;
      return close;
    });
    const plugin = Notify as unknown as { create?: typeof create };
    const installed = plugin.create;
    plugin.create = create;
    const retry = vi.fn();

    expect(browserStaleChunkEnv().notify(retry)).toBe(close);

    const options = create.mock.calls[0]![0] as {
      message: string;
      timeout: number;
      group: boolean;
      actions: { label: string; handler?: () => void }[];
    };
    expect(options.message).toBe(CHUNK_LOAD_FAILED_MESSAGE);
    expect(options.message).toBe(
      'Impossible de charger cette page (connexion ou mise à jour en cours). Réessayez.',
    );
    expect(options.timeout).toBe(0);
    // Not grouped: Quasar would count repeated failures in a badge on it.
    expect(options.group).toBe(false);
    const reload = options.actions.find((a) => a.label === 'Recharger')!;
    reload.handler!();
    expect(retry).toHaveBeenCalledTimes(1);
    if (installed) plugin.create = installed;
    else delete plugin.create;
  });
});
