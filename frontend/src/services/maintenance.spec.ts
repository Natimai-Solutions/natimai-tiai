import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  cycleLabel,
  deleteSession,
  dueLabel,
  isDue,
  getDue,
  listAssignableOwners,
  maintenanceStateLabel,
  ownerLabel,
  recordSession,
  recordSessionInParts,
  SESSION_PART_SIZE,
  sessionProgress,
  updateMachineMaintenance,
  updateRoomMaintenance,
} from './maintenance';

describe('maintenance service', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.patch).mockReset();
  });

  it('asks what is due for one owner, or for everybody', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: {} });
    await getDue('me');
    await getDue();
    expect(api.get).toHaveBeenNthCalledWith(1, '/maintenance/due', { params: { owner: 'me' } });
    expect(api.get).toHaveBeenNthCalledWith(2, '/maintenance/due', { params: {} });
  });

  it('asks who may own the maintenance of a poste, of a room, or of the parc', async () => {
    const owners = [{ id: 'u-1', name: 'Alice' }];
    vi.mocked(api.get).mockResolvedValue({ data: owners });

    expect(await listAssignableOwners({ machineId: 'm-1' })).toEqual(owners);
    await listAssignableOwners({ roomId: 'r-1' });
    await listAssignableOwners({ machineId: null, roomId: null });
    await listAssignableOwners();

    expect(api.get).toHaveBeenNthCalledWith(1, '/maintenance/assignable-owners', {
      params: { machine_id: 'm-1' },
    });
    expect(api.get).toHaveBeenNthCalledWith(2, '/maintenance/assignable-owners', {
      params: { room_id: 'r-1' },
    });
    // Neither: the parc's default owner. No empty parameter is sent.
    expect(api.get).toHaveBeenNthCalledWith(3, '/maintenance/assignable-owners', undefined);
    expect(api.get).toHaveBeenNthCalledWith(4, '/maintenance/assignable-owners', undefined);
  });

  it('records a visit and patches the two levels of settings', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    await recordSession({ room_id: 'r-1', note: 'RAS', items: [{ machine_id: 'm-1' }] });
    await updateMachineMaintenance('m-1', { maintenance_cycle_days: 0 });
    await updateRoomMaintenance('r-1', { maintenance_owner_id: 'u-1' });
    expect(api.post).toHaveBeenCalledWith('/maintenance', {
      room_id: 'r-1',
      note: 'RAS',
      items: [{ machine_id: 'm-1' }],
    });
    expect(api.patch).toHaveBeenNthCalledWith(1, '/machines/m-1/maintenance', {
      maintenance_cycle_days: 0,
    });
    expect(api.patch).toHaveBeenNthCalledWith(2, '/rooms/r-1/maintenance', {
      maintenance_owner_id: 'u-1',
    });
  });
});

describe('a visit sent in parts (audit T30)', () => {
  beforeEach(() => vi.mocked(api.post).mockReset());

  const ids = (n: number, prefix: string) =>
    Array.from({ length: n }, (_, i) => ({ machine_id: `${prefix}-${i}`, note: 'x' }));

  it('creates the visit with the first part and adds the others to it', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: 's-1' } });
    // More than one request takes: 1,000 done and 200 left out.
    const payload = { room_id: 'r-1', note: 'RAS', items: ids(1000, 'd'), skipped: ids(200, 'k') };
    const progress = sessionProgress(payload);
    await recordSessionInParts(payload, progress);

    const calls = vi.mocked(api.post).mock.calls;
    expect(calls.map((c) => c[0])).toEqual([
      '/maintenance',
      '/maintenance/s-1/lines',
      '/maintenance/s-1/lines',
      '/maintenance/s-1/lines',
      '/maintenance/s-1/lines',
    ]);
    const parts = calls.map((c) => c[1] as { items: unknown[]; skipped: unknown[] });
    expect(parts.every((p) => p.items.length + p.skipped.length <= SESSION_PART_SIZE)).toBe(true);
    // The date and the note go once, with the done postes first.
    expect(calls[0]![1]).toMatchObject({ room_id: 'r-1', note: 'RAS' });
    expect(parts[0]!.items).toHaveLength(SESSION_PART_SIZE);
    expect(calls[1]![1]).not.toHaveProperty('note');
    expect(parts.flatMap((p) => p.items)).toEqual(payload.items);
    expect(parts.flatMap((p) => p.skipped)).toEqual(payload.skipped);
    expect(progress).toEqual({ sessionId: 's-1', sent: 1200, total: 1200 });
  });

  it('resumes after a failed part without sending the recorded ones again', async () => {
    vi.mocked(api.post)
      .mockResolvedValueOnce({ data: { id: 's-1' } })
      .mockRejectedValueOnce(new Error('réseau'))
      .mockResolvedValue({ data: { id: 's-1' } });
    const payload = { room_id: 'r-1', items: ids(600, 'd') };
    const progress = sessionProgress(payload);
    await expect(recordSessionInParts(payload, progress)).rejects.toThrow('réseau');
    expect(progress).toMatchObject({ sessionId: 's-1', sent: 250 });

    await recordSessionInParts(payload, progress);
    const calls = vi.mocked(api.post).mock.calls.slice(2);
    expect(calls.map((c) => c[0])).toEqual(['/maintenance/s-1/lines', '/maintenance/s-1/lines']);
    expect((calls[0]![1] as { items: { machine_id: string }[] }).items[0]!.machine_id).toBe(
      'd-250',
    );
    expect(progress.sent).toBe(600);
  });

  it('records a visit with nothing done in one request', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: 's-1' } });
    await recordSessionInParts({ room_id: 'r-1', note: 'Salle fermée', items: [] });
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith('/maintenance', {
      room_id: 'r-1',
      note: 'Salle fermée',
      items: [],
      skipped: [],
    });
  });
});

describe('labels', () => {
  it('names the four states and falls back on the raw value', () => {
    expect(maintenanceStateLabel('overdue')).toBe('En retard');
    expect(maintenanceStateLabel('excluded')).toBe('Exclu');
    expect(maintenanceStateLabel(null)).toBe('—');
    expect(maintenanceStateLabel('odd')).toBe('odd');
  });

  it('says where a cycle comes from, and when it excludes', () => {
    expect(cycleLabel(90, 'room')).toBe('90 jours (hérité de la salle)');
    expect(cycleLabel(0, 'machine')).toBe('exclu de la maintenance (propre au poste)');
  });
});

describe('due dates (audit U22)', () => {
  const now = new Date('2026-11-11T12:00:00Z');

  it('says how long a passed date has been overdue', () => {
    expect(dueLabel('2026-11-01T12:00:00Z', now)).toBe('en retard depuis 10 jours');
    expect(dueLabel('2026-11-10T11:00:00Z', now)).toBe('en retard depuis 1 jour');
    expect(dueLabel('2026-11-11T08:00:00Z', now)).toBe("en retard depuis aujourd'hui");
  });

  it('gives a future date as a day, without the time', () => {
    expect(dueLabel('2026-12-24T12:00:00Z', now)).toMatch(/^échéance le \d{2}\/\d{2}\/2026$/);
    expect(dueLabel(null, now)).toBe('');
  });

  it('counts overdue and due soon as to do', () => {
    expect(isDue('overdue')).toBe(true);
    expect(isDue('due_soon')).toBe(true);
    expect(isDue('ok')).toBe(false);
    expect(isDue('excluded')).toBe(false);
  });
});

describe('a recorded visit (item 6) and its owner labels (item 4)', () => {
  it('deletes a visit by id', async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined });
    await deleteSession('s-1');
    expect(api.delete).toHaveBeenCalledWith('/maintenance/s-1');
  });

  it('names a deactivated owner as such, never by id', () => {
    expect(ownerLabel({ id: 'u', name: 'Marie', active: false })).toBe('Marie (désactivé)');
    expect(ownerLabel({ id: 'u', name: 'Marie', active: true })).toBe('Marie');
    expect(ownerLabel({ id: 'u', name: 'Marie' })).toBe('Marie');
    expect(ownerLabel(null)).toBe('');
  });
});
