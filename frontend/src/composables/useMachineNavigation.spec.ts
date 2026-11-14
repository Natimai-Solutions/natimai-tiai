// @vitest-environment jsdom
// This composable is driven by the router and needs a component to live in, so
// it is the one spec that wants a DOM. The suite as a whole stays on `node` —
// see vitest.config.ts.
import type { AxiosRequestConfig } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { api } from 'boot/axios';
import { resetMachineNavigation, useMachineNavigation } from './useMachineNavigation';

/**
 * The composable walks a search by reading it in blocks of 50 rows, frozen
 * for the session, so every test here drives it through the axios mock and a
 * real (memory) router — the two things it actually talks to.
 */

const Stub = defineComponent({ render: () => h('div') });

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub, props: true },
    ],
  });
}

function machine(id: string) {
  return { id, machine_uuid: `uuid-${id}`, hostname: id.toUpperCase() };
}

/**
 * Answer /machines from a search of `total` rows: the ones given by rank, and
 * a filler for every other rank.
 */
function respondWith(rowsByRank: Record<number, unknown>, total: number) {
  // `config` must be typed as axios sees it (parameters are contravariant),
  // so the page is narrowed from `params` rather than declared on the way in.
  vi.mocked(api.get).mockImplementation((_url: string, config?: AxiosRequestConfig) => {
    const params = config?.params as { page?: number; page_size?: number } | undefined;
    const page = params?.page ?? 1;
    const size = params?.page_size ?? 50;
    const items = [];
    for (let r = (page - 1) * size; r < Math.min(page * size, total); r++) {
      items.push(rowsByRank[r] ?? machine(`r${r}`));
    }
    return Promise.resolve({ data: { items, total, page, page_size: size } });
  });
}

/** Mount the composable inside a component on the given detail route. */
async function mount(router: ReturnType<typeof makeRouter>, path: string) {
  let nav!: ReturnType<typeof useMachineNavigation>;
  const Host = defineComponent({
    setup() {
      nav = useMachineNavigation();
      return () => h('div');
    },
  });
  await router.push(path);
  const { createApp } = await import('vue');
  const app = createApp(Host);
  app.use(router);
  app.mount(document.createElement('div'));
  await nextTick();
  return { nav, app };
}

describe('useMachineNavigation', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    resetMachineNavigation();
  });

  it('stays silent when the fiche was not opened from a search', async () => {
    respondWith({}, 0);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc');

    expect(nav.fromSearch.value).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('resolves both neighbours and the position in the search', async () => {
    respondWith({ 4: machine('prev'), 5: machine('abc'), 6: machine('next') }, 340);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&i=5');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.previousMachine.value?.id).toBe('prev');
    expect(nav.nextMachine.value?.id).toBe('next');
    expect(nav.positionLabel.value).toBe('Poste 6 sur 340');
  });

  it('carries the search filters into every neighbour lookup', async () => {
    respondWith({ 0: machine('abc'), 1: machine('next') }, 2);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&search=pc&i=0');
    await vi.waitUntil(() => nav.total.value !== null);

    // One block holds the poste and both neighbours: one request.
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith('/machines', {
      params: { status: 'outdated', search: 'pc', page: 1, page_size: 50 },
    });
  });

  it('offers no previous on the first result and no next on the last', async () => {
    respondWith({}, 1);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?i=0');
    await vi.waitUntil(() => nav.index.value === 0);

    expect(nav.previousMachine.value).toBeNull();
    expect(nav.nextMachine.value).toBeNull();
  });

  it('returns to the page that actually holds the poste, not the one opened from', async () => {
    // Opened from page 1 (no `page` in the URL), then walked to rank 59.
    // With the default page size of 50 that poste sits on page 2.
    respondWith({ 58: machine('prev'), 59: machine('abc'), 60: machine('next') }, 340);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&i=59');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.backQuery.value).toEqual({ status: 'outdated', page: '2' });
  });

  it('leaves page 1 out of the return query, as the list itself does', async () => {
    respondWith({ 0: machine('abc') }, 10);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?i=0');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.backQuery.value.page).toBeUndefined();
  });

  it('honours a non-default page size when computing the return page', async () => {
    respondWith({ 25: machine('abc') }, 100);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?page_size=25&i=25');
    await vi.waitUntil(() => nav.total.value !== null);

    // rank 25 with 25 rows per page is the first row of page 2.
    expect(nav.backQuery.value.page).toBe('2');
  });

  it('never walks to the poste it just left when clicked twice quickly', async () => {
    // The bug this guards: the neighbours belong to the *previous* poste for
    // the two round trips it takes to resolve the new ones. A second click in
    // that window used to navigate to the same machine again, with the rank
    // moved on — desynchronising identity and position for the whole session.
    //
    // The second resolution is left hanging so the window is observable rather
    // than a race: that is precisely the state a fast double-click lands in.
    // « b » is the last row of the first block: its next neighbour sits in a
    // block not read yet, whose request is left hanging.
    respondWith({ 48: machine('a'), 49: machine('b') }, 100);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/a?i=48');
    await vi.waitUntil(() => nav.nextMachine.value !== null);

    vi.mocked(api.get).mockImplementation(() => new Promise(() => {}));

    nav.goNext(); // → /machines/b?i=49
    await vi.waitUntil(() => router.currentRoute.value.params.id === 'b');

    // Mid-resolution the arrows are inert, not stale.
    expect(nav.nextMachine.value).toBeNull();
    nav.goNext(); // does nothing at all
    await nextTick();

    expect(router.currentRoute.value.params.id).toBe('b');
    expect(router.currentRoute.value.query.i).toBe('49');
  });

  it('walks the order the reader saw, not the one of the moment (audit B18)', async () => {
    respondWith({ 0: machine('a'), 1: machine('b'), 2: machine('c') }, 3);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/a?i=0');
    await vi.waitUntil(() => nav.nextMachine.value !== null);
    expect(nav.nextMachine.value?.id).toBe('b');

    // A heartbeat later, « c » was seen last and the server's order moved.
    respondWith({ 0: machine('c'), 1: machine('a'), 2: machine('b') }, 3);
    nav.goNext();
    await vi.waitUntil(() => router.currentRoute.value.params.id === 'b');
    await vi.waitUntil(() => nav.nextMachine.value !== null);
    expect(nav.previousMachine.value?.id).toBe('a');
    expect(nav.nextMachine.value?.id).toBe('c');
  });

  it('finds the poste when the list it was opened from had moved', async () => {
    // Opened as rank 0, but the order is already c, a, b.
    respondWith({ 0: machine('c'), 1: machine('a'), 2: machine('b') }, 3);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/a?i=0');
    await vi.waitUntil(() => nav.nextMachine.value !== null);
    expect(nav.index.value).toBe(1);
    expect(nav.previousMachine.value?.id).toBe('c');
    expect(nav.nextMachine.value?.id).toBe('b');
  });

  describe('across blocks of 50 (audit B18)', () => {
    /** The server answers from an ordered list of ids, as it stands now. */
    function serve(order: string[]) {
      vi.mocked(api.get).mockImplementation((_url: string, config?: AxiosRequestConfig) => {
        const params = config?.params as { page?: number; page_size?: number } | undefined;
        const page = params?.page ?? 1;
        const size = params?.page_size ?? 50;
        const items = order.slice((page - 1) * size, page * size).map(machine);
        return Promise.resolve({ data: { items, total: order.length, page, page_size: size } });
      });
    }

    async function step(
      router: ReturnType<typeof makeRouter>,
      nav: ReturnType<typeof useMachineNavigation>,
      move: () => void,
    ) {
      const before = router.currentRoute.value.fullPath;
      move();
      await vi.waitUntil(() => router.currentRoute.value.fullPath !== before);
      await vi.waitUntil(() => nav.total.value !== null);
      return String(router.currentRoute.value.params.id);
    }

    it('never shows a poste twice when the order moved before the next block was read', async () => {
      const t0 = Array.from({ length: 120 }, (_, i) => `m${i}`);
      serve(t0);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m48?i=48');
      await vi.waitUntil(() => nav.nextMachine.value !== null);

      // The last poste heartbeats: it goes to the top, every other one moves
      // down a rank — m49, last of the first block, now opens the second.
      serve(['m119', ...t0.slice(0, 119)]);
      const seen = ['m48'];
      for (let k = 0; k < 4; k++) seen.push(await step(router, nav, nav.goNext));

      expect(seen).toEqual(['m48', 'm49', 'm50', 'm51', 'm52']);
      expect(nav.positionLabel.value).toBe('Poste 53 sur 120');
      expect(nav.previousMachine.value?.id).toBe('m51');
      expect(nav.nextMachine.value?.id).toBe('m53');
    });

    it('finds the opened poste in a further block when the list had moved', async () => {
      // The list showed « x » at rank 5; by the time the fiche opens, it is at 156.
      const order = Array.from({ length: 300 }, (_, i) => `m${i}`);
      order.splice(156, 0, 'x');
      serve(order);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/x?i=5');
      await vi.waitUntil(() => nav.total.value !== null);

      expect(nav.positionLabel.value).toBe('Poste 157 sur 301');
      expect(nav.previousMachine.value?.id).toBe('m155');
      expect(nav.nextMachine.value?.id).toBe('m156');

      // Next then Previous comes back to it.
      expect(await step(router, nav, nav.goNext)).toBe('m156');
      expect(await step(router, nav, nav.goPrevious)).toBe('x');
    });

    it('finds a poste that moved up into an earlier block', async () => {
      const order = Array.from({ length: 200 }, (_, i) => `m${i}`);
      order.splice(10, 0, 'x');
      serve(order);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/x?i=120');
      await vi.waitUntil(() => nav.total.value !== null);

      expect(nav.index.value).toBe(10);
      expect(nav.previousMachine.value?.id).toBe('m9');
      expect(nav.nextMachine.value?.id).toBe('m10');
    });

    it('shows no position and no neighbours when the poste is not within reach', async () => {
      // A search of 3,000 postes that no longer holds « x » at all.
      serve(Array.from({ length: 3000 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/x?i=5');
      await vi.waitUntil(() => vi.mocked(api.get).mock.calls.length > 1);
      await vi.waitUntil(async () => {
        const n = vi.mocked(api.get).mock.calls.length;
        await new Promise((r) => setTimeout(r, 20));
        return vi.mocked(api.get).mock.calls.length === n;
      });

      expect(nav.positionLabel.value).toBe('');
      expect(nav.previousMachine.value).toBeNull();
      expect(nav.nextMachine.value).toBeNull();
      // Bounded: 2,000 rows looked through after the first block, no more.
      expect(vi.mocked(api.get).mock.calls.length).toBeLessThanOrEqual(1 + 2000 / 50);
    });
  });
});
