// @vitest-environment jsdom
// This composable is driven by the router and needs a component to live in, so
// it is the one spec that wants a DOM. The suite as a whole stays on `node` —
// see vitest.config.ts.
import type { AxiosRequestConfig } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick, watch } from 'vue';
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

    /** The pages of the search asked for so far, in order (1-based, as sent). */
    function pagesAsked(): number[] {
      return vi
        .mocked(api.get)
        .mock.calls.map(([, config]) => (config?.params as { page: number }).page);
    }

    /** Wait until no request has been sent for a moment. */
    async function quiet() {
      await vi.waitUntil(async () => {
        const n = vi.mocked(api.get).mock.calls.length;
        await new Promise((r) => setTimeout(r, 20));
        return vi.mocked(api.get).mock.calls.length === n;
      });
    }

    /**
     * The same server, answering only when told to: `answer()` lets the
     * oldest request waiting through, and the composable react to it.
     */
    function serveOnDemand(order: string[]) {
      const waiting: (() => void)[] = [];
      vi.mocked(api.get).mockImplementation((_url: string, config?: AxiosRequestConfig) => {
        const params = config?.params as { page?: number; page_size?: number } | undefined;
        const page = params?.page ?? 1;
        const size = params?.page_size ?? 50;
        const items = order.slice((page - 1) * size, page * size).map(machine);
        return new Promise((resolve) => {
          waiting.push(() =>
            resolve({ data: { items, total: order.length, page, page_size: size } }),
          );
        });
      });
      return {
        waiting: () => waiting.length,
        async answer() {
          await vi.waitUntil(() => waiting.length > 0);
          waiting.shift()!();
          await new Promise((r) => setTimeout(r, 5));
        },
      };
    }

    it('does not look again for a poste it did not find when only the tab changes', async () => {
      // A search of 3,000 postes that does not hold « x »: 41 requests to know.
      serve(Array.from({ length: 3000 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/x?status=outdated&i=5');
      await vi.waitUntil(() => vi.mocked(api.get).mock.calls.length > 1);
      await quiet();
      const asked = vi.mocked(api.get).mock.calls.length;
      expect(asked).toBe(1 + 2000 / 50);

      // The reader goes through the fiche's tabs: the URL changes, the poste
      // and the search do not.
      for (const tab of ['hardware', 'software', 'commands']) {
        await router.replace({ query: { ...router.currentRoute.value.query, tab } });
        await quiet();
      }

      expect(vi.mocked(api.get).mock.calls.length).toBe(asked);
      expect(nav.positionLabel.value).toBe('');
      expect(nav.fromSearch.value).toBe(true);
    });

    it('remembers a poste not found in a search: coming back to its fiche reads nothing', async () => {
      serve(Array.from({ length: 3000 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const first = await mount(router, '/machines/x?i=5');
      await vi.waitUntil(() => vi.mocked(api.get).mock.calls.length > 1);
      await quiet();
      const asked = vi.mocked(api.get).mock.calls.length;
      first.app.unmount();

      // Forward then Back in the browser: the fiche is mounted afresh.
      const again = await mount(router, '/machines/x?i=5');
      await quiet();

      expect(vi.mocked(api.get).mock.calls.length).toBe(asked);
      expect(again.nav.positionLabel.value).toBe('');
      expect(again.nav.previousMachine.value).toBeNull();
    });

    it('stops reading as soon as the fiche closes', async () => {
      const server = serveOnDemand(Array.from({ length: 3000 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const { app } = await mount(router, '/machines/x?i=5');
      await server.answer();
      await server.answer();
      // The third block is on its way when the reader leaves.
      await vi.waitUntil(() => server.waiting() === 1);
      expect(vi.mocked(api.get).mock.calls.length).toBe(3);

      app.unmount();
      await server.answer();
      await new Promise((r) => setTimeout(r, 30));

      expect(vi.mocked(api.get).mock.calls.length).toBe(3);
    });

    it('stops looking for a poste when the fiche shows another one', async () => {
      const server = serveOnDemand(Array.from({ length: 3000 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/x?i=5');
      await server.answer();
      await vi.waitUntil(() => server.waiting() === 1);

      // Another poste of the same search, already read: nothing more to ask.
      await router.push('/machines/m7?i=7');
      await server.answer();
      await vi.waitUntil(() => nav.total.value !== null);
      await new Promise((r) => setTimeout(r, 30));

      expect(vi.mocked(api.get).mock.calls.length).toBe(2);
      expect(nav.positionLabel.value).toBe('Poste 8 sur 3000');
      expect(nav.previousMachine.value?.id).toBe('m6');
      expect(nav.nextMachine.value?.id).toBe('m8');
    });

    it('resumes a search cut short with what is left of its 2,000 rows, not 2,000 more', async () => {
      const order = Array.from({ length: 6000 }, (_, i) => `m${i}`);
      const server = serveOnDemand(order);
      const router = makeRouter();
      const first = await mount(router, '/machines/x?i=5');
      for (let k = 0; k < 10; k++) await server.answer();
      await vi.waitUntil(() => server.waiting() === 1);
      first.app.unmount();
      await server.answer();

      serve(order);
      await mount(router, '/machines/x?i=5');
      await quiet();

      expect(vi.mocked(api.get).mock.calls.length).toBe(1 + 2000 / 50);
      // And no block twice: the second visit went on from where the first stopped.
      expect(new Set(pagesAsked()).size).toBe(pagesAsked().length);
    });

    it('reads one block at a time: two resolutions at once do not read the same block twice', async () => {
      const order = Array.from({ length: 120 }, (_, i) => `m${i}`);
      const server = serveOnDemand(order);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m5?i=5');
      await vi.waitUntil(() => server.waiting() === 1);

      // The reader moves on before the first block has answered.
      await router.push('/machines/m49?i=49');
      await new Promise((r) => setTimeout(r, 20));
      // The second resolution waits for the first one's block.
      expect(pagesAsked()).toEqual([1]);

      await server.answer();
      await server.answer();
      await vi.waitUntil(() => nav.total.value !== null);

      // Block 1 once, then block 2 for the poste after « m49 » — in that order.
      expect(pagesAsked()).toEqual([1, 2]);
      expect(nav.positionLabel.value).toBe('Poste 50 sur 120');
      expect(nav.previousMachine.value?.id).toBe('m48');
      expect(nav.nextMachine.value?.id).toBe('m50');
    });

    it('never shows a poste twice when one was removed before the block read backwards', async () => {
      const t0 = Array.from({ length: 120 }, (_, i) => `m${i}`);
      serve(t0);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m51?i=51');
      await vi.waitUntil(() => nav.nextMachine.value !== null);

      // « m3 » is deleted: every poste after it moves up a rank, and « m50 »,
      // first of the block already read, now closes the block before it.
      serve(t0.filter((id) => id !== 'm3'));
      const seen = ['m51'];
      for (let k = 0; k < 4; k++) seen.push(await step(router, nav, nav.goPrevious));

      expect(seen).toEqual(['m51', 'm50', 'm49', 'm48', 'm47']);
      // 119 postes now, and « m47 » is the 47th of them.
      expect(nav.positionLabel.value).toBe('Poste 47 sur 119');
      expect(nav.previousMachine.value?.id).toBe('m46');
      expect(nav.nextMachine.value?.id).toBe('m48');

      // And the way back goes through each of them once.
      const back = [];
      for (let k = 0; k < 5; k++) back.push(await step(router, nav, nav.goNext));
      expect(back).toEqual(['m48', 'm49', 'm50', 'm51', 'm52']);
    });

    it('never says a rank beyond the total when postes after the cursor are gone', async () => {
      const t0 = Array.from({ length: 120 }, (_, i) => `m${i}`);
      serve(t0);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m110?i=110');
      await vi.waitUntil(() => nav.total.value !== null);
      expect(nav.positionLabel.value).toBe('Poste 111 sur 120');

      // The last thirty postes are deleted; the walk still holds the twenty
      // it had read, in the order the reader saw, and goes on with what the
      // server has before them now.
      serve(t0.slice(0, 90));
      for (let k = 0; k < 11; k++) await step(router, nav, nav.goPrevious);

      expect(String(router.currentRoute.value.params.id)).toBe('m89');
      const [, rank, total] = /^Poste (\d+) sur (\d+)$/.exec(nav.positionLabel.value)!;
      expect(Number(rank)).toBeLessThanOrEqual(Number(total));
      expect(nav.positionLabel.value).toBe('Poste 100 sur 120');
    });

    it('leaves the arrows alone when the reader changes tab on a poste it found', async () => {
      serve(Array.from({ length: 120 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m5?i=5');
      await vi.waitUntil(() => nav.total.value !== null);
      const asked = vi.mocked(api.get).mock.calls.length;

      // Resolving again would disable both arrows for the time of a round trip.
      const previous: (string | null)[] = [];
      const stop = watch(nav.previousMachine, (m) => previous.push(m?.id ?? null), {
        flush: 'sync',
      });
      await router.replace({ query: { i: '5', tab: 'hardware' } });
      await quiet();
      stop();

      expect(previous).toEqual([]);
      expect(nav.previousMachine.value?.id).toBe('m4');
      expect(vi.mocked(api.get).mock.calls.length).toBe(asked);
    });

    it('numbers the first poste 1 after a removal before the cursor', async () => {
      const t0 = Array.from({ length: 120 }, (_, i) => `m${i}`);
      serve(t0);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m60?i=60');
      await vi.waitUntil(() => nav.total.value !== null);
      expect(nav.positionLabel.value).toBe('Poste 61 sur 120');

      serve(t0.filter((id) => id !== 'm3'));
      await router.push('/machines/m0?i=0');
      await vi.waitUntil(() => nav.total.value !== null && nav.nextMachine.value !== null);

      expect(nav.positionLabel.value).toBe('Poste 1 sur 119');
      expect(nav.previousMachine.value).toBeNull();
      expect(nav.nextMachine.value?.id).toBe('m1');

      // The postes read first moved with it: « m60 » is now the 60th.
      await router.push('/machines/m60?i=60');
      await vi.waitUntil(() => nav.total.value !== null && nav.nextMachine.value !== null);
      expect(nav.positionLabel.value).toBe('Poste 60 sur 119');
      expect(nav.previousMachine.value?.id).toBe('m59');
    });

    it('numbers from what exists when the search is shorter than the rank given', async () => {
      // A fiche reloaded with i=120, from a search that now holds 80 postes.
      const order = Array.from({ length: 80 }, (_, i) => `m${i}`);
      for (const [id, label] of [
        ['m70', 'Poste 71 sur 80'],
        ['m79', 'Poste 80 sur 80'],
        ['m30', 'Poste 31 sur 80'],
        ['m0', 'Poste 1 sur 80'],
      ] as const) {
        resetMachineNavigation();
        serve(order);
        const router = makeRouter();
        const { nav, app } = await mount(router, `/machines/${id}?i=120`);
        await vi.waitUntil(() => nav.total.value !== null);

        expect(nav.positionLabel.value, id).toBe(label);
        const rank = Number(id.slice(1));
        expect(nav.previousMachine.value?.id ?? null, id).toBe(rank > 0 ? `m${rank - 1}` : null);
        expect(nav.nextMachine.value?.id ?? null, id).toBe(rank < 79 ? `m${rank + 1}` : null);
        app.unmount();
      }
    });

    it('never says a rank beyond the total while walking a search that shrank', async () => {
      serve(Array.from({ length: 80 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m79?i=120');
      await vi.waitUntil(() => nav.total.value !== null);

      const labels = [nav.positionLabel.value];
      for (let k = 0; k < 79; k++) {
        await step(router, nav, nav.goPrevious);
        labels.push(nav.positionLabel.value);
      }

      expect(labels).toEqual(Array.from({ length: 80 }, (_, k) => `Poste ${80 - k} sur 80`));
      expect(nav.previousMachine.value).toBeNull();
    });

    it('starts from the end of the search when the rank given is far past it', async () => {
      // i=5000 on a search of 300 postes; the poste is the 11th.
      serve(Array.from({ length: 300 }, (_, i) => `m${i}`));
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/m10?i=5000');
      await vi.waitUntil(() => nav.total.value !== null);

      expect(nav.positionLabel.value).toBe('Poste 11 sur 300');
      expect(nav.previousMachine.value?.id).toBe('m9');
      expect(nav.nextMachine.value?.id).toBe('m11');
      // One request to learn where the search ends, then its six blocks from
      // the last one down — none of the forty past the end.
      expect(pagesAsked()).toEqual([101, 6, 5, 4, 3, 2, 1]);
    });

    it('asks nothing more of a search that has become empty', async () => {
      serve([]);
      const router = makeRouter();
      const { nav } = await mount(router, '/machines/x?i=120');
      await vi.waitUntil(() => vi.mocked(api.get).mock.calls.length > 0);
      await quiet();

      expect(pagesAsked()).toEqual([3]);
      expect(nav.positionLabel.value).toBe('');
    });
  });
});
