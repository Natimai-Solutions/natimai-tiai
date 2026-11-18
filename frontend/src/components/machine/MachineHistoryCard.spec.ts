import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn, QForm } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/interventions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/interventions')>()),
  createIntervention: vi.fn(),
  updateIntervention: vi.fn(),
  deleteIntervention: vi.fn(),
}));

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getSession: vi.fn(),
}));

import { tasksVersion } from 'src/composables/useTasksBadge';
import { getSession } from 'src/services/maintenance';
import { useAuthStore } from 'src/stores/auth';
import {
  createIntervention,
  deleteIntervention,
  type Intervention,
} from 'src/services/interventions';
import CardLoadError from 'src/components/CardLoadError.vue';
import MachineHistoryCard from './MachineHistoryCard.vue';

function mountCard(items: Intervention[] = [], permissions: string[] = []) {
  setActivePinia(createPinia());
  useAuthStore().user = { id: 'me', email: 'a@b.c', permissions } as never;
  return mount(MachineHistoryCard, {
    props: { machineId: 'm1', items, total: items.length, loading: false, canWrite: true },
    attachTo: document.body,
  });
}

const visit = {
  id: 'i1',
  machine_id: 'm1',
  kind: 'maintenance',
  title: 'Dépoussiérage',
  note: null,
  performed_at: '2026-11-10T20:00:00Z',
  performed_by: 'Alice',
  created_at: '2026-11-10T20:00:00Z',
  updated_at: '2026-11-10T20:00:00Z',
} as unknown as Intervention;

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

  describe('deleting a line', () => {
    /** Open the line's menu, pick « Supprimer », and answer the confirmation. */
    async function deleteLine(wrapper: ReturnType<typeof mountCard>) {
      let confirm: (() => void) | null = null;
      const dialog = vi.spyOn(wrapper.vm.$q, 'dialog').mockImplementation((() => ({
        onOk(fn: () => void) {
          confirm = fn;
          return this;
        },
      })) as never);
      await wrapper.find('[aria-label="Actions sur l\'intervention"]').trigger('click');
      await flushPromises();
      const entry = [...document.body.querySelectorAll('.q-menu .q-item')].find((el) =>
        el.textContent?.includes('Supprimer'),
      ) as HTMLElement;
      entry.click();
      await flushPromises();
      expect(dialog).toHaveBeenCalledTimes(1);
      confirm!();
      await flushPromises();
    }

    // Audit U19: the maintenance line deleted, the poste is due again.
    it('has the tasks badge read again once it is deleted', async () => {
      vi.mocked(deleteIntervention).mockResolvedValue(undefined);
      const wrapper = mountCard([visit]);
      const before = tasksVersion.value;

      await deleteLine(wrapper);

      expect(deleteIntervention).toHaveBeenCalledWith('i1');
      expect(tasksVersion.value).toBe(before + 1);
      expect(wrapper.emitted('changed')).toHaveLength(1);
      wrapper.unmount();
    });

    it('leaves the tasks badge alone when the deletion is refused', async () => {
      vi.mocked(deleteIntervention).mockRejectedValue(new Error('down'));
      const wrapper = mountCard([visit]);
      const before = tasksVersion.value;

      await deleteLine(wrapper);

      expect(tasksVersion.value).toBe(before);
      expect(wrapper.emitted('changed')).toBeUndefined();
      wrapper.unmount();
    });
  });
});

describe('MachineHistoryCard — a line of a maintenance visit (item 1, C8)', () => {
  const line = {
    ...visit,
    id: 'i2',
    title: 'Maintenance — A101',
    note: 'Clavier changé',
    maintenance_id: 's-1',
  } as unknown as Intervention;

  beforeEach(() => {
    vi.mocked(getSession).mockResolvedValue({
      id: 's-1',
      room_id: 'r-1',
      room_name: 'A101',
      performed_by: 'alice@test.local',
      performed_at: '2026-11-10T20:00:00Z',
      note: 'Salle dépoussiérée, vidéoprojecteur à revoir',
      machine_count: 1,
      items: [{ intervention_id: 'i2', machine_id: 'm1', hostname: 'PC-01', note: 'Clavier' }],
      skipped: [{ intervention_id: 'i3', machine_id: 'm2', hostname: 'PC-02', note: 'Absent' }],
    });
  });

  it('opens the visit with its global note and the postes done and skipped', async () => {
    const wrapper = mountCard([line], ['maintenance:read']);
    // The kind once: « Maintenance — A101 », not « Maintenance — Maintenance — A101 ».
    expect(wrapper.text()).toContain('Maintenance — A101');
    expect(wrapper.text()).not.toContain('Maintenance — Maintenance');
    const open = wrapper.findAllComponents(QBtn).find((b) => b.text().includes('Voir la séance'));
    expect(open).toBeDefined();
    await open!.trigger('click');
    await flushPromises();

    expect(getSession).toHaveBeenCalledWith('s-1');
    const dialog = document.body.querySelector('.q-dialog')!;
    expect(dialog.textContent).toContain('Salle dépoussiérée, vidéoprojecteur à revoir');
    expect(dialog.querySelector('[data-test="visit-done"]')!.textContent).toContain('PC-01');
    expect(dialog.querySelector('[data-test="visit-skipped"]')!.textContent).toContain('Absent');
    wrapper.unmount();
  });

  it('offers no link to whoever cannot read the maintenance', () => {
    const wrapper = mountCard([line], []);
    expect(wrapper.text()).not.toContain('Voir la séance');
    wrapper.unmount();
  });
});

// Review finding 4: the card must not say « aucune intervention » about a
// journal it has not read.
describe('MachineHistoryCard — a journal that was not read', () => {
  function mountWith(props: Record<string, unknown>) {
    setActivePinia(createPinia());
    useAuthStore().user = { id: 'me', email: 'a@b.c', permissions: [] } as never;
    return mount(MachineHistoryCard, {
      props: { machineId: 'm1', items: [], total: 0, loading: false, canWrite: true, ...props },
      attachTo: document.body,
    });
  }

  it('says the journal is empty once it was read, and empty', () => {
    const wrapper = mountWith({});
    expect(wrapper.text()).toContain('Aucune intervention enregistrée sur ce poste.');
    expect(wrapper.findComponent(CardLoadError).exists()).toBe(false);
    wrapper.unmount();
  });

  it('says the read failed, with « Réessayer », and claims no empty journal', async () => {
    const wrapper = mountWith({ failed: true });
    expect(wrapper.text()).not.toContain('Aucune intervention');
    const error = wrapper.findComponent(CardLoadError);
    expect(error.text()).toContain("Impossible de charger l'historique des interventions.");
    await error.findComponent(QBtn).trigger('click');
    expect(wrapper.emitted('retry')).toHaveLength(1);
    wrapper.unmount();
  });

  it('keeps the lines already shown under the error of a later read', () => {
    const wrapper = mountWith({ failed: true, items: [visit], total: 30 });
    expect(wrapper.findComponent(CardLoadError).exists()).toBe(true);
    expect(wrapper.text()).toContain('Dépoussiérage');
    wrapper.unmount();
  });

  // intervention:write without the read (a group made through the API): the
  // account may add a line, and is told why it sees none.
  it('says the account may not read the journal, rather than that it is empty', () => {
    const wrapper = mountWith({ canRead: false });
    expect(wrapper.text()).not.toContain('Aucune intervention');
    expect(wrapper.text()).toContain("Votre compte ne permet pas de consulter l'historique");
    expect(wrapper.text()).toContain('Ajouter une intervention');
    wrapper.unmount();
  });
});
