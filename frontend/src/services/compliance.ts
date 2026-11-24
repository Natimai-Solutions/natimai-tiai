import { api } from 'boot/axios';
import { t } from 'src/i18n';

/** The checks of the server's closed list (`features/compliance/checks.py`), in its order. */
export const COMPLIANCE_CHECKS = [
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
export type ComplianceCheck = (typeof COMPLIANCE_CHECKS)[number];

export const COMPLIANCE_STATES = ['failing', 'passing', 'unknown'] as const;

export function isComplianceCheck(value: string): value is ComplianceCheck {
  return (COMPLIANCE_CHECKS as readonly string[]).includes(value);
}

/** A check's name; an unknown code (a newer server) as itself. */
export function complianceCheckLabel(check: string): string {
  return isComplianceCheck(check) ? t(`compliance.checks.${check}`) : check;
}

export interface WingetUpdate {
  winget_id: string;
  name: string | null;
  installed: number;
  outdated: number;
  available: string | null;
  up_to_date_percent: number;
}

export interface WingetUpdateList {
  items: WingetUpdate[];
  reporting: number;
}

export async function listWingetUpdates(params: {
  search?: string;
  outdated_only?: boolean;
}): Promise<WingetUpdateList> {
  const { data } = await api.get<WingetUpdateList>('/software/updates', { params });
  return data;
}
