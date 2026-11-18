import { t } from 'src/i18n';
import type { Group, GroupScope } from 'src/services/groups';

/**
 * The escalation rule of the backend (`app/features/user/permissions.py`,
 * `escalation`), mirrored so that the console does not offer what the server
 * will refuse: a non-administrator account manager neither grants nor lays
 * hands on more than it holds — no permission outside its own set, no place
 * outside its own scope, never the administrators' group.
 *
 * Computed from what the pages already load (the profile, the group list).
 * Cosmetic like every client-side check: when something cannot be told — a
 * group the list does not hold — nothing is disabled and the server decides.
 */
export interface Authority {
  isAdmin: boolean;
  permissions: ReadonlySet<string>;
  /** null = the whole parc. */
  scope: GroupScope | null;
}

/** The tooltip on an account withheld for that reason, in the reader's language. */
export function moreRightsAccount(): string {
  return t('permissions.authority.moreRightsAccount');
}

/** The tooltip on a group withheld for that reason, in the reader's language. */
export function moreRightsGroup(): string {
  return t('permissions.authority.moreRightsGroup');
}

function emptyScope(): GroupScope {
  return { locations: [], buildings: [], rooms: [] };
}

/** What membership of `groups` grants together; null scope as soon as one is unrestricted. */
export function groupsAuthority(groups: readonly Group[]): Authority {
  const isAdmin = groups.some((g) => g.is_admin);
  const permissions = new Set(groups.flatMap((g) => g.permissions));
  let scope: GroupScope | null = emptyScope();
  for (const g of groups) {
    if (g.scope === null) {
      scope = null;
      break;
    }
    scope.locations.push(...g.scope.locations);
    scope.buildings.push(...g.scope.buildings);
    scope.rooms.push(...g.scope.rooms);
  }
  return { isAdmin, permissions, scope: isAdmin ? null : scope };
}

/** The groups `ids` name in `all`, or null when one of them is not there. */
export function groupsByIds(ids: readonly string[], all: readonly Group[]): Group[] | null {
  const found = ids.map((id) => all.find((g) => g.id === id));
  return found.every((g): g is Group => g !== undefined) ? found : null;
}

/** Whether `target` reaches places `actor` does not — kind by kind, literally. */
function scopeWider(actor: GroupScope | null, target: GroupScope | null): boolean {
  if (actor === null) return false;
  if (target === null) return true;
  const within = (inner: string[], outer: string[]) => inner.every((v) => outer.includes(v));
  return !(
    within(target.locations, actor.locations) &&
    within(target.buildings, actor.buildings) &&
    within(target.rooms, actor.rooms)
  );
}

/** Whether `target` grants more than `actor` holds (the server would answer 403). */
export function exceeds(actor: Authority, target: Authority): boolean {
  if (actor.isAdmin) return false;
  if (target.isAdmin) return true;
  for (const p of target.permissions) if (!actor.permissions.has(p)) return true;
  return scopeWider(actor.scope, target.scope);
}

/**
 * The caller's authority: its permissions from the profile, its scope and
 * administrator status from its groups. Null when its groups are not all in
 * `all` — nothing is then withheld.
 */
export function callerAuthority(
  profile: { permissions?: readonly string[]; groups?: readonly { id: string }[] } | null,
  all: readonly Group[],
): Authority | null {
  if (!profile || !Array.isArray(profile.permissions) || !Array.isArray(profile.groups)) {
    return null;
  }
  const groups = groupsByIds(
    profile.groups.map((g) => g.id),
    all,
  );
  if (!groups) return null;
  const fromGroups = groupsAuthority(groups);
  return { ...fromGroups, permissions: new Set(profile.permissions) };
}
