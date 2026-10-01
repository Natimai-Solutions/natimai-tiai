import type { LocationQuery } from 'vue-router';

import type { ListAuditParams } from 'src/services/audit';
import { queryInt, queryValue } from 'src/utils/machineQuery';

/**
 * The audit page's state as it travels in the URL — filters and page — so a
 * search (« tout ce qu'a fait marie@ en septembre ») can be pasted to a
 * colleague, and the back button returns to it from a fiche.
 */

export const AUDIT_DEFAULT_PAGE_SIZE = 50;

/** Rows-per-page choices offered by the table, and the only ones a URL may ask for. */
export const AUDIT_PAGE_SIZE_OPTIONS: readonly number[] = [25, 50, 100];

export interface AuditFilters {
  action: string | null;
  actor: string;
  resourceType: string | null;
  resourceId: string | null;
  /** First day of the period, `YYYY-MM-DD` in the reader's calendar. */
  from: string | null;
  /** Last day of the period, `YYYY-MM-DD` in the reader's calendar, included. */
  to: string | null;
}

export interface AuditPageState {
  filters: AuditFilters;
  page: number;
  pageSize: number;
}

export function emptyAuditFilters(): AuditFilters {
  return { action: null, actor: '', resourceType: null, resourceId: null, from: null, to: null };
}

/** Whether any filter is set — the empty state then says "nothing matches". */
export function hasAuditFilters(f: AuditFilters): boolean {
  return !!(f.action || f.actor.trim() || f.resourceType || f.resourceId || f.from || f.to);
}

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A calendar day `YYYY-MM-DD` as numbers, or null when not a real date. */
function parseDay(value: string | null | undefined): [number, number, number] | null {
  const m = value ? DATE_RE.exec(value) : null;
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const check = new Date(Date.UTC(y, mo - 1, d));
  // Rejects 2026-02-30 and friends, which Date.UTC would quietly roll over.
  if (check.getUTCFullYear() !== y || check.getUTCMonth() !== mo - 1 || check.getUTCDate() !== d) {
    return null;
  }
  return [y, mo, d];
}

/** A `YYYY-MM-DD` day from a URL value, or null. */
function queryDay(v: unknown): string | null {
  const raw = queryValue(v);
  return raw && parseDay(raw) ? raw : null;
}

/** The page state carried by a URL. Unknown or malformed values fall back to "none". */
export function auditStateFromQuery(q: LocationQuery): AuditPageState {
  const pageSize = queryInt(q.page_size);
  return {
    filters: {
      action: queryValue(q.action),
      actor: queryValue(q.actor) ?? '',
      resourceType: queryValue(q.resource_type),
      resourceId: queryValue(q.resource_id),
      from: queryDay(q.from),
      to: queryDay(q.to),
    },
    page: queryInt(q.page) ?? 1,
    pageSize:
      pageSize !== null && AUDIT_PAGE_SIZE_OPTIONS.includes(pageSize)
        ? pageSize
        : AUDIT_DEFAULT_PAGE_SIZE,
  };
}

/** The page state as URL query params, defaults omitted so the common URL stays short. */
export function auditQueryFromState(state: AuditPageState): Record<string, string> {
  const { filters: f } = state;
  const query: Record<string, string> = {};
  if (f.action) query.action = f.action;
  if (f.actor.trim()) query.actor = f.actor.trim();
  if (f.resourceType) query.resource_type = f.resourceType;
  if (f.resourceId) query.resource_id = f.resourceId;
  if (f.from) query.from = f.from;
  if (f.to) query.to = f.to;
  if (state.page > 1) query.page = String(state.page);
  if (state.pageSize !== AUDIT_DEFAULT_PAGE_SIZE) query.page_size = String(state.pageSize);
  return query;
}

/** The reader's IANA time zone, as the browser knows it. */
export function readerTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** How far `timeZone`'s wall clock runs ahead of UTC at instant `ms`, in ms. */
function zoneOffset(ms: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(ms));
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const wall = Date.UTC(
    get('year'),
    get('month') - 1,
    get('day'),
    get('hour'),
    get('minute'),
    get('second'),
  );
  return wall - Math.floor(ms / 1000) * 1000;
}

/** The instant a wall-clock midnight of `y-m-d` happens in `timeZone`. */
function midnightIn(y: number, m: number, d: number, timeZone: string): Date {
  const guess = Date.UTC(y, m - 1, d);
  let at = guess - zoneOffset(guess, timeZone);
  // A second pass settles the days where the offset differs between the guess
  // and the answer (a DST switch within the first hours of the day).
  const settled = guess - zoneOffset(at, timeZone);
  if (settled !== at) at = settled;
  return new Date(at);
}

/**
 * The instant a calendar day starts in a time zone, as ISO 8601 UTC — or null
 * for something that is not a `YYYY-MM-DD` day. Explicit zone, so the result
 * does not depend on the machine running the code (the tests pin it).
 */
export function localDayStart(day: string, timeZone: string): string | null {
  const parsed = parseDay(day);
  return parsed ? midnightIn(...parsed, timeZone).toISOString() : null;
}

/** The instant the day *after* `day` starts in a time zone — an exclusive end bound. */
export function localDayEnd(day: string, timeZone: string): string | null {
  const parsed = parseDay(day);
  if (!parsed) return null;
  const next = new Date(Date.UTC(parsed[0], parsed[1] - 1, parsed[2] + 1));
  return midnightIn(
    next.getUTCFullYear(),
    next.getUTCMonth() + 1,
    next.getUTCDate(),
    timeZone,
  ).toISOString();
}

/**
 * A period picked as two calendar days, as the API's bounds: `since` the start
 * of the first day (included), `until` the start of the day after the last
 * (excluded) — so « jusqu'au 30 » includes all of the 30th.
 */
export function auditPeriodParams(
  from: string | null,
  to: string | null,
  timeZone: string,
): Pick<ListAuditParams, 'since' | 'until'> {
  const out: Pick<ListAuditParams, 'since' | 'until'> = {};
  const since = from ? localDayStart(from, timeZone) : null;
  const until = to ? localDayEnd(to, timeZone) : null;
  if (since) out.since = since;
  if (until) out.until = until;
  return out;
}

/** Whether a period ends before it starts — said on the field rather than sent. */
export function isAuditPeriodInverted(from: string | null, to: string | null): boolean {
  return !!(from && to && parseDay(from) && parseDay(to) && to < from);
}

/** The page state as API params, the period read in `timeZone`. */
export function auditListParams(state: AuditPageState, timeZone: string): ListAuditParams {
  const { filters: f } = state;
  const params: ListAuditParams = { page: state.page, page_size: state.pageSize };
  if (f.action) params.action = f.action;
  if (f.actor.trim()) params.actor = f.actor.trim();
  if (f.resourceType) params.resource_type = f.resourceType;
  if (f.resourceId) params.resource_id = f.resourceId;
  return { ...params, ...auditPeriodParams(f.from, f.to, timeZone) };
}
