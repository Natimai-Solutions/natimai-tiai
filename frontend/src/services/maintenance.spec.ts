import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  cycleLabel,
  getDue,
  maintenanceStateLabel,
  recordSession,
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
