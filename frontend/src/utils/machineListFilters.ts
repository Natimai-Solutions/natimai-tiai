import type { LocationQuery } from 'vue-router';
import { ASSET_STATUSES, assetStatusLabel } from 'src/services/assets';
import { alertRuleLabel, isAlertRule } from 'src/services/alerts';
import { isDirectoryStatus } from 'src/services/directory';
import {
  COMPLIANCE_STATES,
  complianceCheckLabel,
  isComplianceCheck,
} from 'src/services/compliance';
import { t } from 'src/i18n';
import type {
  ListMachinesParams,
  MachineStatus,
  ScanFilter,
  WindowsUpdateFilter,
} from 'src/services/machines';
import {
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

/**
 * A dropdown entry whose label is worded when it is read, not when the entry
 * is made: the language may change while the list is open (« Mon compte »),
 * and the dropdowns, their chips and the fleet's entries must follow. The
 * label is an enumerable getter, so a copy or a comparison sees the words.
 */
export function liveOption<T>(label: () => string, value: T): FilterOption<T> {
  return {
    get label() {
      return label();
    },
    value,
  };
}

/** An entry worded by a key of the `machines` catalogue. */
function keyed<T>(key: string, value: T): FilterOption<T> {
  return liveOption(() => t(`machines.${key}`), value);
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
  /** C2: a re-enrolment waits for approval (`pending`), or the token is revoked. */
  enrollment: 'pending' | 'revoked' | null;
  /**
   * Hardware past the parc's renewal age — the dashboard's « À renouveler »
   * card, opened as a list. Set by that link, cleared from its chip.
   */
  aging: 'true' | null;
  /** Postes with an open alert: of one rule, or of any (`any`). From the
   * alerts page's « Voir ces postes »; cleared from its chip. */
  alert: string | null;
  /** The status of a poste's asset (`none`: no asset); from the Matériels
   * page's « Voir ces postes ». */
  assetStatus: string | null;
  /** Postes the inventory says cannot take Windows 11; from the dashboard. */
  win11: 'true' | null;
  /** Compliance (C5): failing / passing / unknown, from the dashboard. */
  compliance: string | null;
  /** Postes failing one compliance check; from the dashboard's card. */
  complianceCheck: string | null;
  /** Postes winget would upgrade a program on (its winget id); from the
   * « Mises à jour tierces » view. */
  wingetOutdated: string | null;
  /** Postes carrying a program a licence covers (C6); from the « Licences » view. */
  licenseId: string | null;
  /** The directory's verdict (plan-lecture-annuaire); from Paramètres. */
  directoryStatus: string | null;
  /**
   * Postes in the parc only, the retired ones left out: the dashboard's
   * links carry it while the parc has retired postes, as its figures leave
   * them out. Cleared from its chip.
   */
  inParc: 'true' | null;
}

/** `alert=any` or a rule of the catalogue; anything else is dropped. */
function alertQuery(value: unknown): string | null {
  const v = queryValue(value);
  return v && (v === 'any' || isAlertRule(v)) ? v : null;
}

/** A compliance state of the list's filter; anything else is dropped. */
function complianceQuery(value: unknown): string | null {
  const v = queryValue(value);
  return v && (COMPLIANCE_STATES as readonly string[]).includes(v) ? v : null;
}

/** A winget id, as the agent reports them; anything else is dropped. */
function wingetQuery(value: unknown): string | null {
  const v = queryValue(value);
  return v && /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/.test(v) ? v : null;
}

/** An asset status, or `none`; anything else is dropped. */
function assetStatusQuery(value: unknown): string | null {
  const v = queryValue(value);
  return v && (v === 'none' || (ASSET_STATUSES as readonly string[]).includes(v)) ? v : null;
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
    enrollment: null,
    aging: null,
    alert: null,
    assetStatus: null,
    win11: null,
    compliance: null,
    complianceCheck: null,
    wingetOutdated: null,
    licenseId: null,
    directoryStatus: null,
    inParc: null,
  };
}

// The closed dropdowns. Their values are the only ones a URL may set: an entry
// that is not offered here could not be shown, nor cleared from its chip.

export const MAINTENANCE_OPTIONS: FilterOption[] = [
  keyed('options.maintenance.all', null),
  keyed('options.maintenance.overdue', 'overdue'),
  keyed('options.maintenance.due_soon', 'due_soon'),
  keyed('options.maintenance.ok', 'ok'),
  keyed('options.maintenance.excluded', 'excluded'),
];

export const CHECK_OPTIONS: FilterOption[] = [
  keyed('options.check.all', null),
  keyed('options.check.open', 'true'),
];

// « Antivirus » in the labels, not just « à jour » : since the Windows Update
// filter joined it, this axis has to say which of the two updates it means.
export const STATUS_OPTIONS: FilterOption[] = [
  keyed('options.status.all', null),
  keyed('options.status.up_to_date', 'up_to_date'),
  keyed('options.status.outdated', 'outdated'),
  keyed('options.status.needs_verification', 'needs_verification'),
  keyed('options.status.inactive', 'inactive'),
];

export const WU_OPTIONS: FilterOption[] = [
  keyed('options.wu.all', null),
  keyed('options.wu.pending', 'pending'),
  keyed('options.wu.reboot_required', 'reboot_required'),
];

// « > 1 sem. » / « > 1 mois » : the two questions asked of a scan date. A
// never-run scan counts as overdue server-side — those are the postes the
// filter exists to surface.
export const SCAN_OPTIONS: FilterOption[] = [
  keyed('options.scan.all', null),
  keyed('options.scan.quick7', 'quick:7'),
  keyed('options.scan.quick30', 'quick:30'),
  keyed('options.scan.full7', 'full:7'),
  keyed('options.scan.full30', 'full:30'),
  keyed('options.scan.both7', 'both:7'),
  keyed('options.scan.both30', 'both:30'),
];

export const ENROLLMENT_OPTIONS: FilterOption[] = [
  keyed('options.enrollment.all', null),
  keyed('options.enrollment.pending', 'pending'),
  keyed('options.enrollment.revoked', 'revoked'),
];

/**
 * A dropdown's entries, plus the value in use when it is none of them — a
 * link, or a value the fleet listing has not loaded yet. Without it the select
 * shows nothing for a filter that is narrowing the list.
 */
export function optionsWithCurrent(
  options: FilterOption[],
  current: string | null,
  labelOf: (value: string) => string = (value) => value,
): FilterOption[] {
  if (current == null || options.some((o) => o.value === current)) return options;
  return [...options, liveOption(() => labelOf(current), current)];
}

export const MISMATCH_OPTIONS: FilterOption[] = [
  keyed('options.mismatch.all', null),
  keyed('options.mismatch.mismatch', 'true'),
];

export const RAM_OP_OPTIONS: FilterOption<'min' | 'max' | null>[] = [
  keyed('options.ram.all', null),
  keyed('options.ram.min', 'min'),
  keyed('options.ram.max', 'max'),
];

/** The chip and menu label of a free-space threshold, whatever its value. */
export function diskFreeLabel(percent: number): string {
  return t('machines.options.disk.below', { percent });
}

export const DISK_OPTIONS: FilterOption<number | null>[] = [
  keyed('options.disk.all', null),
  liveOption(() => diskFreeLabel(10), 10),
  liveOption(() => diskFreeLabel(20), 20),
];

/**
 * The menu's choices, plus the threshold in use when it is none of them —
 * the dashboard's card links with the threshold set in Paramètres, which can
 * be any value from 1 to 99 (audit B01).
 */
export function diskOptionsFor(current: number | null): FilterOption<number | null>[] {
  if (current == null || DISK_OPTIONS.some((o) => o.value === current)) return DISK_OPTIONS;
  return [...DISK_OPTIONS, liveOption(() => diskFreeLabel(current), current)].sort(
    (a, b) => (a.value ?? -1) - (b.value ?? -1),
  );
}

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

/** A fleet dropdown's « Tous » entry. */
export function fleetAllOption(key: keyof MachineFleetOptions): FilterOption {
  return keyed(`options.fleet.${key}`, null);
}

/** The fleet dropdowns before anything is loaded: each its « Tous » entry alone. */
export function initialFleetOptions(): MachineFleetOptions {
  return {
    antivirus: [fleetAllOption('antivirus')],
    os: [fleetAllOption('os')],
    agent: [fleetAllOption('agent')],
    location: [fleetAllOption('location')],
    building: [fleetAllOption('building')],
    room: [fleetAllOption('room')],
    model: [fleetAllOption('model')],
    manufacturer: [fleetAllOption('manufacturer')],
    processor: [fleetAllOption('processor')],
    // The kinds are a closed list the agent normalises to, so the entries are
    // known in advance; the fleet only says which of them are present, and
    // how many of each.
    chassis: [fleetAllOption('chassis')],
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
  // The bound alone, while its figure is being retyped: kept in the URL so
  // that emptying the box does not reset the bound and lock the box (item 8).
  const ramOpAlone = queryValue(q.ram_op);
  const enrollment = queryValue(q.enrollment);
  const below = Number(queryValue(q.disk_free_below));
  const days = queryInt(q.usage_days);
  const software = Number(queryValue(q.software_id));
  return {
    search: queryValue(q.search)?.trim() ?? '',
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
    // Any kind the fleet lists, « chassis-35 » included (item 8).
    chassis: kind,
    ramOp:
      ramMin !== null
        ? 'min'
        : ramMax !== null
          ? 'max'
          : ramOpAlone === 'min' || ramOpAlone === 'max'
            ? ramOpAlone
            : null,
    ramGb: ramMin ?? ramMax,
    // Any whole percentage the settings accept, not only the menu's two.
    diskFree: Number.isInteger(below) && below >= 1 && below <= 99 ? below : null,
    usageBelow: queryFloat(q.usage_hours_below),
    usageAbove: queryFloat(q.usage_hours_above),
    usageDays: days !== null && days <= USAGE_MAX_DAYS ? days : null,
    softwareId: Number.isInteger(software) && software > 0 ? software : null,
    enrollment: enrollment === 'pending' || enrollment === 'revoked' ? enrollment : null,
    aging: queryValue(q.hardware_aging) === 'true' ? 'true' : null,
    alert: alertQuery(q.alert),
    assetStatus: assetStatusQuery(q.asset_status),
    win11: queryValue(q.win11_blocked) === 'true' ? 'true' : null,
    compliance: complianceQuery(q.compliance),
    complianceCheck: (() => {
      const v = queryValue(q.compliance_check);
      return v && isComplianceCheck(v) ? v : null;
    })(),
    wingetOutdated: wingetQuery(q.winget_outdated),
    licenseId: (() => {
      const v = queryValue(q.license_id);
      return v && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v)
        ? v.toLowerCase()
        : null;
    })(),
    directoryStatus: (() => {
      const v = queryValue(q.directory_status);
      return v && isDirectoryStatus(v) ? v : null;
    })(),
    inParc: queryValue(q.in_parc) === 'true' ? 'true' : null,
  };
}

/**
 * The filters as URL query params, defaults omitted so the common URL stays
 * short. The sort and the page are the table's, added by the caller.
 */
export function machineFiltersToQuery(f: MachineFilters): Record<string, string> {
  const query: Record<string, string> = {};
  const search = f.search.trim();
  if (search) query.search = search;
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
  } else if (f.ramOp) {
    query.ram_op = f.ramOp;
  }
  if (f.diskFree != null) query.disk_free_below = String(f.diskFree);
  const usage = usageBoundsOf(f);
  if (usage.below !== null) query.usage_hours_below = String(usage.below);
  if (usage.above !== null) query.usage_hours_above = String(usage.above);
  if (f.usageDays !== null) query.usage_days = String(f.usageDays);
  if (f.softwareId != null) query.software_id = String(f.softwareId);
  if (f.enrollment) query.enrollment = f.enrollment;
  if (f.aging) query.hardware_aging = 'true';
  if (f.alert) query.alert = f.alert;
  if (f.assetStatus) query.asset_status = f.assetStatus;
  if (f.win11) query.win11_blocked = 'true';
  if (f.compliance) query.compliance = f.compliance;
  if (f.complianceCheck) query.compliance_check = f.complianceCheck;
  if (f.wingetOutdated) query.winget_outdated = f.wingetOutdated;
  if (f.licenseId) query.license_id = f.licenseId;
  if (f.directoryStatus) query.directory_status = f.directoryStatus;
  if (f.inParc) query.in_parc = 'true';
  return query;
}

/**
 * The filters as API params — every facet, no pagination and no sort. One
 * definition for the list and the export: an export that silently ignored a
 * facet the reader had set would be worse than no export at all.
 */
export function machineFiltersToParams(f: MachineFilters): ListMachinesParams {
  const params: ListMachinesParams = {};
  // Trimmed: « PC-01 » pasted with its trailing space found nothing.
  const search = f.search.trim();
  if (search) params.search = search;
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
  if (f.enrollment) params.enrollment = f.enrollment;
  if (f.aging) params.hardware_aging = true;
  if (f.alert) params.alert = f.alert;
  if (f.assetStatus) params.asset_status = f.assetStatus;
  if (f.win11) params.win11_blocked = true;
  if (f.compliance) params.compliance = f.compliance;
  if (f.complianceCheck) params.compliance_check = f.complianceCheck;
  if (f.wingetOutdated) params.winget_outdated = f.wingetOutdated;
  if (f.licenseId) params.license_id = f.licenseId;
  if (f.directoryStatus) params.directory_status = f.directoryStatus;
  if (f.inParc) params.in_parc = true;
  // The console sets these five from dropdowns fed by the fleet's exact
  // values, with their counts: matched exactly, « OptiPlex 7010 (12) » lists
  // those 12 postes and not the « OptiPlex 7010 AIO » too. The API keeps the
  // substring for a value without `exact`.
  const exact = (
    [
      ['antivirus', f.antivirus],
      ['os_version', f.os],
      ['hw_model', f.model],
      ['hw_manufacturer', f.manufacturer],
      ['cpu_model', f.processor],
    ] as const
  )
    .filter(([, value]) => value)
    .map(([facet]) => facet);
  if (exact.length) params.exact = exact.join(',');
  return params;
}

export type MachineFilterKey =
  | 'domain'
  | 'enrollment'
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
  | 'agent'
  | 'aging'
  | 'alert'
  | 'assetStatus'
  | 'win11'
  | 'compliance'
  | 'complianceCheck'
  | 'wingetOutdated'
  | 'licenseId'
  | 'directoryStatus'
  | 'inParc';

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
  // No dropdown for the domain: it arrives by a link or a hand-typed URL, and
  // its chip is the only thing on screen that says it narrows the list.
  if (f.domain)
    chips.push({ key: 'domain', label: t('machines.chips.domain', { domain: f.domain }) });
  if (f.enrollment) {
    chips.push({ key: 'enrollment', label: label(ENROLLMENT_OPTIONS, f.enrollment) });
  }
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
      label: t('machines.chips.ram', { op: f.ramOp === 'min' ? '≥' : '≤', gb: ramGbValue(f) }),
    });
  }
  if (f.diskFree != null) {
    chips.push({
      key: 'disk',
      label: diskFreeLabel(f.diskFree),
    });
  }
  const bounds = usageBoundsOf(f);
  if (bounds.below !== null || bounds.above !== null) {
    chips.push({ key: 'usage', label: usageFilterLabel(bounds, usageWindowDays) });
  }
  // No option list behind this one: it comes from a link, so the chip is what
  // tells the reader why the list is short — and the only way back out of it.
  if (f.softwareId != null) {
    chips.push({ key: 'software', label: t('machines.chips.software') });
  }
  // From the dashboard's card, like the software one: the chip says why.
  if (f.aging) chips.push({ key: 'aging', label: t('machines.chips.aging') });
  if (f.alert) {
    chips.push({
      key: 'alert',
      label:
        f.alert === 'any'
          ? t('machines.chips.alertAny')
          : t('machines.chips.alert', { rule: alertRuleLabel(f.alert) }),
    });
  }
  if (f.assetStatus) {
    chips.push({
      key: 'assetStatus',
      label:
        f.assetStatus === 'none'
          ? t('machines.chips.assetNone')
          : t('machines.chips.assetStatus', { status: assetStatusLabel(f.assetStatus) }),
    });
  }
  if (f.win11) chips.push({ key: 'win11', label: t('machines.chips.win11') });
  if (f.compliance) {
    chips.push({ key: 'compliance', label: t(`compliance.chips.${f.compliance}`) });
  }
  if (f.complianceCheck) {
    chips.push({
      key: 'complianceCheck',
      label: t('compliance.chips.check', { check: complianceCheckLabel(f.complianceCheck) }),
    });
  }
  if (f.wingetOutdated) {
    chips.push({
      key: 'wingetOutdated',
      label: t('compliance.chips.winget', { id: f.wingetOutdated }),
    });
  }
  if (f.licenseId) {
    chips.push({ key: 'licenseId', label: t('licenses.chip') });
  }
  if (f.directoryStatus) {
    chips.push({
      key: 'directoryStatus',
      label: t('directory.chip', { status: t(`directory.status.${f.directoryStatus}`) }),
    });
  }
  if (f.inParc) chips.push({ key: 'inParc', label: t('machines.chips.inParc') });
  return chips;
}

/** A filter set to a value the parc does not hold: see `unmatchedExactFilters`. */
export interface UnmatchedFilter {
  key: MachineFilterKey;
  /** The facet in the console's words: « Modèle ». */
  facet: string;
  value: string;
}

/**
 * The facets the server matches exactly — the whole value, case included —
 * whose current value is not one of the parc's. Their dropdowns only offer the
 * parc's own values, so such a value was typed into the URL (`?hw_model=
 * OptiPlex`, where the parc holds « OptiPlex 7010 »): it matches nothing, and
 * a bare empty list would not say that the match is exact.
 *
 * Only once the dropdown has been filled: before that — or when its listing
 * failed — nobody knows what the parc holds, and nothing is claimed.
 */
export function unmatchedExactFilters(
  f: MachineFilters,
  options: MachineFleetOptions,
): UnmatchedFilter[] {
  const facets: [MachineFilterKey, string, string | null, FilterOption[]][] = [
    ['location', t('machines.facets.location'), f.location, options.location],
    ['antivirus', t('machines.facets.antivirus'), f.antivirus, options.antivirus],
    ['os', t('machines.facets.os'), f.os, options.os],
    ['agent', t('machines.facets.agent'), f.agent, options.agent],
    ['manufacturer', t('machines.facets.manufacturer'), f.manufacturer, options.manufacturer],
    ['model', t('machines.facets.model'), f.model, options.model],
    ['processor', t('machines.facets.processor'), f.processor, options.processor],
  ];
  return facets.flatMap(([key, facet, value, known]) => {
    // The « Tous » entry alone: the listing has not answered.
    if (!value || known.length <= 1) return [];
    // « Agent obsolète » is the console's own entry, not a version.
    if (key === 'agent' && value === AGENT_OUTDATED) return [];
    return known.some((o) => o.value === value) ? [] : [{ key, facet, value }];
  });
}

/** The usage filter off, window included: a widened window is part of it. */
export function clearUsageFilter(f: MachineFilters): MachineFilters {
  return { ...f, usageBelow: null, usageAbove: null, usageDays: null };
}

/** The fields each chip stands for — the memory and usage ones are several. */
const FIELDS_BY_KEY: Record<
  Exclude<MachineFilterKey, 'ram' | 'usage' | 'domain'>,
  keyof MachineFilters
> = {
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
  enrollment: 'enrollment',
  aging: 'aging',
  alert: 'alert',
  assetStatus: 'assetStatus',
  win11: 'win11',
  compliance: 'compliance',
  complianceCheck: 'complianceCheck',
  wingetOutdated: 'wingetOutdated',
  licenseId: 'licenseId',
  directoryStatus: 'directoryStatus',
  inParc: 'inParc',
};

/** The filters with one chip's facet off. */
export function clearMachineFilter(f: MachineFilters, key: MachineFilterKey): MachineFilters {
  if (key === 'ram') return { ...f, ramOp: null, ramGb: null };
  if (key === 'usage') return clearUsageFilter(f);
  if (key === 'domain') return { ...f, domain: '' };
  return { ...f, [FIELDS_BY_KEY[key]]: null };
}
