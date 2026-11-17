import { api } from 'boot/axios';

/**
 * Maintenance: a cycle and an owner resolved over three levels (the poste,
 * its room, the parc), what is due for whom, and the visits recorded.
 */

export type MaintenanceState = 'excluded' | 'overdue' | 'due_soon' | 'ok';
export type Origin = 'machine' | 'room' | 'global';

export interface UserRef {
  id: string;
  name: string;
  /** false for an account deactivated since it was named (absent: active). */
  active?: boolean;
}

export interface Resolved {
  cycle_days: number;
  cycle_origin: Origin;
  owner: UserRef | null;
  owner_origin: Origin;
  last_maintenance_at: string | null;
  due_at: string | null;
  state: MaintenanceState;
}

export interface MachineMaintenance {
  /** The poste's own overrides; null = inherit. */
  maintenance_cycle_days: number | null;
  maintenance_owner: UserRef | null;
  resolved: Resolved;
}

export interface RoomMaintenance {
  maintenance_cycle_days: number | null;
  maintenance_owner: UserRef | null;
  effective_cycle_days: number;
  effective_owner: UserRef | null;
  /**
   * Where each effective value comes from. The room's own owner, deactivated
   * or out of reach, counts as none: the parc's default applies.
   */
  effective_cycle_origin?: 'room' | 'global';
  effective_owner_origin?: 'room' | 'global';
}

export interface MaintenanceSettingsPayload {
  /** null inherits, 0 excludes. */
  maintenance_cycle_days?: number | null;
  /** null inherits — a transfer is setting it. */
  maintenance_owner_id?: string | null;
}

export interface DueMachine {
  id: string;
  hostname: string | null;
  location: string | null;
  room_name: string | null;
  building_name: string | null;
  last_maintenance_at: string | null;
  due_at: string | null;
  state: MaintenanceState;
  owner: UserRef | null;
}

export interface DueRoom {
  /** The room's id. */
  id: string;
  /**
   * The group's own key: a room is one group for the postes following its
   * owner and cycle, and one more per (owner, cycle) its postes override it
   * with.
   */
  key?: string;
  /**
   * 'room': the postes following the room's owner and cycle — taking the
   * group sets the room's owner. 'machine': postes that override them —
   * taking the group sets those postes' own owner.
   */
  level?: 'room' | 'machine';
  name: string;
  building_name: string | null;
  location: string | null;
  owner: UserRef | null;
  cycle_days: number;
  total: number;
  overdue: number;
  due_soon: number;
  excluded: number;
  next_due_at: string | null;
  machines: DueMachine[];
}

export interface Due {
  rooms: DueRoom[];
  /** Postes in no room, one by one. */
  machines: DueMachine[];
  overdue: number;
  due_soon: number;
}

export interface SessionItem {
  intervention_id: string;
  machine_id: string;
  hostname: string | null;
  note: string | null;
}

export interface MaintenanceSession {
  id: string;
  room_id: string | null;
  room_name: string | null;
  performed_by: string;
  performed_at: string;
  note: string | null;
  /** The postes it still maintains: its remaining maintenance lines. */
  machine_count: number;
  items: SessionItem[];
  /** Postes left out, with why (and lines turned since into another kind). */
  skipped?: SessionItem[];
  /**
   * Part of the visit lies beyond the reader's scope: its other postes, and —
   * when the room is not the reader's either — the room and the global note,
   * which come back null.
   */
  partial?: boolean;
}

export interface SessionList {
  items: MaintenanceSession[];
  total: number;
  page: number;
  page_size: number;
}

export interface SessionPayload {
  room_id?: string | null;
  performed_at?: string | null;
  note?: string | null;
  items: { machine_id: string; note?: string | null }[];
  /** Postes not done, with why: written to their own journal, cycle untouched. */
  skipped?: { machine_id: string; note: string }[];
}

/** Something to do now: overdue or due soon. */
export function isDue(state: string | null | undefined): boolean {
  return state === 'overdue' || state === 'due_soon';
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** A deadline as a date alone, in the browser's time zone. */
export function dueDate(value: string): string {
  return new Date(value).toLocaleDateString('fr-FR');
}

/**
 * A due date as the technician wants it read (audit U22): how long it has been
 * overdue when it has passed, the day it falls due otherwise — never to the
 * second.
 */
export function dueLabel(dueAt: string | null, now: Date = new Date()): string {
  if (!dueAt) return '';
  const due = new Date(dueAt);
  const late = Math.floor((now.getTime() - due.getTime()) / DAY_MS);
  if (due.getTime() <= now.getTime()) {
    if (late < 1) return "en retard depuis aujourd'hui";
    return `en retard depuis ${late} jour${late > 1 ? 's' : ''}`;
  }
  return `échéance le ${dueDate(dueAt)}`;
}

export const MAINTENANCE_STATES: Record<MaintenanceState, { label: string; color: string }> = {
  overdue: { label: 'En retard', color: 'negative' },
  due_soon: { label: 'À échéance', color: 'orange' },
  ok: { label: 'À jour', color: 'positive' },
  excluded: { label: 'Exclu', color: 'grey-6' },
};

export function maintenanceStateLabel(state: string | null | undefined): string {
  return state ? (MAINTENANCE_STATES[state as MaintenanceState]?.label ?? state) : '—';
}

export function maintenanceStateColor(state: string | null | undefined): string {
  return state ? (MAINTENANCE_STATES[state as MaintenanceState]?.color ?? 'grey') : 'grey';
}

export const ORIGIN_LABELS: Record<Origin, string> = {
  machine: 'propre au poste',
  room: 'hérité de la salle',
  global: 'défaut du parc',
};

/** "90 jours (hérité de la salle)", or "exclu" for a zero cycle. */
export function cycleLabel(days: number, origin: Origin): string {
  const from = ORIGIN_LABELS[origin];
  return days > 0 ? `${days} jours (${from})` : `exclu de la maintenance (${from})`;
}

export async function getMachineMaintenance(machineId: string): Promise<MachineMaintenance> {
  const { data } = await api.get<MachineMaintenance>(`/machines/${machineId}/maintenance`);
  return data;
}

export async function updateMachineMaintenance(
  machineId: string,
  payload: MaintenanceSettingsPayload,
): Promise<MachineMaintenance> {
  const { data } = await api.patch<MachineMaintenance>(
    `/machines/${machineId}/maintenance`,
    payload,
  );
  return data;
}

export async function getRoomMaintenance(roomId: string): Promise<RoomMaintenance> {
  const { data } = await api.get<RoomMaintenance>(`/rooms/${roomId}/maintenance`);
  return data;
}

export async function updateRoomMaintenance(
  roomId: string,
  payload: MaintenanceSettingsPayload,
): Promise<RoomMaintenance> {
  const { data } = await api.patch<RoomMaintenance>(`/rooms/${roomId}/maintenance`, payload);
  return data;
}

/**
 * Who the maintenance can be given to: the accounts the server accepts as
 * owner of this poste, of this room or — with neither — of the parc by
 * default. Narrower than `/checks/assignable-users`, which lists whoever may
 * read a check and left the save to refuse most of them.
 */
export async function listAssignableOwners(
  level: { machineId?: string | null | undefined; roomId?: string | null | undefined } = {},
): Promise<UserRef[]> {
  const params = level.machineId
    ? { machine_id: level.machineId }
    : level.roomId
      ? { room_id: level.roomId }
      : null;
  const { data } = await api.get<UserRef[]>(
    '/maintenance/assignable-owners',
    params ? { params } : undefined,
  );
  return data;
}

/** What is due: for `owner` = 'me', 'none', an account id, or everybody when omitted. */
export async function getDue(owner?: string): Promise<Due> {
  const { data } = await api.get<Due>('/maintenance/due', { params: owner ? { owner } : {} });
  return data;
}

export async function recordSession(payload: SessionPayload): Promise<MaintenanceSession> {
  const { data } = await api.post<MaintenanceSession>('/maintenance', payload);
  return data;
}

/** More postes of a visit already recorded — its next part. */
export async function addSessionLines(
  id: string,
  lines: Pick<SessionPayload, 'items' | 'skipped'>,
): Promise<MaintenanceSession> {
  const { data } = await api.post<MaintenanceSession>(`/maintenance/${id}/lines`, lines);
  return data;
}

/**
 * Lines (done and left out) per request. The server takes 1,000 of each, and
 * Caddy 8 MB a body; a note may hold 5,000 characters, so a part of 250 stays
 * under both whatever was typed.
 */
export const SESSION_PART_SIZE = 250;

/** How far a visit sent in parts got: kept by the caller to resume after a failure. */
export interface SessionProgress {
  /** The visit, once its first part is recorded. */
  sessionId: string | null;
  /** Lines recorded so far, done first then left out, in payload order. */
  sent: number;
  total: number;
}

export function sessionProgress(payload: SessionPayload): SessionProgress {
  return { sessionId: null, sent: 0, total: payload.items.length + (payload.skipped?.length ?? 0) };
}

/**
 * Record a visit of any size as one visit (audit T30): the first part creates
 * it with the date and the global note, the next ones are added to it. Done
 * postes go first, so the part that creates the visit carries one whenever
 * there is any. `progress` moves as each part is recorded: on a failure the
 * caller keeps it and calls again with the same payload to send the rest —
 * a part the server recorded but whose answer was lost is passed over there.
 */
export async function recordSessionInParts(
  payload: SessionPayload,
  progress: SessionProgress = sessionProgress(payload),
  size: number = SESSION_PART_SIZE,
): Promise<MaintenanceSession> {
  const lines = [
    ...payload.items.map((line) => ({ done: true, line })),
    ...(payload.skipped ?? []).map((line) => ({ done: false, line })),
  ];
  let last: MaintenanceSession | null = null;
  while (progress.sessionId === null || progress.sent < lines.length) {
    const part = lines.slice(progress.sent, progress.sent + size);
    const items = part.filter((p) => p.done).map((p) => p.line);
    const skipped = part
      .filter((p) => !p.done)
      .map((p) => p.line as { machine_id: string; note: string });
    if (progress.sessionId === null) {
      last = await recordSession({ ...payload, items, skipped });
      progress.sessionId = last.id;
    } else {
      last = await addSessionLines(progress.sessionId, { items, skipped });
    }
    progress.sent += part.length;
  }
  return last ?? getSession(progress.sessionId);
}

export async function listSessions(
  params: { room_id?: string; machine_id?: string; page?: number; page_size?: number } = {},
): Promise<SessionList> {
  const { data } = await api.get<SessionList>('/maintenance', { params });
  return data;
}

export async function getSession(id: string): Promise<MaintenanceSession> {
  const { data } = await api.get<MaintenanceSession>(`/maintenance/${id}`);
  return data;
}

/**
 * Remove a visit recorded by mistake, with every journal line it wrote; the
 * postes' last maintenance goes back to what their journal then says.
 */
export async function deleteSession(id: string): Promise<void> {
  await api.delete(`/maintenance/${id}`);
}

/** « Responsable » as a level shows it: the name, and « (désactivé) » when it is. */
export function ownerLabel(owner: UserRef | null | undefined): string {
  if (!owner) return '';
  return owner.active === false ? `${owner.name} (désactivé)` : owner.name;
}
