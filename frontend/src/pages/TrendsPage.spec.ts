import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn, QBtnToggle, QChip, QSelect } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/trends', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/trends')>()),
  getTrends: vi.fn(),
  getIndicators: vi.fn(),
  getRecurringFailures: vi.fn(),
  downloadReport: vi.fn(),
}));
vi.mock('src/utils/format', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/utils/format')>()),
  downloadBlob: vi.fn(),
}));

import {
  DEFAULT_TREND_KEYS,
  downloadReport,
  getIndicators,
  getRecurringFailures,
  getTrends,
  type Indicators,
  type Trends,
} from 'src/services/trends';
import { useAuthStore } from 'src/stores/auth';
import { downloadBlob } from 'src/utils/format';
import TrendsPage from './TrendsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

function trendsData(over: Partial<Trends> = {}): Trends {
  const values = (n: number) => [n, null, n + 1];
  return {
    days: ['2026-11-23', '2026-11-24', '2026-11-25'],
    series: Object.fromEntries(DEFAULT_TREND_KEYS.map((k, i) => [k, values(10 + i)])),
    step: 'day',
    provisional_day: '2026-11-25',
    since: '2026-11-23',
    policy_changes: [],
    ...over,
  };
}

function indicatorsData(over: Partial<Indicators> = {}): Indicators {
  return {
    months: ['2026-10', '2026-11'],
    checks: null,
    maintenance: null,
    commands: [
      { month: '2026-10', succeeded: 3, failed: 1, expired: 0, unanswered: 0 },
      { month: '2026-11', succeeded: 0, failed: 0, expired: 0, unanswered: 0 },
    ],
    deployments: null,
    retention: { commands_days: 365, schedule_runs_days: 180 },
    ...over,
  };
}

async function mountTrends(permissions: string[] = ['machine:read', 'intervention:read']) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/trends', name: 'trends', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
    ],
  });
  await router.push('/trends');
  const wrapper = mount(TrendsPage, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return wrapper;
}

describe('TrendsPage', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.mocked(getTrends).mockReset().mockResolvedValue(trendsData());
    vi.mocked(getIndicators).mockReset().mockResolvedValue(indicatorsData());
    vi.mocked(getRecurringFailures).mockReset().mockResolvedValue([]);
    vi.mocked(downloadReport).mockReset().mockResolvedValue(new Blob());
    vi.mocked(downloadBlob).mockReset();
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('loads its three blocks for twelve months, the default series by name', async () => {
    const w = await mountTrends();
    expect(getTrends).toHaveBeenCalledWith({ months: 12, keys: [...DEFAULT_TREND_KEYS] });
    expect(getIndicators).toHaveBeenCalledWith(12);
    expect(getRecurringFailures).toHaveBeenCalledWith({ months: 12, by: 'hw_model' });
    expect(w.find('[data-test="trends-fleet"] svg').exists()).toBe(true);
    expect(w.find('[data-test="indicator-commands"]').text()).toContain('75 % de réussite');
    expect(w.find('[data-test="trends-failures"]').exists()).toBe(true);
    expect(w.findAllComponents(QChip)).toHaveLength(DEFAULT_TREND_KEYS.length);
  });

  it('says since when the fleet is tracked, and that today’s point is provisional', async () => {
    const w = await mountTrends();
    const text = w.find('[data-test="trends-fleet"]').text();
    expect(text).toContain('Suivi depuis le 23/11/2026.');
    expect(text).toContain('Le point d’aujourd’hui est provisoire');
    expect(text).toContain('Postes de votre périmètre');
  });

  it('says the tracking has not started before the first photo', async () => {
    vi.mocked(getTrends).mockResolvedValue(
      trendsData({ days: [], series: {}, since: null, provisional_day: null }),
    );
    const w = await mountTrends();
    expect(w.find('[data-test="trends-not-started"]').exists()).toBe(true);
    expect(w.find('[data-test="trends-fleet"] svg').exists()).toBe(false);
  });

  it('asks again for every block when the period changes', async () => {
    const w = await mountTrends();
    w.findComponent(QBtnToggle).vm.$emit('update:modelValue', 24);
    await flushPromises();
    expect(getTrends).toHaveBeenLastCalledWith({ months: 24, keys: [...DEFAULT_TREND_KEYS] });
    expect(getIndicators).toHaveBeenLastCalledWith(24);
    expect(getRecurringFailures).toHaveBeenLastCalledWith({ months: 24, by: 'hw_model' });
  });

  it('asks for a series added, and keeps the others’ colours when one is removed', async () => {
    const w = await mountTrends();
    w.findComponent(QSelect).vm.$emit('update:modelValue', 'alerts.disk_low');
    await flushPromises();
    expect(getTrends).toHaveBeenLastCalledWith({
      months: 12,
      keys: [...DEFAULT_TREND_KEYS, 'alerts.disk_low'],
    });
    const chips = () => w.findAllComponents(QChip);
    expect(chips().at(-1)!.text()).toContain('Alerte : Disque système presque plein');
    const calls = vi.mocked(getTrends).mock.calls.length;
    chips()[0]!.vm.$emit('remove');
    await flushPromises();
    // Removing needs nothing from the server; the survivors keep their slots.
    expect(vi.mocked(getTrends).mock.calls.length).toBe(calls);
    const swatches = chips().map((c) => c.find('.trend-chip-swatch').attributes('style'));
    expect(swatches[0]).toContain('--ti-series-2');
    expect(swatches.at(-1)).toContain('--ti-series-8');
  });

  it('shows the figures in a table, a dash for a day without a photo', async () => {
    const w = await mountTrends();
    expect(w.find('[data-test="trends-table"]').exists()).toBe(false);
    await w.find('[data-test="trends-table-toggle"]').trigger('click');
    const rows = w.findAll('[data-test="trends-table"] tbody tr').map((r) => r.text());
    expect(rows).toHaveLength(3);
    expect(rows[0]).toContain('23/11/2026');
    expect(rows[0]).toContain('10');
    expect(rows[1]).toContain('—');
  });

  it('marks the threshold changes under the chart', async () => {
    vi.mocked(getTrends).mockResolvedValue(
      trendsData({
        policy_changes: [
          { day: '2026-11-24', key: 'fleet.low_disk_free_percent', before: 10, after: 15 },
          { day: '2026-11-24', key: 'fleet.agent_expected_version', before: null, after: '2.1.0' },
        ],
      }),
    );
    const w = await mountTrends();
    const text = w.find('[data-test="trends-policies"]').text();
    expect(text).toContain('24/11/2026 : Seuil « disque presque plein » (%), 10 → 15');
    expect(text).toContain('Version d’agent de référence, aucun → 2.1.0');
  });

  it('words the choices and the yes/no of a threshold, free text as it is', async () => {
    vi.mocked(getTrends).mockResolvedValue(
      trendsData({
        policy_changes: [
          {
            day: '2026-11-24',
            key: 'compliance.unencrypted_scope',
            before: 'laptops',
            after: 'all',
          },
          { day: '2026-11-24', key: 'fleet.some_flag', before: false, after: true },
        ],
      }),
    );
    const w = await mountTrends();
    const text = w.find('[data-test="trends-policies"]').text();
    expect(text).toContain(
      'Périmètre du chiffrement, Portables et tablettes seulement → Tous les postes',
    );
    expect(text).toContain('fleet.some_flag, non → oui');
    expect(text).not.toContain('laptops');
  });

  // A late answer for an earlier period is not drawn under the period chosen since.
  it('drops a late answer to a period left since', async () => {
    const w = await mountTrends();
    let answer12!: (t: Trends) => void;
    let answerIndicators12!: (i: Indicators) => void;
    vi.mocked(getTrends)
      .mockImplementationOnce(() => new Promise((ok) => (answer12 = ok)))
      .mockResolvedValueOnce(trendsData({ since: '2024-01-01' }));
    vi.mocked(getIndicators)
      .mockImplementationOnce(() => new Promise((ok) => (answerIndicators12 = ok)))
      .mockResolvedValueOnce(
        indicatorsData({ retention: { commands_days: 90, schedule_runs_days: 180 } }),
      );
    const toggle = w.findComponent(QBtnToggle);
    toggle.vm.$emit('update:modelValue', 3);
    await flushPromises();
    toggle.vm.$emit('update:modelValue', 24);
    await flushPromises();
    answer12(trendsData({ since: '2026-09-01' }));
    answerIndicators12(indicatorsData());
    await flushPromises();
    const text = w.find('[data-test="trends-fleet"]').text();
    expect(text).toContain('Suivi depuis le 01/01/2024.');
    expect(text).not.toContain('01/09/2026');
    expect(w.find('[data-test="indicators-retention"]').text()).toContain(
      'Historique conservé : 90 jours',
    );
  });

  it('shows no indicator card for a section the account may not read', async () => {
    const w = await mountTrends();
    expect(w.find('[data-test="indicator-checks"]').exists()).toBe(false);
    expect(w.find('[data-test="indicator-commands"]').exists()).toBe(true);
  });

  it('warns when the history is purged sooner than the period', async () => {
    vi.mocked(getIndicators).mockResolvedValue(
      indicatorsData({ retention: { commands_days: 90, schedule_runs_days: 180 } }),
    );
    const w = await mountTrends();
    expect(w.find('[data-test="indicators-retention"]').text()).toContain(
      'Historique conservé : 90 jours',
    );
  });

  it('leaves the recurring failures out without intervention:read', async () => {
    const w = await mountTrends(['machine:read']);
    expect(w.find('[data-test="trends-failures"]').exists()).toBe(false);
    expect(getRecurringFailures).not.toHaveBeenCalled();
  });

  it('downloads the report for the period shown', async () => {
    const w = await mountTrends();
    const button = w.findAllComponents(QBtn).find((b) => b.props('label') === 'Rapport Excel');
    await button!.trigger('click');
    await flushPromises();
    expect(downloadReport).toHaveBeenCalledWith(12);
    expect(vi.mocked(downloadBlob).mock.calls[0]![1]).toMatch(
      /^rapport-tendances-\d{4}-\d{2}-\d{2}\.xlsx$/,
    );
  });

  it('says so when the fleet’s history cannot be loaded', async () => {
    vi.mocked(getTrends).mockRejectedValue(new Error('down'));
    const w = await mountTrends();
    expect(w.find('[data-test="trends-fleet"]').text()).toContain(
      'L’évolution du parc n’a pas pu être chargée.',
    );
  });
});
