import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  getRoomConfig: vi.fn(),
  listBuildings: vi.fn(),
  listRooms: vi.fn(),
  syncDirectory: vi.fn(),
}));
vi.mock('src/services/machines', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/machines')>()),
  listLocations: vi.fn(),
}));

import { listLocations } from 'src/services/machines';
import { getRoomConfig, listBuildings, listRooms, syncDirectory } from 'src/services/rooms';
import { useAuthStore } from 'src/stores/auth';
import RoomsPage from './RoomsPage.vue';

const Stub = defineComponent({ render: () => h('div') });
// A q-page only renders inside a q-layout: its content is all a spec needs.
const PageStub = defineComponent({
  setup:
    (_, { slots }) =>
    () =>
      h('div', slots.default?.()),
});

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: ['room:read', 'room:write'],
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/rooms', name: 'rooms', component: Stub },
      { path: '/rooms/:id', name: 'room-detail', component: Stub },
    ],
  });
  await router.push('/rooms');
  const wrapper = mount(RoomsPage, {
    global: {
      plugins: [router, pinia],
      // (q-tabs measures itself with a ResizeObserver, which jsdom has not.)
      stubs: { QPage: PageStub, QTabs: true, RoomFormDialog: true, BuildingFormDialog: true },
    },
  });
  await flushPromises();
  return wrapper;
}

async function resync(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);
  await wrapper
    .findAll('button')
    .find((b) => b.text().includes("Resynchroniser depuis l'annuaire"))!
    .trigger('click');
  await flushPromises();
  return notify;
}

describe('RoomsPage — re-sync from the directory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'ad_ou', manual: false });
    vi.mocked(listRooms).mockResolvedValue([]);
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
  });

  it('says which rooms were left undecided, and what to do about them', async () => {
    vi.mocked(syncDirectory).mockResolvedValue({
      placed: 12,
      unplaced: 0,
      rooms_created: 1,
      undecided: 4,
      undecided_rooms: ['B12', 'CDI'],
    });
    const wrapper = await mountPage();

    const notify = await resync(wrapper);

    expect(notify).toHaveBeenCalledTimes(1);
    const said = notify.mock.calls[0]![0] as { type: string; message: string; caption: string };
    expect(said.type).toBe('warning');
    expect(said.message).toContain('4 poste(s) laissé(s) en place');
    expect(said.caption).toContain('« B12 », « CDI »');
    expect(said.caption).toContain('Renommez la salle');
    // The list is read again all the same: the other postes were filed.
    expect(listRooms).toHaveBeenCalledTimes(2);
  });

  it('says the plain count when nothing was left undecided', async () => {
    vi.mocked(syncDirectory).mockResolvedValue({ placed: 12, unplaced: 0, rooms_created: 1 });
    const wrapper = await mountPage();

    const notify = await resync(wrapper);

    expect(notify).toHaveBeenCalledWith({
      type: 'positive',
      message: '12 poste(s) rangé(s), 0 retiré(s), 1 salle(s) créée(s)',
    });
  });
});
