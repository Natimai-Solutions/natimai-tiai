import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the axios boot module before importing the service under test.
vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import { createUser, deleteUser, listUsers, resetUserPassword, updateUser } from './users';

describe('listUsers', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('calls GET /users with the given filters and returns the payload', async () => {
    const payload = { items: [], total: 0, page: 1, page_size: 50 };
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    const result = await listUsers({ search: 'marie' });

    expect(api.get).toHaveBeenCalledWith('/users', { params: { search: 'marie' } });
    expect(result).toEqual(payload);
  });

  it('passes no params when called with no arguments', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    });

    await listUsers();

    expect(api.get).toHaveBeenCalledWith('/users', { params: {} });
  });
});

describe('createUser', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('posts the new account and returns it', async () => {
    const created = { id: 'u-1', email: 'marie@test.local' };
    vi.mocked(api.post).mockResolvedValue({ data: created });

    const result = await createUser({
      email: 'marie@test.local',
      password: 'correct-horse-battery',
      role: 'admin',
    });

    expect(api.post).toHaveBeenCalledWith('/users', {
      email: 'marie@test.local',
      password: 'correct-horse-battery',
      role: 'admin',
    });
    expect(result).toEqual(created);
  });
});

describe('updateUser', () => {
  beforeEach(() => {
    vi.mocked(api.patch).mockReset();
  });

  it('patches only the supplied fields', async () => {
    vi.mocked(api.patch).mockResolvedValue({ data: { id: 'u-1', is_active: false } });

    await updateUser('u-1', { is_active: false });

    expect(api.patch).toHaveBeenCalledWith('/users/u-1', { is_active: false });
  });
});

describe('deleteUser', () => {
  beforeEach(() => {
    vi.mocked(api.delete).mockReset();
  });

  it('deletes the account', async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined });

    await deleteUser('u-9');

    expect(api.delete).toHaveBeenCalledWith('/users/u-9');
  });
});

describe('resetUserPassword', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('sends an empty body when the server should generate the password', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { password: 'generated-one' } });

    const result = await resetUserPassword('u-1');

    expect(api.post).toHaveBeenCalledWith('/users/u-1/reset-password', {});
    expect(result).toBe('generated-one');
  });

  it('forwards an explicitly chosen password', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { password: 'chosen-passphrase' } });

    const result = await resetUserPassword('u-1', 'chosen-passphrase');

    expect(api.post).toHaveBeenCalledWith('/users/u-1/reset-password', {
      password: 'chosen-passphrase',
    });
    expect(result).toBe('chosen-passphrase');
  });
});
