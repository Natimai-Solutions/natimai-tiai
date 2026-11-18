import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  getRoom: vi.fn(),
  getRoomConfig: vi.fn(),
  listBuildings: vi.fn(),
  placeMachines: vi.fn(),
  unassignMachines: vi.fn(),
}));
vi.mock('src/services/machines', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/machines')>()),
  listMachines: vi.fn(),
  listLocations: vi.fn(),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getRoomMaintenance: vi.fn(),
  listSessions: vi.fn(),
  updateRoomMaintenance: vi.fn(),
}));

import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { setLocale } from 'src/i18n';
import { listLocations, listMachines, type Machine } from 'src/services/machines';
import { getRoomMaintenance, listSessions, type RoomMaintenance } from 'src/services/maintenance';
import {
  getRoom,
  getRoomConfig,
  listBuildings,
  unassignMachines,
  type Room,
} from 'src/services/rooms';
import { useAuthStore } from 'src/stores/auth';
import { machineDetail } from 'src/test/fixtures';
import RoomDetailPage from './RoomDetailPage.vue';

const Stub = defineComponent({ render: () => h('div') });
const PageStub = defineComponent({
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
  machine_count: 1,
  mismatch_count: 1,
  maintenance_overdue: 1,
  maintenance_due_soon: 0,
} as unknown as Room;

const settings: RoomMaintenance = {
  maintenance_cycle_days: null,
  maintenance_owner: { id: 'u-2', name: 'Mary', active: false },
  effective_cycle_days: 90,
  effective_owner: { id: 'u-3', name: 'John' },
  effective_cycle_origin: 'global',
  effective_owner_origin: 'global',
};

// Never seen: the time ago is worded by the format utilities (another batch).
const pc = {
  ...machineDetail({
    id: 'm-1',
    hostname: 'PC-01',
    room_id: 'r-1',
    location: 'South campus',
    location_mismatch: true,
    maintenance_state: 'overdue',
  }),
  last_seen: null,
} as unknown as Machine;

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: ['room:read', 'room:write', 'maintenance:read', 'maintenance:write'],
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/rooms', name: 'rooms', component: Stub },
      { path: '/rooms/:id', name: 'room-detail', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/rooms/r-1');
  const wrapper = mount(RoomDetailPage, {
    props: { id: 'r-1' },
    global: {
      plugins: [router, pinia],
      stubs: {
        QPage: PageStub,
        MaintenanceSettingsDialog: true,
        MaintenanceSessionDialog: true,
        MaintenanceSessionViewDialog: true,
        RoomFormDialog: true,
      },
    },
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

describe('RoomDetailPage in English', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoom).mockResolvedValue(room);
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'manual', manual: true });
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(listMachines).mockResolvedValue({ items: [pc], total: 1 } as never);
    vi.mocked(getRoomMaintenance).mockResolvedValue(settings);
    vi.mocked(listSessions).mockResolvedValue({
      items: [
        {
          id: 's-1',
          room_id: 'r-1',
          room_name: 'B12',
          performed_by: 'tech@school.test',
          performed_at: '2026-11-02T09:00:00Z',
          note: null,
          machine_count: 3,
          items: [],
        },
      ],
      total: 7,
      page: 1,
      page_size: 5,
    });
    vi.mocked(unassignMachines).mockResolvedValue({ moved: 1, mismatched: [] });
  });
  afterEach(() => setLocale('fr'));

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const wrapper = await mountPage();
    const text = wrapper.text();

    expect(text).toContain('Add computers');
    expect(text).toContain('Carry out maintenance');
    expect(text).toContain('(from the building)');
    expect(text).toContain('1 mismatched');
    expect(text).toContain('Directory');
    expect(text).toContain('90 days');
    expect(text).toContain('(fleet default)');
    expect(text).toContain('Room owner not in effect: Mary (deactivated)');
    expect(text).toContain('1 overdue');
    expect(text).toContain('Sessions');
    expect(text).toContain('3 computers');
    expect(text).toContain('Show more (6)');
    expect(text).toContain('Location (agent)');
    expect(text).toContain('IP address');
    expect(text).toContain('Overdue');
    expect(wrapper.find('[aria-label="Remove PC-01 from the room"]').exists()).toBe(true);
    expect(wrapper.findComponent(MaintenanceSettingsDialog).props('inheritHint')).toBe(
      "Empty: the fleet's default owner",
    );
    expect(text).not.toMatch(/[éèàùç«»]/);
    expect(text).not.toMatch(/Salle|Postes|poste\(s\)|retard|Responsable|Séances/);
    wrapper.unmount();
  });

  it('asks before taking a computer out of the room, and says it is done, in English', async () => {
    setLocale('en');
    const wrapper = await mountPage();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);
    let ok: (() => void) | null = null;
    const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation((() => ({
      onOk(fn: () => void) {
        ok = fn;
        return this;
      },
    })) as never);

    await wrapper.find('[aria-label="Remove PC-01 from the room"]').trigger('click');
    const opts = dialog.mock.calls[0]![0] as { title: string; message: string };
    expect(opts.title).toBe('Remove from the room');
    expect(opts.message).toBe(
      "Remove PC-01 from room B12? It stays in the fleet, without a room, and no longer follows the room's cycle or owner.",
    );
    ok!();
    await flushPromises();
    expect(notify).toHaveBeenCalledWith({
      type: 'positive',
      message: 'PC-01 removed from the room',
    });
    wrapper.unmount();
  });

  it('switches language live', async () => {
    const wrapper = await mountPage();
    expect(wrapper.text()).toContain('Ajouter des postes');

    setLocale('en');
    await nextTick();

    expect(wrapper.text()).toContain('Add computers');
    expect(wrapper.text()).toContain('IP address');
    expect(wrapper.text()).not.toContain('Ajouter des postes');
    wrapper.unmount();
  });
});
