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

/**
 * Label for the antivirus registered with the Windows Security Center.
 *
 * Three states, deliberately distinct: an absent name means the agent never
 * reported one (too old, or a host with no Security Center — Windows Server has
 * none), while an *empty* name means the registry was read and holds nothing,
 * i.e. the machine runs no antivirus at all. Collapsing the two would hide a
 * finding behind a missing measurement.
 */
export function antivirusLabel(name: string | null | undefined): string {
  if (name === null || name === undefined) return 'Inconnu';
  return name === '' ? 'Aucun' : name;
}

/** Badge colour for the antivirus cell: red for none or stopped, grey for unknown. */
export function antivirusColor(
  name: string | null | undefined,
  enabled: boolean | null | undefined,
): string {
  if (name === null || name === undefined) return 'grey-6';
  // No antivirus at all is the one case that is unambiguously bad.
  if (name === '') return 'negative';
  if (enabled === null || enabled === undefined) return 'grey-7';
  return enabled ? 'positive' : 'negative';
}

/**
 * Sentence describing the registered antivirus, for the tooltip and the detail
 * card. The signature clause is dropped when the product reports no freshness
 * bit — vendors fill it in unevenly, and inventing "à jour" would be a claim the
 * Security Center never made.
 */
export function antivirusStatusLabel(
  name: string | null | undefined,
  enabled: boolean | null | undefined,
  signaturesUpToDate: boolean | null | undefined,
): string {
  if (name === null || name === undefined) return "Jamais remonté par l'agent";
  if (name === '') return 'Aucun antivirus enregistré';

  const parts: string[] = [];
  if (enabled === null || enabled === undefined) parts.push('protection à l’état inconnu');
  else parts.push(enabled ? 'protection active' : 'protection désactivée');
  if (signaturesUpToDate === true) parts.push('signatures à jour');
  else if (signaturesUpToDate === false) parts.push('signatures périmées');

  return `${name} — ${parts.join(', ')}`;
}

/**
 * Defender's execution mode (AMRunningMode), spelled out.
 *
 * The raw values are English identifiers, and "Passive" on its own tells an admin
 * nothing about *why* the antivirus flags above it read "Non" — so the passive
 * modes say so. An unrecognised value is shown as-is rather than swallowed: a
 * future Windows mode should surface, not vanish.
 */
export function runningModeLabel(mode: string | null | undefined): string {
  if (!mode) return '—';
  switch (mode) {
    case 'Normal':
      return 'Normal';
    case 'Passive':
    case 'SxS Passive Mode':
      return 'Passif (un antivirus tiers protège le poste)';
    case 'EDR Block Mode':
      return 'EDR en mode blocage';
    default:
      return mode;
  }
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

/**
 * Label for the pending-update count. A null count is not zero: it means the
 * agent has never reported a Windows Update search — too old for the feature,
 * or a machine whose WU service could not be queried — and showing "0" there
 * would credit a machine we know nothing about.
 */
export function wuPendingLabel(count: number | null | undefined): string {
  if (count === null || count === undefined) return 'Inconnu';
  return count === 0 ? 'À jour' : String(count);
}

/** Badge colour for the pending count: grey unknown, green none, amber some. */
export function wuPendingColor(count: number | null | undefined): string {
  if (count === null || count === undefined) return 'grey-6';
  return count === 0 ? 'positive' : 'warning';
}

/**
 * Badge colour for an update's MSRC severity. Only the ratings Microsoft
 * actually publishes are coloured; anything else — most updates are unrated —
 * stays neutral rather than being ranked by guesswork.
 */
export function wuSeverityColor(severity: string | null | undefined): string {
  switch (severity) {
    case 'critical':
      return 'negative';
    case 'important':
      return 'warning';
    case 'moderate':
      return 'amber-7';
    case 'low':
      return 'grey-7';
    default:
      return 'grey-5';
  }
}

/** MSRC severity in French, or a dash for the many updates carrying no rating. */
export function wuSeverityLabel(severity: string | null | undefined): string {
  switch (severity) {
    case 'critical':
      return 'Critique';
    case 'important':
      return 'Importante';
    case 'moderate':
      return 'Modérée';
    case 'low':
      return 'Faible';
    // Shown as-is rather than swallowed: a rating Microsoft adds later should
    // surface, not vanish.
    default:
      return severity || '—';
  }
}

/** Update kind, spelled out: the distinction the two install commands hinge on. */
export function wuTypeLabel(type: string | null | undefined): string {
  if (type === 'driver') return 'Pilote';
  if (type === 'software') return 'Logicielle';
  return type || '—';
}

/** Download size in MiB, or a dash when Windows Update reported none. */
export function wuSizeLabel(sizeMb: number | null | undefined): string {
  if (sizeMb === null || sizeMb === undefined) return '—';
  return `${sizeMb.toLocaleString('fr-FR')} Mio`;
}
