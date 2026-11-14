import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QForm } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/interventions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/interventions')>()),
  createIntervention: vi.fn(),
  updateIntervention: vi.fn(),
  deleteIntervention: vi.fn(),
}));

import { tasksVersion } from 'src/composables/useTasksBadge';
import { createIntervention } from 'src/services/interventions';
import MachineHistoryCard from './MachineHistoryCard.vue';

function mountCard() {
  return mount(MachineHistoryCard, {
    props: { machineId: 'm1', items: [], total: 0, loading: false, canWrite: true },
    attachTo: document.body,
  });
}

describe('MachineHistoryCard', () => {
  beforeEach(() => {
    vi.mocked(createIntervention).mockResolvedValue({} as never);
  });

  // Audit U19: a maintenance line moves the poste's due date, and with it
  // what « Mes tâches » counts.
  it('has the tasks badge read again once a line is added', async () => {
    const wrapper = mountCard();
    const before = tasksVersion.value;
    await wrapper
      .findAllComponents(QBtn)
      .find((b) => b.text().includes('Ajouter une intervention'))!
      .trigger('click');
    await flushPromises();

    wrapper.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();

    expect(createIntervention).toHaveBeenCalledWith('m1', expect.anything());
    expect(tasksVersion.value).toBe(before + 1);
    expect(wrapper.emitted('changed')).toHaveLength(1);
    wrapper.unmount();
  });
});
