import { api } from 'boot/axios';

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
  const created = `${res.created} vérification(s) demandée(s)`;
  if (!res.skipped) return { type: 'positive', message: created };
  return {
    type: res.created ? 'warning' : 'warning',
    message: `${created} — ${res.skipped} poste(s) en avaient déjà une ouverte`,
  };
}
