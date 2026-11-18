import type { QTableColumn } from 'quasar';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getDue: vi.fn(),
  getRoomMaintenance: vi.fn(),
  updateMachineMaintenance: vi.fn(),
  updateRoomMaintenance: vi.fn(),
}));
vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  listChecks: vi.fn(),
  listAllChecks: vi.fn(),
}));

import {
  effectiveAssignee,
  formerAssigneeNote,
  listAllChecks,
  listChecks,
  type Check,
} from 'src/services/checks';
import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import {
  getDue,
  getRoomMaintenance,
  updateMachineMaintenance,
  updateRoomMaintenance,
  type Due,
  type DueMachine,
  type DueRoom,
} from 'src/services/maintenance';
import { useAuthStore } from 'src/stores/auth';
import TasksPage from './TasksPage.vue';

const Stub = defineComponent({ render: () => h('div') });

function loose(id: string, state: DueMachine['state']): DueMachine {
  return {
    id,
    hostname: id.toUpperCase(),
    location: null,
    room_name: null,
    building_name: null,
    last_maintenance_at: null,
    due_at: '2026-12-02T01:00:00Z',
    state,
    owner: { id: 'me', name: 'Moi' },
  };
}

async function mountPage(due: Due, permissions = ['check:read', 'maintenance:read']) {
  vi.mocked(getDue).mockResolvedValue(due);
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'me', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tasks', name: 'tasks', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
      { path: '/rooms/:id', name: 'room-detail', component: Stub },
    ],
  });
  await router.push('/tasks');
  const wrapper = mount(TasksPage, {
    shallow: true,
    global: { plugins: [router, pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return wrapper;
}

describe('TasksPage — maintenances to do (audit B09)', () => {
  beforeEach(() => {
    vi.mocked(listChecks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 });
    vi.mocked(listAllChecks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 0 });
  });

  it('says there is nothing to do when the room-less postes are all up to date', async () => {
    const wrapper = await mountPage({
      rooms: [],
      machines: [loose('pc-1', 'ok'), loose('pc-2', 'ok')],
      overdue: 0,
      due_soon: 0,
    });

    expect(wrapper.text()).toContain('Rien à faire.');
    expect(wrapper.text()).not.toContain('PC-1');
  });

  it('lists only the room-less postes overdue or due soon', async () => {
    const wrapper = await mountPage({
      rooms: [],
      machines: [loose('pc-1', 'ok'), loose('pc-2', 'overdue'), loose('pc-3', 'due_soon')],
      overdue: 1,
      due_soon: 1,
    });

    expect(wrapper.text()).not.toContain('Rien à faire.');
    expect(wrapper.text()).not.toContain('PC-1');
    expect(wrapper.text()).toContain('PC-2');
    expect(wrapper.text()).toContain('PC-3');
  });
});

describe('TasksPage — handing a room on', () => {
  beforeEach(() => {
    vi.mocked(listChecks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 });
    vi.mocked(listAllChecks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 0 });
    vi.mocked(getRoomMaintenance).mockResolvedValue({
      maintenance_cycle_days: null,
      maintenance_owner: { id: 'me', name: 'Moi' },
      effective_cycle_days: 90,
      effective_owner: { id: 'me', name: 'Moi' },
    });
  });

  it('has the dialog offer the owners the server accepts for that room', async () => {
    const room: DueRoom = {
      id: 'r-7',
      name: 'B12',
      building_name: null,
      location: null,
      owner: { id: 'me', name: 'Moi' },
      cycle_days: 90,
      total: 1,
      overdue: 1,
      due_soon: 0,
      excluded: 0,
      next_due_at: '2026-12-02T01:00:00Z',
      machines: [loose('pc-1', 'overdue')],
    };
    const wrapper = await mountPage({ rooms: [room], machines: [], overdue: 1, due_soon: 0 }, [
      'check:read',
      'maintenance:read',
      'maintenance:write',
    ]);
    const dialog = () =>
      wrapper
        .findAllComponents(MaintenanceSettingsDialog)
        .find((d) => d.props('inheritHint') !== undefined)!;
    expect(dialog().props('roomId')).toBeNull();

    await wrapper.find('[label="Transmettre…"]').trigger('click');
    await flushPromises();

    expect(getRoomMaintenance).toHaveBeenCalledWith('r-7');
    expect(dialog().props('roomId')).toBe('r-7');
    expect(dialog().props('machineId')).toBeUndefined();
  });
});

function dueRoom(over: Partial<DueRoom>): DueRoom {
  return {
    id: 'r-7',
    name: 'B12',
    building_name: null,
    location: null,
    owner: { id: 'other', name: 'Paul' },
    cycle_days: 90,
    total: 1,
    overdue: 1,
    due_soon: 0,
    excluded: 0,
    next_due_at: '2026-12-02T01:00:00Z',
    machines: [loose('pc-1', 'overdue')],
    ...over,
  };
}

describe('TasksPage — acceptance fixes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAllChecks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 0 });
    vi.mocked(updateMachineMaintenance).mockResolvedValue({} as never);
    vi.mocked(updateRoomMaintenance).mockResolvedValue({} as never);
  });

  it('reads every check, not the first 200, and says the total (item 9)', async () => {
    const items = Array.from(
      { length: 310 },
      (_, i) => ({ id: `c-${i}`, machine_id: `m-${i}`, machine: null }) as unknown as Check,
    );
    vi.mocked(listAllChecks).mockResolvedValue({ items, total: 310, page: 1, page_size: 310 });
    const wrapper = await mountPage({ rooms: [], machines: [], overdue: 0, due_soon: 0 });

    expect(listAllChecks).toHaveBeenCalledWith({ open: true, assigned_to: 'me' });
    expect(listChecks).not.toHaveBeenCalled();
    expect(wrapper.find('[data-test="checks-total"]').text()).toBe('310 vérification(s)');
    const table = wrapper.findComponent({ name: 'QTable' });
    expect((table.props('rows') as Check[]).length).toBe(310);
  });

  it('shows a check whose assignee no longer sees the poste as « à prendre »', async () => {
    const check = {
      id: 'c-1',
      machine_id: 'm-1',
      machine: { id: 'm-1', hostname: 'PC-1', location: null, room_name: null },
      instructions: 'Écran',
      created_at: '2026-11-10T08:00:00Z',
      assigned_to: { id: 'u-2', name: 'Marie', active: true, reachable: false },
    } as unknown as Check;
    vi.mocked(listAllChecks).mockResolvedValue({ items: [check], total: 1, page: 1, page_size: 1 });
    const wrapper = await mountPage({ rooms: [], machines: [], overdue: 0, due_soon: 0 });
    const table = wrapper.findComponent({ name: 'QTable' });
    const column = (table.props('columns') as QTableColumn<Check>[]).find(
      (c) => c.name === 'assigned_to',
    )!;
    // Sorted and read as nobody's: the name is the reason, not the assignee.
    expect((column.field as (r: Check) => string)(check)).toBe('');
    expect(effectiveAssignee(check.assigned_to)).toBeNull();
    expect(formerAssigneeNote(check.assigned_to)).toBe('Marie ne voit plus ce poste');
    expect(formerAssigneeNote({ id: 'u-3', name: 'Paul', active: false, reachable: false })).toBe(
      'Paul, désactivé',
    );
    expect(formerAssigneeNote({ id: 'u-4', name: 'Léa' })).toBe('');
  });

  it('shows a maintenance-only account its maintenances, and no checks (item 5)', async () => {
    const wrapper = await mountPage(
      { rooms: [dueRoom({})], machines: [], overdue: 1, due_soon: 0 },
      ['maintenance:read', 'maintenance:write'],
    );
    expect(listAllChecks).not.toHaveBeenCalled();
    expect(wrapper.findComponent({ name: 'QTable' }).exists()).toBe(false);
    expect(wrapper.text()).not.toContain('Vérifications');
    expect(wrapper.text()).toContain('Maintenances à faire');
  });

  it('takes the postes, not the room, of a group that overrides it (item 8)', async () => {
    const group = dueRoom({
      key: 'r-7:other:30',
      level: 'machine',
      cycle_days: 30,
      machines: [loose('pc-1', 'overdue'), loose('pc-2', 'due_soon')],
    });
    const wrapper = await mountPage({ rooms: [group], machines: [], overdue: 1, due_soon: 1 }, [
      'maintenance:read',
      'maintenance:write',
    ]);
    // Handing the room on from a group of postes would change the room.
    expect(wrapper.find('[label="Transmettre…"]').exists()).toBe(false);

    await wrapper.find('[label="Me l\'affecter"]').trigger('click');
    await flushPromises();

    expect(updateRoomMaintenance).not.toHaveBeenCalled();
    expect(vi.mocked(updateMachineMaintenance).mock.calls).toEqual([
      ['pc-1', { maintenance_owner_id: 'me' }],
      ['pc-2', { maintenance_owner_id: 'me' }],
    ]);
  });

  it('still takes the room for a room-level group', async () => {
    const wrapper = await mountPage(
      { rooms: [dueRoom({ key: 'r-7', level: 'room' })], machines: [], overdue: 1, due_soon: 0 },
      ['maintenance:read', 'maintenance:write'],
    );
    await wrapper.find('[label="Me l\'affecter"]').trigger('click');
    await flushPromises();
    expect(updateRoomMaintenance).toHaveBeenCalledWith('r-7', { maintenance_owner_id: 'me' });
    expect(updateMachineMaintenance).not.toHaveBeenCalled();
  });

  it('opens a poste by its name only: a click on the row navigates nowhere', async () => {
    const check = { id: 'c-1', machine_id: 'm-1', machine: null } as unknown as Check;
    vi.mocked(listAllChecks).mockResolvedValue({ items: [check], total: 1, page: 1, page_size: 1 });
    const wrapper = await mountPage({ rooms: [], machines: [], overdue: 0, due_soon: 0 });
    const push = vi.spyOn(wrapper.vm.$router, 'push');
    const table = wrapper.findComponent({ name: 'QTable' });
    // No handler at all: a double-click on a word in the row stays a selection.
    expect(table.vm.$attrs).not.toHaveProperty('onRowClick');
    table.vm.$emit('row-click', new Event('click'), check);
    await flushPromises();
    expect(push).not.toHaveBeenCalled();
  });
});
