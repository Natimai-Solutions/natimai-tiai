import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/alerts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/alerts')>()),
  listAlerts: vi.fn(),
}));

import { listAlerts, type Alert } from 'src/services/alerts';
import MachineAlertsCard from './MachineAlertsCard.vue';

function alert(id: string, rule: string, resolved = false): Alert {
  return {
    id,
    machine_id: 'm-1',
    rule,
    opened_at: '2026-11-18T10:00:00Z',
    resolved_at: resolved ? '2026-11-19T10:00:00Z' : null,
    detail: { free_percent: 3, threshold_percent: 10 },
    check_id: null,
    machine: null,
  };
}

function answer(items: Alert[]) {
  vi.mocked(listAlerts).mockResolvedValue({
    items,
    total: items.length,
    page: 1,
    page_size: 100,
    open_by_rule: {},
  });
}

describe('MachineAlertsCard', () => {
  beforeEach(() => vi.mocked(listAlerts).mockReset());

  it('stays out of the way on a poste with no alert', async () => {
    answer([]);
    const wrapper = mount(MachineAlertsCard, { props: { machineId: 'm-1' } });
    await flushPromises();
    expect(wrapper.text()).toBe('');
    expect(listAlerts).toHaveBeenCalledWith({ machine_id: 'm-1', state: 'all', page_size: 100 });
  });

  it('lists the open alerts, the history on demand', async () => {
    answer([alert('a', 'disk_low'), alert('b', 'inactive', true)]);
    const wrapper = mount(MachineAlertsCard, { props: { machineId: 'm-1' } });
    await flushPromises();
    expect(wrapper.text()).toContain('Disque système presque plein');
    expect(wrapper.text()).toContain('3 % libres (seuil : 10 %)');
    expect(wrapper.text()).not.toContain('Sans contact');

    await wrapper.find('button').trigger('click');
    expect(wrapper.text()).toContain('Sans contact');
  });

  it('shows « Vérification demandée » while that verification is open only', async () => {
    answer([
      { ...alert('a', 'disk_low'), check_id: 'c-1', check_open: true },
      { ...alert('b', 'inactive'), check_id: 'c-2', check_open: false },
    ]);
    const wrapper = mount(MachineAlertsCard, { props: { machineId: 'm-1' } });
    await flushPromises();
    expect(wrapper.text().match(/Vérification demandée/g)).toHaveLength(1);
  });

  it('reads again when the fiche reloads', async () => {
    answer([alert('a', 'disk_low')]);
    const wrapper = mount(MachineAlertsCard, { props: { machineId: 'm-1', refreshKey: 1 } });
    await flushPromises();
    await wrapper.setProps({ refreshKey: 2 });
    await flushPromises();
    expect(listAlerts).toHaveBeenCalledTimes(2);
  });
});
