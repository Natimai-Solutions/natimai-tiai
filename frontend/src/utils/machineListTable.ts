import type { LocationQuery } from 'vue-router';
import type { QTableColumn } from 'quasar';
import { t } from 'src/i18n';
import type { Machine, MachineSortField } from 'src/services/machines';
import { antivirusStatusLabel, dash, protectionLabel } from 'src/utils/format';
import type { MachineColumnKey } from 'src/utils/machineColumns';
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, queryValue } from 'src/utils/machineQuery';

/**
 * The machine list's table: its columns, and its sort and page as they travel
 * in the URL. Pure, so the round trips are tested without mounting a QTable.
 */

/**
 * Server-side pagination state. `rowsNumber` present makes the q-table hand
 * every page/sort interaction to the page's `@request` instead of slicing its
 * rows — the server holds the fleet, the table only ever holds one page of it.
 */
export interface MachineListPagination {
  sortBy: string | null;
  descending: boolean;
  page: number;
  rowsPerPage: number;
  rowsNumber: number;
}

/** The list as it opens: freshest first, first page, default size. */
export function initialMachinePagination(): MachineListPagination {
  return {
    sortBy: 'last_seen',
    descending: true,
    page: 1,
    rowsPerPage: DEFAULT_PAGE_SIZE,
    rowsNumber: 0,
  };
}

/**
 * Sortable columns ↔ their API field: the table speaks in column names, the
 * URL and the server in field names.
 */
export const SORT_FIELD_BY_COLUMN: Record<string, MachineSortField> = {
  hostname: 'hostname',
  domain: 'domain',
  location: 'location',
  building: 'building',
  room: 'room',
  maintenance: 'maintenance_due_at',
  antivirus: 'av_product_name',
  windows_update: 'wu_pending_count',
  session: 'session_user_present',
  model: 'hw_model',
  disk: 'disk_free_percent',
  last_seen: 'last_seen',
  agent: 'agent_version',
  usage: 'usage_hours',
};

export const COLUMN_BY_SORT_FIELD = Object.fromEntries(
  Object.entries(SORT_FIELD_BY_COLUMN).map(([column, field]) => [field, column]),
) as Record<string, string>;

/** The API field the table's sort stands for, if it is a sortable column. */
export function sortFieldOf(
  p: Pick<MachineListPagination, 'sortBy'>,
): MachineSortField | undefined {
  return p.sortBy ? SORT_FIELD_BY_COLUMN[p.sortBy] : undefined;
}

/**
 * The sort and page carried by a URL, merged into the current pagination (its
 * `rowsNumber` is the server's to say, not the URL's).
 */
export function machinePaginationFromQuery(
  q: LocationQuery,
  current: MachineListPagination,
): MachineListPagination {
  const sortField = queryValue(q.sort_by);
  const sortColumn = sortField ? COLUMN_BY_SORT_FIELD[sortField] : undefined;
  const page = Number(queryValue(q.page) ?? '1');
  const pageSize = Number(queryValue(q.page_size) ?? String(DEFAULT_PAGE_SIZE));
  return {
    ...current,
    // No sort in the URL = the server's default order, freshest first — shown
    // as such rather than as "unsorted".
    sortBy: sortColumn ?? 'last_seen',
    descending: sortColumn ? queryValue(q.sort_desc) !== 'false' : true,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    rowsPerPage: PAGE_SIZE_OPTIONS.includes(pageSize) ? pageSize : DEFAULT_PAGE_SIZE,
  };
}

/** The sort and page as URL params, defaults omitted so the common URL stays short. */
export function machinePaginationToQuery(p: MachineListPagination): Record<string, string> {
  const query: Record<string, string> = {};
  const field = sortFieldOf(p);
  if (field && !(field === 'last_seen' && p.descending)) {
    query.sort_by = field;
    query.sort_desc = String(p.descending);
  }
  if (p.page > 1) query.page = String(p.page);
  if (p.rowsPerPage !== DEFAULT_PAGE_SIZE) query.page_size = String(p.rowsPerPage);
  return query;
}

/** A column's header in the reader's language. */
export function machineColumnLabel(name: string): string {
  return t(`machines.columns.${name}`);
}

/**
 * A column whose header is worded when read, not when the column is made: the
 * language may change while the list is open. An enumerable getter, so the
 * q-table's own copies of the column carry the words of the moment.
 */
function col(def: Omit<QTableColumn<Machine>, 'label'>): QTableColumn<Machine> {
  return Object.defineProperty({ ...def }, 'label', {
    enumerable: true,
    get: () => machineColumnLabel(def.name),
  }) as QTableColumn<Machine>;
}

/** Every column the list can show, in the catalogue's order. */
export const MACHINE_TABLE_COLUMNS: QTableColumn<Machine>[] = [
  col({
    name: 'hostname',
    field: 'hostname',
    align: 'left',
    sortable: true,
    classes: 'machine-name-cell',
    headerClasses: 'machine-name-cell',
  }),
  col({
    name: 'domain',
    field: 'domain',
    align: 'left',
    sortable: true,
    format: dash,
  }),
  // Sortable, and grouping is the point: a multi-site parc is read one site at
  // a time. Empty on a parc whose agents name no site.
  col({
    name: 'location',
    field: 'location',
    align: 'left',
    sortable: true,
    format: dash,
  }),
  // The console's placement, sortable so a parc reads one room at a time.
  col({
    name: 'building',
    field: 'building_name',
    align: 'left',
    sortable: true,
    format: dash,
  }),
  col({ name: 'room', field: 'room_name', align: 'left', sortable: true }),
  // Where the poste stands on its cycle, sortable by due date: the "what do
  // I do this week" column.
  col({
    name: 'maintenance',
    field: 'maintenance_state',
    align: 'center',
    sortable: true,
  }),
  // Not sortable: a string sort would put 192.168.1.10 before 192.168.1.9, and
  // an octet-aware comparator is not worth it on a column people search, not sort.
  col({
    name: 'ip_address',
    field: 'ip_address',
    align: 'left',
    format: dash,
  }),
  col({ name: 'os_version', field: 'os_version', align: 'left', format: dash }),
  // The agent's version, flagged when below the parc's reference. In the list
  // because the question it answers — "lesquels n'ont pas encore la nouvelle
  // version" — is asked of the parc, not of one poste. Sortable as a version
  // (server-side, "0.10.0" after "0.9.0"): ascending puts the stragglers on
  // top, which is the morning-after-a-deployment reading.
  // « Version de l'agent », not « Agent »: under that bare word, nobody looking
  // for the version in « Colonnes » recognised it.
  col({
    name: 'agent',
    field: 'agent_version',
    align: 'left',
    sortable: true,
  }),
  // name ≠ field like the session column below: the cell renders the product and
  // its state together, while `field` keeps a sensible sort key. Sortable because
  // grouping a mixed parc by product is exactly what this column is for.
  // The badge colour carries the overall state (`is_up_to_date`) and the tooltip
  // the signature detail — one column where there used to be three.
  col({
    name: 'antivirus',
    field: 'av_product_name',
    align: 'left',
    sortable: true,
  }),
  // Sortable, and it is the sort that matters: "show me the postes furthest
  // behind" is the whole point of the column. A null count (never reported)
  // sorts apart from a zero, which is the distinction the badge makes too.
  col({
    name: 'windows_update',
    field: 'wu_pending_count',
    align: 'center',
    sortable: true,
  }),
  // name ≠ field on purpose: the cell renders presence *and* username, while
  // `field` still gives the sort a sensible key (present / absent / unknown).
  col({
    name: 'session',
    field: 'session_user_present',
    align: 'center',
    sortable: true,
  }),
  // Hours on over the usage window, off the default layout (a campaign column).
  // Sortable: « les moins utilisés d'abord » is the reading it exists for. The
  // header names the window the server answered with (`visibleMachineColumns`).
  col({
    name: 'usage',
    field: 'usage_hours',
    align: 'right',
    sortable: true,
  }),
  // The two inventory columns the list is scanned for. The rest of the twenty-five
  // is one machine's business and stays on the fiche.
  col({
    name: 'model',
    field: 'hw_model',
    align: 'left',
    sortable: true,
    format: dash,
  }),
  // Sortable, and the sort is the point: "montre-moi les postes qui n'ont plus
  // de place" is the question this column exists for. The bar carries the
  // percentage, because that is the figure that means something.
  col({
    name: 'disk',
    field: 'system_volume_free_mb',
    align: 'left',
    sortable: true,
  }),
  col({ name: 'last_seen', field: 'last_seen', align: 'left', sortable: true }),
];

const COLUMN_BY_NAME = new Map(MACHINE_TABLE_COLUMNS.map((c) => [c.name, c]));

/**
 * Each column's header, for the « Colonnes » dialog: a getter per column, so
 * the dialog reads the words of the language shown.
 */
export const MACHINE_COLUMN_LABELS: Record<string, string> = Object.defineProperties(
  {},
  Object.fromEntries(
    MACHINE_TABLE_COLUMNS.map((c) => [
      c.name,
      { enumerable: true, get: () => machineColumnLabel(c.name) },
    ]),
  ),
);

/** The reader's layout as table columns, in their order. */
export function visibleMachineColumns(
  order: readonly MachineColumnKey[],
  usageWindowDays: number,
): QTableColumn<Machine>[] {
  return order.flatMap((name) => {
    const column = COLUMN_BY_NAME.get(name);
    if (!column) return [];
    if (name !== 'usage') return [column];
    // The usage header says which window: « 12 h » means nothing without it.
    const usage = { ...column };
    return [
      Object.defineProperty(usage, 'label', {
        enumerable: true,
        get: () => t('machines.columns.usageWindow', { days: usageWindowDays }),
      }),
    ];
  });
}

/**
 * One line: overall state, what the Security Center says of the product, and
 * the signature version — the detail the badge colour compresses.
 */
export function antivirusTooltip(m: Machine): string {
  const parts = [
    protectionLabel(m.is_up_to_date),
    antivirusStatusLabel(
      m.av_product_name,
      m.av_product_enabled,
      m.av_product_signatures_up_to_date,
    ),
  ];
  if (m.signature_version) {
    parts.push(t('machines.table.signatures', { version: m.signature_version }));
  }
  return parts.join(' · ');
}

/** The disk bar fills with what is *used*: a full disk is a full bar. */
export function usedRatio(
  m: Pick<Machine, 'system_volume_total_mb' | 'system_volume_free_mb'>,
): number {
  const total = m.system_volume_total_mb;
  const free = m.system_volume_free_mb;
  if (!total || free == null) return 0;
  return Math.min(1, Math.max(0, (total - free) / total));
}
