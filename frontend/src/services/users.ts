import { api } from 'boot/axios';
import type { EmailPreference, GroupRef } from 'src/services/auth';

/** Minimum enforced by the backend (PASSWORD_MIN_LENGTH). */
export const PASSWORD_MIN_LENGTH = 12;

export interface ConsoleUser {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  /** Which mails this account receives. Visible to an administrator because
   * "who gets told when a poste catches something" is a property of the parc's
   * supervision, not a private setting. */
  email_preference: EmailPreference;
  groups: GroupRef[];
  /** Set while the account is locked after failed logins. */
  locked_until: string | null;
  /** A second factor is active (C7). Absent from an older server. */
  second_factor_enabled?: boolean;
  /** `oidc`: signs in through the directory (C7); no password to reset. */
  auth_source?: 'local' | 'oidc';
  directory_linked?: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserList {
  items: ConsoleUser[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListUsersParams {
  search?: string;
  page?: number;
  page_size?: number;
}

export interface CreateUserPayload {
  email: string;
  password: string;
  full_name?: string | null;
  /** None is a valid account: it can log in and sees nothing. */
  group_ids?: string[];
}

/** Partial update — only the supplied fields are changed. */
export interface UpdateUserPayload {
  email?: string;
  full_name?: string | null;
  /** Replaces the memberships. Refused on one's own account. */
  group_ids?: string[];
  is_active?: boolean;
  email_preference?: EmailPreference;
}

export async function listUsers(params: ListUsersParams = {}): Promise<UserList> {
  const { data } = await api.get<UserList>('/users', { params });
  return data;
}

export async function createUser(payload: CreateUserPayload): Promise<ConsoleUser> {
  const { data } = await api.post<ConsoleUser>('/users', payload);
  return data;
}

export async function updateUser(id: string, payload: UpdateUserPayload): Promise<ConsoleUser> {
  const { data } = await api.patch<ConsoleUser>(`/users/${id}`, payload);
  return data;
}

export async function deleteUser(id: string): Promise<void> {
  await api.delete(`/users/${id}`);
}

/**
 * Reset an account's password. Omit `password` to have the server generate one.
 * The returned value is shown once — it is never retrievable afterwards.
 */
/** Remove an account's second factor and backup codes (C7); its sessions end. */
export async function resetUserSecondFactor(id: string): Promise<void> {
  await api.post(`/users/${id}/reset-second-factor`);
}

export async function resetUserPassword(id: string, password?: string): Promise<string> {
  const body = password ? { password } : {};
  const { data } = await api.post<{ password: string }>(`/users/${id}/reset-password`, body);
  return data.password;
}
