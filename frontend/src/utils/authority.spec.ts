import { describe, expect, it } from 'vitest';
import type { Group } from 'src/services/groups';
import { callerAuthority, exceeds, groupsAuthority } from './authority';

function group(id: string, over: Partial<Group> = {}): Group {
  return {
    id,
    name: id,
    description: null,
    builtin_key: null,
    is_admin: false,
    permissions: [],
    scope: null,
    member_count: 0,
    created_at: '',
    updated_at: '',
    ...over,
  };
}

const admins = group('admins', { is_admin: true, builtin_key: 'admin' });
const managers = group('managers', {
  permissions: ['user:read', 'user:write', 'machine:read'],
  scope: { locations: ['Papeete'], buildings: [], rooms: [] },
});
const techs = group('techs', {
  permissions: ['machine:read', 'command:execute'],
  scope: { locations: ['Papeete'], buildings: [], rooms: [] },
});
const everywhere = group('everywhere', { permissions: ['machine:read'], scope: null });
const all = [admins, managers, techs, everywhere];

describe('authority (item 4: what the server will refuse)', () => {
  const me = callerAuthority(
    { permissions: ['user:read', 'user:write', 'machine:read'], groups: [{ id: 'managers' }] },
    all,
  )!;

  it('lets a manager reach what it holds, on its own places', () => {
    expect(exceeds(me, groupsAuthority([managers]))).toBe(false);
  });

  it('withholds a permission it lacks, a wider place, and the administrators', () => {
    expect(exceeds(me, groupsAuthority([techs]))).toBe(true);
    expect(exceeds(me, groupsAuthority([everywhere]))).toBe(true);
    expect(exceeds(me, groupsAuthority([admins]))).toBe(true);
  });

  it('withholds nothing from an administrator', () => {
    const admin = callerAuthority({ permissions: [], groups: [{ id: 'admins' }] }, all)!;
    expect(exceeds(admin, groupsAuthority([admins, everywhere]))).toBe(false);
  });

  it('cannot tell without the caller’s groups, and then says nothing', () => {
    expect(callerAuthority({ permissions: [], groups: [{ id: 'unknown' }] }, all)).toBeNull();
  });
});
