// The dashboard in English (plan `dev/plan-console-bilingue.md`, I6), and
// following a change of language while it is open.
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/stats', () => ({ getOverview: vi.fn() }));
vi.mock('src/services/machines', () => ({ listMachines: vi.fn() }));
vi.mock('src/services/threats', () => ({ listThreats: vi.fn() }));

import { setLocale } from 'src/i18n';
import { listMachines } from 'src/services/machines';
import { getOverview, type StatsOverview } from 'src/services/stats';
import { listThreats } from 'src/services/threats';
import { useAuthStore } from 'src/stores/auth';
import DashboardPage from './DashboardPage.vue';

const Stub = defineComponent({ render: () => h('div') });

const overview: StatsOverview = {
  total: 120,
  up_to_date: 100,
  outdated: 4,
  needs_verification: 2,
  inactive: 3,
  with_active_threats: 1,
  machines_wu_pending: 7,
  machines_reboot_required: 2,
  machines_low_disk: 5,
  machines_unencrypted: 0,
  machines_aging: 9,
  software_count: 840,
  low_disk_free_percent: 10,
  hardware_aging_years: 6,
  machines_agent_outdated: 11,
  open_checks: 3,
  machines_maintenance_overdue: 4,
  machines_maintenance_due_soon: 6,
  agent_latest_version: '1.4.2',
  machines_usage_low: 12,
  machines_usage_high: 8,
  usage_low_hours: 10,
  usage_high_hours: 200,
  usage_window_days: 30,
  usage_since: '2026-01-01T00:00:00Z',
  machines_reenroll_pending: 1,
  machines_token_revoked: 2,
};

const machine = {
  id: 'm1',
  hostname: 'PC-01',
  machine_uuid: 'uuid-1',
  domain: 'school.local',
  is_up_to_date: false,
  wu_pending_count: 3,
  last_seen: '2026-11-18T08:00:00Z',
};

const threat = {
  id: 't1',
  machine_id: 'm1',
  threat_name: 'Trojan:Win32/Wacatac',
  detection_id: 'd1',
  severity: 'severe',
  status: 'active',
  detected_at: '2026-11-18T07:00:00Z',
};

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'a@b.c',
    permissions: ['machine:read', 'threat:read'],
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: Stub },
      { path: '/machines', name: 'machines', component: Stub },
      { path: '/software', name: 'software', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/');
  const wrapper = mount(DashboardPage, {
    shallow: true,
    global: { plugins: [router, pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return wrapper;
}

describe('DashboardPage in English', () => {
  beforeEach(() => {
    vi.mocked(getOverview).mockResolvedValue(overview);
    vi.mocked(listMachines).mockResolvedValue({
      items: [machine],
      total: 1,
      page: 1,
      page_size: 5,
    } as never);
    vi.mocked(listThreats).mockResolvedValue({
      items: [threat],
      total: 1,
      page: 1,
      page_size: 5,
    } as never);
  });
  afterEach(() => setLocale('fr'));

  it('shows every card and list in English, and no French', async () => {
    setLocale('en');
    const text = (await mountPage()).text();
    for (const words of [
      'Dashboard',
      'Refreshed at',
      'Computers',
      'Software',
      'Rarely used',
      'under 10 h in 30 days',
      'Always on',
      'over 200 h in 30 days',
      'Outdated antivirus signatures',
      'Windows updates needed',
      '2 restarts needed',
      'With threats',
      'Disk almost full',
      'under 10% free',
      'Re-enrolments to approve',
      'Revoked tokens',
      'Identity to confirm',
      'Checks requested',
      'Inactive',
      'Maintenance overdue',
      '6 due soon',
      'Outdated agents',
      'reference 1.4.2',
      'Due for replacement',
      'hardware over 6 years old',
      'Computers to update',
      'Outdated antivirus',
      '3 Windows updates',
      'Active threats',
      'Trojan:Win32/Wacatac',
      'Severe — Active',
    ]) {
      expect(text).toContain(words);
    }
    expect(text).not.toMatch(/[éèàùçêô«»]/);
  });

  it('switches language while it is open', async () => {
    const wrapper = await mountPage();
    expect(wrapper.text()).toContain('Tableau de bord');
    expect(wrapper.text()).toContain('Toujours allumés');
    expect(wrapper.text()).toContain('2 redémarrages requis');
    setLocale('en');
    await nextTick();
    expect(wrapper.text()).toContain('Dashboard');
    expect(wrapper.text()).toContain('Always on');
    expect(wrapper.text()).not.toContain('Tableau de bord');
    expect(wrapper.find('[aria-label="Refresh"]').exists()).toBe(true);
  });

  it('says so in English when the lists are empty', async () => {
    vi.mocked(listMachines).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 5,
    } as never);
    vi.mocked(listThreats).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 5 });
    setLocale('en');
    const text = (await mountPage()).text();
    expect(text).toContain('All computers are up to date.');
    expect(text).toContain('No active threats.');
  });
});
