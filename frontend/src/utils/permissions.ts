/**
 * The permission catalogue, mirrored from the backend
 * (`app/features/user/permissions.py`, `PERMISSION_CATALOGUE`). Keys are
 * `resource:action`; the labels are the console's
 * (`src/i18n/messages/permissions.ts`), worded when the grid is drawn, and the
 * order is the order of the grid on the groups page.
 */

import { intlTag, t } from 'src/i18n';
import permissionMessages from 'src/i18n/messages/permissions';

export type Resource =
  | 'machine'
  | 'threat'
  | 'command'
  | 'risky_command'
  | 'room'
  | 'intervention'
  | 'check'
  | 'maintenance'
  | 'settings'
  | 'user'
  | 'audit'
  | 'package';

export type Action = 'read' | 'write' | 'execute';

/** One permission of the catalogue: what it is, without words. */
export interface PermissionKey {
  key: string;
  resource: Resource;
  action: Action;
}

/** A permission as the grid shows it, in the reader's language. */
export interface PermissionEntry extends PermissionKey {
  /** What the resource is, as a row header. */
  resourceLabel: string;
  /** What granting this lets someone do, as the checkbox's label. */
  label: string;
  /** A sentence for the cases where the label alone would be read two ways. */
  hint?: string;
}

export function permissionKey(resource: Resource, action: Action): string {
  return `${resource}:${action}`;
}

function entry(resource: Resource, action: Action): PermissionKey {
  return { key: permissionKey(resource, action), resource, action };
}

export const PERMISSION_CATALOGUE: PermissionKey[] = [
  entry('machine', 'read'),
  entry('machine', 'write'),
  entry('threat', 'read'),
  entry('command', 'read'),
  entry('command', 'execute'),
  entry('risky_command', 'execute'),
  entry('room', 'read'),
  entry('room', 'write'),
  entry('intervention', 'read'),
  entry('intervention', 'write'),
  entry('check', 'read'),
  entry('check', 'write'),
  entry('maintenance', 'read'),
  entry('maintenance', 'write'),
  entry('settings', 'read'),
  entry('settings', 'write'),
  entry('user', 'read'),
  entry('user', 'write'),
  entry('audit', 'read'),
  entry('package', 'read'),
  entry('package', 'write'),
];

/** Whether the catalogue has a hint for a permission (the same in both languages). */
function hasHint({ resource, action }: PermissionKey): boolean {
  const byAction: Record<string, { label: string; hint?: string }> =
    permissionMessages.fr.entries[resource];
  return byAction[action]?.hint !== undefined;
}

/** What the resource is, as a row header, in the reader's language. */
export function permissionResourceLabel(resource: Resource): string {
  return t(`permissions.resources.${resource}`);
}

/** A permission with its words, in the reader's language. */
export function permissionEntry(permission: PermissionKey): PermissionEntry {
  const { resource, action } = permission;
  const words: PermissionEntry = {
    ...permission,
    resourceLabel: permissionResourceLabel(resource),
    label: t(`permissions.entries.${resource}.${action}.label`),
  };
  if (hasHint(permission)) words.hint = t(`permissions.entries.${resource}.${action}.hint`);
  return words;
}

/** The catalogue as the grid shows it: one row per resource, in order. */
export interface PermissionRow {
  resource: Resource;
  resourceLabel: string;
  entries: PermissionEntry[];
}

/** The grid's rows, worded now — call it where it is drawn. */
export function permissionRows(): PermissionRow[] {
  const rows: PermissionRow[] = [];
  for (const permission of PERMISSION_CATALOGUE) {
    const words = permissionEntry(permission);
    const row = rows.find((r) => r.resource === permission.resource);
    if (row) row.entries.push(words);
    else
      rows.push({ resource: words.resource, resourceLabel: words.resourceLabel, entries: [words] });
  }
  return rows;
}

/** A readable name for a key, for lists that show what a group grants. */
export function permissionLabel(key: string): string {
  const permission = PERMISSION_CATALOGUE.find((e) => e.key === key);
  if (!permission) return key;
  const words = permissionEntry(permission);
  return t('permissions.named', {
    resource: words.resourceLabel,
    action: words.label.toLocaleLowerCase(intlTag()),
  });
}

/**
 * What a permission needs to be of any use (item 4): a write or an execute
 * grants nothing without the read of the same resource — `room:write` alone
 * opens no page — and the risky commands run only with the everyday ones.
 */
export function permissionRequires(key: string): string[] {
  const [resource, action] = key.split(':');
  const needs: string[] = [];
  const read = `${resource}:read`;
  if (action !== 'read' && PERMISSION_CATALOGUE.some((e) => e.key === read)) needs.push(read);
  if (key === 'risky_command:execute') needs.push('command:execute');
  return needs;
}

/** Add everything `key` needs to `out`, transitively. */
function addRequirements(key: string, out: Set<string>): void {
  for (const need of permissionRequires(key)) {
    if (out.has(need)) continue;
    out.add(need);
    addRequirements(need, out);
  }
}

/**
 * The grid's new selection once a box is ticked or unticked: ticking a
 * permission ticks what it needs; unticking one unticks what needs it. `next`
 * is the selection as the checkbox group hands it over, `previous` the one
 * before the click.
 */
export function applyPermissionChange(
  previous: readonly string[],
  next: readonly string[],
): string[] {
  const added = next.filter((k) => !previous.includes(k));
  const removed = previous.filter((k) => !next.includes(k));
  const result = new Set(next);
  for (const key of added) addRequirements(key, result);
  // Unticking: whatever still needs a removed key goes too, until stable.
  let changed = removed.length > 0;
  while (changed) {
    changed = false;
    for (const key of [...result]) {
      if (permissionRequires(key).some((need) => !result.has(need))) {
        result.delete(key);
        changed = true;
      }
    }
  }
  // In the catalogue's order, as the grid lists them.
  return PERMISSION_CATALOGUE.map((e) => e.key).filter((k) => result.has(k));
}
