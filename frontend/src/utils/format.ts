/** Format an ISO timestamp for display, or a dash when absent. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Date(value).toLocaleString('fr-FR');
}

/** Human label for a nullable boolean (e.g. Defender flags). */
export function boolLabel(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return 'Inconnu';
  return value ? 'Oui' : 'Non';
}

/**
 * Label for a machine's logged-on session. A null presence means the agent has
 * never reported one; a user present with no name means the agent is configured
 * to report presence only, so the name never left the machine.
 */
export function sessionLabel(
  present: boolean | null | undefined,
  username: string | null | undefined,
): string {
  if (present === null || present === undefined) return 'Inconnu';
  if (!present) return 'Aucun utilisateur';
  // `||` rather than `??`: an empty string must fall through to the anonymous
  // label too.
  return username || 'Utilisateur connecté';
}

/**
 * Badge colour for a session. Deliberately not positive/negative: someone being
 * logged on is neither good nor bad, unlike `is_up_to_date`.
 */
export function sessionColor(present: boolean | null | undefined): string {
  if (present === null || present === undefined) return 'grey-6';
  return present ? 'primary' : 'grey-5';
}

/** Session kind for the detail row, e.g. "Déconnectée (Bureau à distance)". */
export function sessionTypeLabel(
  state: string | null | undefined,
  isRemote: boolean | null | undefined,
): string {
  if (!state) return '—';
  const base = state === 'active' ? 'Active' : 'Déconnectée';
  return `${base} (${isRemote ? 'Bureau à distance' : 'console'})`;
}
