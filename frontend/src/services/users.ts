import { api } from 'boot/axios';

export type Role = 'admin' | 'readonly';

/** Minimum enforced by the backend (PASSWORD_MIN_LENGTH). */
export const PASSWORD_MIN_LENGTH = 12;

export interface ConsoleUser {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
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
  role?: Role;
}

/** Partial update — only the supplied fields are changed. */
export interface UpdateUserPayload {
  email?: string;
  full_name?: string | null;
  role?: Role;
  is_active?: boolean;
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
export async function resetUserPassword(id: string, password?: string): Promise<string> {
  const body = password ? { password } : {};
  const { data } = await api.post<{ password: string }>(`/users/${id}/reset-password`, body);
  return data.password;
}
