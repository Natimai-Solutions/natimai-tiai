/**
 * A console URL written in hash form (`/#/machines/…`), turned into its
 * history form (`/machines/…`) — or null when there is nothing to rewrite.
 *
 * From the app-vite 3 upgrade (2026-08-28) until the router read its mode
 * from `import.meta.env`, the build fell back to hash mode: bookmarks and
 * links shared in that time carry `/#/`. The router rewrites them before it
 * starts, so they open the page they name instead of the dashboard.
 */
export function hashUrlToHistory(hash: string, base: string): string | null {
  if (!hash.startsWith('#/')) return null;
  return `${base.replace(/\/$/, '')}${hash.slice(1)}`;
}
