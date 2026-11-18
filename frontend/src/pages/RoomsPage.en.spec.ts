import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
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

import { setLocale } from 'src/i18n';
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
// A q-page only renders inside a q-layout; the panels are flattened so that
// both tabs — rooms and buildings — are read at once.
const PassThrough = defineComponent({
  setup:
    (_, { slots }) =>
    () =>
      h('div', slots.default?.()),
});

const room = {
  id: 'r-1',
  name: 'B12',
  building: { id: 'b-1', name: 'Science block', location: 'North campus' },
  location: null,
  effective_location: 'North campus',
  notes: 'Second floor',
  ad_key: 'OU=B12',
  machine_count: 24,
  mismatch_count: 2,
  maintenance_cycle_days: null,
  maintenance_owner_name: null,
  effective_cycle_days: 90,
  effective_owner_name: 'Mary',
  maintenance_overdue: 3,
  maintenance_due_soon: 1,
  created_at: '',
  updated_at: '',
};

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
      stubs: {
        QPage: PassThrough,
        QTabs: true,
        QTabPanels: PassThrough,
        QTabPanel: PassThrough,
        RoomFormDialog: true,
        BuildingFormDialog: true,
      },
    },
  });
  await flushPromises();
  return wrapper;
}

describe('RoomsPage in English', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'ad_ou', manual: false });
    vi.mocked(getRoomCreation).mockResolvedValue({ rooms: true, buildings: true });
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(listRooms).mockResolvedValue([room] as never);
    vi.mocked(listBuildings).mockResolvedValue([
      {
        id: 'b-1',
        name: 'Science block',
        location: 'North campus',
        notes: null,
        room_count: 1,
        machine_count: 24,
        created_at: '',
        updated_at: '',
      },
    ]);
  });
  afterEach(() => setLocale('fr'));

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const wrapper = await mountPage();
    const text = wrapper.text();

    expect(text).toContain('Rooms');
    expect(text).toContain('New building');
    expect(text).toContain('New room');
    expect(text).toContain(
      'Computers are filed by the organisational unit of the computer object (ROOM_SOURCE=ad_ou): rooms are created automatically',
    );
    expect(text).toContain('Re-sync from the directory');
    expect(text).toContain('A room groups computers');
    expect(text).toContain('3 overdue');
    expect(text).toContain('1 due soon');
    expect(text).toContain('90 d');
    expect(text).toContain('Mismatched');
    expect(text).toContain('A building holds the location');
    expect(wrapper.find('[aria-label="Actions for B12"]').exists()).toBe(true);
    expect(text).not.toMatch(/[éèàùç«»]/);
    expect(text).not.toMatch(/Salle|Bâtiment|Postes|poste\(s\)|retard/);
    wrapper.unmount();
  });

  it('asks before a re-sync, in English', async () => {
    vi.mocked(syncDirectory).mockResolvedValue({
      placed: 0,
      unplaced: 1,
      moved_out: 4,
      rooms_created: 2,
      undecided: 1,
    });
    setLocale('en');
    const wrapper = await mountPage();
    const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation((() => {
      const chain = {
        onDismiss() {
          return this;
        },
        update() {
          return this;
        },
        onOk: () => chain,
        onCancel: () => chain,
      };
      return chain;
    }) as never);

    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Re-sync from the directory'))!
      .trigger('click');
    await flushPromises();

    const opts = dialog.mock.calls[0]![0] as {
      title: string;
      message: string;
      ok: { label: string };
      cancel: { label: string };
    };
    expect(opts.title).toBe('Re-sync from the directory');
    expect(opts.message).toBe(
      'Computers that will change room: 4; rooms that will be created: 2. Of which 1 taken out of any room. 1 computer will stay where it is (undecided room). Computers without any directory information stay where they are. Start the re-sync?',
    );
    expect(opts.ok.label).toBe('Re-sync');
    expect(opts.cancel.label).toBe('Cancel');
    wrapper.unmount();
  });

  it('switches language live', async () => {
    const wrapper = await mountPage();
    expect(wrapper.text()).toContain('Nouvelle salle');
    expect(wrapper.text()).toContain('3 en retard');

    setLocale('en');
    await nextTick();

    expect(wrapper.text()).toContain('New room');
    expect(wrapper.text()).toContain('3 overdue');
    expect(wrapper.text()).not.toContain('Nouvelle salle');
    wrapper.unmount();
  });
});
