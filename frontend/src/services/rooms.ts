import { api } from 'boot/axios';

/**
 * Where a poste is, as the console organises it — distinct from the site the
 * agent reports (`Machine.location`). A room sits in a building, a building
 * sits on a site, and a poste whose agent names another site than its room's
 * is flagged (`Machine.location_mismatch`), never refused.
 */

export interface Building {
  id: string;
  name: string;
  /** The site, in the agents' words. null = nobody placed the building yet. */
  location: string | null;
  notes: string | null;
  room_count: number;
  machine_count: number;
  created_at: string;
  updated_at: string;
}

export interface BuildingRef {
  id: string;
  name: string;
  location: string | null;
}

export interface Room {
  id: string;
  name: string;
  building: BuildingRef | null;
  /** The room's own site — only read when it has no building. */
  location: string | null;
  /** The site the room is on: its building's, else its own. */
  effective_location: string | null;
  notes: string | null;
  /** Set on a room the directory created: its membership is the directory's. */
  ad_key: string | null;
  machine_count: number;
  /** Postes of this room whose agent names another site. */
  mismatch_count: number;
  created_at: string;
  updated_at: string;
}

export interface BuildingPayload {
  name: string;
  location?: string | null;
  notes?: string | null;
}

export interface RoomPayload {
  name: string;
  building_id?: string | null;
  location?: string | null;
  notes?: string | null;
}

/** What moving postes did, and which of them now disagree on the site. */
export interface PlacementResult {
  moved: number;
  mismatched: string[];
}

export async function listBuildings(): Promise<Building[]> {
  const { data } = await api.get<Building[]>('/buildings');
  return data;
}

export async function createBuilding(payload: BuildingPayload): Promise<Building> {
  const { data } = await api.post<Building>('/buildings', payload);
  return data;
}

export async function updateBuilding(
  id: string,
  payload: Partial<BuildingPayload>,
): Promise<Building> {
  const { data } = await api.patch<Building>(`/buildings/${id}`, payload);
  return data;
}

export async function deleteBuilding(id: string): Promise<void> {
  await api.delete(`/buildings/${id}`);
}

export async function listRooms(): Promise<Room[]> {
  const { data } = await api.get<Room[]>('/rooms');
  return data;
}

export async function getRoom(id: string): Promise<Room> {
  const { data } = await api.get<Room>(`/rooms/${id}`);
  return data;
}

export async function createRoom(payload: RoomPayload): Promise<Room> {
  const { data } = await api.post<Room>('/rooms', payload);
  return data;
}

export async function updateRoom(id: string, payload: Partial<RoomPayload>): Promise<Room> {
  const { data } = await api.patch<Room>(`/rooms/${id}`, payload);
  return data;
}

export async function deleteRoom(id: string): Promise<void> {
  await api.delete(`/rooms/${id}`);
}

/** Put postes in a room, from another room or from none. */
export async function placeMachines(
  roomId: string,
  machineIds: string[],
): Promise<PlacementResult> {
  const { data } = await api.post<PlacementResult>(`/rooms/${roomId}/machines`, {
    machine_ids: machineIds,
  });
  return data;
}

/** Take postes out of whatever room they are in. */
export async function unassignMachines(machineIds: string[]): Promise<PlacementResult> {
  const { data } = await api.post<PlacementResult>('/rooms/unassign', {
    machine_ids: machineIds,
  });
  return data;
}

/** How postes are filed: by hand, or by the directory (`ROOM_SOURCE`). */
export interface RoomConfig {
  source: 'manual' | 'ad_ou' | 'ad_location' | string;
  manual: boolean;
}

let cachedConfig: Promise<RoomConfig> | null = null;

/**
 * The server's placement mode, fetched once per session: a server setting,
 * read by every page that offers to move a poste so that none offers what the
 * backend would refuse.
 */
export function getRoomConfig(): Promise<RoomConfig> {
  cachedConfig ??= api.get<RoomConfig>('/rooms/config').then(({ data }) => data);
  return cachedConfig.catch((e: unknown) => {
    cachedConfig = null;
    throw e;
  });
}

/** What re-filing the parc from the directory did. */
export interface SyncResult {
  placed: number;
  unplaced: number;
  rooms_created: number;
}

/** Re-file every poste from what its agent last said of the directory. */
export async function syncDirectory(): Promise<SyncResult> {
  const { data } = await api.post<SyncResult>('/rooms/sync-directory');
  return data;
}

export const ROOM_SOURCE_LABELS: Record<string, string> = {
  manual: 'à la main, depuis la console',
  ad_ou: "par l'unité d'organisation de l'objet ordinateur",
  ad_location: "par l'attribut Emplacement de l'objet ordinateur",
};

/** "Bâtiment B › B12", or the room alone when it has no building. */
export function roomLabel(room: Pick<Room, 'name' | 'building'>): string {
  return room.building ? `${room.building.name} › ${room.name}` : room.name;
}

/** The notification a placement earns: what moved, and what now disagrees. */
export function placementNotification(res: PlacementResult): {
  type: 'positive' | 'warning';
  message: string;
} {
  const moved = `${res.moved} poste(s) affecté(s)`;
  if (!res.mismatched.length) return { type: 'positive', message: moved };
  return {
    type: 'warning',
    message: `${moved} — ${res.mismatched.length} dont l'agent déclare un autre emplacement que la salle`,
  };
}
