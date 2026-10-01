import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  changePassword,
  closeSession,
  confirmPasswordReset,
  getMe,
  listSessions,
  login,
  logout,
  requestPasswordReset,
  updateMe,
} from './auth';

describe('login', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('posts form-encoded credentials and returns the token', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { access_token: 'jwt-123', token_type: 'bearer' },
    });

    const result = await login('admin@test.local', 'secret');

    expect(result.access_token).toBe('jwt-123');
    const [url, body] = vi.mocked(api.post).mock.calls[0]!;
    expect(url).toBe('/auth/login');
    expect(body).toBeInstanceOf(URLSearchParams);
    expect((body as URLSearchParams).get('username')).toBe('admin@test.local');
    expect((body as URLSearchParams).get('password')).toBe('secret');
  });

  it('lets the browser store the refresh cookie the server sets', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { access_token: 'jwt', token_type: 'bearer' } });

    await login('admin@test.local', 'secret');

    expect(vi.mocked(api.post).mock.calls[0]![2]).toEqual({ withCredentials: true });
  });
});

describe('logout', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('asks the server to end the session, with the refresh cookie', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: undefined });

    await logout();

    expect(api.post).toHaveBeenCalledWith('/auth/logout', undefined, { withCredentials: true });
  });
});

describe('sessions', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('lists the account open sessions', async () => {
    const sessions = [
      {
        id: 's-1',
        created_at: '2026-10-01T08:00:00Z',
        last_used_at: '2026-10-01T09:00:00Z',
        expires_at: '2026-10-08T09:00:00Z',
        user_agent: 'Firefox',
        ip: '10.0.0.5',
        current: true,
      },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: sessions });

    await expect(listSessions()).resolves.toEqual(sessions);
    expect(api.get).toHaveBeenCalledWith('/auth/sessions');
  });

  it('closes one session by id', async () => {
    vi.mocked(api.delete).mockResolvedValue({ data: undefined });

    await closeSession('a/b');

    expect(api.delete).toHaveBeenCalledWith('/auth/sessions/a%2Fb', { withCredentials: true });
  });
});

describe('getMe', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('fetches the current user', async () => {
    const user = { id: 'u-1', email: 'admin@test.local', full_name: null, role: 'admin' };
    vi.mocked(api.get).mockResolvedValue({ data: user });

    const result = await getMe();

    expect(api.get).toHaveBeenCalledWith('/auth/me');
    expect(result).toEqual(user);
  });
});

describe('changePassword', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('posts the current and new passwords in snake_case', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: undefined });

    await changePassword('old-passphrase', 'new-passphrase');

    expect(api.post).toHaveBeenCalledWith('/auth/password', {
      current_password: 'old-passphrase',
      new_password: 'new-passphrase',
    });
  });
});

describe('requestPasswordReset', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('asks for a reset link', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: undefined });

    await requestPasswordReset('marie@test.local');

    expect(api.post).toHaveBeenCalledWith('/auth/password-reset/request', {
      email: 'marie@test.local',
    });
  });
});

describe('confirmPasswordReset', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('redeems the token with the new password', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: undefined });

    await confirmPasswordReset('tok-123', 'new-passphrase');

    expect(api.post).toHaveBeenCalledWith('/auth/password-reset/confirm', {
      token: 'tok-123',
      new_password: 'new-passphrase',
    });
  });
});

describe('updateMe', () => {
  beforeEach(() => {
    vi.mocked(api.patch).mockReset();
  });

  it('PATCHes the chosen cadence and returns the updated account', async () => {
    const user = {
      id: 'u-1',
      email: 'ops@example.com',
      full_name: null,
      role: 'readonly',
      email_preference: 'immediate',
    };
    vi.mocked(api.patch).mockResolvedValue({ data: user });

    const result = await updateMe({ email_preference: 'immediate' });

    expect(api.patch).toHaveBeenCalledWith('/auth/me', { email_preference: 'immediate' });
    expect(result).toEqual(user);
  });

  it('PATCHes a preference patch as is, nulls included', async () => {
    vi.mocked(api.patch).mockResolvedValue({ data: { id: 'u-1', preferences: {} } });

    await updateMe({ preferences: { machines_columns: ['hostname', 'room'], theme: null } });

    expect(api.patch).toHaveBeenCalledWith('/auth/me', {
      preferences: { machines_columns: ['hostname', 'room'], theme: null },
    });
  });
});
