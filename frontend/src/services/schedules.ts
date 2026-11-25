import { api } from 'boot/axios';
import { errorCodeMessage, t } from 'src/i18n';
import { formatDate, formatDateTime } from 'src/utils/format';
import { weekdayName } from 'src/utils/settingsSchedule';

/**
 * Schedules (C3): a command run later or every week, on behalf of its author,
 * on a target the server resolves when it runs. Times are written and read in
 * the console's zone (`timezone` of the list, a setting of the page
 * Paramètres) — the server sends them already local (`*_local`), whatever the
 * browser's zone.
 */

export type TargetKind =
  'machines' | 'all' | 'domain' | 'location' | 'status' | 'room' | 'building';

export interface ScheduleTargetIn {
  kind: TargetKind;
  machine_ids?: string[];
  value?: string | null;
}

export interface ScheduleTarget {
  kind: TargetKind;
  machine_ids: string[];
  value: string | null;
  /** The room or building named, or the first few postes. */
  label: string | null;
  machine_count: number | null;
}

export interface ScheduleRun {
  id: string;
  started_at: string;
  /** The same instant, and a missed occurrence's planned hour, in the
   * console's zone (`AAAA-MM-JJTHH:MM`). Optional: an older server. */
  started_local?: string | null;
  due_local?: string | null;
  finished_at: string | null;
  /** running, done, suspended, failed, halted. */
  status: string;
  result_code: string | null;
  result_params: Record<string, unknown> | null;
  created: number;
  skipped: number;
  left_out: number;
  woken: number;
  shut_down: number;
  kept_on: number;
  stage: number;
}

export interface Schedule {
  id: string;
  name: string;
  command_type: string;
  package_id: string | null;
  package_name: string | null;
  target: ScheduleTarget;
  recurrence: 'once' | 'weekly';
  /** « 2026-11-25T18:00 », local to the console's zone. */
  run_at_local: string | null;
  weekdays: number[];
  time_of_day: string | null;
  ttl_minutes: number;
  wake_first: boolean;
  shutdown_after: boolean;
  rings: ScheduleTarget[] | null;
  ring_observe_hours: number | null;
  ring_failure_percent: number | null;
  /** `to_approve` (C10): waiting for a second account before it runs. */
  state: 'active' | 'disabled' | 'suspended' | 'done' | 'to_approve';
  suspended_code: string | null;
  suspended_at: string | null;
  next_run_at: string | null;
  next_run_local: string | null;
  last_run_at: string | null;
  last_run: ScheduleRun | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  /**
   * Its approval (C10): the latest request, and who approved it. Null when
   * it never needed one. Optional: an older server does not send it.
   */
  approval?: ScheduleApproval | null;
}

export interface ScheduleApproval {
  id: string | null;
  status: string | null;
  expires_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approved_count: number | null;
}

export interface ForbiddenWindow {
  days: number[];
  start: string;
  end: string;
}

export interface ScheduleList {
  items: Schedule[];
  total: number;
  page: number;
  page_size: number;
  timezone: string;
  forbidden_windows: ForbiddenWindow[];
}

export interface SchedulePayload {
  name: string;
  command_type: string;
  package_id?: string | null;
  target: ScheduleTargetIn;
  recurrence: 'once' | 'weekly';
  run_at_local?: string | null;
  weekdays?: number[];
  time_of_day?: string | null;
  ttl_minutes?: number | null;
  wake_first?: boolean;
  shutdown_after?: boolean;
  rings?: { target: ScheduleTargetIn }[] | null;
  ring_observe_hours?: number | null;
  ring_failure_percent?: number | null;
}

export interface RunList {
  items: ScheduleRun[];
  total: number;
  page: number;
  page_size: number;
}

export async function listSchedules(
  params: { state?: string; page?: number; page_size?: number } = {},
): Promise<ScheduleList> {
  const { data } = await api.get<ScheduleList>('/schedules', { params });
  return data;
}

export async function createSchedule(payload: SchedulePayload): Promise<Schedule> {
  const { data } = await api.post<Schedule>('/schedules', payload);
  return data;
}

export async function updateSchedule(id: string, payload: SchedulePayload): Promise<Schedule> {
  const { data } = await api.put<Schedule>(`/schedules/${id}`, payload);
  return data;
}

export async function setScheduleEnabled(id: string, enabled: boolean): Promise<Schedule> {
  const { data } = await api.post<Schedule>(`/schedules/${id}/state`, { enabled });
  return data;
}

export async function deleteSchedule(id: string): Promise<void> {
  await api.delete(`/schedules/${id}`);
}

export async function listScheduleRuns(
  id: string,
  params: { page?: number; page_size?: number } = {},
): Promise<RunList> {
  const { data } = await api.get<RunList>(`/schedules/${id}/runs`, { params });
  return data;
}

/** The types a deployment in stages is for (the server's `RING_TYPES`). */
export const RING_TYPES = ['wu_install', 'wu_install_full', 'package_install'] as const;

/** The types that take a poste down: never followed by another shutdown. */
export const POWER_TYPES = ['shutdown', 'reboot'] as const;

// --- Wording -------------------------------------------------------------------

/** A list of weekdays, « lundi, mercredi » — every day as one phrase. */
export function daysText(days: number[]): string {
  return [...days]
    .sort((a, b) => a - b)
    .map(weekdayName)
    .join(', ');
}

export function windowText(w: ForbiddenWindow): string {
  return t('schedules.window', { days: daysText(w.days), start: w.start, end: w.end });
}

export function windowsText(windows: ForbiddenWindow[]): string {
  return windows.length ? windows.map(windowText).join(' ; ') : t('schedules.windowsNone');
}

/** « 2026-11-25T18:00 » as « 25/11/2026 18:00 », the zone being the console's. */
export function localText(local: string | null): string {
  if (!local) return '—';
  const [day, time] = local.split('T');
  return `${formatDate(day)} ${time ?? ''}`.trim();
}

export function whenText(
  s: Pick<Schedule, 'recurrence' | 'run_at_local' | 'weekdays' | 'time_of_day'>,
): string {
  if (s.recurrence === 'once') {
    const [day, time] = (s.run_at_local ?? '').split('T');
    return t('schedules.when.once', { date: formatDate(day), time: time ?? '' });
  }
  const time = s.time_of_day ?? '';
  return s.weekdays.length === 7
    ? t('schedules.when.everyDay', { time })
    : t('schedules.when.weekly', { days: daysText(s.weekdays), time });
}

export function targetText(target: ScheduleTarget): string {
  switch (target.kind) {
    case 'all':
      return t('schedules.target.all');
    case 'room':
    case 'building':
      return target.label
        ? t(`schedules.target.${target.kind}`, { value: target.label })
        : t('schedules.target.unknownPlace');
    case 'status':
      return t('schedules.target.status', {
        value: t(`machines.options.status.${target.value ?? 'all'}`),
      });
    case 'machines': {
      const count = target.machine_count ?? target.machine_ids.length;
      const names = target.label ?? '—';
      const shown = Math.min(count, 3);
      return t('schedules.target.machines', { names, more: count - shown }, count > 3 ? 3 : 1);
    }
    default:
      return t(`schedules.target.${target.kind}`, { value: target.value ?? '' });
  }
}

/** Who approved a schedule, when, for how many postes (C10); '' if nobody. */
export function approvedText(s: Pick<Schedule, 'approval'>): string {
  const a = s.approval;
  if (!a?.approved_by) return '';
  const count = a.approved_count ?? 0;
  return t(
    'schedules.approval.approvedBy',
    { by: a.approved_by, at: formatDateTime(a.approved_at), count },
    count,
  );
}

export function stateLabel(state: string): string {
  const key = `schedules.state.${state}`;
  const text = t(key);
  return text === key ? state : text;
}

export function suspendedText(code: string | null, params: Record<string, unknown> = {}): string {
  if (!code) return '';
  const key = `schedules.suspended.${code}`;
  const text = t(key, params);
  return text === key ? code : text;
}

export function runStatusLabel(status: string): string {
  const key = `schedules.runs.status.${status}`;
  const text = t(key);
  return text === key ? status : text;
}

/** Why a run stopped or was skipped, in the reader's language. */
export function runCauseText(
  run: Pick<ScheduleRun, 'result_code' | 'result_params'> & Pick<Partial<ScheduleRun>, 'due_local'>,
): string {
  const code = run.result_code;
  if (!code) return '';
  const params = { ...(run.result_params ?? {}) };
  if (code === 'missed' && typeof params.due === 'string') {
    // In the console's zone, as the schedule was planned; the browser's only
    // for a server that does not send it.
    params.due = run.due_local ? localText(run.due_local) : new Date(params.due).toLocaleString();
  }
  if (code === 'forbidden_window') return t('schedules.runs.cause.forbidden_window');
  // C10: stopped at its start beyond what was approved ({count},
  // {threshold}), or before a next stage ({stage}).
  if (code === 'approval_required' && params.stage !== undefined) {
    return t('schedules.runs.cause.approval_required_stage', params);
  }
  for (const prefix of ['schedules.runs.cause', 'schedules.suspended']) {
    const key = `${prefix}.${code}`;
    const text = t(key, params);
    if (text !== key) return text;
  }
  // A refusal of the API (a package retired, deleted…): its own wording.
  const known = errorCodeMessage(code);
  if (known) return known;
  return code;
}

/** What a run did, in one line. */
export function runSummary(run: ScheduleRun): string {
  const parts = [t('schedules.runs.counts', { created: run.created, skipped: run.skipped })];
  if (run.woken) parts.push(t('schedules.runs.woken', { count: run.woken }));
  if (run.shut_down) parts.push(t('schedules.runs.shutDown', { count: run.shut_down }));
  if (run.kept_on) parts.push(t('schedules.runs.keptOn', { count: run.kept_on }));
  if (run.left_out) parts.push(t('schedules.runs.leftOut', { count: run.left_out }));
  return parts.join(' · ');
}
