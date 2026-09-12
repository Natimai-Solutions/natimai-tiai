import { api } from 'boot/axios';

export interface Token {
  access_token: string;
  token_type: string;
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
}

/**
 * The console's own per-account settings, stored on the server so they follow
 * the operator from one workstation to the next. Keys are the console's
 * vocabulary (`utils/preferences` names them); the server only bounds the
 * size of the document and merges writes key by key.
 */
export type Preferences = Record<string, unknown>;

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  email_preference: EmailPreference;
  preferences: Preferences;
  groups: GroupRef[];
  /**
   * What the account may do — the union of its groups' grants, as
   * `resource:action` keys (see `utils/permissions`). Read by the console to
   * decide what to show; the backend re-checks every call.
   */
  permissions: string[];
}

export async function login(email: string, password: string): Promise<Token> {
  // OAuth2 password flow: the backend expects form-encoded username/password.
  const form = new URLSearchParams();
  form.append('username', email);
  form.append('password', password);
  const { data } = await api.post<Token>('/auth/login', form);
  return data;
}

export async function getMe(): Promise<User> {
  const { data } = await api.get<User>('/auth/me');
  return data;
}

export interface ProfileUpdate {
  email_preference?: EmailPreference;
  /**
   * Merged into the stored document key by key: a key set to `null` is
   * removed, a key not sent is left alone — so a page that remembers one
   * thing never overwrites what another page stored.
   */
  preferences?: Record<string, unknown | null>;
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
 * Change one's own password. The backend invalidates every token issued before
 * the change — including the one that authenticated this call — so the caller
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

/** Redeem a reset link and set the new password. */
export async function confirmPasswordReset(token: string, newPassword: string): Promise<void> {
  await api.post('/auth/password-reset/confirm', {
    token,
    new_password: newPassword,
  });
}
