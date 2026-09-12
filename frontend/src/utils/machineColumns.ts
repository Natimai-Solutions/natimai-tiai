/**
 * Which columns the machine list shows, and in what order — the one thing the
 * page remembers on the account rather than in the URL: a search is shared by
 * pasting a link, a layout is personal and follows the operator from one
 * workstation to the next (`User.preferences`).
 */

/** The key under which the list stores its layout in the account's preferences. */
export const PREF_MACHINE_COLUMNS = 'machines_columns';

/** Every column the list can show, in its default order. */
export const MACHINE_COLUMN_KEYS = [
  'hostname',
  'domain',
  'location',
  'building',
  'room',
  'maintenance',
  'ip_address',
  'os_version',
  'agent',
  'antivirus',
  'windows_update',
  'session',
  'model',
  'disk',
  'last_seen',
] as const;

export type MachineColumnKey = (typeof MACHINE_COLUMN_KEYS)[number];

/**
 * The column that cannot be hidden: it carries the link to the fiche and the
 * online dot, and a list of postes without their names is not a list.
 */
export const MANDATORY_MACHINE_COLUMN: MachineColumnKey = 'hostname';

/** The default layout, the columns in catalogue order. */
export const DEFAULT_MACHINE_COLUMNS: MachineColumnKey[] = [...MACHINE_COLUMN_KEYS];

function isColumnKey(value: unknown): value is MachineColumnKey {
  return typeof value === 'string' && (MACHINE_COLUMN_KEYS as readonly string[]).includes(value);
}

/**
 * A stored layout made safe: unknown names dropped (a column may have been
 * renamed since), duplicates collapsed, the mandatory column forced to the
 * front. Anything that is not a usable list falls back on the default — an
 * empty or corrupt preference must never blank the table.
 */
export function resolveMachineColumns(saved: unknown): MachineColumnKey[] {
  if (!Array.isArray(saved)) return [...DEFAULT_MACHINE_COLUMNS];
  const seen = new Set<MachineColumnKey>();
  const columns: MachineColumnKey[] = [];
  for (const value of saved) {
    if (!isColumnKey(value) || seen.has(value)) continue;
    seen.add(value);
    columns.push(value);
  }
  if (!columns.length) return [...DEFAULT_MACHINE_COLUMNS];
  return [
    MANDATORY_MACHINE_COLUMN,
    ...columns.filter((column) => column !== MANDATORY_MACHINE_COLUMN),
  ];
}

/** Whether a layout is the default one — then nothing is worth storing. */
export function isDefaultMachineColumns(columns: readonly string[]): boolean {
  return (
    columns.length === DEFAULT_MACHINE_COLUMNS.length &&
    columns.every((column, i) => column === DEFAULT_MACHINE_COLUMNS[i])
  );
}
