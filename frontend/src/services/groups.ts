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
  /** Where the group is confined; null = the whole parc. */
  scope: GroupScope | null;
  member_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * The places a group is confined to: sites (in the agents' words), buildings
 * and rooms (ids). A poste is in scope if it matches any of them. An account
 * sees the union of its groups' scopes — and the whole parc as soon as one of
 * its groups has none.
 */
export interface GroupScope {
  locations: string[];
  buildings: string[];
  rooms: string[];
}

export interface CreateGroupPayload {
  name: string;
  description?: string | null;
  permissions: string[];
  scope?: GroupScope | null;
}

/** Partial update — only the supplied fields are changed; `scope: null` lifts the restriction. */
export interface UpdateGroupPayload {
  name?: string;
  description?: string | null;
  permissions?: string[];
  scope?: GroupScope | null;
}

/** The scope to send for what the form holds: null when nothing is ticked. */
export function scopeOrNull(scope: GroupScope): GroupScope | null {
  return scope.locations.length || scope.buildings.length || scope.rooms.length ? scope : null;
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
