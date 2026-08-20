import type { EmailPreference } from 'src/services/auth';

/** Format an ISO timestamp for display, or a dash when absent. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Date(value).toLocaleString('fr-FR');
}

/**
 * How long ago an instant was, coarsely — the useful reading next to a presence
 * indicator, where "il y a 2 min" says what an absolute timestamp makes the
 * reader compute. The absolute time stays in the « Vu le » column beside it.
 */
export function timeAgoLabel(value: string | null | undefined): string {
  if (!value) return '—';
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return '—';
  const seconds = Math.round((Date.now() - then) / 1000);
  // Negative means this browser's clock trails the server's. A few seconds of
  // skew is ordinary, and "à l'instant" is truer than a negative age.
  if (seconds < 60) return "à l'instant";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

/**
 * Presence icon for a machine. Filled versus hollow, so the shape carries the
 * state as well as the colour does.
 */
export function onlineIcon(isOnline: boolean): string {
  return isOnline ? 'circle' : 'radio_button_unchecked';
}

/** Presence colour: green while the agent polls, grey once it goes quiet. */
export function onlineColor(isOnline: boolean): string {
  return isOnline ? 'positive' : 'grey-5';
}

/**
 * Presence in words. « Poste allumé » rather than « connecté » to keep it clear
 * of the session column, which is about a *user* being logged on — a machine at
 * its login screen is on with nobody on it. The negative case names both causes
 * the server cannot tell apart: a poste off, and one whose agent cannot reach it.
 */
export function onlineLabel(isOnline: boolean): string {
  return isOnline ? 'Poste allumé' : 'Poste éteint ou injoignable';
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
 *
 * "Non relevé" and not "Inconnu" for the absent case: on a machine whose
 * Defender columns are visibly alive, "Inconnu" reads as the console failing to
 * name an antivirus it can see, and so as a contradiction. The measurement is
 * what is missing, and the label now says which.
 */
export function antivirusLabel(name: string | null | undefined): string {
  if (name === null || name === undefined) return 'Non relevé';
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
  if (name === null || name === undefined) {
    return 'Security Center jamais relevé (agent antérieur, ou hôte sans Security Center)';
  }
  if (name === '') return 'Aucun antivirus enregistré';

  const parts: string[] = [];
  if (enabled === null || enabled === undefined) parts.push('protection à l’état inconnu');
  else parts.push(enabled ? 'protection active' : 'protection désactivée');
  if (signaturesUpToDate === true) parts.push('signatures à jour');
  else if (signaturesUpToDate === false) parts.push('signatures périmées');

  return `${name} — ${parts.join(', ')}`;
}

/**
 * Overall protection state (`is_up_to_date`), spelled out. Unknown is kept
 * apart from "non à jour": a machine the agent could not measure is not the
 * same finding as one measured and found behind.
 */
export function protectionLabel(isUpToDate: boolean | null | undefined): string {
  if (isUpToDate === null || isUpToDate === undefined) return 'État inconnu';
  return isUpToDate ? 'À jour' : 'Non à jour';
}

/** Badge colour for the overall protection state: grey when never computed. */
export function protectionColor(isUpToDate: boolean | null | undefined): string {
  if (isUpToDate === null || isUpToDate === undefined) return 'grey-6';
  return isUpToDate ? 'positive' : 'negative';
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

/**
 * Download ceiling in MiB, or a dash when Windows Update reported none usable.
 *
 * Prefixed with ≤ on purpose. What WUA reports is MaxDownloadSize, the sum of
 * every payload the update could need — full package and express/delta variants,
 * each architecture, each language — where exactly one of them is fetched. A
 * driver ships a single payload and so reads true; a cumulative update or a
 * Defender definition does not, and printing its ceiling as a plain size is what
 * made the column look broken. The sign says what the number is.
 */
export function wuSizeLabel(sizeMb: number | null | undefined): string {
  if (sizeMb === null || sizeMb === undefined) return '—';
  return `≤ ${sizeMb.toLocaleString('fr-FR')} Mio`;
}

/**
 * Threat severity in French. The raw values come from the agent's mapping of
 * MSFT_MpThreat.SeverityID (low / medium / high / severe), with "moderate"
 * accepted too since that is Microsoft's own spelling of the same rating.
 */
export function threatSeverityLabel(severity: string | null | undefined): string {
  switch (severity) {
    case 'low':
      return 'Faible';
    case 'medium':
    case 'moderate':
      return 'Moyenne';
    case 'high':
      return 'Élevée';
    case 'severe':
      return 'Grave';
    case 'unknown':
      return 'Inconnue';
    // Shown as-is rather than swallowed: a rating Defender adds later should
    // surface, not vanish.
    default:
      return severity || '—';
  }
}

/** Badge colour for a threat's severity; unrated stays neutral. */
export function threatSeverityColor(severity: string | null | undefined): string {
  switch (severity) {
    case 'low':
      return 'grey-7';
    case 'medium':
    case 'moderate':
      return 'amber-7';
    case 'high':
      return 'warning';
    case 'severe':
      return 'negative';
    default:
      return 'grey-5';
  }
}

/**
 * Threat status in French — the agent's mapping of
 * MSFT_MpThreatDetection.ThreatStatusID, failures included. "Active" is the one
 * that matters: it is the only status meaning Defender has not dealt with the
 * detection, and it is what the dashboard counts.
 */
export function threatStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case 'active':
      return 'Active';
    case 'cleaned':
      return 'Nettoyée';
    case 'quarantined':
      return 'En quarantaine';
    case 'removed':
      return 'Supprimée';
    case 'allowed':
      return 'Autorisée';
    case 'blocked':
      return 'Bloquée';
    case 'quarantine_failed':
      return 'Échec de mise en quarantaine';
    case 'remove_failed':
      return 'Échec de suppression';
    case 'allow_failed':
      return "Échec d'autorisation";
    case 'block_failed':
      return 'Échec de blocage';
    case 'abandoned':
      return 'Abandonnée';
    case 'unknown':
      return 'Inconnu';
    default:
      return status || '—';
  }
}

/**
 * Badge colour for a threat status. Red for the ones needing a human — untreated
 * or a remediation Defender failed to carry out — green once handled.
 */
export function threatStatusColor(status: string | null | undefined): string {
  switch (status) {
    case 'active':
    case 'quarantine_failed':
    case 'remove_failed':
    case 'block_failed':
      return 'negative';
    case 'cleaned':
    case 'quarantined':
    case 'removed':
    case 'blocked':
      return 'positive';
    case 'allowed':
    case 'abandoned':
      return 'warning';
    default:
      return 'grey-5';
  }
}

/**
 * An address with the mask the poste reported for it: « 10.4.7.9 /16 ».
 *
 * The two belong on one line because neither answers the question alone: the
 * address says where the poste is, the mask says which network that is — and it
 * is the network a wake packet is broadcast on. A missing mask is simply left
 * out rather than filled with a default: the console would otherwise show a
 * value the poste never confirmed.
 */
export function ipAddressLabel(ip: string | null, prefixLength: number | null): string {
  if (!ip) return '—';
  return prefixLength == null ? ip : `${ip} /${prefixLength}`;
}

/**
 * The four e-mail cadences, in the order they are offered: from silence to a
 * message every morning. Each carries the sentence that tells an operator what
 * they will actually receive — « digest » says nothing to someone choosing.
 */
export const EMAIL_PREFERENCE_OPTIONS: {
  value: EmailPreference;
  label: string;
  hint: string;
  icon: string;
}[] = [
  {
    value: 'none',
    label: 'Aucun e-mail',
    hint: "Rien ne vous sera envoyé. Les messages liés au compte, comme la réinitialisation du mot de passe, continuent d'arriver.",
    icon: 'notifications_off',
  },
  {
    value: 'immediate',
    label: 'Alerte immédiate à chaque menace',
    hint: 'Un e-mail dès qu’un poste signale une menace nouvellement détectée. Pas de résumé quotidien.',
    icon: 'notification_important',
  },
  {
    value: 'digest_events',
    label: 'Résumé quotidien, seulement s’il y a du nouveau',
    hint: 'Un e-mail par jour, uniquement les jours où il y a quelque chose à traiter : menace active, mise à jour critique ou importante en attente, poste à vérifier.',
    icon: 'event_note',
  },
  {
    value: 'digest_daily',
    label: 'Résumé quotidien, tous les jours',
    hint: 'Un e-mail chaque matin, même sans incident : état du parc, antivirus périmés, postes à mettre à jour. Un « rien à signaler » est aussi une information.',
    icon: 'calendar_month',
  },
];

/** The chosen cadence in one short phrase, for a list or a badge. */
export function emailPreferenceLabel(preference: string | null | undefined): string {
  return EMAIL_PREFERENCE_OPTIONS.find((o) => o.value === preference)?.label ?? '—';
}
