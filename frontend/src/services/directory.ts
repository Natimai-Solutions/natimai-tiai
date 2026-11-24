import { api } from 'boot/axios';

/** The verdicts on a poste (plan-lecture-annuaire.md). */
export const DIRECTORY_STATUSES = [
  'verified',
  'mismatch',
  'unknown',
  'stale',
  'contested',
] as const;
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
  /** The account is confined to some places: the parc's state is not shown. */
  restricted?: boolean;
}

/** The pending moves as they were shown: confirmed or discarded only while
 * they are still those. */
export type PendingRef = Pick<DirectoryDomain, 'pending_since' | 'pending_count'>;

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

function pendingRef(seen: PendingRef) {
  return { pending_since: seen.pending_since, pending_count: seen.pending_count };
}

export async function confirmMoves(sid: string, seen: PendingRef): Promise<{ moved: number }> {
  const { data } = await api.post<{ moved: number }>(
    `/directory/domains/${encodeURIComponent(sid)}/confirm`,
    pendingRef(seen),
  );
  return data;
}

export async function discardMoves(sid: string, seen: PendingRef): Promise<void> {
  await api.post(`/directory/domains/${encodeURIComponent(sid)}/discard`, pendingRef(seen));
}

/** Forget a domain the server read (rebuilt under another SID). */
export async function forgetDomain(sid: string): Promise<void> {
  await api.delete(`/directory/domains/${encodeURIComponent(sid)}`);
}
