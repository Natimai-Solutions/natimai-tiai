import { flushPromises, mount } from '@vue/test-utils';
import { QTable, QTabs } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/alerts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/alerts')>()),
  listAlerts: vi.fn(),
}));

import { listAlerts } from 'src/services/alerts';
import AlertsPage from './AlertsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/alerts', name: 'alerts', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push(path);
  const wrapper = mount(AlertsPage, {
    shallow: true,
    global: { plugins: [router], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('AlertsPage', () => {
  beforeEach(() => {
    vi.mocked(listAlerts).mockReset();
    vi.mocked(listAlerts).mockResolvedValue({
      items: [
        {
          id: 'a',
          machine_id: 'm-1',
          rule: 'disk_low',
          opened_at: '2026-11-18T10:00:00Z',
          resolved_at: null,
          detail: { free_percent: 3, threshold_percent: 10 },
          check_id: null,
          machine: { id: 'm-1', hostname: 'PC-1', room_name: 'A101', building_name: 'Bât. A' },
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      open_by_rule: { disk_low: 1, inactive: 0 },
    });
  });

  it('reads the open alerts of every rule by default', async () => {
    const { wrapper } = await mountAt('/alerts');
    expect(listAlerts).toHaveBeenCalledWith({ state: 'open', page: 1, page_size: 50 });
    expect((wrapper.findComponent(QTable).props('rows') as unknown[]).length).toBe(1);
  });

  it('opens on the rule the URL names, and follows a change of tab', async () => {
    const { wrapper, router } = await mountAt('/alerts?rule=disk_low');
    expect(listAlerts).toHaveBeenLastCalledWith({
      state: 'open',
      rule: 'disk_low',
      page: 1,
      page_size: 50,
    });
    wrapper.findComponent(QTabs).vm.$emit('update:modelValue', 'inactive');
    await flushPromises();
    expect(router.currentRoute.value.query.rule).toBe('inactive');
    expect(listAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ rule: 'inactive' }));
  });

  it('ignores an unknown rule in the URL', async () => {
    await mountAt('/alerts?rule=nope');
    expect(listAlerts).toHaveBeenCalledWith({ state: 'open', page: 1, page_size: 50 });
  });
});
