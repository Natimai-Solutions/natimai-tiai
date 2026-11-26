import { api } from 'boot/axios';
import { errorCodeMessage, t } from 'src/i18n';
import { commandRowLabel } from 'src/services/commands';

/**
 * Two-person approval of mass actions (C10, `dev/plan-approbation-masse.md`).
 * Beyond a threshold of postes, a command at risk sent by hand — or a
 * schedule at risk — is not queued: it becomes a request that another
 * account, holding the same rights and seeing every poste of it, approves or
 * rejects. Every route asks for `risky_command:execute`.
 */

export type ApprovalStatus =
  'pending' | 'approved' | 'rejected' | 'cancelled' | 'expired' | 'failed';

export interface ApprovalTarget {
  kind: string;
  value?: string | null;
}

export interface Approval {
  id: string;
  kind: 'command' | 'schedule';
  status: ApprovalStatus;
  command_type: string;
  package_id: string | null;
  package_name: string | null;
  /** The target as asked (a list is reduced to `{kind: 'machines'}`). */
  target: ApprovalTarget;
  machine_count: number;
  threshold: number;
  ttl_minutes: number | null;
  schedule_id: string | null;
  schedule_name: string | null;
  requested_by: string;
  requested_at: string;
  expires_at: string;
  decided_by: string | null;
  decided_at: string | null;
  note: string | null;
  result_code: string | null;
  result_params: Record<string, unknown> | null;
  created: number | null;
  skipped: number | null;
  left_out: number | null;
}

export interface ApprovalMachine {
  id: string;
  hostname: string | null;
  room: string | null;
}

export interface ApprovalSchedule {
  id: string;
  name: string;
  state: string;
  recurrence: string;
  run_at: string | null;
  weekdays: number[];
  time_of_day: string | null;
  stages: number;
}

export interface ApprovalDetail extends Approval {
  /** The postes of the list within the reader's scope as it is now. */
  machines: ApprovalMachine[];
  /** How many others: out of the reader's scope, their names not given. */
  hidden: number;
  schedule: ApprovalSchedule | null;
}

export interface ApprovalList {
  items: Approval[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApprovalSummary {
  enabled: boolean;
  to_decide: number;
  mine_pending: number;
}

export type ApprovalView = 'to_decide' | 'mine';

export async function listApprovals(
  params: { view?: ApprovalView; status?: ApprovalStatus; page?: number; page_size?: number } = {},
): Promise<ApprovalList> {
  const { data } = await api.get<ApprovalList>('/approvals', { params });
  return data;
}

export async function getApprovalSummary(): Promise<ApprovalSummary> {
  const { data } = await api.get<ApprovalSummary>('/approvals/summary');
  return data;
}

export async function getApproval(id: string): Promise<ApprovalDetail> {
  const { data } = await api.get<ApprovalDetail>(`/approvals/${id}`);
  return data;
}

export async function approveApproval(
  id: string,
  confirmForbiddenWindow = false,
): Promise<Approval> {
  const { data } = await api.post<Approval>(`/approvals/${id}/approve`, {
    confirm_forbidden_window: confirmForbiddenWindow,
  });
  return data;
}

export async function rejectApproval(id: string, note: string | null): Promise<Approval> {
  const { data } = await api.post<Approval>(`/approvals/${id}/reject`, { note: note || null });
  return data;
}

export async function cancelApproval(id: string): Promise<Approval> {
  const { data } = await api.post<Approval>(`/approvals/${id}/cancel`);
  return data;
}

/**
 * The codes after which the request is closed (or was already): the page
 * reads its list and the badge again rather than offering a decision on it.
 */
export const CLOSING_CODES = [
  'approval.not_pending',
  'approval.not_found',
  'approval.author_not_allowed',
  'approval.package_gone',
  'approval.package_changed',
  'approval.nothing_left',
  'approval.target_grew',
  'schedule.in_past',
  'schedule.forbidden_window',
  // A deployment whose package was retired, set not ready or deleted since the
  // request: the approval fails the request (execute.failed) with that code.
  'package.retired',
  'package.not_ready',
  'package.not_found',
  'package.required',
] as const;

// --- Wording -------------------------------------------------------------------

/** The action asked: the catalogue's label, with the package of a deployment. */
export function approvalAction(a: Pick<Approval, 'command_type' | 'package_name'>): string {
  return commandRowLabel({ type: a.command_type, package_name: a.package_name });
}

/** The target as asked, in a few words (a room or building is not named). */
export function approvalTarget(a: Pick<Approval, 'kind' | 'target' | 'schedule_name'>): string {
  if (a.kind === 'schedule') {
    return t('approvals.target.schedule', { name: a.schedule_name ?? '—' });
  }
  const kind = a.target?.kind ?? 'machines';
  switch (kind) {
    case 'all':
    case 'machines':
    case 'room':
    case 'building':
      return t(`approvals.target.${kind}`);
    case 'status':
      return t('approvals.target.status', {
        value: t(`machines.options.status.${a.target.value ?? 'all'}`),
      });
    case 'domain':
    case 'location':
      return t(`approvals.target.${kind}`, { value: a.target.value ?? '' });
    default:
      return kind;
  }
}

export function approvalStatusLabel(status: string): string {
  const key = `approvals.status.${status}`;
  const text = t(key);
  return text === key ? status : text;
}

export function approvalStatusColor(status: string): string {
  switch (status) {
    case 'pending':
      return 'orange-8';
    case 'approved':
      return 'positive';
    case 'rejected':
    case 'failed':
      return 'negative';
    default:
      return 'grey-7';
  }
}

/** Why a request closed the way it did, in the reader's language. */
export function approvalCauseText(a: Pick<Approval, 'result_code' | 'result_params'>): string {
  const code = a.result_code;
  if (!code) return '';
  const key = `approvals.cause.${code}`;
  const text = t(key, { ...(a.result_params ?? {}) });
  if (text !== key) return text;
  // A refusal of the package (retired, not ready…): the API's own wording.
  return errorCodeMessage(code) ?? code;
}

/** The outcome of a request, one line: who decided, and what came of it. */
export function approvalOutcome(a: Approval): string {
  switch (a.status) {
    case 'approved':
      return a.kind === 'command' && a.created !== null
        ? t('approvals.outcome.approvedCommand', {
            by: a.decided_by ?? '—',
            created: a.created ?? 0,
            skipped: a.skipped ?? 0,
            left: a.left_out ?? 0,
          })
        : t('approvals.outcome.approved', { by: a.decided_by ?? '—' });
    case 'rejected':
      return a.note
        ? t('approvals.outcome.rejectedNote', { by: a.decided_by ?? '—', note: a.note })
        : t('approvals.outcome.rejected', { by: a.decided_by ?? '—' });
    case 'failed':
    case 'cancelled': {
      const cause = approvalCauseText(a);
      return cause ? t('approvals.outcome.withCause', { cause }) : '';
    }
    default:
      return '';
  }
}

/** What an approval did, for the notification after it. */
export function approvedNotification(a: Approval): string {
  if (a.kind === 'schedule') return t('approvals.decision.approvedSchedule');
  const created = a.created ?? 0;
  const parts = [t('approvals.decision.sent', { count: created }, created)];
  if (a.skipped) parts.push(t('approvals.decision.skipped', { count: a.skipped }, a.skipped));
  if (a.left_out) parts.push(t('approvals.decision.leftOut', { count: a.left_out }, a.left_out));
  return parts.join(t('approvals.decision.separator'));
}
