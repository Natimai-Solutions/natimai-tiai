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
