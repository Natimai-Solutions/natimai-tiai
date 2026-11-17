// « Mes tâches » for an account that only owns maintenances (item 5): the
// reminder mails link /tasks, which used to land it on the dashboard.
import { describe, expect, it } from 'vitest';
import type { RouteRecordRaw } from 'vue-router';
import { canOpen } from './access';
import routes from './routes';

function find(records: readonly RouteRecordRaw[], name: string): RouteRecordRaw | undefined {
  for (const r of records) {
    if (r.name === name) return r;
    const inner = r.children ? find(r.children, name) : undefined;
    if (inner) return inner;
  }
  return undefined;
}

describe('the tasks page opens with check:read or maintenance:read', () => {
  const required = find(routes, 'tasks')?.meta?.requiresPermission;

  it('opens for a maintenance-only account', () => {
    expect(canOpen(['maintenance:read', 'maintenance:write'], required)).toBe(true);
  });

  it('opens for a checks-only account', () => {
    expect(canOpen(['check:read'], required)).toBe(true);
  });

  it('stays closed to an account reading neither', () => {
    expect(canOpen(['room:read', 'machine:read'], required)).toBe(false);
  });
});
