import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getDue: vi.fn(),
}));
vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  listChecks: vi.fn(),
}));

import { listChecks } from 'src/services/checks';
import { getDue, type Due, type DueMachine } from 'src/services/maintenance';
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

async function mountPage(due: Due) {
  vi.mocked(getDue).mockResolvedValue(due);
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'a@b.c',
    permissions: ['check:read', 'maintenance:read'],
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
    shallow: true,
    global: { plugins: [router, pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return wrapper;
}

describe('TasksPage — maintenances to do (audit B09)', () => {
  beforeEach(() => {
    vi.mocked(listChecks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 });
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
