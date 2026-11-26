import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput, QOptionGroup, QSelect, QToggle } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const shown = vi.hoisted(() => [] as { type?: string; message?: string }[]);
vi.mock('src/utils/notify', () => ({
  notify: (_q: unknown, build: () => { type?: string; message?: string }) => {
    shown.push(build());
    return () => undefined;
  },
}));
vi.mock('src/services/schedules', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/schedules')>()),
  createSchedule: vi.fn(),
  updateSchedule: vi.fn(),
}));
vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  listRooms: vi.fn(),
  listBuildings: vi.fn(),
}));
vi.mock('src/services/packages', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/packages')>()),
  listPackages: vi.fn(),
}));

import { listBuildings, listRooms, type Room } from 'src/services/rooms';
import { listPackages } from 'src/services/packages';
import {
  createSchedule,
  updateSchedule,
  type Schedule,
  type SchedulePayload,
  type ScheduleTargetIn,
} from 'src/services/schedules';
import { useAuthStore } from 'src/stores/auth';
import { approvalsVersion } from 'src/composables/useApprovalsBadge';
import ScheduleDialog from './ScheduleDialog.vue';

const ALL = [
  'command:execute',
  'risky_command:execute',
  'schedule:write',
  'room:read',
  'package:read',
];

async function open(
  props: { schedule?: Schedule | null; initialTarget?: ScheduleTargetIn | null } = {},
) {
  const wrapper = mount(ScheduleDialog, {
    props: {
      modelValue: false,
      schedule: props.schedule ?? null,
      initialTarget: props.initialTarget ?? null,
      timezone: 'Pacific/Tahiti',
      forbiddenWindows: [{ days: [0], start: '07:30', end: '12:00' }],
    },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  const input = (label: string) =>
    wrapper.findAllComponents(QInput).find((i) => i.props('label') === label)!;
  const select = (label: string) =>
    wrapper.findAllComponents(QSelect).find((i) => i.props('label') === label)!;
  const toggle = (label: string) =>
    wrapper.findAllComponents(QToggle).find((i) => i.props('label') === label)!;
  const set = async (component: { vm: { $emit: (e: string, v: unknown) => void } }, v: unknown) => {
    component.vm.$emit('update:modelValue', v);
    await flushPromises();
  };
  const submit = async () => {
    await wrapper.findComponent(QForm).trigger('submit');
    await flushPromises();
  };
  return { wrapper, input, select, toggle, set, submit };
}

function sent(fn: unknown): SchedulePayload {
  const calls = vi.mocked(fn as (...a: unknown[]) => unknown).mock.calls;
  return calls[calls.length - 1]!.at(-1) as SchedulePayload;
}

describe('ScheduleDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = '';
    useAuthStore().user = { id: 'u', email: 'a@b.c', permissions: ALL } as never;
    vi.mocked(createSchedule)
      .mockReset()
      .mockResolvedValue({} as Schedule);
    vi.mocked(updateSchedule)
      .mockReset()
      .mockResolvedValue({} as Schedule);
    vi.mocked(listRooms).mockResolvedValue([
      { id: 'r-1', name: 'A101', building: null } as unknown as Room,
    ]);
    vi.mocked(listBuildings).mockResolvedValue([]);
    vi.mocked(listPackages).mockResolvedValue([]);
  });

  it('plans a one-off on a room opened from it, in the console’s zone', async () => {
    const { input, submit, wrapper } = await open({
      initialTarget: { kind: 'room', value: 'r-1' },
    });
    expect(document.body.textContent).toContain('Heure du fuseau Pacific/Tahiti');
    expect(document.body.textContent).toContain('lundi 07:30–12:00');
    input('Nom').vm.$emit('update:modelValue', 'Analyse du soir');
    input('Date').vm.$emit('update:modelValue', '2026-12-01');
    input('Heure').vm.$emit('update:modelValue', '18:30');
    await flushPromises();
    await submit();
    expect(createSchedule).toHaveBeenCalledTimes(1);
    expect(sent(createSchedule)).toEqual({
      name: 'Analyse du soir',
      command_type: 'quick_scan',
      package_id: null,
      target: { kind: 'room', value: 'r-1' },
      recurrence: 'once',
      run_at_local: '2026-12-01T18:30',
      ttl_minutes: 180,
      wake_first: false,
      shutdown_after: false,
    });
    expect(wrapper.emitted('saved')).toHaveLength(1);
    wrapper.unmount();
  });

  // C10: beyond the threshold, saved but waiting for a second account.
  it('says a schedule saved beyond the threshold waits for approval', async () => {
    vi.mocked(createSchedule).mockResolvedValue({
      state: 'to_approve',
      approval: {
        id: 'ap-1',
        status: 'pending',
        expires_at: '2026-11-26T10:00:00Z',
        approved_by: null,
        approved_at: null,
        approved_count: null,
      },
    } as Schedule);
    const before = approvalsVersion.value;
    const { input, submit, wrapper } = await open({
      initialTarget: { kind: 'room', value: 'r-1' },
    });
    input('Nom').vm.$emit('update:modelValue', 'Redémarrage du soir');
    input('Date').vm.$emit('update:modelValue', '2026-12-01');
    input('Heure').vm.$emit('update:modelValue', '18:30');
    await flushPromises();
    await submit();
    await flushPromises();
    expect(approvalsVersion.value).toBe(before + 1);
    expect(shown.at(-1)?.type).toBe('info');
    expect(shown.at(-1)?.message).toContain(
      'Planification enregistrée, en attente d’approbation : un second compte doit l’approuver avant le',
    );
    expect(wrapper.emitted('saved')).toHaveLength(1);
    wrapper.unmount();
  });

  it('plans every week, wakes first and shuts down after', async () => {
    const { input, select, toggle, set, submit, wrapper } = await open({
      initialTarget: { kind: 'machines', machine_ids: ['m-1', 'm-2'] },
    });
    await set(input('Nom'), 'Mises à jour');
    await set(select('Action'), 'wu_install');
    await set(wrapper.findAllComponents(QOptionGroup)[0]!, 'weekly');
    // No day: refused here, nothing sent.
    await submit();
    expect(createSchedule).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Au moins un jour');
    await set(wrapper.findAllComponents(QOptionGroup)[1]!, [4, 2]);
    await set(toggle('Réveiller d’abord les postes éteints'), true);
    await set(toggle('Éteindre ensuite les postes réveillés'), true);
    await submit();
    expect(sent(createSchedule)).toMatchObject({
      command_type: 'wu_install',
      target: { kind: 'machines', machine_ids: ['m-1', 'm-2'] },
      recurrence: 'weekly',
      weekdays: [2, 4],
      time_of_day: '18:00',
      wake_first: true,
      shutdown_after: true,
    });
    expect(sent(createSchedule)).not.toHaveProperty('run_at_local');
    wrapper.unmount();
  });

  it('never shuts down after a shutdown, nor without waking first', async () => {
    const { input, select, toggle, set, submit, wrapper } = await open();
    await set(input('Nom'), 'Extinction');
    await set(input('Date'), '2026-12-01');
    await set(toggle('Réveiller d’abord les postes éteints'), true);
    await set(toggle('Éteindre ensuite les postes réveillés'), true);
    await set(toggle('Réveiller d’abord les postes éteints'), false);
    await submit();
    expect(sent(createSchedule)).toMatchObject({ wake_first: false, shutdown_after: false });
    await set(select('Action'), 'shutdown');
    expect(toggle('Éteindre ensuite les postes réveillés')).toBeUndefined();
    wrapper.unmount();
  });

  it('deploys in stages: two at least, the observation and the threshold sent', async () => {
    const { input, select, toggle, set, submit, wrapper } = await open({
      initialTarget: { kind: 'room', value: 'r-1' },
    });
    await set(input('Nom'), 'Par étapes');
    await set(input('Date'), '2026-12-01');
    expect(toggle('Déployer par étapes')).toBeUndefined();
    await set(select('Action'), 'wu_install');
    await set(toggle('Déployer par étapes'), true);
    await submit();
    expect(sent(createSchedule)).toMatchObject({
      rings: [{ target: { kind: 'room', value: 'r-1' } }, { target: { kind: 'all' } }],
      ring_observe_hours: 24,
      ring_failure_percent: 10,
    });
    wrapper.unmount();
  });

  it('rewrites a schedule from what it holds', async () => {
    const schedule = {
      id: 's-1',
      name: 'Scan',
      command_type: 'quick_scan',
      package_id: null,
      target: { kind: 'all', machine_ids: [], value: null, label: null, machine_count: null },
      recurrence: 'weekly',
      run_at_local: null,
      weekdays: [0, 2],
      time_of_day: '19:15',
      ttl_minutes: 120,
      wake_first: false,
      shutdown_after: false,
      rings: null,
    } as unknown as Schedule;
    const { submit, wrapper } = await open({ schedule });
    await submit();
    expect(updateSchedule).toHaveBeenCalledWith('s-1', expect.any(Object));
    expect(sent(updateSchedule)).toMatchObject({
      name: 'Scan',
      weekdays: [0, 2],
      time_of_day: '19:15',
      ttl_minutes: 120,
      target: { kind: 'all' },
    });
    wrapper.unmount();
  });

  // Rewritten under the threshold, a schedule that was waiting no longer is:
  // the server closed its request, so the badge reads again.
  it('has the approvals read again when a waiting schedule is rewritten to need none', async () => {
    const schedule = {
      id: 's-2',
      name: 'Redémarrage',
      command_type: 'quick_scan',
      package_id: null,
      state: 'to_approve',
      target: { kind: 'room', value: 'r-1', machine_ids: [], label: null, machine_count: null },
      recurrence: 'weekly',
      run_at_local: null,
      weekdays: [1],
      time_of_day: '18:00',
      ttl_minutes: 120,
      wake_first: false,
      shutdown_after: false,
      rings: null,
    } as unknown as Schedule;
    vi.mocked(updateSchedule).mockResolvedValue({ ...schedule, state: 'active' });
    const before = approvalsVersion.value;
    const { submit, wrapper } = await open({ schedule });
    await submit();
    expect(updateSchedule).toHaveBeenCalledWith('s-2', expect.any(Object));
    expect(approvalsVersion.value).toBe(before + 1);
    expect(shown.at(-1)?.type).toBe('positive');
    wrapper.unmount();
  });

  it('leaves the approvals alone when an active schedule is rewritten', async () => {
    const schedule = {
      id: 's-3',
      name: 'Scan',
      command_type: 'quick_scan',
      package_id: null,
      state: 'active',
      target: { kind: 'all', machine_ids: [], value: null, label: null, machine_count: null },
      recurrence: 'weekly',
      run_at_local: null,
      weekdays: [1],
      time_of_day: '18:00',
      ttl_minutes: 120,
      wake_first: false,
      shutdown_after: false,
      rings: null,
    } as unknown as Schedule;
    vi.mocked(updateSchedule).mockResolvedValue({ ...schedule });
    const before = approvalsVersion.value;
    const { submit, wrapper } = await open({ schedule });
    await submit();
    expect(updateSchedule).toHaveBeenCalledWith('s-3', expect.any(Object));
    expect(approvalsVersion.value).toBe(before);
    wrapper.unmount();
  });
});
