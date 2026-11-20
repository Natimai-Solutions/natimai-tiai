import { api } from 'boot/axios';
import { t } from 'src/i18n';
import { formatDate } from 'src/utils/format';

/**
 * Alerts: a closed catalogue of rules the server evaluates every five
 * minutes over what the postes report, opening and resolving the alerts
 * itself. The console only reads them; the rules are set in Paramètres.
 */

export const ALERT_RULES = [
  'disk_low',
  'disk_unhealthy',
  'volume_unencrypted',
  'reboot_pending',
  'os_unsupported',
  'forbidden_software',
  'inactive',
  'warranty_ending',
] as const;

export type AlertRule = (typeof ALERT_RULES)[number];

export interface AlertMachineRef {
  id: string;
  hostname: string | null;
  room_name: string | null;
  building_name: string | null;
}

export interface Alert {
  id: string;
  machine_id: string;
  rule: string;
  opened_at: string;
  /** null = still holds. */
  resolved_at: string | null;
  /** The values worded by `alertDetailText`. */
  detail: Record<string, unknown> | null;
  check_id: string | null;
  machine: AlertMachineRef | null;
}

export interface AlertList {
  items: Alert[];
  total: number;
  page: number;
  page_size: number;
  /** Open alerts per rule over the reader's scope. */
  open_by_rule: Record<string, number>;
}

export interface ListAlertsParams {
  rule?: AlertRule;
  state?: 'open' | 'resolved' | 'all';
  machine_id?: string;
  page?: number;
  page_size?: number;
}

export async function listAlerts(params: ListAlertsParams = {}): Promise<AlertList> {
  const { data } = await api.get<AlertList>('/alerts', { params });
  return data;
}

export function isAlertRule(value: string): value is AlertRule {
  return (ALERT_RULES as readonly string[]).includes(value);
}

/** A rule's name in the reader's language; an unknown one as it is. */
export function alertRuleLabel(rule: string): string {
  return isAlertRule(rule) ? t(`alerts.rules.${rule}`) : rule;
}

function str(value: unknown): string {
  if (typeof value === 'string') return value || '?';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '?';
}

function day(value: unknown): string {
  return typeof value === 'string' ? formatDate(value) : '?';
}

function names(value: unknown, key: string): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) =>
      item && typeof item === 'object' ? (item as Record<string, unknown>)[key] : null,
    )
    .filter((name): name is string => typeof name === 'string' && name !== '');
}

/** What made an alert hold, in one line in the reader's language. */
export function alertDetailText(rule: string, detail: Record<string, unknown> | null): string {
  const d = detail ?? {};
  switch (rule) {
    case 'disk_low':
      return t('alerts.detail.disk_low', {
        percent: str(d.free_percent),
        threshold: str(d.threshold_percent),
      });
    case 'disk_unhealthy': {
      const disks = Array.isArray(d.disks) ? d.disks : [];
      const text = disks
        .map((disk) => {
          const row = (disk ?? {}) as Record<string, unknown>;
          return `${str(row.model)} (${str(row.health)})`;
        })
        .join(', ');
      return t('alerts.detail.disk_unhealthy', { disks: text || '?' });
    }
    case 'volume_unencrypted':
      return t('alerts.detail.volume_unencrypted', {
        letter: str(d.letter),
        status: str(d.status),
      });
    case 'reboot_pending':
      return t('alerts.detail.reboot_pending', { date: day(d.since) });
    case 'os_unsupported':
      return d.end_of_support
        ? t('alerts.detail.os_unsupported', { os: str(d.os_version), date: day(d.end_of_support) })
        : t('alerts.detail.os_unsupportedNoDate', { os: str(d.os_version) });
    case 'forbidden_software': {
      const programs = names(d.programs, 'name');
      const count = typeof d.count === 'number' ? d.count : programs.length;
      const more = count - programs.length;
      return more > 0
        ? t('alerts.detail.forbidden_softwareMore', { programs: programs.join(', '), count: more })
        : t('alerts.detail.forbidden_software', { programs: programs.join(', ') || '?' });
    }
    case 'inactive':
      return t('alerts.detail.inactive', { date: day(d.last_seen) });
    case 'warranty_ending':
      return t('alerts.detail.warranty_ending', { date: day(d.warranty_end) });
  }
  return '';
}

/**
 * A verification's instructions: worded in the reader's language when the
 * server opened it for an alert (`instructions_code` « alert.<rule> »), as
 * typed — or as an older server wrote them — otherwise.
 */
export function checkInstructionsText(check: {
  instructions: string | null;
  instructions_code?: string | null;
  instructions_params?: Record<string, unknown> | null;
}): string | null {
  const code = check.instructions_code;
  if (code && code.startsWith('alert.')) {
    const rule = code.slice('alert.'.length);
    if (isAlertRule(rule)) {
      return t('alerts.instructions', {
        rule: alertRuleLabel(rule),
        detail: alertDetailText(rule, check.instructions_params ?? null),
      });
    }
  }
  return check.instructions;
}
