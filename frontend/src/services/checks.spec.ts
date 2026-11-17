import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  bulkCheckNotification,
  closeCheck,
  createCheck,
  createChecksBulk,
  listAllChecks,
  listAssignableUsers,
  listChecks,
  updateCheck,
} from './checks';

describe('checks service', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.patch).mockReset();
  });

  it('lists tasks with their filter', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } });
    await listChecks({ assigned_to: 'me', open: true });
    expect(api.get).toHaveBeenCalledWith('/checks', { params: { assigned_to: 'me', open: true } });
    await listAssignableUsers();
    expect(api.get).toHaveBeenCalledWith('/checks/assignable-users', undefined);
    await listAssignableUsers('m-1');
    expect(api.get).toHaveBeenLastCalledWith('/checks/assignable-users', {
      params: { machine_id: 'm-1' },
    });
  });

  it('asks, asks in bulk, reassigns and closes', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    await createCheck('m-1', { assigned_to_id: 'u-1', instructions: 'Écran' });
    await createChecksBulk(['m-1', 'm-2'], { instructions: 'Tour' });
    await updateCheck('c-1', { assigned_to_id: null });
    await closeCheck('c-1', { note: 'OK' });
    expect(api.post).toHaveBeenNthCalledWith(1, '/machines/m-1/check', {
      assigned_to_id: 'u-1',
      instructions: 'Écran',
    });
    expect(api.post).toHaveBeenNthCalledWith(2, '/checks/bulk', {
      machine_ids: ['m-1', 'm-2'],
      instructions: 'Tour',
    });
    expect(api.patch).toHaveBeenCalledWith('/checks/c-1', { assigned_to_id: null });
    expect(api.post).toHaveBeenNthCalledWith(3, '/checks/c-1/close', { note: 'OK' });
  });
});

describe('bulkCheckNotification', () => {
  it('is positive when nothing was skipped, and says what was', () => {
    expect(bulkCheckNotification({ created: 2, skipped: 0 }).type).toBe('positive');
    const n = bulkCheckNotification({ created: 1, skipped: 1 });
    expect(n.type).toBe('warning');
    expect(n.message).toContain('1 poste(s) en avaient déjà');
  });
});

describe('listAllChecks (« Mes tâches » cut at 200)', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('reads every page until the total is reached', async () => {
    const page = (n: number, from: number) => ({
      data: {
        items: Array.from({ length: n }, (_, i) => ({ id: `c-${from + i}` })),
        total: 310,
        page: 1,
        page_size: 200,
      },
    });
    vi.mocked(api.get).mockResolvedValueOnce(page(200, 0)).mockResolvedValueOnce(page(110, 200));
    const res = await listAllChecks({ open: true, assigned_to: 'me' });
    expect(res.items).toHaveLength(310);
    expect(res.total).toBe(310);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(api.get).toHaveBeenLastCalledWith('/checks', {
      params: { open: true, assigned_to: 'me', page: 2, page_size: 200 },
    });
  });

  it('stops on an empty page even if the total says more', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: { items: [{ id: 'a' }], total: 5, page: 1, page_size: 200 } })
      .mockResolvedValueOnce({ data: { items: [], total: 5, page: 2, page_size: 200 } });
    const res = await listAllChecks();
    expect(res.items).toHaveLength(1);
    expect(api.get).toHaveBeenCalledTimes(2);
  });
});
