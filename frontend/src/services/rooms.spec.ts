import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import { apiErrorMessage } from './errors';
import {
  createRoom,
  getRoomConfig,
  getRoomCreation,
  syncDirectory,
  syncPreviewMessage,
  deleteBuilding,
  listRooms,
  placeMachines,
  placementNotification,
  roomLabel,
  syncNotification,
  unassignMachines,
  updateBuilding,
} from './rooms';

describe('rooms service', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.patch).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('lists rooms in one call', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    await listRooms();
    expect(api.get).toHaveBeenCalledWith('/rooms');
  });

  it('creates a room with its building', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    await createRoom({ name: 'B12', building_id: 'b-1' });
    expect(api.post).toHaveBeenCalledWith('/rooms', { name: 'B12', building_id: 'b-1' });
  });

  it('patches and deletes buildings by id', async () => {
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    vi.mocked(api.delete).mockResolvedValue({ data: undefined });
    await updateBuilding('b-1', { location: 'Taravao' });
    await deleteBuilding('b-1');
    expect(api.patch).toHaveBeenCalledWith('/buildings/b-1', { location: 'Taravao' });
    expect(api.delete).toHaveBeenCalledWith('/buildings/b-1');
  });

  it('places and unassigns postes with snake_case ids', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { moved: 2, mismatched: [] } });
    await placeMachines('r-1', ['m-1', 'm-2']);
    await unassignMachines(['m-3']);
    expect(api.post).toHaveBeenNthCalledWith(1, '/rooms/r-1/machines', {
      machine_ids: ['m-1', 'm-2'],
    });
    expect(api.post).toHaveBeenNthCalledWith(2, '/rooms/unassign', { machine_ids: ['m-3'] });
  });
});

describe('room config and directory sync', () => {
  it('reads the placement mode once and posts a sync', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { source: 'ad_ou', manual: false } });
    vi.mocked(api.post).mockResolvedValue({
      data: { placed: 3, unplaced: 1, rooms_created: 2 },
    });
    expect(await getRoomConfig()).toEqual({ source: 'ad_ou', manual: false });
    expect(await getRoomConfig()).toEqual({ source: 'ad_ou', manual: false });
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(await syncDirectory()).toEqual({ placed: 3, unplaced: 1, rooms_created: 2 });
    expect(api.post).toHaveBeenCalledWith('/rooms/sync-directory', undefined, undefined);
  });

  it('reads the placement mode again after a failed read, not the failure', async () => {
    // A fresh module: the test above cached a successful read in this one.
    vi.resetModules();
    const { api: freshApi } = await import('boot/axios');
    const { getRoomConfig: freshGetRoomConfig } = await import('./rooms');
    vi.mocked(freshApi.get)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue({ data: { source: 'manual', manual: true } });
    await expect(freshGetRoomConfig()).rejects.toThrow('network');
    expect(await freshGetRoomConfig()).toEqual({ source: 'manual', manual: true });
    expect(freshApi.get).toHaveBeenCalledTimes(2);
  });

  it('asks a dry run with dry_run=true (C9)', async () => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.post).mockResolvedValue({ data: { placed: 0 } });
    await syncDirectory(true);
    expect(api.post).toHaveBeenCalledWith('/rooms/sync-directory', undefined, {
      params: { dry_run: true },
    });
  });

  it('turns the dry run into the question asked before the real run', () => {
    const msg = syncPreviewMessage({
      placed: 20,
      unplaced: 3,
      moved_out: 7,
      rooms_created: 2,
      undecided: 0,
      undecided_rooms: [],
    });
    expect(msg).toContain('7 poste(s) changeront de salle, 2 salle(s) seront créées.');
    expect(msg).toContain('Dont 3 retiré(s) de toute salle.');
    expect(msg).toContain('Lancer la resynchronisation ?');
  });

  it('reads what the scope lets create', async () => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.get).mockResolvedValue({ data: { rooms: true, buildings: false } });
    expect(await getRoomCreation()).toEqual({ rooms: true, buildings: false });
    expect(api.get).toHaveBeenCalledWith('/rooms/creation');
  });
});

describe('room errors (C11, item 12)', () => {
  const err = (code: string, details: Record<string, unknown>) => ({
    response: { data: { error: { code, message: 'x', details } } },
  });

  it('names the groups whose scope holds the place', () => {
    expect(apiErrorMessage(err('room.in_group_scope', { groups: ['Tech A', 'Profs'] }))).toBe(
      'Le périmètre d’un groupe nomme ce lieu : retirez-le du groupe avant de le supprimer (groupe(s) : « Tech A », « Profs »)',
    );
  });

  it('names the postes of another room in a visit', () => {
    expect(
      apiErrorMessage(err('maintenance.items.not_in_room', { hostnames: ['PC-1', 'PC-2'] })),
    ).toBe('Ces postes ne sont pas dans la salle de la séance : PC-1, PC-2');
  });
});

describe('roomLabel', () => {
  it('prefixes the building when there is one', () => {
    expect(
      roomLabel({ name: 'B12', building: { id: 'b', name: 'Bâtiment B', location: null } }),
    ).toBe('Bâtiment B › B12');
    expect(roomLabel({ name: 'Réserve', building: null })).toBe('Réserve');
  });

  it('names the site when two sites have a building of that name (item 14)', async () => {
    const b1 = { id: 'b1', name: 'Bâtiment B', location: 'Lycée A' };
    const b2 = { id: 'b2', name: 'bâtiment b', location: 'Lycée B' };
    const c = { id: 'c', name: 'Bâtiment C', location: 'Lycée A' };
    const rooms = [
      { name: 'B12', building: b1 },
      { name: 'B12', building: b2 },
      { name: 'C1', building: c },
    ];
    expect(roomLabel(rooms[0]!, rooms)).toBe('Lycée A › Bâtiment B › B12');
    expect(roomLabel(rooms[1]!, rooms)).toBe('Lycée B › bâtiment b › B12');
    expect(roomLabel(rooms[2]!, rooms)).toBe('Bâtiment C › C1');
    // Without the list: what the last listRooms() taught.
    vi.mocked(api.get).mockResolvedValue({ data: rooms });
    await listRooms();
    expect(roomLabel(rooms[0]!)).toBe('Lycée A › Bâtiment B › B12');
    expect(roomLabel(rooms[2]!)).toBe('Bâtiment C › C1');
  });
});

describe('syncNotification', () => {
  const done = { placed: 3, unplaced: 1, rooms_created: 2 };

  it('is the plain count when every poste was decided — or the server says nothing of it', () => {
    const plain = {
      type: 'positive',
      message: '3 poste(s) rangé(s), 1 retiré(s), 2 salle(s) créée(s)',
    };
    // An older server sends neither field.
    expect(syncNotification(done)).toEqual(plain);
    expect(syncNotification({ ...done, undecided: 0, undecided_rooms: [] })).toEqual(plain);
  });

  it('warns, names the rooms and says what settles them when postes were left undecided', () => {
    const n = syncNotification({ ...done, undecided: 7, undecided_rooms: ['B12', 'CDI'] });

    expect(n.type).toBe('warning');
    expect(n.message).toBe(
      '3 poste(s) rangé(s), 1 retiré(s), 2 salle(s) créée(s) — 7 poste(s) laissé(s) en place',
    );
    expect(n.caption).toContain('« B12 », « CDI »');
    expect(n.caption).toContain('majoritaire');
    expect(n.caption).toMatch(/Renommez la salle/);
    expect(n.caption).toMatch(/puis resynchronisez/);
    // Names to act on: the notification stays until closed.
    expect(n.timeout).toBe(0);
    expect(n.actions).toEqual([{ label: 'Fermer', color: 'white' }]);
  });

  it('names five rooms at most, and says there are others', () => {
    const rooms = Array.from({ length: 20 }, (_, i) => `S${i + 1}`);
    const n = syncNotification({ ...done, undecided: 60, undecided_rooms: rooms });

    expect(n.caption).toContain("« S1 », « S2 », « S3 », « S4 », « S5 » et d'autres salles");
    expect(n.caption).not.toContain('S6');
  });

  it('still warns when the server counts undecided postes without naming a room', () => {
    const n = syncNotification({ ...done, undecided: 2 });

    expect(n.type).toBe('warning');
    expect(n.caption).toMatch(/^Aucune unité d'organisation n'est majoritaire\. /);
  });
});

describe('placementNotification', () => {
  it('is positive when every poste agrees on the site', () => {
    expect(placementNotification({ moved: 3, mismatched: [] })).toEqual({
      type: 'positive',
      message: '3 poste(s) affecté(s)',
    });
  });

  it('warns, and counts, when some disagree', () => {
    const n = placementNotification({ moved: 3, mismatched: ['a'] });
    expect(n.type).toBe('warning');
    expect(n.message).toContain('1 dont');
  });
});
