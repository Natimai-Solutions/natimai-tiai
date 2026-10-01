import type { LocationQuery } from 'vue-router';
import type {
  ListMachinesParams,
  MachineStatus,
  ScanFilter,
  WindowsUpdateFilter,
} from 'src/services/machines';
import {
  CHASSIS_TYPES,
  MACHINE_STATUSES,
  SCAN_AGE_DAYS,
  SCAN_FILTERS,
  USAGE_MAX_DAYS,
  WU_FILTERS,
  queryFloat,
  queryInt,
  queryValue,
} from 'src/utils/machineQuery';
import { parseHours, usageFilterLabel, type UsageBounds } from 'src/utils/usageFilter';

/**
 * The machine list's filters, as the page holds them between the URL and the
 * widgets — and the pure translations between the three: URL ⇄ filters, and
 * filters → API params.
 *
 * The URL stays the single source of truth (see `machineQuery.ts`, which the
 * fiche d'un poste reads too): every widget change is written into it, and the
 * page reads its filters back out of it. The shapes below are the widgets'
 * own — a dropdown's token, a figure typed in a box — which is why they differ
 * from the API params in a few places (the scan token, the memory bound).
 */

/** The « Sans salle » entry of the room filter: the postes nobody filed. */
export const ROOM_NONE = 'none';

/**
 * One dropdown for two questions: "behind the reference" (this sentinel) or one
 * exact version. A version is never spelled like the sentinel.
 */
export const AGENT_OUTDATED = 'outdated';

/** One entry of a filter dropdown. */
export interface FilterOption<T = string | null> {
  label: string;
  value: T;
  disable?: boolean;
}

export interface MachineFilters {
  search: string;
  domain: string;
  /** The site, exact like the domain: the dropdown feeds it fleet values. */
  location: string | null;
  /** The console's placement: a building id, a room id or `ROOM_NONE`. */
  building: string | null;
  room: string | null;
  /** The agent/room disagreement: `'true'` or null, as its dropdown speaks. */
  mismatch: string | null;
  /** A verification request is open on the poste: `'true'` or null. */
  checkOpen: string | null;
  /** Where the poste stands on its maintenance cycle. */
  maintenance: string | null;
  antivirus: string | null;
  status: MachineStatus | null;
  wu: WindowsUpdateFilter | null;
  /**
   * One token "<type>:<days>" (e.g. "quick:7"): the dropdown speaks in one
   * value, the URL and the server in a scan type and an age — split at the
   * boundaries.
   */
  scan: string | null;
  os: string | null;
  /** An exact version, or `AGENT_OUTDATED`. */
  agent: string | null;
  threatsOnly: boolean;
  onlineOnly: boolean;
  /**
   * Inventory facets. `model` is a substring like the antivirus one —
   * "OptiPlex" has to gather the 7010 and the 7020, which is how a parc is
   * reasoned about.
   */
  model: string | null;
  manufacturer: string | null;
  processor: string | null;
  chassis: string | null;
  /**
   * Memory in two halves — a bound and a figure in GiB — because "au moins 16"
   * is how the upgrade question is asked. Only counts once both are set.
   */
  ramOp: 'min' | 'max' | null;
  /**
   * A string as often as a number: QInput hands back what was typed, whatever
   * the `type`, and the URL hands back a parsed integer. `ramGbValue` is the
   * one reading the filter uses.
   */
  ramGb: number | string | null;
  /**
   * A *percentage* of free space and not a size: 40 Go left on a 4 To disk and
   * on a 128 Go SSD are not the same news.
   */
  diskFree: number | null;
  /**
   * Usage over a window: two bounds in hours, typed or set by a preset — the
   * boxes hand back strings, `parseHours` reads both. The window itself only
   * travels through the URL (a link may widen it).
   */
  usageBelow: number | string | null;
  usageAbove: number | string | null;
  usageDays: number | null;
  /**
   * Set by a link from the software catalogue or from a fiche; never by a
   * widget, since nobody types a catalogue id. Carried through the URL so the
   * back arrow from a fiche comes back to the same filtered list.
   */
  softwareId: number | null;
}

/** The whole parc: no search, no facet, both toggles off. */
export function emptyMachineFilters(): MachineFilters {
  return {
    search: '',
    domain: '',
    location: null,
    building: null,
    room: null,
    mismatch: null,
    checkOpen: null,
    maintenance: null,
    antivirus: null,
    status: null,
    wu: null,
    scan: null,
    os: null,
    agent: null,
    threatsOnly: false,
    onlineOnly: false,
    model: null,
    manufacturer: null,
    processor: null,
    chassis: null,
    ramOp: null,
    ramGb: null,
    diskFree: null,
    usageBelow: null,
    usageAbove: null,
    usageDays: null,
    softwareId: null,
  };
}

// The closed dropdowns. Their values are the only ones a URL may set: an entry
// that is not offered here could not be shown, nor cleared from its chip.

export const MAINTENANCE_OPTIONS: FilterOption[] = [
  { label: 'Maintenance : tous', value: null },
  { label: 'Maintenance en retard', value: 'overdue' },
  { label: 'Maintenance à échéance', value: 'due_soon' },
  { label: 'Maintenance à jour', value: 'ok' },
  { label: 'Exclus de la maintenance', value: 'excluded' },
];

export const CHECK_OPTIONS: FilterOption[] = [
  { label: 'Vérifications : toutes', value: null },
  { label: 'Vérification demandée (ouverte)', value: 'true' },
];

// « Antivirus » in the labels, not just « à jour » : since the Windows Update
// filter joined it, this axis has to say which of the two updates it means.
export const STATUS_OPTIONS: FilterOption[] = [
  { label: 'Antivirus : Tous statuts', value: null },
  { label: 'Antivirus à jour', value: 'up_to_date' },
  { label: 'Antivirus périmé', value: 'outdated' },
  { label: 'Identité à confirmer', value: 'needs_verification' },
  { label: 'Inactif', value: 'inactive' },
];

export const WU_OPTIONS: FilterOption[] = [
  { label: 'Windows Update : Tous statuts', value: null },
  { label: 'MAJ Windows requises', value: 'pending' },
  { label: 'Redémarrage requis', value: 'reboot_required' },
];

// « > 1 sem. » / « > 1 mois » : the two questions asked of a scan date. A
// never-run scan counts as overdue server-side — those are the postes the
// filter exists to surface.
export const SCAN_OPTIONS: FilterOption[] = [
  { label: 'Scan AV : Tous', value: null },
  { label: 'Scan rapide > 1 sem.', value: 'quick:7' },
  { label: 'Scan rapide > 1 mois', value: 'quick:30' },
  { label: 'Scan complet > 1 sem.', value: 'full:7' },
  { label: 'Scan complet > 1 mois', value: 'full:30' },
  { label: 'Les 2 scans > 1 sem.', value: 'both:7' },
  { label: 'Les 2 scans > 1 mois', value: 'both:30' },
];

export const MISMATCH_OPTIONS: FilterOption[] = [
  { label: 'Emplacement / salle : tous', value: null },
  { label: 'Emplacement divergent de la salle', value: 'true' },
];

export const RAM_OP_OPTIONS: FilterOption<'min' | 'max' | null>[] = [
  { label: 'Mémoire : toutes', value: null },
  { label: 'Mémoire : au moins', value: 'min' },
  { label: 'Mémoire : au plus', value: 'max' },
];

export const DISK_OPTIONS: FilterOption<number | null>[] = [
  { label: 'Espace disque : tous', value: null },
  { label: 'Moins de 10 % libres', value: 10 },
  { label: 'Moins de 20 % libres', value: 20 },
];

/**
 * The dropdowns filled from the fleet (and from the rooms the console holds):
 * what a parc contains is data, not a list the console can know in advance.
 * Each starts with its « Tous » entry, which is all it keeps if its listing
 * fails.
 */
export interface MachineFleetOptions {
  antivirus: FilterOption[];
  os: FilterOption[];
  agent: FilterOption[];
  location: FilterOption[];
  building: FilterOption[];
  room: FilterOption[];
  model: FilterOption[];
  manufacturer: FilterOption[];
  processor: FilterOption[];
  chassis: FilterOption[];
}

/** The fleet dropdowns before anything is loaded: each its « Tous » entry alone. */
export function initialFleetOptions(): MachineFleetOptions {
  return {
    antivirus: [{ label: 'Tous les antivirus', value: null }],
    os: [{ label: 'Tous les OS', value: null }],
    agent: [{ label: 'Agent : toutes versions', value: null }],
    location: [{ label: 'Tous les emplacements', value: null }],
    building: [{ label: 'Tous les bâtiments', value: null }],
    room: [{ label: 'Toutes les salles', value: null }],
    model: [{ label: 'Tous les modèles', value: null }],
    manufacturer: [{ label: 'Tous les constructeurs', value: null }],
    processor: [{ label: 'Tous les processeurs', value: null }],
    // The kinds are a closed list the agent normalises to, so the entries are
    // known in advance; the fleet only says which of them are present, and
    // how many of each.
    chassis: [{ label: 'Tous les types de poste', value: null }],
  };
}

/** The typed memory figure as a positive whole number of GiB, or null. */
export function ramGbValue(f: Pick<MachineFilters, 'ramGb'>): number | null {
  if (f.ramGb === null || f.ramGb === '') return null;
  const n = Number(f.ramGb);
  return Number.isInteger(n) && n > 0 ? n : null;
}

/** Whether the memory filter is complete enough to apply. */
export function isRamActive(f: Pick<MachineFilters, 'ramOp' | 'ramGb'>): boolean {
  return f.ramOp !== null && ramGbValue(f) !== null;
}

/** The usage bounds as hours, whatever the boxes handed back. */
export function usageBoundsOf(f: Pick<MachineFilters, 'usageBelow' | 'usageAbove'>): UsageBounds {
  return { below: parseHours(f.usageBelow), above: parseHours(f.usageAbove) };
}

/**
 * Read the filters from the URL — the dashboard cards land on the list with
 * one set, and the detail page's back arrow with another. Values no widget
 * could have written are dropped, so a hand-edited URL degrades to a broader
 * search.
 */
export function machineFiltersFromQuery(q: LocationQuery): MachineFilters {
  const ms = queryValue(q.maintenance_state);
  const s = queryValue(q.status);
  const w = queryValue(q.wu_status);
  const scanType = queryValue(q.scan_type);
  const scanDays = Number(queryValue(q.scan_days));
  const kind = queryValue(q.hw_chassis_type);
  // One bound at a time on screen: a URL carrying both keeps the lower one,
  // which is the upgrade question and the more common of the two.
  const ramMin = queryInt(q.ram_min_gb);
  const ramMax = queryInt(q.ram_max_gb);
  const below = Number(queryValue(q.disk_free_below));
  const days = queryInt(q.usage_days);
  const software = Number(queryValue(q.software_id));
  return {
    search: queryValue(q.search) ?? '',
    domain: queryValue(q.domain) ?? '',
    location: queryValue(q.location),
    building: queryValue(q.building),
    room: queryValue(q.room),
    mismatch: queryValue(q.location_mismatch) === 'true' ? 'true' : null,
    checkOpen: queryValue(q.check_open) === 'true' ? 'true' : null,
    maintenance: ms && MAINTENANCE_OPTIONS.some((o) => o.value === ms) ? ms : null,
    antivirus: queryValue(q.antivirus),
    os: queryValue(q.os_version),
    agent: queryValue(q.agent_outdated) === 'true' ? AGENT_OUTDATED : queryValue(q.agent_version),
    status: s && MACHINE_STATUSES.includes(s) ? (s as MachineStatus) : null,
    wu: w && WU_FILTERS.includes(w) ? (w as WindowsUpdateFilter) : null,
    scan:
      scanType && SCAN_FILTERS.includes(scanType)
        ? `${scanType}:${SCAN_AGE_DAYS.includes(scanDays) ? scanDays : SCAN_AGE_DAYS[0]}`
        : null,
    threatsOnly: queryValue(q.with_active_threats) === 'true',
    onlineOnly: queryValue(q.online) === 'true',
    model: queryValue(q.hw_model),
    manufacturer: queryValue(q.hw_manufacturer),
    processor: queryValue(q.cpu_model),
    chassis: kind && CHASSIS_TYPES.some((c) => c.value === kind) ? kind : null,
    ramOp: ramMin !== null ? 'min' : ramMax !== null ? 'max' : null,
    ramGb: ramMin ?? ramMax,
    diskFree: DISK_OPTIONS.some((o) => o.value === below) ? below : null,
    usageBelow: queryFloat(q.usage_hours_below),
    usageAbove: queryFloat(q.usage_hours_above),
    usageDays: days !== null && days <= USAGE_MAX_DAYS ? days : null,
    softwareId: Number.isInteger(software) && software > 0 ? software : null,
  };
}

/**
 * The filters as URL query params, defaults omitted so the common URL stays
 * short. The sort and the page are the table's, added by the caller.
 */
export function machineFiltersToQuery(f: MachineFilters): Record<string, string> {
  const query: Record<string, string> = {};
  if (f.search) query.search = f.search;
  if (f.domain) query.domain = f.domain;
  if (f.location) query.location = f.location;
  if (f.building) query.building = f.building;
  if (f.room) query.room = f.room;
  if (f.mismatch) query.location_mismatch = f.mismatch;
  if (f.checkOpen) query.check_open = f.checkOpen;
  if (f.maintenance) query.maintenance_state = f.maintenance;
  if (f.antivirus) query.antivirus = f.antivirus;
  if (f.os) query.os_version = f.os;
  if (f.agent === AGENT_OUTDATED) query.agent_outdated = 'true';
  else if (f.agent) query.agent_version = f.agent;
  if (f.status) query.status = f.status;
  if (f.wu) query.wu_status = f.wu;
  if (f.scan) {
    const [scanType, scanDays] = f.scan.split(':');
    query.scan_type = scanType!;
    query.scan_days = scanDays!;
  }
  if (f.threatsOnly) query.with_active_threats = 'true';
  if (f.onlineOnly) query.online = 'true';
  if (f.model) query.hw_model = f.model;
  if (f.manufacturer) query.hw_manufacturer = f.manufacturer;
  if (f.processor) query.cpu_model = f.processor;
  if (f.chassis) query.hw_chassis_type = f.chassis;
  if (isRamActive(f)) {
    query[f.ramOp === 'min' ? 'ram_min_gb' : 'ram_max_gb'] = String(ramGbValue(f));
  }
  if (f.diskFree != null) query.disk_free_below = String(f.diskFree);
  const usage = usageBoundsOf(f);
  if (usage.below !== null) query.usage_hours_below = String(usage.below);
  if (usage.above !== null) query.usage_hours_above = String(usage.above);
  if (f.usageDays !== null) query.usage_days = String(f.usageDays);
  if (f.softwareId != null) query.software_id = String(f.softwareId);
  return query;
}

/**
 * The filters as API params — every facet, no pagination and no sort. One
 * definition for the list and the export: an export that silently ignored a
 * facet the reader had set would be worse than no export at all.
 */
export function machineFiltersToParams(f: MachineFilters): ListMachinesParams {
  const params: ListMachinesParams = {};
  if (f.search) params.search = f.search;
  if (f.domain) params.domain = f.domain;
  if (f.location) params.location = f.location;
  if (f.building) params.building_id = f.building;
  if (f.room === ROOM_NONE) params.without_room = true;
  else if (f.room) params.room_id = f.room;
  if (f.mismatch) params.location_mismatch = true;
  if (f.checkOpen) params.check_open = true;
  if (f.maintenance) {
    params.maintenance_state = f.maintenance as 'excluded' | 'overdue' | 'due_soon' | 'ok';
  }
  if (f.antivirus) params.antivirus = f.antivirus;
  if (f.os) params.os_version = f.os;
  if (f.agent === AGENT_OUTDATED) params.agent_outdated = true;
  else if (f.agent) params.agent_version = f.agent;
  if (f.status) params.status = f.status;
  if (f.wu) params.wu_status = f.wu;
  if (f.scan) {
    const [scanType, scanDays] = f.scan.split(':');
    params.scan_type = scanType as ScanFilter;
    params.scan_older_than_days = Number(scanDays);
  }
  if (f.threatsOnly) params.with_active_threats = true;
  if (f.onlineOnly) params.online = true;
  if (f.model) params.hw_model = f.model;
  if (f.manufacturer) params.hw_manufacturer = f.manufacturer;
  if (f.processor) params.cpu_model = f.processor;
  if (f.chassis) params.hw_chassis_type = f.chassis;
  const ram = ramGbValue(f);
  if (isRamActive(f) && ram !== null) {
    if (f.ramOp === 'min') params.ram_min_gb = ram;
    else params.ram_max_gb = ram;
  }
  if (f.diskFree != null) params.disk_free_below = f.diskFree;
  const usage = usageBoundsOf(f);
  if (usage.below !== null) params.usage_hours_below = usage.below;
  if (usage.above !== null) params.usage_hours_above = usage.above;
  if (f.usageDays !== null) params.usage_days = f.usageDays;
  if (f.softwareId != null) params.software_id = f.softwareId;
  return params;
}

export type MachineFilterKey =
  | 'location'
  | 'building'
  | 'room'
  | 'mismatch'
  | 'check'
  | 'maintenance'
  | 'antivirus'
  | 'status'
  | 'wu'
  | 'scan'
  | 'os'
  | 'manufacturer'
  | 'model'
  | 'processor'
  | 'chassis'
  | 'ram'
  | 'disk'
  | 'usage'
  | 'software'
  | 'agent';

export interface MachineFilterChip {
  key: MachineFilterKey;
  label: string;
}

/**
 * The folded filters currently narrowing the list, as chip labels. The label
 * is looked up in the dropdown's own options, so a chip always reads exactly
 * like the entry that set it. The search and the two toggles have no chip:
 * they stay on the bar, folded or not.
 */
export function machineFilterChips(
  f: MachineFilters,
  options: MachineFleetOptions,
  usageWindowDays: number,
): MachineFilterChip[] {
  const label = (opts: FilterOption[], v: string) => opts.find((o) => o.value === v)?.label ?? v;
  const chips: MachineFilterChip[] = [];
  if (f.location) chips.push({ key: 'location', label: label(options.location, f.location) });
  if (f.building) chips.push({ key: 'building', label: label(options.building, f.building) });
  if (f.room) chips.push({ key: 'room', label: label(options.room, f.room) });
  if (f.mismatch) chips.push({ key: 'mismatch', label: label(MISMATCH_OPTIONS, f.mismatch) });
  if (f.checkOpen) chips.push({ key: 'check', label: label(CHECK_OPTIONS, f.checkOpen) });
  if (f.maintenance) {
    chips.push({ key: 'maintenance', label: label(MAINTENANCE_OPTIONS, f.maintenance) });
  }
  if (f.antivirus) chips.push({ key: 'antivirus', label: label(options.antivirus, f.antivirus) });
  if (f.status) chips.push({ key: 'status', label: label(STATUS_OPTIONS, f.status) });
  if (f.wu) chips.push({ key: 'wu', label: label(WU_OPTIONS, f.wu) });
  if (f.scan) chips.push({ key: 'scan', label: label(SCAN_OPTIONS, f.scan) });
  if (f.os) chips.push({ key: 'os', label: label(options.os, f.os) });
  if (f.agent) chips.push({ key: 'agent', label: label(options.agent, f.agent) });
  if (f.manufacturer) {
    chips.push({ key: 'manufacturer', label: label(options.manufacturer, f.manufacturer) });
  }
  if (f.model) chips.push({ key: 'model', label: label(options.model, f.model) });
  if (f.processor) {
    chips.push({ key: 'processor', label: label(options.processor, f.processor) });
  }
  if (f.chassis) chips.push({ key: 'chassis', label: label(options.chassis, f.chassis) });
  if (isRamActive(f)) {
    chips.push({
      key: 'ram',
      label: `Mémoire ${f.ramOp === 'min' ? '≥' : '≤'} ${ramGbValue(f)} Gio`,
    });
  }
  if (f.diskFree != null) {
    chips.push({
      key: 'disk',
      label: DISK_OPTIONS.find((o) => o.value === f.diskFree)?.label ?? 'Espace disque',
    });
  }
  const bounds = usageBoundsOf(f);
  if (bounds.below !== null || bounds.above !== null) {
    chips.push({ key: 'usage', label: usageFilterLabel(bounds, usageWindowDays) });
  }
  // No option list behind this one: it comes from a link, so the chip is what
  // tells the reader why the list is short — and the only way back out of it.
  if (f.softwareId != null) {
    chips.push({ key: 'software', label: 'Postes portant un logiciel' });
  }
  return chips;
}

/** The usage filter off, window included: a widened window is part of it. */
export function clearUsageFilter(f: MachineFilters): MachineFilters {
  return { ...f, usageBelow: null, usageAbove: null, usageDays: null };
}

/** The fields each chip stands for — the memory and usage ones are several. */
const FIELDS_BY_KEY: Record<Exclude<MachineFilterKey, 'ram' | 'usage'>, keyof MachineFilters> = {
  location: 'location',
  building: 'building',
  room: 'room',
  mismatch: 'mismatch',
  check: 'checkOpen',
  maintenance: 'maintenance',
  antivirus: 'antivirus',
  status: 'status',
  wu: 'wu',
  scan: 'scan',
  os: 'os',
  manufacturer: 'manufacturer',
  model: 'model',
  processor: 'processor',
  chassis: 'chassis',
  disk: 'diskFree',
  software: 'softwareId',
  agent: 'agent',
};

/** The filters with one chip's facet off. */
export function clearMachineFilter(f: MachineFilters, key: MachineFilterKey): MachineFilters {
  if (key === 'ram') return { ...f, ramOp: null, ramGb: null };
  if (key === 'usage') return clearUsageFilter(f);
  return { ...f, [FIELDS_BY_KEY[key]]: null };
}
