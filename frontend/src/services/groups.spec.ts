import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import { createGroup, deleteGroup, listGroups, updateGroup } from './groups';

const group = {
  id: 'g-1',
  name: 'Opérateurs',
  description: null,
  builtin_key: null,
  is_admin: false,
  permissions: ['machine:read', 'command:execute'],
  member_count: 2,
  created_at: '2026-09-10T00:00:00Z',
  updated_at: '2026-09-10T00:00:00Z',
};

describe('groups service', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.patch).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('lists every group in one call', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [group] });
    expect(await listGroups()).toEqual([group]);
    expect(api.get).toHaveBeenCalledWith('/groups');
  });

  it('creates with the permission keys as given', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: group });
    await createGroup({ name: 'Opérateurs', permissions: ['machine:read', 'command:execute'] });
    expect(api.post).toHaveBeenCalledWith('/groups', {
      name: 'Opérateurs',
      permissions: ['machine:read', 'command:execute'],
    });
  });

  it('patches only what it is handed', async () => {
    vi.mocked(api.patch).mockResolvedValue({ data: group });
    await updateGroup('g-1', { permissions: ['machine:read'] });
    expect(api.patch).toHaveBeenCalledWith('/groups/g-1', { permissions: ['machine:read'] });
  });

  it('deletes by id', async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined });
    await deleteGroup('g-1');
    expect(api.delete).toHaveBeenCalledWith('/groups/g-1');
  });
});
