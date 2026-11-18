import { api } from 'boot/axios';
import { currentLocale, t, type Locale } from 'src/i18n';

/**
 * The journal of a poste: every human intervention on it, whatever the cause.
 * One list, newest first — a repair, an install, an upgrade, a maintenance
 * visit, a closed verification — rather than one per kind.
 */

export type InterventionKind =
  'maintenance' | 'verification' | 'incident' | 'software_install' | 'upgrade' | 'other';

export interface Intervention {
  id: string;
  machine_id: string;
  kind: InterventionKind | (string & {});
  title: string | null;
  /**
   * Set when the server wrote the title itself (« Maintenance non faite —
   * A101 »): the console words it from the code and its parameters, `title`
   * keeping the server's French. Absent from an older server, null on a
   * title typed by someone (an edit clears it).
   */
  title_code?: string | null;
  title_params?: Record<string, unknown> | null;
  note: string | null;
  /** The acting account's e-mail, kept as text: the entry outlives the account. */
  performed_by: string;
  /** When it happened — not when it was typed in; backdating is allowed. */
  performed_at: string;
  /** The verification request whose closing wrote this line, if any. */
  check_id?: string | null;
  /** The maintenance visit this line belongs to, if any: it holds the global note. */
  maintenance_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface InterventionList {
  items: Intervention[];
  total: number;
  page: number;
  page_size: number;
}

export interface InterventionPayload {
  kind: InterventionKind;
  title?: string | null;
  note?: string | null;
  /** ISO instant; omitted = now. */
  performed_at?: string | null;
}

/** The kinds, in the order the form offers them; each label is `interventions.kinds.<kind>`. */
export const INTERVENTION_KINDS: readonly {
  value: InterventionKind;
  icon: string;
  color: string;
}[] = [
  { value: 'incident', icon: 'report_problem', color: 'negative' },
  { value: 'software_install', icon: 'apps', color: 'primary' },
  { value: 'upgrade', icon: 'upgrade', color: 'primary' },
  { value: 'maintenance', icon: 'build', color: 'positive' },
  { value: 'verification', icon: 'fact_check', color: 'orange' },
  { value: 'other', icon: 'notes', color: 'grey-7' },
];

function isKind(kind: string): kind is InterventionKind {
  return INTERVENTION_KINDS.some((k) => k.value === kind);
}

/** A kind's label — in `locale` when given, else in the language shown; an unknown kind as is. */
export function interventionKindLabel(kind: string, locale?: Locale): string {
  if (!isKind(kind)) return kind;
  const key = `interventions.kinds.${kind}`;
  return locale ? t(key, {}, { locale }) : t(key);
}

/** The titles the server writes itself, by their code (`title_code`). */
const TITLE_CODES: Record<string, (params: Record<string, unknown>) => string> = {
  'maintenance.skipped': (params) =>
    typeof params.room === 'string' && params.room
      ? t('interventions.titles.maintenanceSkippedIn', { room: params.room })
      : t('interventions.titles.maintenanceSkipped'),
};

/**
 * A line's title in the reader's language when the server wrote it under a
 * code this console knows; otherwise as stored — typed by someone, or
 * written before the codes (plan console bilingue: old rows keep their
 * French).
 */
export function interventionTitle(
  item: Pick<Intervention, 'title' | 'title_code' | 'title_params'>,
): string | null {
  const word = item.title_code ? TITLE_CODES[item.title_code] : undefined;
  return word ? word(item.title_params ?? {}) : item.title;
}

/**
 * The title without a leading `label` followed by a dash, or null when it
 * does not start with it. Only the whole word followed by a dash: «
 * Maintenance non faite » stays. A plain hyphen counts only after a space,
 * so a compound word is not cut: « Check-up of the screen » stays whole.
 */
function withoutKind(title: string, label: string): string | null {
  if (!title.toLocaleLowerCase('fr-FR').startsWith(label.toLocaleLowerCase('fr-FR'))) return null;
  const rest = title.slice(label.length);
  const dash = /^(?:\s*[—–:]|\s+-)\s*/;
  if (rest.trim() && !dash.test(rest)) return null;
  return rest.replace(dash, '').trim();
}

/**
 * « Maintenance — A101 »: the kind, then the title — without repeating the
 * kind when the title starts with it, as the lines written before the server
 * stopped doing so do (« Maintenance — Maintenance — A101 », « Vérification —
 * Vérification »). Those lines are in French whatever the reader's language:
 * the French label is looked for too.
 */
export function interventionHeading(
  item: Pick<Intervention, 'kind' | 'title'> &
    Partial<Pick<Intervention, 'title_code' | 'title_params'>>,
): string {
  const label = interventionKindLabel(item.kind);
  let title = (interventionTitle({ title_code: null, title_params: null, ...item }) ?? '').trim();
  const stripped =
    withoutKind(title, label) ??
    (currentLocale() === 'fr' ? null : withoutKind(title, interventionKindLabel(item.kind, 'fr')));
  if (stripped !== null) title = stripped;
  return title ? t('interventions.heading', { label, title }) : label;
}

export function interventionKindIcon(kind: string): string {
  return INTERVENTION_KINDS.find((k) => k.value === kind)?.icon ?? 'notes';
}

export function interventionKindColor(kind: string): string {
  return INTERVENTION_KINDS.find((k) => k.value === kind)?.color ?? 'grey-7';
}

export async function listInterventions(
  machineId: string,
  params: { page?: number; page_size?: number } = {},
): Promise<InterventionList> {
  const { data } = await api.get<InterventionList>(`/machines/${machineId}/interventions`, {
    params,
  });
  return data;
}

export async function createIntervention(
  machineId: string,
  payload: InterventionPayload,
): Promise<Intervention> {
  const { data } = await api.post<Intervention>(`/machines/${machineId}/interventions`, payload);
  return data;
}

export async function updateIntervention(
  id: string,
  payload: Partial<InterventionPayload>,
): Promise<Intervention> {
  const { data } = await api.patch<Intervention>(`/interventions/${id}`, payload);
  return data;
}

export async function deleteIntervention(id: string): Promise<void> {
  await api.delete(`/interventions/${id}`);
}
