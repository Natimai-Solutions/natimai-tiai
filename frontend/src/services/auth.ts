import { api } from 'boot/axios';

export interface Token {
  access_token: string;
  token_type: string;
}

/**
 * A right password for an account with a second factor (C7): no session yet,
 * a challenge to redeem with a code. Only ever answered to whoever typed the
 * right password.
 */
export interface SecondFactorChallenge {
  second_factor_required: true;
  challenge: string;
  expires_in: number;
}

export function isChallenge(
  answer: Token | SecondFactorChallenge,
): answer is SecondFactorChallenge {
  return (answer as SecondFactorChallenge).second_factor_required === true;
}

/**
 * How much this account hears from Tia'i by e-mail. One axis rather than a set
 * of switches — see the backend enum of the same name.
 *
 * Account mail (the password-reset link) is outside this: it answers a request
 * the user just made, and « aucun e-mail » does not suppress it.
 */
export type EmailPreference = 'none' | 'immediate' | 'digest_events' | 'digest_daily';

/** A group as the profile names it: enough to display, not to edit. */
export interface GroupRef {
  id: string;
  name: string;
  /** A built-in group's key (`utils/groupText`); absent from an older server. */
  builtin_key?: string | null;
}

/**
 * The console's own per-account settings, stored on the server so they follow
 * the operator from one workstation to the next. Keys are the console's
 * vocabulary (`utils/preferences` names them); the server only bounds the
 * size of the document and merges writes key by key.
 */
export type Preferences = Record<string, unknown>;

/** A language the account can choose (`users.language` on the server). */
export type AccountLanguage = 'fr' | 'en';

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  email_preference: EmailPreference;
  /**
   * The language the account chose, or null to follow the browser. Absent
   * from a server older than the bilingual console: read as null.
   */
  language?: AccountLanguage | null;
  preferences: Preferences;
  groups: GroupRef[];
  /**
   * What the account may do — the union of its groups' grants, as
   * `resource:action` keys (see `utils/permissions`). Read by the console to
   * decide what to show; the backend re-checks every call.
   */
  permissions: string[];
  /** Second factor (C7). Absent from an older server: read as off. */
  second_factor_enabled?: boolean;
  /** A group of the account requires one. */
  second_factor_required?: boolean;
  backup_codes_left?: number;
  /** This session was opened for enrolment only: « Mon compte » until then. */
  enrolment_only?: boolean;
  /** Where the account signs in from (C7): `local`, or `oidc` for the directory. */
  auth_source?: 'local' | 'oidc';
  /** A local account linked to a directory identity. */
  directory_linked?: boolean;
}

/**
 * Log in. The access token comes back in the body; the refresh token is set
 * by the server as an HttpOnly cookie the page never reads (see
 * `services/session`). `withCredentials` lets that cookie be stored even when
 * the API sits on another origin than the console (`BACKEND_CORS_ORIGINS`).
 */
export async function login(
  email: string,
  password: string,
): Promise<Token | SecondFactorChallenge> {
  // OAuth2 password flow: the backend expects form-encoded username/password.
  const form = new URLSearchParams();
  form.append('username', email);
  form.append('password', password);
  const { data } = await api.post<Token | SecondFactorChallenge>('/auth/login', form, {
    withCredentials: true,
  });
  return data;
}

/** The second step: a challenge redeemed with a code (or a backup code). */
export async function verifySecondFactor(challenge: string, code: string): Promise<Token> {
  const { data } = await api.post<Token>(
    '/auth/login/second-factor',
    { challenge, code },
    { withCredentials: true },
  );
  return data;
}

/** « Mon compte »: start an enrolment — a secret pending until a code confirms it. */
export async function totpSetup(
  currentPassword: string,
): Promise<{ secret: string; otpauth_uri: string }> {
  const { data } = await api.post<{ secret: string; otpauth_uri: string }>('/auth/totp/setup', {
    current_password: currentPassword,
  });
  return data;
}

/** Confirm the enrolment with a first code; returns the ten backup codes, shown once. */
export async function totpConfirm(code: string): Promise<string[]> {
  const { data } = await api.post<{ backup_codes: string[] }>('/auth/totp/confirm', { code });
  return data.backup_codes;
}

export async function totpDisable(currentPassword: string, code: string): Promise<void> {
  await api.post('/auth/totp/disable', { current_password: currentPassword, code });
}

/** What the login page offers beside the password (C7). */
export interface AuthMethods {
  oidc_enabled: boolean;
  oidc_label: string;
}

export async function getAuthMethods(): Promise<AuthMethods> {
  const { data } = await api.get<AuthMethods>('/auth/methods');
  return data;
}

/**
 * Where the browser goes to sign in through the directory: a navigation, not
 * a request — the provider's page must take the whole window.
 */
export function directorySignInUrl(redirect: string | null): string {
  const base = (api.defaults?.baseURL ?? '/api/v1').replace(/\/$/, '');
  const query = redirect ? `?redirect=${encodeURIComponent(redirect)}` : '';
  return `${base}/auth/oidc/start${query}`;
}

/** « Associer mon compte »: the provider's URL to go through, for this account. */
export async function startDirectoryLink(
  currentPassword: string,
  code: string | null,
): Promise<string> {
  const { data } = await api.post<{ url: string }>(
    '/auth/oidc/link',
    { current_password: currentPassword, ...(code ? { code } : {}) },
    { withCredentials: true },
  );
  // Only ever the provider's https page: anything else is not followed.
  if (!/^https:\/\//i.test(data.url)) throw new Error('unexpected sign-in address');
  return data.url;
}

export async function unlinkDirectory(): Promise<void> {
  await api.delete('/auth/oidc/link');
}

export async function regenerateBackupCodes(code: string): Promise<string[]> {
  const { data } = await api.post<{ backup_codes: string[] }>('/auth/totp/backup-codes', {
    code,
  });
  return data.backup_codes;
}

/**
 * End the session on the server: it is revoked there — the access token
 * stops working at once, everywhere — and the refresh cookie is cleared.
 * Always succeeds server-side (204), even for a session already over.
 */
export async function logout(): Promise<void> {
  await api.post('/auth/logout', undefined, { withCredentials: true });
}

/** One of the account's open sessions, as « Mon compte » lists them. */
export interface AuthSession {
  id: string;
  created_at: string;
  /** Last time the session bought a new access token: accurate to ~15 min. */
  last_used_at: string;
  expires_at: string;
  user_agent: string | null;
  ip: string | null;
  /** The session this console is using: closing it is logging out. */
  current: boolean;
}

/** The account's open sessions, most recently active first. */
export async function listSessions(): Promise<AuthSession[]> {
  const { data } = await api.get<AuthSession[]>('/auth/sessions');
  return data;
}

/** Close one of the account's sessions (a workstation left logged in). */
export async function closeSession(id: string): Promise<void> {
  await api.delete(`/auth/sessions/${encodeURIComponent(id)}`, { withCredentials: true });
}

export async function getMe(): Promise<User> {
  const { data } = await api.get<User>('/auth/me');
  return data;
}

export interface ProfileUpdate {
  email_preference?: EmailPreference;
  /** A language, or `null` to go back to the browser's. */
  language?: AccountLanguage | null;
  /**
   * Merged into the stored document key by key: a key set to `null` is
   * removed, a key not sent is left alone — so a page that remembers one
   * thing never overwrites what another page stored.
   */
  preferences?: Record<string, unknown>;
}

/**
 * Update one's own profile. Self-service and deliberately narrow: an account
 * changes how much mail it receives and its console preferences, never its
 * role or its activation — those stay with an administrator.
 */
export async function updateMe(payload: ProfileUpdate): Promise<User> {
  const { data } = await api.patch<User>('/auth/me', payload);
  return data;
}

/**
 * Change one's own password. The backend revokes every session of the
 * account — including the one that authenticated this call — so the caller
 * must log in again right after.
 */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await api.post('/auth/password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

/**
 * Ask for a reset link. Always resolves, even for an unknown address: the
 * backend answers 204 either way so the endpoint cannot be used to probe which
 * e-mails have an account.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  await api.post('/auth/password-reset/request', { email });
}

/**
 * Whether a reset link can still be used, asked before the form is shown
 * (C7): `valid` (204), `invalid` (400: expired, used, or garbled), or
 * `unknown` — an older server without the check, or no answer — in which case
 * the form is shown and the confirmation decides.
 *
 * The token goes in the body of a POST, never in the URL: a query string ends
 * up in the server's access log, and this link is still good for an hour.
 */
export async function checkPasswordResetToken(
  token: string,
): Promise<'valid' | 'invalid' | 'unknown'> {
  try {
    await api.post('/auth/password-reset/check', { token });
    return 'valid';
  } catch (e) {
    const status = (e as { response?: { status?: number } } | null)?.response?.status;
    return status === 400 ? 'invalid' : 'unknown';
  }
}

/** Redeem a reset link and set the new password. */
export async function confirmPasswordReset(token: string, newPassword: string): Promise<void> {
  await api.post('/auth/password-reset/confirm', {
    token,
    new_password: newPassword,
  });
}

/** A personal API token (C8), as « Mon compte » lists it: never its value. */
export interface ApiToken {
  id: string;
  name: string;
  prefix: string;
  can_write: boolean;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
}

export async function listApiTokens(): Promise<ApiToken[]> {
  const { data } = await api.get<ApiToken[]>('/auth/api-tokens');
  return data;
}

/** A new token; its value comes back once, here. */
export async function createApiToken(fields: {
  name: string;
  can_write: boolean;
  days: number;
  current_password?: string;
  code?: string;
}): Promise<ApiToken & { token: string }> {
  const { data } = await api.post<ApiToken & { token: string }>('/auth/api-tokens', fields);
  return data;
}

export async function revokeApiToken(id: string): Promise<void> {
  await api.delete(`/auth/api-tokens/${id}`);
}
