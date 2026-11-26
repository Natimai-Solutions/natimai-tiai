import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn, QTable } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/schedules', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/schedules')>()),
  listSchedules: vi.fn(),
  setScheduleEnabled: vi.fn(),
  listScheduleRuns: vi.fn(),
}));

import ScheduleDialog from 'src/components/schedule/ScheduleDialog.vue';
import {
  listScheduleRuns,
  listSchedules,
  setScheduleEnabled,
  type Schedule,
} from 'src/services/schedules';
import { setLocale } from 'src/i18n';
import { useAuthStore } from 'src/stores/auth';
import { approvalsVersion } from 'src/composables/useApprovalsBadge';
import SchedulesPage from './SchedulesPage.vue';

const Stub = defineComponent({ render: () => h('div') });

const suspended = {
  id: 's-1',
  name: 'Redémarrage du soir',
  command_type: 'reboot',
  package_id: null,
  package_name: null,
  target: { kind: 'room', machine_ids: [], value: 'r-1', label: 'A101', machine_count: null },
  recurrence: 'weekly',
  run_at_local: null,
  weekdays: [0, 1, 2, 3, 4],
  time_of_day: '18:00',
  ttl_minutes: 180,
  wake_first: true,
  shutdown_after: false,
  rings: null,
  ring_observe_hours: null,
  ring_failure_percent: null,
  state: 'suspended',
  suspended_code: 'permission_lost',
  suspended_at: '2026-11-20T04:00:00Z',
  next_run_at: null,
  next_run_local: null,
  last_run_at: '2026-11-20T04:00:00Z',
  last_run: {
    id: 'run-1',
    started_at: '2026-11-20T04:00:00Z',
    finished_at: '2026-11-20T04:00:00Z',
    status: 'suspended',
    result_code: 'permission_lost',
    result_params: { permission: 'risky_command:execute' },
    created: 0,
    skipped: 0,
    left_out: 0,
    woken: 0,
    shut_down: 0,
    kept_on: 0,
    stage: 0,
  },
  created_by: 'tech@lycee.test',
  created_at: '2026-11-19T04:00:00Z',
  updated_at: '2026-11-19T04:00:00Z',
} as Schedule;

async function mountAt(path: string, permissions: string[]) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/schedules', name: 'schedules', component: Stub },
      { path: '/approvals', name: 'approvals', component: Stub },
    ],
  });
  await router.push(path);
  const wrapper = mount(SchedulesPage, {
    attachTo: document.body,
    global: {
      plugins: [pinia, router],
      stubs: { ScheduleDialog: true, QPage: { template: '<div><slot /></div>' } },
    },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('SchedulesPage', () => {
  beforeEach(() => {
    vi.mocked(listSchedules)
      .mockReset()
      .mockResolvedValue({
        items: [suspended],
        total: 1,
        page: 1,
        page_size: 200,
        timezone: 'Pacific/Tahiti',
        forbidden_windows: [],
      });
    vi.mocked(setScheduleEnabled).mockReset().mockResolvedValue(suspended);
    vi.mocked(listScheduleRuns)
      .mockReset()
      .mockResolvedValue({
        items: [suspended.last_run!],
        total: 1,
        page: 1,
        page_size: 50,
      });
  });

  it('lists the schedules, a suspended one with why', async () => {
    const { wrapper } = await mountAt('/schedules', ['schedule:read']);
    expect(wrapper.findComponent(QTable).props('rows')).toHaveLength(1);
    const text = wrapper.text();
    expect(text).toContain('Pacific/Tahiti');
    expect(text).toContain('Suspendue');
    expect(text).toContain('Son auteur n’a plus le droit « risky_command:execute ».');
    // Read-only: nothing to write with.
    expect(wrapper.findAllComponents(QBtn).some((b) => b.props('icon') === 'edit')).toBe(false);
  });

  it('turns one back on, and shows its runs', async () => {
    const { wrapper } = await mountAt('/schedules', ['schedule:read', 'schedule:write']);
    const button = (icon: string) =>
      wrapper.findAllComponents(QBtn).find((b) => b.props('icon') === icon)!;
    await button('play_arrow').trigger('click');
    await flushPromises();
    expect(setScheduleEnabled).toHaveBeenCalledWith('s-1', true);
    expect(listSchedules).toHaveBeenCalledTimes(2);
    await button('history').trigger('click');
    await flushPromises();
    expect(listScheduleRuns).toHaveBeenCalledWith('s-1', { page_size: 50 });
  });

  it('opens the form on the room or the postes it was sent from', async () => {
    const { wrapper, router } = await mountAt('/schedules?room=r-9', [
      'schedule:read',
      'schedule:write',
    ]);
    const dialog = wrapper.findComponent(ScheduleDialog);
    expect(dialog.props('modelValue')).toBe(true);
    expect(dialog.props('initialTarget')).toEqual({ kind: 'room', value: 'r-9' });
    expect(router.currentRoute.value.query).toEqual({});

    const second = await mountAt('/schedules?machines=m-1,m-2', [
      'schedule:read',
      'schedule:write',
    ]);
    expect(second.wrapper.findComponent(ScheduleDialog).props('initialTarget')).toEqual({
      kind: 'machines',
      machine_ids: ['m-1', 'm-2'],
    });
  });

  // C10: a schedule waiting for a second account, and the causes of a
  // suspension that came from an approval.
  describe('two-person approval', () => {
    const waiting = {
      ...suspended,
      id: 's-2',
      state: 'to_approve',
      suspended_code: null,
      last_run: null,
      approval: {
        id: 'ap-1',
        status: 'pending',
        expires_at: '2026-11-26T10:00:00Z',
        approved_by: null,
        approved_at: null,
        approved_count: null,
      },
    } as Schedule;

    function listing(items: Schedule[]) {
      vi.mocked(listSchedules).mockResolvedValue({
        items,
        total: items.length,
        page: 1,
        page_size: 200,
        timezone: 'Pacific/Tahiti',
        forbidden_windows: [],
      });
    }

    it('shows « À approuver » with its deadline, and the way to the page for an approver', async () => {
      listing([waiting]);
      const { wrapper } = await mountAt('/schedules', [
        'schedule:read',
        'command:execute',
        'risky_command:execute',
      ]);
      expect(wrapper.find('[data-test="schedule-state"]').text()).toContain('À approuver');
      const note = wrapper.find('[data-test="schedule-to-approve"]');
      expect(note.text()).toContain('En attente d’approbation, avant le');
      expect(note.find('a').text()).toBe('Approbations');

      const reader = await mountAt('/schedules', ['schedule:read']);
      expect(reader.wrapper.find('[data-test="schedule-to-approve"] a').exists()).toBe(false);
    });

    it('can be turned off while it waits, which closes its request', async () => {
      listing([waiting]);
      vi.mocked(setScheduleEnabled).mockResolvedValue({ ...waiting, state: 'disabled' });
      const { wrapper } = await mountAt('/schedules', ['schedule:read', 'schedule:write']);
      const before = approvalsVersion.value;
      await wrapper
        .findAllComponents(QBtn)
        .find((b) => b.props('icon') === 'pause')!
        .trigger('click');
      await flushPromises();
      expect(setScheduleEnabled).toHaveBeenCalledWith('s-2', false);
      expect(approvalsVersion.value).toBe(before + 1);
    });

    it('turned back on beyond the threshold, it waits again and the badge reads again', async () => {
      vi.mocked(setScheduleEnabled).mockResolvedValue(waiting);
      const { wrapper } = await mountAt('/schedules', ['schedule:read', 'schedule:write']);
      const before = approvalsVersion.value;
      await wrapper
        .findAllComponents(QBtn)
        .find((b) => b.props('icon') === 'play_arrow')!
        .trigger('click');
      await flushPromises();
      expect(approvalsVersion.value).toBe(before + 1);
    });

    it.each([
      ['approval_rejected', 'Sa demande d’approbation a été refusée.'],
      ['approval_expired', 'Sa demande d’approbation a expiré sans décision.'],
      ['approval_required', 'une approbation est nécessaire'],
    ])('says why it was suspended: %s', async (code, text) => {
      listing([{ ...suspended, suspended_code: code, last_run: null }]);
      const { wrapper } = await mountAt('/schedules', ['schedule:read']);
      expect(wrapper.text()).toContain(text);
    });

    // An approval that found the target grown suspends without a run: the
    // text has no number to show, so it carries none (FR and EN).
    it.each([
      [
        'fr',
        'Au moment de l’approbation, elle visait plus de postes que la demande n’en annonçait.',
      ],
      ['en', 'When it was approved, it targeted more computers than the request stated.'],
    ] as const)('says the target grew, without a run, in %s', async (locale, text) => {
      listing([{ ...suspended, suspended_code: 'target_grew', last_run: null }]);
      setLocale(locale);
      try {
        const { wrapper } = await mountAt('/schedules', ['schedule:read']);
        const note = wrapper.find('.text-negative').text();
        expect(note).toBe(text);
        expect(note).not.toMatch(/[{}]|\s{2}|\s[,.]/);
      } finally {
        setLocale('fr');
      }
    });
  });
});
