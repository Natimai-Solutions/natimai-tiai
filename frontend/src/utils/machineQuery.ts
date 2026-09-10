import type { LocationQuery } from 'vue-router';
import type {
  ListMachinesParams,
  MachineSortField,
  MachineStatus,
  ScanFilter,
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

export const SCAN_FILTERS: readonly string[] = ['quick', 'full', 'both'];

/**
 * Age thresholds the scan filter offers, in days — and the only ones a URL may
 * ask for. Two rather than a free integer: "> 1 semaine" and "> 1 mois" are the
 * questions an administrator actually asks, and a bounded set keeps the URL
 * round-trippable into the dropdown that wrote it.
 */
export const SCAN_AGE_DAYS: readonly number[] = [7, 30];

export const MACHINE_SORT_FIELDS: readonly string[] = [
  'hostname',
  'domain',
  'location',
  'building',
  'room',
  'av_product_name',
  'wu_pending_count',
  'session_user_present',
  'last_seen',
  'hw_model',
  'ram_total_mb',
  'disk_free_percent',
];

/**
 * Chassis kinds the agent normalises to, with the words the console uses for
 * them. A closed list, so the filter is a dropdown and the URL round-trips.
 */
export const CHASSIS_TYPES: readonly { value: string; label: string }[] = [
  { value: 'desktop', label: 'Poste fixe' },
  { value: 'laptop', label: 'Portable' },
  { value: 'tablet', label: 'Tablette' },
  { value: 'all-in-one', label: 'Tout-en-un' },
  { value: 'server', label: 'Serveur' },
];

/** A positive integer from a route-query value, or null. */
export function queryInt(v: unknown): number | null {
  const raw = queryValue(v);
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

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
  const location = queryValue(q.location);
  if (location) params.location = location;
  // The placement: a room id, the sentinel "none" for the unfiled, a building.
  const room = queryValue(q.room);
  if (room === 'none') params.without_room = true;
  else if (room) params.room_id = room;
  const building = queryValue(q.building);
  if (building) params.building_id = building;
  const mismatch = queryValue(q.location_mismatch);
  if (mismatch === 'true') params.location_mismatch = true;
  if (queryValue(q.check_open) === 'true') params.check_open = true;
  const antivirus = queryValue(q.antivirus);
  if (antivirus) params.antivirus = antivirus;
  const os = queryValue(q.os_version);
  if (os) params.os_version = os;
  const status = queryValue(q.status);
  if (status && MACHINE_STATUSES.includes(status)) params.status = status as MachineStatus;
  const wu = queryValue(q.wu_status);
  if (wu && WU_FILTERS.includes(wu)) params.wu_status = wu as WindowsUpdateFilter;
  const scan = queryValue(q.scan_type);
  if (scan && SCAN_FILTERS.includes(scan)) {
    params.scan_type = scan as ScanFilter;
    // The age only means something next to a scan type; sent even at the
    // server's own default so the reading does not depend on the two agreeing.
    const days = Number(queryValue(q.scan_days));
    params.scan_older_than_days = SCAN_AGE_DAYS.includes(days) ? days : SCAN_AGE_DAYS[0]!;
  }
  if (queryValue(q.with_active_threats) === 'true') params.with_active_threats = true;
  if (queryValue(q.online) === 'true') params.online = true;
  // Inventory facets. Text ones travel as-is (the server matches substrings);
  // the numeric ones must parse, or they are dropped like an unknown status.
  const model = queryValue(q.hw_model);
  if (model) params.hw_model = model;
  const manufacturer = queryValue(q.hw_manufacturer);
  if (manufacturer) params.hw_manufacturer = manufacturer;
  const cpu = queryValue(q.cpu_model);
  if (cpu) params.cpu_model = cpu;
  const chassis = queryValue(q.hw_chassis_type);
  if (chassis && CHASSIS_TYPES.some((c) => c.value === chassis)) {
    params.hw_chassis_type = chassis;
  }
  const ramMin = queryInt(q.ram_min_gb);
  if (ramMin !== null) params.ram_min_gb = ramMin;
  const ramMax = queryInt(q.ram_max_gb);
  if (ramMax !== null) params.ram_max_gb = ramMax;
  const diskBelow = queryInt(q.disk_free_below);
  if (diskBelow !== null && diskBelow <= 100) params.disk_free_below = diskBelow;
  const software = queryInt(q.software_id);
  if (software !== null) params.software_id = software;
  // The agent: an exact version travels as-is (the server matches equality),
  // "behind" as the flag.
  const agentVersion = queryValue(q.agent_version);
  if (agentVersion) params.agent_version = agentVersion;
  if (queryValue(q.agent_outdated) === 'true') params.agent_outdated = true;
  const sort = queryValue(q.sort_by);
  if (sort && MACHINE_SORT_FIELDS.includes(sort)) {
    params.sort_by = sort as MachineSortField;
    params.sort_desc = queryValue(q.sort_desc) !== 'false';
  }
  return params;
}
