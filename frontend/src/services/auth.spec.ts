import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    defaults: { baseURL: '/api/v1' },
  },
}));

import { api } from 'boot/axios';
import {
  changePassword,
  checkPasswordResetToken,
  closeSession,
  confirmPasswordReset,
  directorySignInUrl,
  getAuthMethods,
  getMe,
  isChallenge,
  regenerateBackupCodes,
  startDirectoryLink,
  totpConfirm,
  totpDisable,
  totpSetup,
  unlinkDirectory,
  verifySecondFactor,
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

    expect(result).toEqual({ access_token: 'jwt-123', token_type: 'bearer' });
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

describe('checkPasswordResetToken (C7)', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
  });

  it('reads 204 as valid, 400 as invalid, and anything else as unknown', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ status: 204, data: '' });
    expect(await checkPasswordResetToken('t')).toBe('valid');
    // In the body, never in the URL: a query string is what an access log keeps.
    expect(api.post).toHaveBeenCalledWith('/auth/password-reset/check', { token: 't' });
    expect(api.get).not.toHaveBeenCalled();
    vi.mocked(api.post).mockRejectedValueOnce({ response: { status: 400 } });
    expect(await checkPasswordResetToken('t')).toBe('invalid');
    // An older server (404, 405) or no answer at all: the form decides.
    vi.mocked(api.post).mockRejectedValueOnce({ response: { status: 405 } });
    expect(await checkPasswordResetToken('t')).toBe('unknown');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('Network Error'));
    expect(await checkPasswordResetToken('t')).toBe('unknown');
  });
});

describe('second factor and directory (C7)', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.get).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('tells a challenge from a token', () => {
    expect(isChallenge({ access_token: 'a', token_type: 'bearer' })).toBe(false);
    expect(isChallenge({ second_factor_required: true, challenge: 'c', expires_in: 300 })).toBe(
      true,
    );
  });

  it('sends the code, the password and what each call needs', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { access_token: 't', backup_codes: ['A'], secret: 's', otpauth_uri: 'u' },
    });
    await verifySecondFactor('ch', '123456');
    expect(vi.mocked(api.post).mock.calls[0]!.slice(0, 2)).toEqual([
      '/auth/login/second-factor',
      { challenge: 'ch', code: '123456' },
    ]);
    await totpSetup('pw');
    expect(vi.mocked(api.post).mock.calls[1]!.slice(0, 2)).toEqual([
      '/auth/totp/setup',
      { current_password: 'pw' },
    ]);
    expect(await totpConfirm('111111')).toEqual(['A']);
    await totpDisable('pw', '222222');
    expect(vi.mocked(api.post).mock.calls[3]!.slice(0, 2)).toEqual([
      '/auth/totp/disable',
      { current_password: 'pw', code: '222222' },
    ]);
    expect(await regenerateBackupCodes('333333')).toEqual(['A']);
  });

  it('builds the directory sign-in address and follows only https', async () => {
    expect(directorySignInUrl('/machines?x=1')).toBe(
      '/api/v1/auth/oidc/start?redirect=%2Fmachines%3Fx%3D1',
    );
    expect(directorySignInUrl(null)).toBe('/api/v1/auth/oidc/start');
    vi.mocked(api.get).mockResolvedValue({ data: { oidc_enabled: true, oidc_label: 'M' } });
    expect(await getAuthMethods()).toEqual({ oidc_enabled: true, oidc_label: 'M' });

    vi.mocked(api.post).mockResolvedValue({ data: { url: 'https://login.test/a' } });
    expect(await startDirectoryLink('pw', null)).toBe('https://login.test/a');
    expect(vi.mocked(api.post).mock.calls[0]!.slice(0, 2)).toEqual([
      '/auth/oidc/link',
      { current_password: 'pw' },
    ]);
    vi.mocked(api.post).mockResolvedValue({ data: { url: 'javascript:alert(1)' } });
    await expect(startDirectoryLink('pw', '123456')).rejects.toThrow();
    await unlinkDirectory();
    expect(api.delete).toHaveBeenCalledWith('/auth/oidc/link');
  });
});
