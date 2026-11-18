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

  // Item 3: the row is text to select and copy; the eye button opens the details.
  it('opens the details from the eye button only, not from a click on the row', async () => {
    const w = await mountPage();
    const row = w.find('tbody tr');
    const cell = row.find('td.audit-summary');
    // The two clicks of a double-click on a word, then the double-click.
    await cell.trigger('click');
    await cell.trigger('click');
    await cell.trigger('dblclick');
    expect(w.findComponent(AuditDetailsDialog).props('modelValue')).toBe(false);

    await row.find('button[aria-label="Voir le détail"]').trigger('click');
    expect(w.findComponent(AuditDetailsDialog).props('modelValue')).toBe(true);
  });
});
