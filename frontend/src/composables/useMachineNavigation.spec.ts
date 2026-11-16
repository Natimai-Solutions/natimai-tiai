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
 * The neighbours are the server's (`GET /machines/{id}/neighbours`, audit
 * T31), so every test here drives the composable through the axios mock and a
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

function neighbour(id: string, cursor = `c-${id}`) {
  return { id, machine_uuid: `uuid-${id}`, hostname: id.toUpperCase(), cursor };
}

interface Answer {
  previous?: string | null;
  next?: string | null;
  rank: number | null;
  total: number;
}

/** Answer every neighbours request with the same place. */
function respond(answer: Answer) {
  vi.mocked(api.get).mockResolvedValue({
    data: {
      previous: answer.previous ? neighbour(answer.previous) : null,
      next: answer.next ? neighbour(answer.next) : null,
      rank: answer.rank,
      total: answer.total,
      cursor: answer.rank === null ? null : 'c-self',
    },
  });
}

/** The params of the `n`-th request (0-based). */
function paramsOf(n: number): Record<string, unknown> {
  const config = vi.mocked(api.get).mock.calls[n]?.[1];
  return (config?.params ?? {}) as Record<string, unknown>;
}

/**
 * A server holding an ordered list, as the API does: each poste has a sort
 * value, `move()` changes it, and the neighbours of a place are worked out
 * on the list as it is now — by keyset, as the endpoint does. It also answers
 * `GET /machines` in pages, so the same scenario can be played against a
 * client that reads the list itself.
 */
function server(n: number) {
  const values = new Map<string, number>();
  for (let i = 0; i < n; i++) values.set(`m${String(i).padStart(3, '0')}`, i);
  const ordered = () => [...values.entries()].sort(([a, x], [b, y]) => x - y || a.localeCompare(b));
  vi.mocked(api.get).mockImplementation((url: string, config?: AxiosRequestConfig) => {
    const params = (config?.params ?? {}) as {
      cursor?: string;
      page?: number;
      page_size?: number;
    };
    const rows = ordered();
    if (url === '/machines') {
      const page = params.page ?? 1;
      const size = params.page_size ?? 50;
      const items = rows.slice((page - 1) * size, page * size).map(([id]) => neighbour(id));
      return Promise.resolve({ data: { items, total: rows.length, page, page_size: size } });
    }
    const id = url.split('/')[2]!;
    const place = params.cursor !== undefined ? Number(params.cursor) : values.get(id)!;
    const others = rows.filter(([other]) => other !== id);
    const before = others.filter(([other, v]) => v < place || (v === place && other < id));
    const after = others.filter(([other, v]) => v > place || (v === place && other > id));
    const at = (row: [string, number] | undefined) =>
      row ? neighbour(row[0], String(row[1])) : null;
    return Promise.resolve({
      data: {
        previous: at(before[before.length - 1]),
        next: at(after[0]),
        rank: before.length,
        total: rows.length,
        cursor: String(place),
      },
    });
  });
  return {
    move(id: string, value: number) {
      values.set(id, value);
    },
  };
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

/** Wait until no request has been sent for a moment. */
async function quiet() {
  await vi.waitUntil(async () => {
    const n = vi.mocked(api.get).mock.calls.length;
    await new Promise((r) => setTimeout(r, 20));
    return vi.mocked(api.get).mock.calls.length === n;
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

describe('useMachineNavigation', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    resetMachineNavigation();
  });

  it('stays silent when the fiche was not opened from a search', async () => {
    respond({ rank: 0, total: 1 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc');

    expect(nav.fromSearch.value).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('shows the neighbours and the position the server gives', async () => {
    respond({ previous: 'prev', next: 'next', rank: 5, total: 340 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&i=5');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.previousMachine.value?.id).toBe('prev');
    expect(nav.nextMachine.value?.hostname).toBe('NEXT');
    expect(nav.positionLabel.value).toBe('Poste 6 sur 340');
  });

  it('asks the server once, with the search filters and sort, for the open poste', async () => {
    respond({ next: 'next', rank: 0, total: 2 });
    const router = makeRouter();
    const { nav } = await mount(
      router,
      '/machines/abc?status=outdated&search=pc&sort_by=hostname&sort_desc=false&page=3&i=0',
    );
    await vi.waitUntil(() => nav.total.value !== null);

    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith('/machines/abc/neighbours', {
      params: { status: 'outdated', search: 'pc', sort_by: 'hostname', sort_desc: false },
    });
  });

  it('takes the rank from the server when the poste moved since the list was read', async () => {
    respond({ previous: 'c', next: 'b', rank: 156, total: 301 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/a?i=5');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.index.value).toBe(156);
    expect(nav.positionLabel.value).toBe('Poste 157 sur 301');
    // And the list to go back to is the page that holds it now.
    expect(nav.backQuery.value).toEqual({ page: '4' });
  });

  it('offers no previous on the first result and no next on the last', async () => {
    respond({ rank: 0, total: 1 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?i=0');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.previousMachine.value).toBeNull();
    expect(nav.nextMachine.value).toBeNull();
    expect(nav.positionLabel.value).toBe('Poste 1 sur 1');
  });

  it('shows no position and no neighbours when the poste has left the list', async () => {
    respond({ rank: null, total: 12 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?hw_model=OptiPlex&i=5');
    await quiet();

    // The arrows are still drawn (opened from a search), disabled.
    expect(nav.fromSearch.value).toBe(true);
    expect(nav.positionLabel.value).toBe('');
    expect(nav.previousMachine.value).toBeNull();
    expect(nav.nextMachine.value).toBeNull();
    // Back to the list on the page the URL gave.
    expect(nav.backQuery.value).toEqual({ hw_model: 'OptiPlex' });
  });

  it('hides the position when the lookup fails, without an error over the fiche', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('network'));
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?i=5');
    await quiet();

    expect(nav.positionLabel.value).toBe('');
    expect(nav.nextMachine.value).toBeNull();
  });

  it('returns to the page that actually holds the poste, not the one opened from', async () => {
    // Opened from page 1 (no `page` in the URL), then walked to rank 59.
    // With the default page size of 50 that poste sits on page 2.
    respond({ previous: 'prev', next: 'next', rank: 59, total: 340 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&i=59');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.backQuery.value).toEqual({ status: 'outdated', page: '2' });
  });

  it('leaves page 1 out of the return query, as the list itself does', async () => {
    respond({ rank: 0, total: 10 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?page=2&i=0');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.backQuery.value.page).toBeUndefined();
  });

  it('honours a non-default page size when computing the return page', async () => {
    respond({ rank: 25, total: 100 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?page_size=25&i=25');
    await vi.waitUntil(() => nav.total.value !== null);

    // rank 25 with 25 rows per page is the first row of page 2.
    expect(nav.backQuery.value.page).toBe('2');
  });

  it('walks with the arrows, carrying the tab and the next rank', async () => {
    server(10);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/m004?sort_by=hostname&i=4&tab=hardware');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(await step(router, nav, nav.goNext)).toBe('m005');
    expect(router.currentRoute.value.query).toEqual({
      sort_by: 'hostname',
      tab: 'hardware',
      i: '5',
    });
    expect(nav.positionLabel.value).toBe('Poste 6 sur 10');
    expect(await step(router, nav, nav.goPrevious)).toBe('m004');
    expect(await step(router, nav, nav.goPrevious)).toBe('m003');
    expect(nav.positionLabel.value).toBe('Poste 4 sur 10');
  });

  it('never walks to the poste it just left when clicked twice quickly', async () => {
    // The bug this guards: the neighbours belong to the *previous* poste for
    // the round trip it takes to resolve the new ones. A second click in that
    // window used to navigate to the same machine again, with the rank moved
    // on — desynchronising identity and position for the whole session.
    //
    // The second resolution is left hanging so the window is observable rather
    // than a race: that is precisely the state a fast double-click lands in.
    respond({ previous: 'z', next: 'b', rank: 48, total: 100 });
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

  it('ignores an answer that arrives after the reader moved on', async () => {
    let answerFirst!: (value: unknown) => void;
    vi.mocked(api.get).mockImplementationOnce(
      () => new Promise((resolve) => (answerFirst = resolve)),
    );
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/a?i=0');
    respond({ previous: 'a', next: 'c', rank: 1, total: 3 });
    await router.push('/machines/b?i=1');
    await vi.waitUntil(() => nav.total.value !== null);

    answerFirst({ data: { previous: null, next: neighbour('b'), rank: 0, total: 3, cursor: 'x' } });
    await quiet();

    expect(nav.positionLabel.value).toBe('Poste 2 sur 3');
    expect(nav.nextMachine.value?.id).toBe('c');
  });

  it('sends back where the poste reached stood, and where the poste left stood', async () => {
    respond({ next: 'b', rank: 0, total: 3 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/a?status=outdated&i=0');
    await vi.waitUntil(() => nav.total.value !== null);
    // Opened from the list: the poste's place now, no cursor.
    expect(paramsOf(0)).toEqual({ status: 'outdated' });

    await step(router, nav, nav.goNext);
    expect(paramsOf(1)).toEqual({ status: 'outdated', cursor: 'c-b' });

    // Back in the browser: « a » is placed where its first answer put it.
    router.back();
    await vi.waitUntil(() => router.currentRoute.value.params.id === 'a');
    await quiet();
    expect(paramsOf(2)).toEqual({ status: 'outdated', cursor: 'c-self' });
  });

  it('forgets the places once back on the list', async () => {
    respond({ next: 'b', rank: 0, total: 3 });
    const router = makeRouter();
    const first = await mount(router, '/machines/a?i=0');
    await vi.waitUntil(() => first.nav.total.value !== null);
    first.app.unmount();

    resetMachineNavigation();
    const again = await mount(router, '/machines/b?i=1');
    await vi.waitUntil(() => again.nav.total.value !== null);

    expect(paramsOf(1)).toEqual({});
  });

  it('keeps the place of the poste reached when its own heartbeat moves it (audit B18)', async () => {
    // Sorted on the last contact, oldest first: the poste reached with ▶
    // reports in and goes to the end of the list. It is still walked from
    // where it was reached.
    const fleet = server(6);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/m002?sort_by=last_seen&i=2');
    await vi.waitUntil(() => nav.total.value !== null);

    fleet.move('m003', 100);
    expect(await step(router, nav, nav.goNext)).toBe('m003');
    expect(nav.positionLabel.value).toBe('Poste 4 sur 6');
    expect(nav.previousMachine.value?.id).toBe('m002');
    expect(nav.nextMachine.value?.id).toBe('m004');
  });

  it('reaches a poste that moved just ahead of the reader (audit T31)', async () => {
    // 120 postes; the reader opens the 31st and walks on. The 91st moves to
    // just after the 36th — into the first 50 rows, which a client reading
    // the list in blocks has already read, and where it never looks again.
    const fleet = server(120);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/m030?sort_by=hostname&sort_desc=false&i=30');
    await vi.waitUntil(() => nav.total.value !== null);

    const seen = ['m030'];
    for (let k = 0; k < 3; k++) seen.push(await step(router, nav, nav.goNext));
    fleet.move('m090', 35.5);
    for (let k = 0; k < 4; k++) seen.push(await step(router, nav, nav.goNext));

    expect(seen).toEqual(['m030', 'm031', 'm032', 'm033', 'm034', 'm035', 'm090', 'm036']);
    expect(nav.positionLabel.value).toBe('Poste 38 sur 120');
  });

  it('asks nothing more when the reader changes tab', async () => {
    respond({ previous: 'm4', next: 'm6', rank: 5, total: 120 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/m5?i=5');
    await vi.waitUntil(() => nav.total.value !== null);

    // Asking again would disable both arrows for the time of a round trip.
    const previous: (string | null)[] = [];
    const stop = watch(nav.previousMachine, (m) => previous.push(m?.id ?? null), {
      flush: 'sync',
    });
    for (const tab of ['hardware', 'software', 'commands']) {
      await router.replace({ query: { i: '5', tab } });
      await quiet();
    }
    stop();

    expect(previous).toEqual([]);
    expect(nav.previousMachine.value?.id).toBe('m4');
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('asks again when the search changes', async () => {
    respond({ rank: 5, total: 120 });
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/m5?i=5');
    await vi.waitUntil(() => nav.total.value !== null);

    respond({ rank: null, total: 3 });
    await router.replace({ query: { i: '5', status: 'outdated' } });
    await quiet();

    expect(api.get).toHaveBeenCalledTimes(2);
    expect(paramsOf(1)).toEqual({ status: 'outdated' });
    expect(nav.positionLabel.value).toBe('');
  });
});
