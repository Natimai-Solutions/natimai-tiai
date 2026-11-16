import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/audit', () => ({
  listAudit: vi.fn(),
  listAuditActions: vi.fn(() => Promise.resolve([])),
}));

import AuditDetailsDialog from 'src/components/audit/AuditDetailsDialog.vue';
import { listAudit, type AuditEntry } from 'src/services/audit';
import AuditPage from './AuditPage.vue';

const Stub = defineComponent({ render: () => h('div') });

const entry: AuditEntry = {
  id: 'a1',
  at: '2026-11-10T10:00:00Z',
  actor: 'admin@x',
  action: 'machine.revoke_token',
  resource_type: 'machine',
  resource_id: 'm-1',
  details: {},
  ip: '10.62.0.7',
};

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/audit', name: 'audit', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/audit');
  // QPage wants a QLayout around it; the page's content is all this needs.
  const w = mount(AuditPage, {
    global: { plugins: [router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return w;
}

describe('AuditPage', () => {
  beforeEach(() => {
    vi.mocked(listAudit).mockResolvedValue({ items: [entry], total: 1, page: 1, page_size: 50 });
  });

  // C10: where the action came from.
  it('shows the address of each action, in a column hidden on a phone', async () => {
    const w = await mountPage();
    const cell = w.find('tbody td.gt-xs');
    expect(cell.text()).toBe('10.62.0.7');
    expect(w.find('thead th.gt-xs').text()).toContain('Adresse');
  });

  // Item 3: selecting text to copy it does not open the details.
  it('opens nothing on a click that ends a text selection', async () => {
    const w = await mountPage();
    const selection = vi
      .spyOn(window, 'getSelection')
      .mockReturnValue({ isCollapsed: false, toString: () => 'admin@x' } as unknown as Selection);
    await w.find('tbody tr').trigger('click');
    expect(w.findComponent(AuditDetailsDialog).props('modelValue')).toBe(false);

    selection.mockReturnValue({ isCollapsed: true, toString: () => '' } as unknown as Selection);
    await w.find('tbody tr').trigger('click');
    expect(w.findComponent(AuditDetailsDialog).props('modelValue')).toBe(true);
    selection.mockRestore();
  });
});
