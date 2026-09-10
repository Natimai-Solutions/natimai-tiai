import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  createRoom,
  getRoomConfig,
  syncDirectory,
  deleteBuilding,
  listRooms,
  placeMachines,
  placementNotification,
  roomLabel,
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
    expect(api.post).toHaveBeenCalledWith('/rooms/sync-directory');
  });
});

describe('roomLabel', () => {
  it('prefixes the building when there is one', () => {
    expect(
      roomLabel({ name: 'B12', building: { id: 'b', name: 'Bâtiment B', location: null } }),
    ).toBe('Bâtiment B › B12');
    expect(roomLabel({ name: 'Réserve', building: null })).toBe('Réserve');
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
