import { api } from 'boot/axios';
import { t } from 'src/i18n';

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
  /** Maintenance: the room's own settings (null = inherit), what they resolve to, and where its postes stand. */
  maintenance_cycle_days: number | null;
  maintenance_owner_name: string | null;
  effective_cycle_days: number;
  effective_owner_name: string | null;
  maintenance_overdue: number;
  maintenance_due_soon: number;
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

/**
 * Building names held by several buildings — « Bâtiment B » on two sites —
 * as last read: where `roomLabel` must name the site too. Learnt from every
 * list of buildings or rooms read, so that every room picker built from
 * `listRooms()` says it without each caller passing the whole list.
 */
const homonymousBuildings = new Set<string>();

function learnBuildings(buildings: readonly (BuildingRef | null)[]): void {
  // Each list read is the whole current state: a building renamed since is
  // forgotten rather than kept as an homonym for good.
  homonymousBuildings.clear();
  const ids = new Map<string, Set<string>>();
  for (const b of buildings) {
    if (!b) continue;
    const key = b.name.toLocaleLowerCase('fr-FR');
    if (!ids.has(key)) ids.set(key, new Set());
    ids.get(key)!.add(b.id);
  }
  for (const [name, set] of ids) {
    if (set.size > 1) homonymousBuildings.add(name);
  }
}

export async function listBuildings(): Promise<Building[]> {
  const { data } = await api.get<Building[]>('/buildings');
  learnBuildings(data);
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
  learnBuildings(data.map((r) => r.building));
  return data;
}

/** What the account's scope lets it create: the page hides the rest. */
export interface RoomCreation {
  rooms: boolean;
  buildings: boolean;
}

export async function getRoomCreation(): Promise<RoomCreation> {
  const { data } = await api.get<RoomCreation>('/rooms/creation');
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
  source: 'manual' | 'ad_ou' | 'ad_location' | (string & {});
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
  /** Postes that leave the room they were in, for another or for none. */
  moved_out?: number;
  rooms_created: number;
  /**
   * Postes left where they were: the room made by hand that bears their name
   * is claimed by several directory keys, none with a majority. Absent from an
   * older server.
   */
  undecided?: number;
  /** Those rooms, by name (the server sends 20 at most). */
  undecided_rooms?: string[];
}

/** How many undecided rooms the notification names before « et d'autres ». */
const UNDECIDED_ROOMS_NAMED = 5;

/**
 * The notification a re-sync earns. Postes left undecided turn it into a
 * warning that stays, names the rooms and says what settles them.
 */
export function syncNotification(res: SyncResult): {
  type: 'positive' | 'warning';
  message: string;
  caption?: string;
  timeout?: number;
  actions?: { label: string; color: string }[];
} {
  const message = t('rooms.sync.done', {
    placed: res.placed,
    unplaced: res.unplaced,
    created: res.rooms_created,
  });
  const undecided = res.undecided ?? 0;
  if (!undecided) return { type: 'positive', message };
  const rooms = res.undecided_rooms ?? [];
  const named = rooms
    .slice(0, UNDECIDED_ROOMS_NAMED)
    .map((name) => t('rooms.sync.quoted', { name }))
    .join(t('rooms.sync.listSeparator'));
  const names =
    rooms.length > UNDECIDED_ROOMS_NAMED ? t('rooms.sync.namesAndOthers', { names: named }) : named;
  return {
    type: 'warning',
    message: t('rooms.sync.undecided', { message, count: undecided }, undecided),
    caption: rooms.length ? t('rooms.sync.captionFor', { names }) : t('rooms.sync.caption'),
    // Names to act on: it stays until read.
    timeout: 0,
    actions: [{ label: t('rooms.actions.close'), color: 'white' }],
  };
}

/**
 * Re-file every poste from what its agent last said of the directory. With
 * `dryRun`, what it would do — nothing written: the console shows it and asks
 * before the real run.
 */
export async function syncDirectory(dryRun = false): Promise<SyncResult> {
  const { data } = await api.post<SyncResult>(
    '/rooms/sync-directory',
    undefined,
    dryRun ? { params: { dry_run: true } } : undefined,
  );
  return data;
}

/** The confirmation a re-sync asks, from its dry run. */
export function syncPreviewMessage(res: SyncResult): string {
  const moved = res.moved_out ?? 0;
  const lines = [t('rooms.sync.previewMoved', { moved, created: res.rooms_created })];
  if (res.unplaced) lines.push(t('rooms.sync.previewUnplaced', { count: res.unplaced }));
  if (res.undecided) {
    lines.push(t('rooms.sync.previewUndecided', { count: res.undecided }, res.undecided));
  }
  lines.push(t('rooms.sync.previewAsk'));
  return lines.join(' ');
}

const ROOM_SOURCES = ['manual', 'ad_ou', 'ad_location'];

/** How postes are filed, after « Les postes sont rangés »; an unknown mode as is. */
export function roomSourceLabel(source: string): string {
  return ROOM_SOURCES.includes(source) ? t(`rooms.sources.${source}`) : source;
}

/**
 * "Bâtiment B › B12", or the room alone when it has no building — and
 * "Lycée A › Bâtiment B › B12" when another site has a « Bâtiment B » too,
 * which a picker listing both would otherwise show as twins. `rooms`: the
 * list to tell apart; omitted, the buildings last read by `listRooms` or
 * `listBuildings`.
 */
export function roomLabel(
  room: Pick<Room, 'name' | 'building'>,
  rooms?: readonly Pick<Room, 'building'>[],
): string {
  const b = room.building;
  if (!b) return room.name;
  const name = b.name.toLocaleLowerCase('fr-FR');
  const homonymous = rooms
    ? rooms.some(
        (r) =>
          r.building &&
          r.building.id !== b.id &&
          r.building.name.toLocaleLowerCase('fr-FR') === name,
      )
    : homonymousBuildings.has(name);
  return homonymous && b.location
    ? `${b.location} › ${b.name} › ${room.name}`
    : `${b.name} › ${room.name}`;
}

/** The notification a placement earns: what moved, and what now disagrees. */
export function placementNotification(res: PlacementResult): {
  type: 'positive' | 'warning';
  message: string;
} {
  const moved = t('rooms.placement.moved', { count: res.moved }, res.moved);
  if (!res.mismatched.length) return { type: 'positive', message: moved };
  return {
    type: 'warning',
    message: t(
      'rooms.placement.mismatch',
      { moved, count: res.mismatched.length },
      res.mismatched.length,
    ),
  };
}
