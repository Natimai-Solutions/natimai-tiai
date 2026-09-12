/**
 * Shared shapes for the machine detail cards.
 *
 * Kept in a plain module rather than in one of the components: `<script setup>`
 * cannot export a type, and every card that renders a label/value list needs
 * the same one.
 */

/** One label/value line of a detail card. */
export interface InfoRow {
  label: string;
  /** Numbers are allowed through unformatted — a day count, a slot count. */
  value: string | number;
}

/**
 * The tabs of the machine detail page. Named after what each answers rather
 * than after the cards it holds: « Antivirus » and not « Defender », because
 * on a poste running ESET the Defender card is the smaller half of the tab.
 */
export type MachineTab =
  'identity' | 'antivirus' | 'windows_update' | 'hardware' | 'software' | 'commands' | 'history';

export const MACHINE_TABS: readonly MachineTab[] = [
  'identity',
  'antivirus',
  'windows_update',
  'hardware',
  'software',
  'commands',
  'history',
];

export const DEFAULT_MACHINE_TAB: MachineTab = 'identity';

/** Server-side pagination state, as QTable holds it. */
export interface TablePagination {
  page: number;
  rowsPerPage: number;
  rowsNumber: number;
}

/**
 * Rows per page for the two histories on the machine detail page.
 *
 * Both are paginated by the server: a poste that has been running for a year
 * holds far more than a page of either, and showing the first rows as if they
 * were all of it is what this replaced.
 */
export const DEFAULT_PAGE_SIZE = 10;
