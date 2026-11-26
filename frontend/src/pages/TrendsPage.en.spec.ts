import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn } from 'quasar';
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

import { setLocale } from 'src/i18n';
import {
  downloadReport,
  getIndicators,
  getRecurringFailures,
  getTrends,
} from 'src/services/trends';
import { useAuthStore } from 'src/stores/auth';
import { downloadBlob } from 'src/utils/format';
import TrendsPage from './TrendsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function mountTrends() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: ['machine:read', 'intervention:read'],
  } as never;
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

describe('TrendsPage in English', () => {
  beforeEach(() => {
    setLocale('en');
    document.body.innerHTML = '';
    vi.mocked(getTrends).mockResolvedValue({
      days: ['2026-11-24', '2026-11-25'],
      series: { total: [5, 6], up_to_date: [4, 4] },
      step: 'day',
      provisional_day: '2026-11-25',
      since: '2026-11-24',
      policy_changes: [
        { day: '2026-11-25', key: 'maintenance.cycle_days', before: 365, after: 180 },
      ],
    });
    vi.mocked(getIndicators).mockResolvedValue({
      months: ['2026-10', '2026-11'],
      checks: [
        { month: '2026-10', closed: 1, median_hours: 2, p90_hours: 2, with_due: 0, on_time_due: 0 },
        {
          month: '2026-11',
          closed: 0,
          median_hours: null,
          p90_hours: null,
          with_due: 0,
          on_time_due: 0,
        },
      ],
      maintenance: null,
      commands: null,
      deployments: null,
      retention: { commands_days: 365, schedule_runs_days: 180 },
    });
    vi.mocked(getRecurringFailures).mockResolvedValue([
      {
        hw_model: null,
        incidents: 2,
        machines: 1,
        parc: 0,
        per_100: null,
        retired_incidents: 0,
        retired_machines: 0,
        last_at: null,
      },
    ]);
    vi.mocked(downloadReport).mockResolvedValue(new Blob());
  });
  afterEach(() => {
    setLocale('fr');
    document.body.innerHTML = '';
  });

  it('speaks English throughout', async () => {
    const w = await mountTrends();
    const text = w.text();
    expect(text).toContain('Fleet over time');
    expect(text).toContain('Tracked since 24/11/2026.');
    expect(text).toContain('Computers');
    expect(text).toContain('Maintenance cycle (days), 365 → 180');
    expect(text).toContain('Median: 2.0 h');
    expect(text).toContain('October 2026');
    expect(text).toContain('Unknown model');
    expect(text).toContain('12 months');
    expect(text).not.toMatch(/Tendances|Évolution|Modèle inconnu|mois/);
  });

  it('names the report’s file in English', async () => {
    const w = await mountTrends();
    const button = w.findAllComponents(QBtn).find((b) => b.props('label') === 'Excel report');
    await button!.trigger('click');
    await flushPromises();
    expect(vi.mocked(downloadBlob).mock.calls[0]![1]).toMatch(/^trends-report-/);
  });
});
