import { api } from 'boot/axios';
import { currentLocale } from 'src/i18n';

/**
 * Trends, indicators and recurring failures (C9, `dev/plan-tendances-indicateurs.md`).
 *
 * The trends are the dashboard's counters photographed once a day, summed
 * over the reader's scope by the server; the indicators and the failures are
 * computed when read from the history already in the database.
 */

/** The counters a photo carries, in the dashboard's order (`counters.BASE_KEYS`). */
export const TREND_BASE_KEYS = [
  'total', // i18n-ignore — an API key, not a text
  'up_to_date',
  'outdated',
  'needs_verification',
  'inactive',
  'with_active_threats',
  'machines_wu_pending',
  'machines_reboot_required',
  'machines_low_disk',
  'machines_unencrypted',
  'machines_aging',
  'machines_agent_outdated',
  'open_checks',
  'machines_maintenance_overdue',
  'machines_maintenance_due_soon',
  'machines_usage_low',
  'machines_usage_high',
  'machines_reenroll_pending',
  'machines_token_revoked',
  'machines_with_alerts',
  'machines_win11_blocked',
  'machines_compliant',
  'machines_noncompliant',
  'machines_retired',
] as const;

/** The alert rules and compliance checks broken down by the photo (`alerts.<rule>`, `compliance.<check>`). */
export const TREND_ALERT_RULES = [
  'disk_low',
  'disk_unhealthy',
  'volume_unencrypted',
  'reboot_pending',
  'os_unsupported',
  'forbidden_software',
  'inactive',
  'warranty_ending',
] as const;

export const TREND_COMPLIANCE_CHECKS = [
  'encryption',
  'secure_boot',
  'tpm',
  'antivirus',
  'patches',
  'reboot',
  'os_supported',
  'agent_current',
  'firewall',
  'local_admins',
] as const;

/** Every key `GET /stats/trends?keys=` takes. */
export const TREND_KEYS: readonly string[] = [
  ...TREND_BASE_KEYS,
  ...TREND_ALERT_RULES.map((r) => `alerts.${r}`),
  ...TREND_COMPLIANCE_CHECKS.map((c) => `compliance.${c}`),
];

/** The series drawn when the reader picked none (`trend.crud.DEFAULT_KEYS`). */
export const DEFAULT_TREND_KEYS: readonly string[] = [
  'total', // i18n-ignore — an API key, not a text
  'up_to_date',
  'with_active_threats',
  'machines_with_alerts',
  'machines_noncompliant',
  'machines_maintenance_overdue',
  'open_checks',
];

/** The periods offered, in months. */
export const TREND_PERIODS = [3, 12, 24] as const;
export type TrendPeriod = (typeof TREND_PERIODS)[number];

export type TrendStep = 'day' | 'week';

export interface PolicyChange {
  /** `AAAA-MM-JJ`: the first day photographed with the new value. */
  day: string;
  /** The setting's key, e.g. `fleet.low_disk_free_percent`. */
  key: string;
  before: unknown;
  after: unknown;
}

export interface Trends {
  /** `AAAA-MM-JJ`, one per point. */
  days: string[];
  /** One value per day: the sum over the scope, or null for a day never photographed. */
  series: Record<string, (number | null)[]>;
  step: TrendStep;
  /** Today, when on the axis: its point is redrawn every hour. */
  provisional_day: string | null;
  /** The first day ever photographed; null before the first photo. */
  since: string | null;
  policy_changes: PolicyChange[];
}

/** One line of the chart: a series with its colour slot and its values. */
export interface TrendChartSeries {
  key: string;
  label: string;
  /** 1 to 8: the colour slot the series keeps while others come and go. */
  slot: number;
  values: (number | null)[];
}

export async function getTrends(params: {
  months: number;
  keys?: readonly string[];
  step?: TrendStep;
}): Promise<Trends> {
  const query: Record<string, unknown> = { months: params.months };
  if (params.keys?.length) query.keys = params.keys.join(',');
  if (params.step) query.step = params.step;
  const { data } = await api.get<Trends>('/stats/trends', { params: query });
  return data;
}

export interface CheckMonth {
  /** `AAAA-MM`. */
  month: string;
  closed: number;
  median_hours: number | null;
  p90_hours: number | null;
  with_due: number;
  on_time_due: number;
}

export interface MaintenanceMonth {
  month: string;
  done: number;
  on_time: number;
}

export interface CommandMonth {
  month: string;
  succeeded: number;
  failed: number;
  /** Never delivered: outside the success rate. */
  expired: number;
  /** Delivered, never answered (`command.unanswered`): outside the rate. */
  unanswered: number;
}

export interface Deployments {
  direct: CommandMonth[];
  scheduled: CommandMonth[];
  /** Ring runs halted, by month; null for a confined account or one without `schedule:read`. */
  halted_runs: number[] | null;
}

export interface Indicators {
  /** `AAAA-MM`, oldest first; the last one is the month in progress. */
  months: string[];
  /** Each section is null when the reader may not read its source. */
  checks: CheckMonth[] | null;
  maintenance: MaintenanceMonth[] | null;
  commands: CommandMonth[] | null;
  deployments: Deployments | null;
  retention: {
    /** Null when nothing is purged (`COMMAND_RETENTION_DAYS = 0`). */
    commands_days: number | null;
    schedule_runs_days: number;
  };
}

export async function getIndicators(months: number): Promise<Indicators> {
  const { data } = await api.get<Indicators>('/stats/indicators', { params: { months } });
  return data;
}

export type FailureGrouping = 'hw_model' | 'room';

export interface FailureRow {
  /** By model: the model, null for an unknown one. */
  hw_model?: string | null;
  /** By room: null for « no room », or for the anonymous row when `out_of_scope`. */
  room_id?: string | null;
  room_name?: string | null;
  building_name?: string | null;
  out_of_scope?: boolean;
  incidents: number;
  machines: number;
  parc: number;
  /** Incidents per 100 postes of the parc; null when the parc is empty. */
  per_100: number | null;
  retired_incidents: number;
  retired_machines: number;
  last_at: string | null;
}

export async function getRecurringFailures(params: {
  months: number;
  by: FailureGrouping;
  min_incidents?: number;
  limit?: number;
}): Promise<FailureRow[]> {
  const { data } = await api.get<FailureRow[]>('/stats/recurring-failures', { params });
  return data;
}

/**
 * The page as a workbook, in the language shown (`lang`, sent only when it
 * is not French, the server's default). Fetched as a blob: the API needs the
 * Authorization header, which a plain link would not carry.
 */
export async function downloadReport(months: number): Promise<Blob> {
  const lang = currentLocale();
  const { data } = await api.get<Blob>('/stats/report.xlsx', {
    params: lang === 'fr' ? { months } : { months, lang },
    responseType: 'blob',
  });
  return data;
}
