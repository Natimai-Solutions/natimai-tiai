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
    for (const name of ['dashboard', 'trends', 'machines', 'software', 'machine-detail']) {
      expect(find(name)?.meta?.requiresPermission, name).toBe('machine:read');
    }
  });

  it('has a page for an account that can read nothing, and « Mon compte » for everyone', () => {
    expect(find('no-access')).toBeDefined();
    expect(find('account')?.meta?.requiresPermission).toBeUndefined();
  });
});

/** Every path a route answers, children joined to their parent's. */
function paths(list: RouteRecordRaw[] = routes, prefix = ''): string[] {
  return list.flatMap((r) => {
    const path = r.path.startsWith('/') ? r.path : `${prefix.replace(/\/$/, '')}/${r.path}`;
    return [path, ...(r.children ? paths(r.children, path) : [])];
  });
}

describe('paths and the server in front of the console', () => {
  it('keeps every page out of /assets, where nginx serves the build and never the console', () => {
    // `nginx.conf`: `location ^~ /assets/` answers 404 rather than
    // index.html, and `/assets` itself resolves to that directory — a page
    // there loads in the app but not on a reload, a bookmark or a new tab.
    for (const path of paths()) {
      expect(path === '/assets' || path.startsWith('/assets/'), path).toBe(false);
    }
  });

  it('opens Matériels and its labels at /equipment', () => {
    expect(find('assets')?.path).toBe('equipment');
    expect(find('asset-labels')?.path).toBe('/equipment/labels');
  });
});
