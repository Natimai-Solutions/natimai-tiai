import { api } from 'boot/axios';
import { t } from 'src/i18n';

/**
 * Verification requests: "go and look at this poste", assigned or not, closed
 * with a note that stays. Distinct from `Machine.needs_verification`, the
 * server's own doubt about a poste's identity.
 */

export interface UserRef {
  id: string;
  name: string;
  /** false for an assignee deactivated since (absent: active). */
  active?: boolean;
  /**
   * false, on an open check, when the assignee no longer reaches the poste
   * (rights withdrawn, poste moved, account deactivated): the check is
   * « à prendre » again, the name kept to say who had it.
   */
  reachable?: boolean;
}

/** The assignee a check really has: none when the one named no longer reaches it. */
export function effectiveAssignee(a: UserRef | null | undefined): UserRef | null {
  return a && a.reachable !== false ? a : null;
}

/** Why a check named after someone is « à prendre »; empty when it is not. */
export function formerAssigneeNote(a: UserRef | null | undefined): string {
  if (!a || a.reachable !== false) return '';
  return a.active === false
    ? t('checks.former.deactivated', { name: a.name })
    : t('checks.former.unreachable', { name: a.name });
}

export interface CheckMachineRef {
  id: string;
  hostname: string | null;
  location: string | null;
  room_name: string | null;
  building_name: string | null;
}

export interface Check {
  id: string;
  machine_id: string;
  requested_by: string;
  assigned_to: UserRef | null;
  instructions: string | null;
  created_at: string;
  updated_at: string;
  /** null = still open. */
  closed_at: string | null;
  closed_by: string | null;
  closing_note: string | null;
  /**
   * Set when the server wrote the closing note itself (a merge): the console
   * words it, `closing_note` keeping the server's French. Absent from an
   * older server, null on a note typed by someone.
   */
  closing_note_code?: string | null;
  /** Set when the server opened the request for an alert (« alert.<rule> »):
   * the console words the instructions (`checkInstructionsText`). */
  instructions_code?: string | null;
  instructions_params?: Record<string, unknown> | null;
  /** Filled on the task lists, where no fiche is open. */
  machine: CheckMachineRef | null;
}

export interface CheckList {
  items: Check[];
  total: number;
  page: number;
  page_size: number;
}

export interface CheckPayload {
  assigned_to_id?: string | null;
  instructions?: string | null;
}

export interface ListChecksParams {
  open?: boolean;
  /** An account id, 'me', or 'none' for the unassigned. */
  assigned_to?: string;
  page?: number;
  page_size?: number;
}

export async function listChecks(params: ListChecksParams = {}): Promise<CheckList> {
  const { data } = await api.get<CheckList>('/checks', { params });
  return data;
}

/** The server serves this many checks a page at most. */
const CHECK_PAGE_MAX = 200;

/**
 * Every check matching `params`, page after page: a list cut at the server's
 * 200 said « 310 » on the badge and showed 200 (the room page's rule, audit
 * U24). Bounded, so a server that keeps answering cannot loop it forever.
 */
export async function listAllChecks(
  params: Omit<ListChecksParams, 'page' | 'page_size'> = {},
): Promise<CheckList> {
  const items: Check[] = [];
  let total = 0;
  for (let page = 1; page <= 100; page++) {
    const res = await listChecks({ ...params, page, page_size: CHECK_PAGE_MAX });
    items.push(...res.items);
    total = res.total;
    if (items.length >= total || res.items.length === 0) break;
  }
  return { items, total, page: 1, page_size: items.length };
}

export async function listMachineChecks(
  machineId: string,
  params: { page?: number; page_size?: number } = {},
): Promise<CheckList> {
  const { data } = await api.get<CheckList>(`/machines/${machineId}/checks`, { params });
  return data;
}

export async function createCheck(machineId: string, payload: CheckPayload): Promise<Check> {
  const { data } = await api.post<Check>(`/machines/${machineId}/check`, payload);
  return data;
}

/** One request per poste of a selection; those already asked are skipped. */
export async function createChecksBulk(
  machineIds: string[],
  payload: CheckPayload,
): Promise<{ created: number; skipped: number }> {
  const { data } = await api.post<{ created: number; skipped: number }>('/checks/bulk', {
    machine_ids: machineIds,
    ...payload,
  });
  return data;
}

export async function updateCheck(id: string, payload: CheckPayload): Promise<Check> {
  const { data } = await api.patch<Check>(`/checks/${id}`, payload);
  return data;
}

export async function closeCheck(
  id: string,
  payload: { note?: string | null; closed_at?: string | null },
): Promise<Check> {
  const { data } = await api.post<Check>(`/checks/${id}/close`, payload);
  return data;
}

/** Active accounts, id and name only: who a task can be given to. */
/** Who a task can be given to; for one poste, only who can see it. */
export async function listAssignableUsers(machineId?: string): Promise<UserRef[]> {
  const { data } = await api.get<UserRef[]>(
    '/checks/assignable-users',
    machineId ? { params: { machine_id: machineId } } : undefined,
  );
  return data;
}

/** The notification a bulk request earns. */
export function bulkCheckNotification(res: { created: number; skipped: number }): {
  type: 'positive' | 'warning';
  message: string;
} {
  const created = t('checks.bulk.created', { count: res.created }, res.created);
  if (!res.skipped) return { type: 'positive', message: created };
  return {
    type: res.created ? 'warning' : 'warning',
    message: t('checks.bulk.skipped', { created, count: res.skipped }, res.skipped),
  };
}

/** The codes of the closing notes the server writes itself, and their text. */
const CLOSING_NOTES: Record<string, string> = {
  'check.closed.merged': 'checks.closingNotes.merged',
};

/**
 * A check's closing note in the reader's language when the server wrote it
 * (`closing_note_code`); what was typed — or written by an older server, or
 * under a code this console does not know — as it is.
 */
export function closingNoteText(
  check: Pick<Check, 'closing_note' | 'closing_note_code'>,
): string | null {
  const key = check.closing_note_code ? CLOSING_NOTES[check.closing_note_code] : undefined;
  return key ? t(key) : check.closing_note;
}
