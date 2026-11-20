import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput, QOptionGroup, QSelect, QToggle } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
});
