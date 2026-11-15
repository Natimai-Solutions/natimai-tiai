import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
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
import { tasksVersion } from 'src/composables/useTasksBadge';
import { listLocations, listMachines, type Machine } from 'src/services/machines';
import {
  getRoomMaintenance,
  listSessions,
  updateRoomMaintenance,
  type MaintenanceSettingsPayload,
  type RoomMaintenance,
} from 'src/services/maintenance';
import {
  getRoom,
  getRoomConfig,
  listBuildings,
  placeMachines,
  unassignMachines,
  type Room,
} from 'src/services/rooms';
import { useAuthStore } from 'src/stores/auth';
import { machineDetail } from 'src/test/fixtures';
import RoomDetailPage from './RoomDetailPage.vue';

const Stub = defineComponent({ render: () => h('div') });
// A q-page only renders inside a q-layout: its content is all a spec needs.
const PageStub = defineComponent({
  setup:
    (_, { slots }) =>
    () =>
      h('div', slots.default?.()),
});

const room = {
  id: 'r-1',
  name: 'B12',
  building: null,
  location: null,
  effective_location: null,
  notes: null,
  ad_key: null,
  machine_count: 1,
  mismatch_count: 0,
  maintenance_overdue: 0,
  maintenance_due_soon: 0,
} as unknown as Room;

const settings: RoomMaintenance = {
  maintenance_cycle_days: null,
  maintenance_owner: null,
  effective_cycle_days: 90,
  effective_owner: null,
};

const inRoom = machineDetail({ id: 'm-1', hostname: 'PC-01', room_id: 'r-1' }) as Machine;
const elsewhere = machineDetail({ id: 'm-2', hostname: 'PC-02', room_id: 'r-2' }) as Machine;

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
  // The page for real — its table rows carry the « Retirer » button — and its
  // three dialogs as stubs: each has its own spec.
  const wrapper = mount(RoomDetailPage, {
    props: { id: 'r-1' },
    global: {
      plugins: [router, pinia],
      stubs: {
        QPage: PageStub,
        MaintenanceSettingsDialog: true,
        MaintenanceSessionDialog: true,
        RoomFormDialog: true,
      },
    },
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

describe('RoomDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoom).mockResolvedValue(room);
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'manual', manual: true });
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(listMachines).mockResolvedValue({ items: [inRoom], total: 1 } as never);
    vi.mocked(getRoomMaintenance).mockResolvedValue(settings);
    vi.mocked(listSessions).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 3 });
    vi.mocked(updateRoomMaintenance).mockResolvedValue(settings);
    vi.mocked(placeMachines).mockResolvedValue({ moved: 1, mismatched: [] });
    vi.mocked(unassignMachines).mockResolvedValue({ moved: 1, mismatched: [] });
  });

  it('has the settings dialog offer the owners the server accepts for this room', async () => {
    const wrapper = await mountPage();

    const dialog = wrapper.findComponent(MaintenanceSettingsDialog);
    expect(dialog.props('roomId')).toBe('r-1');
    expect(dialog.props('machineId')).toBeUndefined();
    wrapper.unmount();
  });

  describe('what changes « Mes tâches » (audit U19)', () => {
    it('has the tasks badge read again once the room’s maintenance settings are saved', async () => {
      const wrapper = await mountPage();
      const before = tasksVersion.value;

      const save = wrapper.findComponent(MaintenanceSettingsDialog).props('save') as (
        payload: MaintenanceSettingsPayload,
      ) => Promise<void>;
      await save({ maintenance_owner_id: 'u-2' });

      expect(updateRoomMaintenance).toHaveBeenCalledWith('r-1', { maintenance_owner_id: 'u-2' });
      expect(tasksVersion.value).toBe(before + 1);
      wrapper.unmount();
    });

    it('has the tasks badge read again once a poste is taken out of the room', async () => {
      const wrapper = await mountPage();
      const before = tasksVersion.value;

      await wrapper.find('[aria-label="Retirer PC-01 de la salle"]').trigger('click');
      await flushPromises();

      expect(unassignMachines).toHaveBeenCalledWith(['m-1']);
      expect(tasksVersion.value).toBe(before + 1);
      wrapper.unmount();
    });

    it('has the tasks badge read again once postes are moved into the room', async () => {
      const wrapper = await mountPage();
      const before = tasksVersion.value;

      await wrapper
        .findAll('button')
        .find((b) => b.text().includes('Ajouter des postes'))!
        .trigger('click');
      await flushPromises();
      // A poste of another room, picked in the search.
      (wrapper.vm as unknown as { picked: Machine[] }).picked = [elsewhere];
      await flushPromises();
      const add = [...document.body.querySelectorAll('.q-dialog button')].find(
        (b) => b.textContent?.trim() === 'Ajouter',
      ) as HTMLButtonElement;
      add.click();
      await flushPromises();

      expect(placeMachines).toHaveBeenCalledWith('r-1', ['m-2']);
      expect(tasksVersion.value).toBe(before + 1);
      wrapper.unmount();
    });

    it('leaves the tasks badge alone when the server refuses the move', async () => {
      vi.mocked(unassignMachines).mockRejectedValue(new Error('down'));
      const wrapper = await mountPage();
      const before = tasksVersion.value;

      await wrapper.find('[aria-label="Retirer PC-01 de la salle"]').trigger('click');
      await flushPromises();

      expect(unassignMachines).toHaveBeenCalledTimes(1);
      expect(tasksVersion.value).toBe(before);
      wrapper.unmount();
    });
  });
});
