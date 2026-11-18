import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Screen } from 'quasar';
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

/** Click « Retirer » on PC-01 and say yes to the question it now asks. */
async function removeConfirmed(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  let confirm: (() => void) | null = null;
  const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation((() => ({
    onDismiss() {
      return this;
    },
    update() {
      return this;
    },
    onOk(fn: () => void) {
      confirm = fn;
      return this;
    },
  })) as never);
  await wrapper.find('[aria-label="Retirer PC-01 de la salle"]').trigger('click');
  await flushPromises();
  expect(dialog).toHaveBeenCalledTimes(1);
  confirm!();
  await flushPromises();
}

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
        MaintenanceSessionViewDialog: true,
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

      await removeConfirmed(wrapper);

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

      await removeConfirmed(wrapper);

      expect(unassignMachines).toHaveBeenCalledTimes(1);
      expect(tasksVersion.value).toBe(before);
      wrapper.unmount();
    });
  });
});

describe('RoomDetailPage — acceptance fixes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoom).mockResolvedValue(room);
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'manual', manual: true });
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(listMachines).mockResolvedValue({ items: [inRoom], total: 1 } as never);
    vi.mocked(getRoomMaintenance).mockResolvedValue(settings);
    vi.mocked(listSessions).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 5 });
    vi.mocked(unassignMachines).mockResolvedValue({ moved: 1, mismatched: [] });
  });

  it('asks before taking a poste out of the room (item 14)', async () => {
    const wrapper = await mountPage();
    const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation((() => ({
      onDismiss() {
        return this;
      },
      update() {
        return this;
      },
      onOk() {
        return this;
      },
    })) as never);
    await wrapper.find('[aria-label="Retirer PC-01 de la salle"]').trigger('click');
    await flushPromises();
    expect(dialog).toHaveBeenCalledTimes(1);
    expect(unassignMachines).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('says « défaut du parc » when the room owner no longer applies (item 4)', async () => {
    vi.mocked(getRoomMaintenance).mockResolvedValue({
      maintenance_cycle_days: null,
      maintenance_owner: { id: 'u-gone', name: 'Marie', active: false },
      effective_cycle_days: 90,
      effective_owner: { id: 'u-def', name: 'Paul' },
      effective_cycle_origin: 'global',
      effective_owner_origin: 'global',
    });
    const wrapper = await mountPage();
    expect(wrapper.find('[data-test="owner-origin"]').text()).toBe('(défaut du parc)');
    expect(wrapper.text()).toContain('Marie (désactivé)');
    expect(wrapper.findComponent(MaintenanceSettingsDialog).props('ownerLabel')).toBe(
      'Marie (désactivé)',
    );
    wrapper.unmount();
  });

  it('lists every visit a page at a time, each opening its detail (item 1)', async () => {
    const visit = (n: number) => ({
      id: `s-${n}`,
      room_id: 'r-1',
      room_name: 'B12',
      performed_by: 'alice@test.local',
      performed_at: `2026-11-${String(10 - n).padStart(2, '0')}T20:00:00Z`,
      note: `Note ${n}`,
      machine_count: 1,
      items: [],
    });
    vi.mocked(listSessions)
      .mockResolvedValueOnce({
        items: [0, 1, 2, 3, 4].map(visit),
        total: 7,
        page: 1,
        page_size: 5,
      })
      .mockResolvedValueOnce({ items: [5, 6].map(visit), total: 7, page: 2, page_size: 5 });
    const wrapper = await mountPage();
    const sessions = () => wrapper.find('[data-test="room-sessions"]');
    expect(sessions().text()).toContain('Note 4');
    expect(sessions().text()).not.toContain('Note 6');

    await sessions()
      .findAll('button')
      .find((b) => b.text().includes('Afficher plus'))!
      .trigger('click');
    await flushPromises();
    expect(listSessions).toHaveBeenLastCalledWith({ room_id: 'r-1', page: 2, page_size: 5 });
    expect(sessions().text()).toContain('Note 6');

    await wrapper.find('[data-test="session-s-6"]').trigger('click');
    await flushPromises();
    const view = wrapper.findComponent({ name: 'MaintenanceSessionViewDialog' });
    expect(view.props('sessionId')).toBe('s-6');
    expect(view.props('modelValue')).toBe(true);
    wrapper.unmount();
  });

  it('opens a poste by its name only: the rest of the row is text to select', async () => {
    const wrapper = await mountPage();
    const push = vi.spyOn(wrapper.vm.$router, 'push');
    const row = wrapper.find('tbody tr');
    const cell = row.findAll('td').at(1)!;
    // The two clicks of a double-click on a word, then the double-click.
    await cell.trigger('click');
    await cell.trigger('click');
    await cell.trigger('dblclick');
    await flushPromises();
    expect(push).not.toHaveBeenCalled();
    expect(row.classes()).not.toContain('cursor-pointer');
    expect(row.find('a.row-link').attributes('href')).toBe('/machines/m-1');
    wrapper.unmount();
  });
});

describe('RoomDetailPage — on a phone (audit U23)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRoom).mockResolvedValue(room);
    vi.mocked(getRoomConfig).mockResolvedValue({ source: 'manual', manual: true });
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listLocations).mockResolvedValue([]);
    vi.mocked(listMachines).mockResolvedValue({ items: [inRoom], total: 1 } as never);
    vi.mocked(getRoomMaintenance).mockResolvedValue(settings);
    vi.mocked(listSessions).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 5 });
    Screen.lt.sm = true;
  });
  afterEach(() => {
    Screen.lt.sm = false;
  });

  it('shows a card per poste with its link and « Retirer » at touch size, no table', async () => {
    const wrapper = await mountPage();
    expect(wrapper.find('table').exists()).toBe(false);
    const card = wrapper.find('[data-test="machine-card-m-1"]');
    expect(card.find('a').attributes('href')).toBe('/machines/m-1');
    expect(card.text()).toContain('PC-01');
    const remove = card.find('[aria-label="Retirer PC-01 de la salle"]');
    expect(remove.classes()).not.toContain('q-btn--dense');

    const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation((() => ({
      onDismiss() {
        return this;
      },
      update() {
        return this;
      },
      onOk() {
        return this;
      },
    })) as never);
    await remove.trigger('click');
    expect(dialog).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
});
