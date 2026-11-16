import { describe, expect, it } from 'vitest';
import type { RouteRecordRaw } from 'vue-router';
import routes from './routes';

function find(name: string, list: RouteRecordRaw[] = routes): RouteRecordRaw | undefined {
  for (const r of list) {
    if (r.name === name) return r;
    const child = r.children && find(name, r.children);
    if (child) return child;
  }
  return undefined;
}

describe('routes (item 4)', () => {
  it('puts the parc pages behind machine:read, so a forbidden account is sent elsewhere', () => {
    for (const name of ['dashboard', 'machines', 'software', 'machine-detail']) {
      expect(find(name)?.meta?.requiresPermission, name).toBe('machine:read');
    }
  });

  it('has a page for an account that can read nothing, and « Mon compte » for everyone', () => {
    expect(find('no-access')).toBeDefined();
    expect(find('account')?.meta?.requiresPermission).toBeUndefined();
  });
});
