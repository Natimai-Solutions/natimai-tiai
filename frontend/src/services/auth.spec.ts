import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from 'boot/axios';
import { changePassword, confirmPasswordReset, getMe, login, requestPasswordReset } from './auth';

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
