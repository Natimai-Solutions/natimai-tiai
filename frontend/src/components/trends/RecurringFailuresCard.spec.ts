import { flushPromises, mount } from '@vue/test-utils';
import { QBtnToggle } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { RouterLink, createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/trends', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/trends')>()),
  getRecurringFailures: vi.fn(),
}));

import { getRecurringFailures, type FailureRow } from 'src/services/trends';
import RecurringFailuresCard from './RecurringFailuresCard.vue';

const Stub = defineComponent({ render: () => h('div') });

const row = (over: Partial<FailureRow>): FailureRow => ({
  incidents: 4,
  machines: 3,
  parc: 10,
  per_100: 40,
  retired_incidents: 0,
  retired_machines: 0,
  last_at: '2026-11-20T04:00:00Z',
  ...over,
});

async function mountCard(months = 12) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'trends', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
    ],
  });
  await router.push('/');
  const w = mount(RecurringFailuresCard, { props: { months }, global: { plugins: [router] } });
  await flushPromises();
  const links = () =>
    w.findAllComponents(RouterLink).map((l) => JSON.stringify(l.props('to') as unknown));
  return { w, links };
}

describe('RecurringFailuresCard', () => {
  beforeEach(() => vi.mocked(getRecurringFailures).mockReset());

  it('lists the models, each opening the postes of that exact model', async () => {
    vi.mocked(getRecurringFailures).mockResolvedValue([
      row({ hw_model: 'OptiPlex 7010' }),
      row({ hw_model: null, incidents: 2, per_100: null, parc: 0 }),
    ]);
    const { w, links } = await mountCard();
    expect(getRecurringFailures).toHaveBeenCalledWith({ months: 12, by: 'hw_model' });
    expect(w.text()).toContain('OptiPlex 7010');
    expect(w.text()).toContain('Modèle inconnu');
    // The list matches a model from its URL exactly; the unknown one has no link.
    expect(links()).toEqual([
      JSON.stringify({ name: 'machines', query: { hw_model: 'OptiPlex 7010' } }),
    ]);
  });

  it('writes « — » for a rate over an empty parc', async () => {
    vi.mocked(getRecurringFailures).mockResolvedValue([
      row({ hw_model: 'Vieux', parc: 0, per_100: null, retired_incidents: 5 }),
    ]);
    const { w } = await mountCard();
    const cells = w.findAll('tbody td').map((td) => td.text());
    expect(cells).toEqual(['Vieux', '4', '3', '0', '—', '5', '0', expect.any(String)]);
  });

  it('switches to the rooms, the one outside the scope named but never linked', async () => {
    vi.mocked(getRecurringFailures).mockResolvedValue([row({ hw_model: 'X' })]);
    const { w, links } = await mountCard(3);
    vi.mocked(getRecurringFailures).mockResolvedValue([
      row({ room_id: 'r-1', room_name: 'A101', building_name: 'Bât. A' }),
      row({ room_id: null, out_of_scope: true }),
      row({ room_id: null, out_of_scope: false }),
    ]);
    w.findComponent(QBtnToggle).vm.$emit('update:modelValue', 'room');
    await flushPromises();
    expect(getRecurringFailures).toHaveBeenLastCalledWith({ months: 3, by: 'room' });
    expect(w.text()).toContain('Bât. A — A101');
    expect(w.text()).toContain('Autre salle (hors de votre périmètre)');
    expect(w.text()).toContain('Sans salle');
    expect(links()).toEqual([JSON.stringify({ name: 'machines', query: { room: 'r-1' } })]);
  });

  it('reloads when the period changes', async () => {
    vi.mocked(getRecurringFailures).mockResolvedValue([]);
    const { w } = await mountCard(12);
    expect(w.text()).toContain('Aucune panne récurrente sur la période.');
    await w.setProps({ months: 24 });
    await flushPromises();
    expect(getRecurringFailures).toHaveBeenLastCalledWith({ months: 24, by: 'hw_model' });
  });
});
