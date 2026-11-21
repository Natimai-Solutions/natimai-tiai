import { api } from 'boot/axios';

/** The verdicts on a poste (plan-lecture-annuaire.md). */
export const DIRECTORY_STATUSES = ['verified', 'mismatch', 'unknown', 'stale'] as const;
export type DirectoryStatus = (typeof DIRECTORY_STATUSES)[number];

export function isDirectoryStatus(value: string): value is DirectoryStatus {
  return (DIRECTORY_STATUSES as readonly string[]).includes(value);
}

export interface DirectoryReader {
  id: string;
  hostname: string | null;
  domain: string | null;
  since: string | null;
  last_seen: string;
}

export interface PendingMove {
  machine_id: string;
  hostname: string | null;
  from_room: string | null;
  to_room: string | null;
}

export interface DirectoryDomain {
  sid: string;
  name: string;
  netbios_name: string;
  last_read_at: string | null;
  last_reader: string | null;
  objects_read: number;
  disagreement_at: string | null;
  disagreement: { object_guid: string; sam: string }[];
  pending_count: number;
  pending_since: string | null;
  pending_moves: PendingMove[];
  readers: DirectoryReader[];
}

export interface DirectoryState {
  mode: 'off' | 'relay';
  sync_minutes: number;
  stale_hours: number;
  confirm_moves: number;
  room_source: string;
  domains: DirectoryDomain[];
  readers_waiting: DirectoryReader[];
  domains_without_reader: string[];
  status_counts: Record<string, number>;
}

export async function getDirectoryState(): Promise<DirectoryState> {
  const { data } = await api.get<DirectoryState>('/directory');
  return data;
}

export async function designateReader(machineId: string): Promise<DirectoryReader> {
  const { data } = await api.post<DirectoryReader>(`/directory/readers/${machineId}`);
  return data;
}

export async function revokeReader(machineId: string): Promise<void> {
  await api.delete(`/directory/readers/${machineId}`);
}

export async function confirmMoves(sid: string): Promise<{ moved: number }> {
  const { data } = await api.post<{ moved: number }>(
    `/directory/domains/${encodeURIComponent(sid)}/confirm`,
  );
  return data;
}

export async function discardMoves(sid: string): Promise<void> {
  await api.post(`/directory/domains/${encodeURIComponent(sid)}/discard`);
}
