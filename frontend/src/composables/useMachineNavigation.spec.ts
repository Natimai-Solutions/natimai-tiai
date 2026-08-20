// @vitest-environment jsdom
// This composable is driven by the router and needs a component to live in, so
// it is the one spec that wants a DOM. The suite as a whole stays on `node` —
// see vitest.config.ts.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { api } from 'boot/axios';
import { useMachineNavigation } from './useMachineNavigation';

/**
 * The composable walks a search by asking the server for single-row pages at
 * rank-1 and rank+1, so every test here drives it through the axios mock and a
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

/** Answer /machines with one row, keyed by the requested page. */
function respondWith(rowsByPage: Record<number, unknown>, total: number) {
  vi.mocked(api.get).mockImplementation((_url: string, config?: { params?: { page?: number } }) => {
    const page = config?.params?.page ?? 1;
    const row = rowsByPage[page];
    return Promise.resolve({ data: { items: row ? [row] : [], total, page, page_size: 1 } });
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
  });

  it('stays silent when the fiche was not opened from a search', async () => {
    respondWith({}, 0);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc');

    expect(nav.fromSearch.value).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('resolves both neighbours and the position in the search', async () => {
    // rank 5 → asks for page 5 (rank 4) and page 7 (rank 6), page_size 1.
    respondWith({ 5: machine('prev'), 7: machine('next') }, 340);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&i=5');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.previousMachine.value?.id).toBe('prev');
    expect(nav.nextMachine.value?.id).toBe('next');
    expect(nav.positionLabel.value).toBe('Poste 6 sur 340');
  });

  it('carries the search filters into every neighbour lookup', async () => {
    respondWith({ 2: machine('next') }, 2);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&search=pc&i=0');
    await vi.waitUntil(() => nav.total.value !== null);

    // rank 0 has no previous, so exactly one request goes out — for rank 1.
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith('/machines', {
      params: { status: 'outdated', search: 'pc', page: 2, page_size: 1 },
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
    respondWith({ 59: machine('prev'), 61: machine('next') }, 340);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?status=outdated&i=59');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.backQuery.value).toEqual({ status: 'outdated', page: '2' });
  });

  it('leaves page 1 out of the return query, as the list itself does', async () => {
    respondWith({ 2: machine('next') }, 10);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/abc?i=0');
    await vi.waitUntil(() => nav.total.value !== null);

    expect(nav.backQuery.value.page).toBeUndefined();
  });

  it('honours a non-default page size when computing the return page', async () => {
    respondWith({ 25: machine('prev'), 27: machine('next') }, 100);
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
    respondWith({ 2: machine('b') }, 10);
    const router = makeRouter();
    const { nav } = await mount(router, '/machines/a?i=0');
    await vi.waitUntil(() => nav.nextMachine.value !== null);

    vi.mocked(api.get).mockImplementation(() => new Promise(() => {}));

    nav.goNext(); // → /machines/b?i=1
    await vi.waitUntil(() => router.currentRoute.value.params.id === 'b');

    // Mid-resolution the arrows are inert, not stale.
    expect(nav.nextMachine.value).toBeNull();
    nav.goNext(); // does nothing at all
    await nextTick();

    expect(router.currentRoute.value.params.id).toBe('b');
    expect(router.currentRoute.value.query.i).toBe('1');
  });
});
