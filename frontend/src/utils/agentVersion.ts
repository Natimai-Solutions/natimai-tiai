/**
 * Whether a poste's agent is behind the parc's reference version.
 *
 * The reference comes from the server (`agent_latest_version` on the list, the
 * fiche and the dashboard): the highest version reported anywhere on the parc,
 * or the one pinned in its configuration. What is decided here is only the
 * comparison, and it mirrors the server's own (`agent_version.py`) so a poste
 * the list flags is a poste the "obsolète" filter returns.
 */

/** "0.4.2", "v0.4.2", "0.4.2-dev.abc1234" → numbers, release flag, suffix. */
function versionKey(version: string): { numbers: number[]; release: number; pre: string } {
  let text = version.trim();
  if (text.startsWith('v') || text.startsWith('V')) text = text.slice(1);
  const dash = text.indexOf('-');
  const main = dash === -1 ? text : text.slice(0, dash);
  const pre = dash === -1 ? '' : text.slice(dash + 1);
  const numbers = (main.match(/\d+/g) ?? []).map(Number);
  // A release outranks its own pre-releases; the suffix only orders those.
  return { numbers, release: pre ? 0 : 1, pre };
}

/** Negative when `a` is older than `b`, positive when newer, 0 when equal. */
export function compareVersions(a: string, b: string): number {
  const ka = versionKey(a);
  const kb = versionKey(b);
  const len = Math.max(ka.numbers.length, kb.numbers.length);
  for (let i = 0; i < len; i++) {
    const diff = (ka.numbers[i] ?? -1) - (kb.numbers[i] ?? -1);
    if (diff !== 0) return diff;
  }
  if (ka.release !== kb.release) return ka.release - kb.release;
  return ka.pre.localeCompare(kb.pre);
}

/**
 * Behind the reference. Unknown on either side is *not* behind: a poste that
 * never reported a version is a question, not a straggler — and on an empty
 * parc there is nothing to be behind.
 */
export function isAgentOutdated(version: string | null, latest: string | null): boolean {
  if (!version || !latest) return false;
  return compareVersions(version, latest) < 0;
}

/** The identity row's wording: the version, and where it stands. */
export function agentVersionLabel(version: string | null, latest: string | null): string {
  if (!version) return '—';
  if (!latest) return version;
  if (isAgentOutdated(version, latest)) return `${version} — obsolète (référence ${latest})`;
  return `${version} — à jour`;
}
