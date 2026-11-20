/**
 * Which console pages an account may open, from its permissions.
 *
 * The menu and the router read the same table: a page the account cannot read
 * is neither offered in the drawer nor rendered — it would only answer 403 to
 * each of its requests. Cosmetic like every client-side check: the backend
 * authorizes each call on its own.
 */

/** The pages an account can land on, in the order the drawer lists them. */
export const LANDING_PAGES: readonly {
  name: string;
  permission: string | readonly string[] | null;
}[] = [
  { name: 'dashboard', permission: 'machine:read' },
  { name: 'machines', permission: 'machine:read' },
  { name: 'alerts', permission: 'machine:read' },
  // An intendance account may read the purchases and not the parc.
  { name: 'assets', permission: 'asset:read' },
  { name: 'software', permission: 'machine:read' },
  { name: 'packages', permission: 'package:read' },
  { name: 'tasks', permission: ['check:read', 'maintenance:read'] },
  { name: 'schedules', permission: 'schedule:read' },
  { name: 'rooms', permission: 'room:read' },
  { name: 'users', permission: 'user:read' },
  { name: 'groups', permission: 'user:read' },
  { name: 'settings', permission: 'settings:read' },
  { name: 'audit', permission: 'audit:read' },
];

/** The page an account with nothing to read lands on (« Aucune page accessible »). */
export const NO_ACCESS_PAGE = 'no-access';

/** Whether `permissions` let the account open a route requiring `required`. */
export function canOpen(permissions: readonly string[], required: unknown): boolean {
  // A list: any one of them opens the page (« Mes tâches »: check:read or
  // maintenance:read, each section shown to whoever reads it).
  if (Array.isArray(required)) {
    return required.some((p) => typeof p === 'string' && permissions.includes(p));
  }
  return typeof required !== 'string' || permissions.includes(required);
}

/** The first page of the drawer the account may read, else « Aucune page accessible ». */
export function firstReadablePage(permissions: readonly string[]): string {
  return LANDING_PAGES.find((p) => canOpen(permissions, p.permission))?.name ?? NO_ACCESS_PAGE;
}

/**
 * Where `/login?redirect=…` may send the reader: a path of this console only —
 * never another site (`//evil.example`, `https://…`), which an attacker could
 * otherwise put in a link to the login page.
 */
export function safeRedirect(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null;
  if (value.startsWith('/\\')) return null;
  return value;
}
