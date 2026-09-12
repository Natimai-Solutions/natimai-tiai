import { api } from 'boot/axios';

/** A group: a named permission set composed on the groups page. */
export interface Group {
  id: string;
  name: string;
  description: string | null;
  /** `admin` / `readonly` / `technician` on the three every installation has; null on a composed one. */
  builtin_key: string | null;
  /** The administrators: every permission, shown but not editable. */
  is_admin: boolean;
  permissions: string[];
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface CreateGroupPayload {
  name: string;
  description?: string | null;
  permissions: string[];
}

/** Partial update — only the supplied fields are changed. */
export interface UpdateGroupPayload {
  name?: string;
  description?: string | null;
  permissions?: string[];
}

/** Every group, built-in ones first. Not paginated: a console has a handful. */
export async function listGroups(): Promise<Group[]> {
  const { data } = await api.get<Group[]>('/groups');
  return data;
}

export async function createGroup(payload: CreateGroupPayload): Promise<Group> {
  const { data } = await api.post<Group>('/groups', payload);
  return data;
}

export async function updateGroup(id: string, payload: UpdateGroupPayload): Promise<Group> {
  const { data } = await api.patch<Group>(`/groups/${id}`, payload);
  return data;
}

export async function deleteGroup(id: string): Promise<void> {
  await api.delete(`/groups/${id}`);
}
