import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

const listCalls: unknown[] = [];

// The list against a fake server: three postes out of a long search, and the
// rest of what the page asks for at mount answered empty or refused (the
// fleet options are best-effort side lists).
vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn((url: string, cfg?: { params?: unknown }) => {
      if (url === '/machines') {
        listCalls.push(cfg?.params);
        const items = ['a', 'b', 'c'].map((id) => ({ id, hostname: id, machine_uuid: id }));
        return Promise.resolve({
          data: {
            items,
            total: 800,
            page: 1,
            page_size: 50,
            agent_latest_version: null,
            usage_days: 7,
            usage_low_hours: 1,
            usage_high_hours: 10,
          },
        });
      }
      if (url === '/rooms/config') return Promise.resolve({ data: { manual: true } });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    }),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import MachinesBulkBar from 'src/components/machines-list/MachinesBulkBar.vue';
import MachinesFiltersBar from 'src/components/machines-list/MachinesFiltersBar.vue';
import MachinesTable from 'src/components/machines-list/MachinesTable.vue';
import { useAuthStore } from 'src/stores/auth';
import { emptyMachineFilters } from 'src/utils/machineListFilters';
import MachinesPage from './MachinesPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function mountList(path: string) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: ['machine:read', 'command:execute'],
    preferences: {},
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push(path);
  const wrapper = mount(MachinesPage, {
    shallow: true,
    global: { plugins: [router, pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('MachinesPage — selection (audit B05)', () => {
  beforeEach(() => {
    listCalls.length = 0;
  });

  async function selectTwo(wrapper: Awaited<ReturnType<typeof mountList>>['wrapper']) {
    const table = wrapper.findComponent(MachinesTable);
    table.vm.$emit('update:selected', (table.props('rows') as unknown[]).slice(0, 2));
    await flushPromises();
    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(2);
  }

  it('drops the selection on a filter change', async () => {
    const { wrapper } = await mountList('/machines?room=B12');
    await selectTwo(wrapper);
    wrapper
      .findComponent(MachinesFiltersBar)
      .vm.$emit('update:modelValue', { ...emptyMachineFilters(), room: 'B14' });
    await flushPromises();

    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(0);
  });

  // The drawer's « Postes » link: the same page, the query dropped, without
  // going through any of the page's own handlers.
  it('drops the selection when the query changes from outside the page', async () => {
    const { wrapper, router } = await mountList('/machines?room=B12');
    await selectTwo(wrapper);
    await router.push({ name: 'machines' });
    await flushPromises();

    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(0);
    // The list reloaded on the new, unfiltered search.
    expect(listCalls.at(-2)).toHaveProperty('room_id', 'B12');
    expect(listCalls.at(-1)).not.toHaveProperty('room_id');
  });

  it('keeps the selection across a navigation to the same search', async () => {
    const { wrapper, router } = await mountList('/machines?room=B12');
    await selectTwo(wrapper);
    await router.replace({ name: 'machines', query: { room: 'B12' }, hash: '#x' });
    await flushPromises();

    expect(wrapper.findComponent(MachinesBulkBar).props('count')).toBe(2);
  });
});
