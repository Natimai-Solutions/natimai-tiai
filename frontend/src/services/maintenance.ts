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
  id: string;
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
  machine_count: number;
  items: SessionItem[];
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

/** What is due: for `owner` = 'me', 'none', an account id, or everybody when omitted. */
export async function getDue(owner?: string): Promise<Due> {
  const { data } = await api.get<Due>('/maintenance/due', { params: owner ? { owner } : {} });
  return data;
}

export async function recordSession(payload: SessionPayload): Promise<MaintenanceSession> {
  const { data } = await api.post<MaintenanceSession>('/maintenance', payload);
  return data;
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
