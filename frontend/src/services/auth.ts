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

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  email_preference: EmailPreference;
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

/**
 * Update one's own profile. Self-service and deliberately narrow: an account
 * changes how much mail it receives, never its role or its activation — those
 * stay with an administrator.
 */
export async function updateMe(payload: { email_preference?: EmailPreference }): Promise<User> {
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
