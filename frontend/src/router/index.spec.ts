// @vitest-environment jsdom
// The router as the app builds it — its scroll behaviour and its recovery from
// a chunk that cannot be loaded are wired here and nowhere else, so they are
// checked here: on the real `createRouter`, with a route table of three pages.
import { Notify } from 'quasar';
import { START_LOCATION, type Router, type RouteLocationNormalized } from 'vue-router';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { SCROLL_RESTORE_TIMEOUT_MS } from 'src/utils/scrollRestore';
import { CHUNK_LOAD_FAILED_MESSAGE } from 'src/utils/staleChunks';

vi.mock('boot/axios', () => ({ refreshSession: vi.fn() }));
vi.mock('src/services/session', () => ({
  ensureSession: () => Promise.resolve(true),
  getAccessToken: () => 'token',
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({ ensureProfile: () => Promise.resolve() }),
  readCachedPermissions: () => [],
}));
vi.mock('./routes', () => {
  const page = { render: () => null };
  return {
    default: [
      { path: '/list', component: page },
      { path: '/fiche/:id', component: page },
      { path: '/other', component: page },
      {
        path: '/stale',
        component: () =>
          Promise.reject(
            new TypeError('Failed to fetch dynamically imported module: /assets/Stale-1a2b.js'),
          ),
      },
      { path: '/broken', component: () => Promise.reject(new Error('boom')) },
    ],
  };
});

type ScrollBehavior = NonNullable<Router['options']['scrollBehavior']>;

let router: Router;
let scrollBehavior: ScrollBehavior;
/** The document's height, which jsdom does not lay out. */
let pageHeight = 0;

beforeAll(async () => {
  // jsdom's history has no `scrollRestoration`; without it set to manual —
  // which the router does in a browser — no position is saved on leaving.
  Object.defineProperty(window.history, 'scrollRestoration', { value: 'manual', writable: true });
  const createAppRouter = (await import('./index')).default as unknown as () => Router;
  router = createAppRouter();
  scrollBehavior = router.options.scrollBehavior!;
  Object.defineProperty(document.documentElement, 'scrollHeight', {
    configurable: true,
    get: () => pageHeight,
  });
  // jsdom implements no scrolling; the router calls this after scrollBehavior.
  window.scrollTo = vi.fn();
});

afterAll(() => {
  delete (document.documentElement as { scrollHeight?: number }).scrollHeight;
});

/** Track how a promise settles without awaiting it. */
function watch<T>(result: T | PromiseLike<T>) {
  const state: { settled: boolean; value?: T } = { settled: false };
  void Promise.resolve(result).then((value) => {
    state.settled = true;
    state.value = value;
  });
  return state;
}

describe('scroll behaviour (audit U10)', () => {
  beforeEach(async () => {
    pageHeight = 0;
    await router.push('/other');
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  /** Open the list as Back does, and ask where to scroll: `saved` is known. */
  async function backToList(saved = { left: 0, top: 1800 }) {
    const from = router.currentRoute.value;
    await router.push('/list?search=pc');
    return watch(scrollBehavior(router.currentRoute.value, from, saved));
  }

  it('holds the saved position until the page is tall enough to reach it', async () => {
    const state = await backToList();

    // The list has no rows yet: scrolling now would be clamped to the top.
    await vi.advanceTimersByTimeAsync(500);
    expect(state.settled).toBe(false);

    // Its rows arrive: 4,000 px of them, in a 768 px window.
    pageHeight = 4000;
    await vi.advanceTimersByTimeAsync(100);
    expect(state.settled).toBe(true);
    expect(state.value).toEqual({ left: 0, top: 1800 });
  });

  it('keeps the position when the page writes its own URL back as it loads', async () => {
    const state = await backToList();

    // What SoftwarePage's load() does: the router answers « duplicated » and
    // asks for the scroll again, for the same route.
    await router.replace({ query: { search: 'pc' } });
    await vi.advanceTimersByTimeAsync(0);
    expect(router.currentRoute.value.fullPath).toBe('/list?search=pc');

    pageHeight = 4000;
    await vi.advanceTimersByTimeAsync(100);
    expect(state.settled).toBe(true);
    expect(state.value).toEqual({ left: 0, top: 1800 });
  });

  it('drops the position once the reader has opened another page', async () => {
    const state = await backToList();

    await router.push('/fiche/1');
    pageHeight = 4000;
    await vi.advanceTimersByTimeAsync(100);
    expect(state.settled).toBe(true);
    // No scroll: the list's position does not belong to the fiche.
    expect(state.value).toBe(false);
  });

  it('gives up on a list now too short for the position, without scrolling', async () => {
    const state = await backToList();
    pageHeight = 1000;

    await vi.advanceTimersByTimeAsync(SCROLL_RESTORE_TIMEOUT_MS + 100);
    expect(state.settled).toBe(true);
    expect(state.value).toBe(false);
  });

  it('drops the position when the reader scrolls by themselves meanwhile', async () => {
    const state = await backToList();

    window.dispatchEvent(new Event('wheel'));
    pageHeight = 4000;
    await vi.advanceTimersByTimeAsync(100);
    expect(state.settled).toBe(true);
    expect(state.value).toBe(false);
  });

  it('shows the first page of the tab from the top, whatever history kept', async () => {
    // A reload: the router hands over the position saved when the entry was
    // last left, which is not where the reader is.
    const to = router.currentRoute.value;
    const state = watch(scrollBehavior(to, START_LOCATION, { left: 0, top: 1800 }));
    pageHeight = 4000;
    await vi.advanceTimersByTimeAsync(SCROLL_RESTORE_TIMEOUT_MS + 100);

    expect(state.settled).toBe(true);
    expect(state.value).toBe(false);
  });

  it('starts another page at the top, and stays put for a query change on the same page', async () => {
    const list = router.resolve('/list') as RouteLocationNormalized;
    const filtered = router.resolve('/list?search=pc') as RouteLocationNormalized;
    const fiche = router.resolve('/fiche/1') as RouteLocationNormalized;

    expect(await scrollBehavior(fiche, list, null)).toEqual({ left: 0, top: 0 });
    expect(await scrollBehavior(filtered, list, null)).toBe(false);
  });

  it('is what the router scrolls by: Back to the list scrolls it once its rows are there', async () => {
    vi.useRealTimers();
    const scrollTo = vi.mocked(window.scrollTo);
    const scrollY = vi.spyOn(window, 'scrollY', 'get');

    await router.push('/list');
    // The reader is 1,800 px down the list when they open a fiche.
    pageHeight = 4000;
    scrollY.mockReturnValue(1800);
    await router.push('/fiche/1');
    scrollY.mockReturnValue(0);

    // (The router scrolls the fiche to the top a tick after the navigation.)
    await vi.waitFor(() => expect(scrollTo).toHaveBeenLastCalledWith({ left: 0, top: 0 }));

    // Back: the list is empty again while its rows are fetched.
    pageHeight = 0;
    scrollTo.mockClear();
    const arrived = new Promise<void>((resolve) => {
      const stop = router.afterEach(() => {
        stop();
        resolve();
      });
    });
    router.back();
    await arrived;
    expect(router.currentRoute.value.path).toBe('/list');
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(scrollTo).not.toHaveBeenCalled();

    pageHeight = 4000;
    await vi.waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(1));
    const [position] = scrollTo.mock.calls[0] as unknown as [{ top: number } | number, number?];
    expect(typeof position === 'number' ? scrollTo.mock.calls[0]![1] : position.top).toBe(1800);
    scrollY.mockRestore();
  });
});

describe('a chunk that cannot be loaded (audit S34)', () => {
  const plugin = Notify as unknown as { create?: unknown };
  let installed: unknown;
  let create: ReturnType<typeof vi.fn>;
  let logged: ReturnType<typeof vi.spyOn>;
  let online: ReturnType<typeof vi.spyOn>;

  beforeEach(async () => {
    await router.push('/other');
    installed = plugin.create;
    create = vi.fn(() => () => undefined);
    plugin.create = create;
    logged = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    online = vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false);
  });
  afterEach(() => {
    if (installed) plugin.create = installed;
    else delete plugin.create;
    logged.mockRestore();
    online.mockRestore();
  });

  it('is told to the reader, offline, instead of a reload — and the console stays', async () => {
    await router.push('/stale').catch(() => undefined);
    await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(1));

    expect((create.mock.calls[0]![0] as { message: string }).message).toBe(
      CHUNK_LOAD_FAILED_MESSAGE,
    );
    // The page the reader was on is still there.
    expect(router.currentRoute.value.path).toBe('/other');
  });

  it('leaves every other navigation error in the console, with no message', async () => {
    await router.push('/broken').catch(() => undefined);

    expect(logged).toHaveBeenCalledWith(expect.objectContaining({ message: 'boom' }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(create).not.toHaveBeenCalled();
  });
});
