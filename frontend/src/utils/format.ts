import type { EmailPreference } from 'src/services/auth';
import { intlTag, t } from 'src/i18n';

/**
 * A number the French way — decimal comma, narrow space between thousands —
 * with exactly `digits` decimals. The one formatter of the console: « 2.3 Gio »
 * beside « 7,5 h » read as two different notations.
 */
export function frNumber(value: number, digits = 0): string {
  return value.toLocaleString(intlTag(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** A table cell's text, or « — » for nothing to show (null, undefined, blank). */
export function dash(value: string | number | null | undefined): string {
  if (value == null) return '—';
  const text = String(value);
  return text.trim() ? text : '—';
}

/** Format an ISO timestamp for display, or a dash when absent. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Date(value).toLocaleString(intlTag());
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
  if (seconds < 60) return t('format.timeAgo.now');
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t('format.timeAgo.minutes', { count: minutes }, minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('format.timeAgo.hours', { count: hours }, hours);
  const days = Math.floor(hours / 24);
  return t('format.timeAgo.days', { count: days }, days);
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
  return t(isOnline ? 'format.online.on' : 'format.online.off');
}

/** Human label for a nullable boolean (e.g. Defender flags). */
export function boolLabel(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return t('format.bool.unknown');
  return t(value ? 'format.bool.yes' : 'format.bool.no');
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
  if (present === null || present === undefined) return t('format.session.unknown');
  if (!present) return t('format.session.none');
  // `||` rather than `??`: an empty string must fall through to the anonymous
  // label too.
  return username || t('format.session.anonymous');
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
  if (name === null || name === undefined) return t('format.antivirus.notReported');
  return name === '' ? t('format.antivirus.none') : name;
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
 * Colour of the antivirus badge, on the fiche and in the machine list's
 * column alike: grey or red while the product itself is unknown or missing
 * (the badge then reads « Non relevé » or « Aucun », audit U28) — never green
 * because Defender alone is up to date — and otherwise the protection state:
 * a named antivirus whose signatures are stale is red, never green.
 */
export function antivirusBadgeColor(
  name: string | null | undefined,
  isUpToDate: boolean | null | undefined,
): string {
  if (name === null || name === undefined || name === '') return antivirusColor(name, null);
  return protectionColor(isUpToDate);
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
    return t('format.antivirus.neverReported');
  }
  if (name === '') return t('format.antivirus.noneRegistered');

  const parts: string[] = [];
  if (enabled === null || enabled === undefined)
    parts.push(t('format.antivirus.protectionUnknown'));
  else {
    parts.push(
      t(enabled ? 'format.antivirus.protectionActive' : 'format.antivirus.protectionDisabled'),
    );
  }
  if (signaturesUpToDate === true) parts.push(t('format.antivirus.signaturesUpToDate'));
  else if (signaturesUpToDate === false) parts.push(t('format.antivirus.signaturesOutdated'));

  return t('format.antivirus.status', {
    name,
    parts: parts.join(t('format.antivirus.partSeparator')),
  });
}

/**
 * Overall protection state (`is_up_to_date`), spelled out. Unknown is kept
 * apart from "non à jour": a machine the agent could not measure is not the
 * same finding as one measured and found behind.
 */
export function protectionLabel(isUpToDate: boolean | null | undefined): string {
  if (isUpToDate === null || isUpToDate === undefined) return t('format.protection.unknown');
  return t(isUpToDate ? 'format.protection.upToDate' : 'format.protection.notUpToDate');
}

/**
 * The antivirus badge of the fleet list: the product, and its state in words
 * when it is not good news. The colour alone said « périmé » to whoever can
 * tell red from green, and to nobody else.
 */
export function protectionBadgeLabel(
  productLabel: string,
  isUpToDate: boolean | null | undefined,
): string {
  if (isUpToDate === true) return productLabel;
  if (isUpToDate === false)
    return t('format.protection.badgeNotUpToDate', { product: productLabel });
  return t('format.protection.badgeUnknown', { product: productLabel });
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
      return t('format.runningMode.normal');
    case 'Passive':
    case 'SxS Passive Mode':
      return t('format.runningMode.passive');
    case 'EDR Block Mode':
      return t('format.runningMode.edrBlock');
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
  return t('format.sessionType.line', {
    state: t(state === 'active' ? 'format.sessionType.active' : 'format.sessionType.disconnected'),
    kind: t(isRemote ? 'format.sessionType.remote' : 'format.sessionType.console'),
  });
}

/**
 * Label for the pending-update count. A null count is not zero: it means the
 * agent has never reported a Windows Update search — too old for the feature,
 * or a machine whose WU service could not be queried — and showing "0" there
 * would credit a machine we know nothing about.
 */
export function wuPendingLabel(count: number | null | undefined): string {
  if (count === null || count === undefined) return t('format.wuPending.unknown');
  return count === 0 ? t('format.wuPending.upToDate') : String(count);
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
    case 'important':
    case 'moderate':
    case 'low':
      return t(`format.wuSeverity.${severity}`);
    // Shown as-is rather than swallowed: a rating Microsoft adds later should
    // surface, not vanish.
    default:
      return severity || '—';
  }
}

/** Update kind, spelled out: the distinction the two install commands hinge on. */
export function wuTypeLabel(type: string | null | undefined): string {
  if (type === 'driver') return t('format.wuType.driver');
  if (type === 'software') return t('format.wuType.software');
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
  return t('format.wuSize', { size: sizeMb.toLocaleString(intlTag()) });
}

/**
 * Threat severity in French. The raw values come from the agent's mapping of
 * MSFT_MpThreat.SeverityID (low / medium / high / severe), with "moderate"
 * accepted too since that is Microsoft's own spelling of the same rating.
 */
export function threatSeverityLabel(severity: string | null | undefined): string {
  switch (severity) {
    case 'low':
      return t('format.threatSeverity.low');
    case 'medium':
    case 'moderate':
      return t('format.threatSeverity.medium');
    case 'high':
      return t('format.threatSeverity.high');
    case 'severe':
      return t('format.threatSeverity.severe');
    case 'unknown':
      return t('format.threatSeverity.unknown');
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
    case 'cleaned':
    case 'quarantined':
    case 'removed':
    case 'allowed':
    case 'blocked':
    case 'quarantine_failed':
    case 'remove_failed':
    case 'allow_failed':
    case 'block_failed':
    case 'abandoned':
    case 'unknown':
      return t(`format.threatStatus.${status}`);
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
 * One cadence, its words read from the catalogue each time they are shown:
 * the list itself is built once, its label and hint follow the language.
 */
function emailPreferenceOption(value: EmailPreference, icon: string) {
  return {
    value,
    icon,
    get label(): string {
      return t(`format.emailPreference.${value}.label`);
    },
    get hint(): string {
      return t(`format.emailPreference.${value}.hint`);
    },
  };
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
  emailPreferenceOption('none', 'notifications_off'),
  emailPreferenceOption('immediate', 'notification_important'),
  emailPreferenceOption('digest_events', 'event_note'),
  emailPreferenceOption('digest_daily', 'calendar_month'),
];

/** The chosen cadence in one short phrase, for a list or a badge. */
export function emailPreferenceLabel(preference: string | null | undefined): string {
  return EMAIL_PREFERENCE_OPTIONS.find((o) => o.value === preference)?.label ?? '—';
}

// --- Inventory ---------------------------------------------------------------

/**
 * A size in mebibytes, rendered in the unit a human would use.
 *
 * Binary units throughout (Mio, Gio, Tio), because that is what the source
 * reports: Windows divides by 1024 and so does everything the figure will be
 * compared against — the properties dialog, the disk manager. Rendering 1024 Mio
 * as "1.07 Go" would be arithmetically defensible and would not match a single
 * other screen the reader has open.
 */
export function sizeLabel(mb: number | null | undefined): string {
  if (mb == null) return '—';
  if (mb < 1024) return t('format.size.mib', { size: Math.round(mb) });
  const gib = mb / 1024;
  if (gib < 1024) {
    // One decimal below ten, none above: "3,5 Gio" is useful, "487,3 Gio" is not.
    return t('format.size.gib', { size: gib < 10 ? frNumber(gib, 1) : Math.round(gib) });
  }
  return t('format.size.tib', { size: frNumber(gib / 1024, 1) });
}

/** Free space as a whole percentage, or null when there is nothing to divide. */
export function freePercent(
  totalMb: number | null | undefined,
  freeMb: number | null | undefined,
): number | null {
  if (!totalMb || freeMb == null) return null;
  return Math.round((freeMb / totalMb) * 100);
}

/**
 * The colour of a volume's occupancy bar.
 *
 * Two thresholds, and the lower one is not decorative: below roughly ten percent
 * Windows Update stops being able to stage a cumulative update, so a poste
 * crosses it and then quietly stops patching. That is the moment the bar has to
 * be red.
 */
export function diskColor(percentFree: number | null, lowPercent?: number): string {
  if (percentFree == null) return 'grey-5';
  const { critical, warning } = diskThresholds(lowPercent);
  if (percentFree < critical) return 'negative';
  if (percentFree < warning) return 'orange';
  return 'positive';
}

/** The parc's default « disque presque plein » threshold, as the server ships it. */
export const DEFAULT_LOW_DISK_PERCENT = 10;

/**
 * The two disk thresholds from the parc's setting (« Paramètres » → seuil
 * d'espace libre): red below it, orange within ten points above it — 10/20 %
 * with the default. Read from the server rather than hard-coded, so that the
 * fiche, the list and the dashboard card all count the same postes.
 */
export function diskThresholds(lowPercent?: number | null): { critical: number; warning: number } {
  const critical =
    typeof lowPercent === 'number' && lowPercent > 0 ? lowPercent : DEFAULT_LOW_DISK_PERCENT;
  return { critical, warning: critical + 10 };
}

/** The media types worded by the catalogue (`format.mediaType`). */
const MEDIA_TYPES = new Set(['SSD', 'HDD', 'NVMe', 'SCM', 'unknown']);

/**
 * A drive's media type in words.
 *
 * "Type inconnu" is a real answer and not a missing one: the WMI class that
 * always responds cannot tell an SSD from a hard disk, and a host without the
 * Storage namespace falls back to it. Saying so beats an empty cell that reads
 * as a bug.
 */
export function mediaTypeLabel(value: string | null | undefined): string {
  if (!value) return '—';
  return MEDIA_TYPES.has(value) ? t(`format.mediaType.${value}`) : value;
}

const CHASSIS_TYPES = new Set(['desktop', 'laptop', 'tablet', 'all-in-one', 'server']);

export function chassisLabel(value: string | null | undefined): string {
  if (!value) return '—';
  return CHASSIS_TYPES.has(value) ? t(`format.chassis.${value}`) : value;
}

const ENCRYPTION_STATES = new Set([
  'FullyEncrypted',
  'FullyDecrypted',
  'EncryptionInProgress',
  'DecryptionInProgress',
  'EncryptionPaused',
  'DecryptionPaused',
]);

/**
 * BitLocker status in words. null is "non relevé", which is deliberately *not*
 * "non chiffré": the WMI class is absent on some SKUs and needs elevation, and
 * an alarm on a machine that may well be encrypted is how a dashboard gets
 * ignored.
 */
export function encryptionLabel(value: string | null | undefined): string {
  if (!value) return t('format.encryption.notReported');
  return ENCRYPTION_STATES.has(value) ? t(`format.encryption.${value}`) : value;
}

export function encryptionColor(value: string | null | undefined): string {
  if (!value) return 'grey-6';
  if (value === 'FullyEncrypted') return 'positive';
  if (value === 'FullyDecrypted') return 'negative';
  return 'orange';
}

const NIC_TYPES = new Set(['ethernet', 'wifi', 'other']);

export function nicTypeLabel(value: string | null | undefined): string {
  if (!value) return '—';
  return NIC_TYPES.has(value) ? t(`format.nicType.${value}`) : value;
}

/** A link speed in the unit it is quoted in — 1 Gb/s, not 1000 Mb/s. */
export function linkSpeedLabel(mbps: number | null | undefined): string {
  if (mbps == null) return '—';
  if (mbps >= 1000) {
    const gbps = mbps / 1000;
    return t('format.linkSpeed.gbps', { speed: Number.isInteger(gbps) ? gbps : frNumber(gbps, 1) });
  }
  return t('format.linkSpeed.mbps', { speed: mbps });
}

/**
 * A CPU in one line: model, then what it actually has.
 *
 * The core and thread counts are appended rather than given rows of their own
 * because they are read together — "un i7 8 cœurs" is one fact, not three.
 */
export function cpuLabel(
  model: string | null,
  cores: number | null,
  threads: number | null,
  count: number | null,
): string {
  if (!model) return '—';
  const parts: string[] = [];
  if (count && count > 1) parts.push(t('format.cpu.processors', { count }));
  if (cores) parts.push(t('format.cpu.cores', { count: cores }, cores));
  if (threads) parts.push(t('format.cpu.threads', { count: threads }, threads));
  if (!parts.length) return model;
  return t('format.cpu.line', { model, parts: parts.join(t('format.cpu.partSeparator')) });
}

/** RAM as "32 Gio (2 barrettes sur 4)" — the sentence an upgrade decision needs. */
export function ramLabel(
  totalMb: number | null,
  slotsUsed: number | null,
  slotsTotal: number | null,
): string {
  if (totalMb == null) return '—';
  const size = sizeLabel(totalMb);
  if (slotsUsed == null || slotsTotal == null || slotsTotal === 0) return size;
  return t('format.ram', { size, used: slotsUsed, total: slotsTotal });
}

/**
 * A date without its time, for the fields that are dates: a BIOS release, an
 * install date. `formatDateTime` would append a midnight nobody reported.
 *
 * Read from the string, never through `new Date()`: the API sends a pure
 * `AAAA-MM-JJ`, which `Date` takes for midnight UTC — the day before, in
 * Papeete. A calendar date has no zone to convert from.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return '—';
  const [, year, month, day] = match;
  const probe = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (probe.getUTCDate() !== Number(day)) return '—';
  return `${day}/${month}/${year}`;
}

/**
 * Hand a fetched blob to the browser as a download.
 *
 * The exports are fetched rather than linked because the API needs the
 * Authorization header; this is what turns the response back into a file.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** The browser tab title for a page: « Postes — Tia'i », or the bare name. */
export function documentTitle(page?: string | null): string {
  return page ? `${page} — Tia'i` : "Tia'i";
}

/**
 * A threat's name as Defender reported it — or « (sans nom) » when it reported
 * a blank one, which used to leave an empty cell that read as a rendering bug.
 */
export function threatNameLabel(name: string | null | undefined, fallback?: string | null): string {
  if (name && name.trim()) return name;
  if (fallback && fallback.trim()) return fallback;
  return t('format.threatNameless');
}
