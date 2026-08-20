import type { LocationQuery } from 'vue-router';
import type {
  ListMachinesParams,
  MachineSortField,
  MachineStatus,
  WindowsUpdateFilter,
} from 'src/services/machines';

/**
 * The machine-list query as it travels in URLs.
 *
 * The list page writes it (filters, sort, page) and two readers parse it back:
 * the list page itself, and the fiche d'un poste — which receives the whole
 * query on navigation so its back arrow can return to the exact search, and so
 * it can walk to the previous/next result of that search.
 */

/**
 * Rows per page the list uses unless the URL says otherwise — and therefore the
 * divisor that turns a result's absolute rank back into a page number. Shared,
 * because the two readings must agree: a fiche computing its return page with a
 * different default would send the reader to the wrong page of their own search.
 */
export const DEFAULT_PAGE_SIZE = 50;

/** Rows-per-page choices offered by the list, and the only ones a URL may ask for. */
export const PAGE_SIZE_OPTIONS: readonly number[] = [25, 50, 100];

export const MACHINE_STATUSES: readonly string[] = [
  'up_to_date',
  'outdated',
  'needs_verification',
  'inactive',
];

export const WU_FILTERS: readonly string[] = ['pending', 'reboot_required'];

export const MACHINE_SORT_FIELDS: readonly string[] = [
  'hostname',
  'domain',
  'av_product_name',
  'wu_pending_count',
  'session_user_present',
  'last_seen',
];

/** First scalar of a route-query value, or null (drops arrays' extra values). */
export function queryValue(v: unknown): string | null {
  const scalar = Array.isArray(v) ? v[0] : v;
  return typeof scalar === 'string' && scalar ? scalar : null;
}

/**
 * Filters and sort carried by a machine-list URL, as API params. Unknown
 * values are dropped rather than forwarded: a hand-edited URL must degrade to
 * a broader search, not to a 422.
 *
 * Page and page size are deliberately left to the caller — the list reads its
 * own, while the fiche asks for single-row pages to walk the results.
 */
export function machineListParamsFromQuery(q: LocationQuery): ListMachinesParams {
  const params: ListMachinesParams = {};
  const search = queryValue(q.search);
  if (search) params.search = search;
  const domain = queryValue(q.domain);
  if (domain) params.domain = domain;
  const antivirus = queryValue(q.antivirus);
  if (antivirus) params.antivirus = antivirus;
  const status = queryValue(q.status);
  if (status && MACHINE_STATUSES.includes(status)) params.status = status as MachineStatus;
  const wu = queryValue(q.wu_status);
  if (wu && WU_FILTERS.includes(wu)) params.wu_status = wu as WindowsUpdateFilter;
  if (queryValue(q.with_active_threats) === 'true') params.with_active_threats = true;
  const sort = queryValue(q.sort_by);
  if (sort && MACHINE_SORT_FIELDS.includes(sort)) {
    params.sort_by = sort as MachineSortField;
    params.sort_desc = queryValue(q.sort_desc) !== 'false';
  }
  return params;
}
