import { api } from 'boot/axios';

/**
 * The audit log: every administrative action, who did it and to what. Read
 * only — the console never writes it, the backend records each action in the
 * same transaction as the action itself.
 */

/** One administrative action. */
export interface AuditEntry {
  id: string;
  /** When it happened, ISO 8601 in UTC — displayed in the reader's time zone. */
  at: string;
  /** The e-mail of the account that acted. */
  actor: string;
  /** Stable slug (« machine.revoke_token »…) — the console labels it. */
  action: string;
  /** What kind of thing was acted on (« machine », « user »…). */
  resource_type: string;
  /** Its id, as text; empty for actions on the parc as a whole (settings). */
  resource_id: string;
  /** Free-form context recorded with the action (names, changed fields…). */
  details: Record<string, unknown>;
}

export interface AuditList {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListAuditParams {
  /** Exact action slug. */
  action?: string;
  /** Part of the actor's e-mail, case-insensitive. */
  actor?: string;
  /** Exact resource type. */
  resource_type?: string;
  /** Exact resource id. */
  resource_id?: string;
  /** Inclusive lower bound, ISO 8601 with its offset. */
  since?: string;
  /** Exclusive upper bound, ISO 8601 with its offset. */
  until?: string;
  page?: number;
  page_size?: number;
}

/** Whether a value is a plain JSON object (not null, not an array). */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The filters that are text, blank meaning "any". */
const TEXT_FILTERS = ['action', 'actor', 'resource_type', 'resource_id', 'since', 'until'] as const;

/**
 * The params as the API should see them: blank filters left out rather than
 * sent empty — `?action=` would ask for the actions whose slug is "", which is
 * none, where the reader meant "any".
 */
export function auditQueryParams(params: ListAuditParams): ListAuditParams {
  const out: ListAuditParams = {};
  for (const key of TEXT_FILTERS) {
    const value = params[key]?.trim();
    if (value) out[key] = value;
  }
  if (params.page !== undefined) out.page = params.page;
  if (params.page_size !== undefined) out.page_size = params.page_size;
  return out;
}

/** An entry as the page can rely on it: `details` always an object. */
function normalizeEntry(entry: AuditEntry): AuditEntry {
  return { ...entry, details: isRecord(entry.details) ? entry.details : {} };
}

export async function listAudit(params: ListAuditParams = {}): Promise<AuditList> {
  const { data } = await api.get<AuditList>('/audit', { params: auditQueryParams(params) });
  return { ...data, items: data.items.map(normalizeEntry) };
}

/** The action slugs present in the log, sorted — what the action filter offers. */
export async function listAuditActions(): Promise<string[]> {
  const { data } = await api.get<unknown>('/audit/actions');
  return Array.isArray(data) ? data.filter((a): a is string => typeof a === 'string' && !!a) : [];
}
