import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  getRoomConfig: vi.fn(),
  getRoomCreation: vi.fn(),
  listBuildings: vi.fn(),
  listRooms: vi.fn(),
  syncDirectory: vi.fn(),
}));
vi.mock('src/services/machines', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/machines')>()),
  listLocations: vi.fn(),
}));

import { listLocations } from 'src/services/machines';
import {
  getRoomConfig,
  getRoomCreation,
  listBuildings,
  listRooms,
  syncDirectory,
} from 'src/services/rooms';
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

/** Click « Resynchroniser », answer the confirmation it asks (yes by default). */
async function resync(wrapper: Awaited<ReturnType<typeof mountPage>>, answer = true) {
  const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);
  const asked: string[] = [];
  const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation(((opts: {
    message: string;
  }) => {
    asked.push(opts.message);
    const chain = {
      onOk(fn: () => void) {
        if (answer) fn();
        return chain;
      },
      onCancel(fn: () => void) {
        if (!answer) fn();
        return chain;
      },
    };
    return chain;
  }) as never);
  await wrapper
    .findAll('button')
    .find((b) => b.text().includes("Resynchroniser depuis l'annuaire"))!
    .trigger('click');
  await flushPromises();
  return Object.assign(notify, { asked, dialog });
}

describe('RoomsPage — re-sync from the directory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'ad_ou', manual: false });
    vi.mocked(listRooms).mockResolvedValue([]);
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(getRoomCreation).mockResolvedValue({ rooms: true, buildings: true });
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

describe('RoomsPage — the re-sync asks first (item 2, C9)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'ad_ou', manual: false });
    vi.mocked(getRoomCreation).mockResolvedValue({ rooms: true, buildings: true });
    vi.mocked(listRooms).mockResolvedValue([]);
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(syncDirectory).mockResolvedValue({
      placed: 22,
      unplaced: 3,
      moved_out: 318,
      rooms_created: 12,
      undecided: 0,
      undecided_rooms: [],
    });
  });

  it('shows the dry run and writes nothing when cancelled', async () => {
    const wrapper = await mountPage();
    const notify = await resync(wrapper, false);

    expect(syncDirectory).toHaveBeenCalledTimes(1);
    expect(syncDirectory).toHaveBeenCalledWith(true);
    expect(notify.asked[0]).toContain(
      '318 poste(s) changeront de salle, 12 salle(s) seront créées.',
    );
    expect(notify).not.toHaveBeenCalled();
  });

  it('runs the real sync once confirmed', async () => {
    const wrapper = await mountPage();
    await resync(wrapper, true);

    expect(vi.mocked(syncDirectory).mock.calls).toEqual([[true], []]);
  });
});

describe('RoomsPage — what the scope lets create, and selecting text (items 14, 15)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'manual', manual: true });
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(listRooms).mockResolvedValue([
      {
        id: 'r-1',
        name: 'B12',
        building: null,
        location: null,
        effective_location: null,
        notes: null,
        ad_key: null,
        machine_count: 0,
        mismatch_count: 0,
        maintenance_cycle_days: null,
        maintenance_owner_name: null,
        effective_cycle_days: 90,
        effective_owner_name: null,
        maintenance_overdue: 0,
        maintenance_due_soon: 0,
        created_at: '',
        updated_at: '',
      },
    ]);
  });

  const buttons = (wrapper: Awaited<ReturnType<typeof mountPage>>) =>
    wrapper.findAll('button').map((b) => b.text());

  it('hides both creation buttons for an account confined to rooms', async () => {
    vi.mocked(getRoomCreation).mockResolvedValue({ rooms: false, buildings: false });
    const wrapper = await mountPage();
    expect(buttons(wrapper).some((t) => t.includes('Nouvelle salle'))).toBe(false);
    expect(buttons(wrapper).some((t) => t.includes('Nouveau bâtiment'))).toBe(false);
  });

  it('keeps « Nouvelle salle » only for an account confined to buildings', async () => {
    vi.mocked(getRoomCreation).mockResolvedValue({ rooms: true, buildings: false });
    const wrapper = await mountPage();
    expect(buttons(wrapper).some((t) => t.includes('Nouvelle salle'))).toBe(true);
    expect(buttons(wrapper).some((t) => t.includes('Nouveau bâtiment'))).toBe(false);
  });

  it('does not open a room when the click ends a text selection', async () => {
    vi.mocked(getRoomCreation).mockResolvedValue({ rooms: true, buildings: true });
    const wrapper = await mountPage();
    const push = vi.spyOn(wrapper.vm.$router, 'push');
    const selection = vi
      .spyOn(window, 'getSelection')
      .mockReturnValue({ toString: () => 'B12' } as Selection);
    await wrapper.find('tbody tr').trigger('click');
    expect(push).not.toHaveBeenCalled();
    selection.mockReturnValue({ toString: () => '' } as Selection);
    await wrapper.find('tbody tr').trigger('click');
    expect(push).toHaveBeenCalledWith({ name: 'room-detail', params: { id: 'r-1' } });
    selection.mockRestore();
  });
});
