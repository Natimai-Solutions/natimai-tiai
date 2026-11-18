import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
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
  listAllChecks: vi.fn(),
  updateCheck: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import { listAllChecks, updateCheck, type Check } from 'src/services/checks';
import { getDue, updateRoomMaintenance, type Due } from 'src/services/maintenance';
import { useAuthStore } from 'src/stores/auth';
import TasksPage from './TasksPage.vue';

const Stub = defineComponent({ render: () => h('div') });
const PageStub = defineComponent({
  setup:
    (_, { slots }) =>
    () =>
      h('div', slots.default?.()),
});

const check: Check = {
  id: 'c-1',
  machine_id: 'm-1',
  requested_by: 'head@school.test',
  assigned_to: { id: 'u-2', name: 'Mary', active: false, reachable: false },
  instructions: 'Screen flickers',
  created_at: '2026-11-01T08:00:00Z',
  updated_at: '2026-11-01T08:00:00Z',
  closed_at: null,
  closed_by: null,
  closing_note: null,
  machine: {
    id: 'm-1',
    hostname: 'PC-01',
    location: 'North campus',
    room_name: 'B12',
    building_name: 'Science block',
  },
};

const due: Due = {
  rooms: [
    {
      id: 'r-1',
      key: 'r-1',
      level: 'room',
      name: 'B12',
      building_name: 'Science block',
      location: null,
      owner: null,
      cycle_days: 90,
      total: 2,
      overdue: 1,
      due_soon: 1,
      excluded: 0,
      next_due_at: null,
      machines: [],
    },
  ],
  machines: [
    {
      id: 'm-9',
      hostname: 'PC-09',
      location: null,
      room_name: null,
      building_name: null,
      last_maintenance_at: null,
      due_at: null,
      state: 'overdue',
      owner: null,
    },
  ],
  overdue: 2,
  due_soon: 1,
};

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'a@b.c',
    permissions: ['check:read', 'check:write', 'maintenance:read', 'maintenance:write'],
  } as never;
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
    global: {
      plugins: [router, pinia],
      stubs: {
        QPage: PageStub,
        MaintenanceSettingsDialog: true,
        MaintenanceSessionDialog: true,
        CheckCloseDialog: true,
        CheckRequestDialog: true,
      },
    },
  });
  await flushPromises();
  return wrapper;
}

describe('TasksPage in English', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAllChecks).mockResolvedValue({ items: [check], total: 1, page: 1, page_size: 1 });
    vi.mocked(getDue).mockResolvedValue(due);
    vi.mocked(updateCheck).mockResolvedValue(check);
    vi.mocked(updateRoomMaintenance).mockResolvedValue({} as never);
  });
  afterEach(() => setLocale('fr'));

  it('reads in English, with no French left', async () => {
    setLocale('en');
    const wrapper = await mountPage();
    const text = wrapper.text();

    expect(text).toContain('My tasks');
    expect(text).toContain('Mine');
    expect(text).toContain('To take');
    expect(text).toContain('Checks requested on computers');
    expect(text).toContain('1 check');
    expect(text).toContain('Instructions');
    expect(text).toContain('Assigned to');
    expect(text).toContain('to take');
    expect(text).toContain('Mary, deactivated');
    expect(text).toContain('by head@school.test');
    expect(text).toContain('Maintenance to do');
    expect(text).toContain('2 overdue · 1 due soon');
    expect(text).toContain('2 computers · 90-day cycle · no owner');
    expect(text).toContain('1 due soon');
    expect(text).toContain('no room · no owner');
    expect(text).toContain('Overdue');
    // Data only: the time ago is the format utilities' (another batch).
    expect(text.replace(/il y a \d+ j/g, '')).not.toMatch(/[éèàùç«»]/);
    expect(text).not.toMatch(/Vérifications|Consignes|retard|à prendre|Mes tâches/);
    wrapper.unmount();
  });

  it('notifies in English', async () => {
    setLocale('en');
    const wrapper = await mountPage();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify').mockImplementation(() => () => undefined);

    const take = wrapper.findAll('button').find((b) => b.text().includes('Assign to me'))!;
    await take.trigger('click');
    await flushPromises();

    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'positive', message: 'Room B12 assigned to you' }),
    );
    expect(updateRoomMaintenance).toHaveBeenCalledWith('r-1', { maintenance_owner_id: 'me' });
    wrapper.unmount();
  });

  it('switches language live', async () => {
    const wrapper = await mountPage();
    expect(wrapper.text()).toContain('Mes tâches');
    expect(wrapper.text()).toContain('Maintenances à faire');

    setLocale('en');
    await nextTick();

    expect(wrapper.text()).toContain('My tasks');
    expect(wrapper.text()).toContain('Maintenance to do');
    expect(wrapper.text()).toContain('Instructions');
    expect(wrapper.text()).not.toContain('Mes tâches');
    wrapper.unmount();
  });
});
