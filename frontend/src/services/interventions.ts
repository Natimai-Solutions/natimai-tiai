import { api } from 'boot/axios';

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

export const INTERVENTION_KINDS: readonly {
  value: InterventionKind;
  label: string;
  icon: string;
  color: string;
}[] = [
  { value: 'incident', label: 'Panne / incident', icon: 'report_problem', color: 'negative' },
  { value: 'software_install', label: 'Installation logicielle', icon: 'apps', color: 'primary' },
  { value: 'upgrade', label: 'Mise à niveau', icon: 'upgrade', color: 'primary' },
  { value: 'maintenance', label: 'Maintenance', icon: 'build', color: 'positive' },
  { value: 'verification', label: 'Vérification', icon: 'fact_check', color: 'orange' },
  { value: 'other', label: 'Autre', icon: 'notes', color: 'grey-7' },
];

export function interventionKindLabel(kind: string): string {
  return INTERVENTION_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

/**
 * « Maintenance — A101 »: the kind, then the title — without repeating the
 * kind when the title starts with it, as the lines written before the server
 * stopped doing so do (« Maintenance — Maintenance — A101 », « Vérification —
 * Vérification »).
 */
export function interventionHeading(item: Pick<Intervention, 'kind' | 'title'>): string {
  const label = interventionKindLabel(item.kind);
  let title = (item.title ?? '').trim();
  if (title.toLocaleLowerCase('fr-FR').startsWith(label.toLocaleLowerCase('fr-FR'))) {
    // Only the whole word followed by a dash: « Maintenance non faite » stays.
    const rest = title.slice(label.length);
    if (!rest.trim() || /^\s*[—–:-]/.test(rest)) {
      title = rest.replace(/^\s*[—–:-]\s*/, '').trim();
    }
  }
  return title ? `${label} — ${title}` : label;
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
