/**
 * Words for the audit log. The backend records stable slugs (`machine.merge`,
 * `user`) and a free-form `details` object; the console words both here, in
 * the reader's language (`src/i18n/messages/audit.ts`), and falls back on the
 * raw slug for anything it does not know yet — an action added server-side
 * must show up readable enough, never as a blank.
 *
 * Every text is worded when asked for, never once at load: the language can
 * change while the page is open.
 */

import { commandTypeLabel } from 'src/services/commands';
import { intlTag, t } from 'src/i18n';
import auditMessages from 'src/i18n/messages/audit';

/** The shape of the catalogue — the same in both languages. */
const CATALOGUE = auditMessages.fr;

function hasOwn(node: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(node, key);
}

/** Whether `path` names a text of `tree` — own properties only, so that a slug
 *  or a key such as `toString` or `a.b` is never mistaken for one. */
function hasText(tree: unknown, path: readonly string[]): boolean {
  let node = tree;
  for (const part of path) {
    if (typeof node !== 'object' || node === null || !hasOwn(node, part)) return false;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === 'string';
}

/** Every leaf of a nested table, as dotted paths. */
function leafPaths(tree: object, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [`${prefix}${key}`]
      : leafPaths(value as object, `${prefix}${key}.`),
  );
}

/**
 * Action slug → catalogue key of its label (`audit.actions.<slug>`). One entry
 * per `audit.record(action=…)` call of the backend; the label itself is
 * `auditActionLabel(slug)`, worded when it is shown.
 */
export const AUDIT_ACTION_LABELS: Record<string, string> = Object.fromEntries(
  leafPaths(CATALOGUE.actions).map((slug) => [slug, `audit.actions.${slug}`]),
);

/** Resource type → catalogue key of its label, in the order the filter offers them. */
export const AUDIT_RESOURCE_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  Object.keys(CATALOGUE.resourceTypes).map((type) => [type, `audit.resourceTypes.${type}`]),
);

/** Detail key → catalogue key of its label, for the full view of an entry. */
export const AUDIT_DETAIL_KEY_LABELS: Record<string, string> = Object.fromEntries(
  Object.keys(CATALOGUE.detailKeys).map((key) => [key, `audit.detailKeys.${key}`]),
);

/** Whether the console has a label for an action slug. */
export function isKnownAuditAction(action: string): boolean {
  return hasText(CATALOGUE.actions, action.split('.'));
}

/** A readable label for an action slug; the slug itself when unknown. */
export function auditActionLabel(action: string): string {
  return isKnownAuditAction(action) ? t(`audit.actions.${action}`) : action;
}

/** A readable label for a resource type; the type itself when unknown. */
export function auditResourceTypeLabel(type: string): string {
  return hasText(CATALOGUE.resourceTypes, [type]) ? t(`audit.resourceTypes.${type}`) : type;
}

/** A readable label for a details key; the key itself when unknown. */
export function auditDetailKeyLabel(key: string): string {
  return hasText(CATALOGUE.detailKeys, [key]) ? t(`audit.detailKeys.${key}`) : key;
}

/** Options for the resource type filter, in the catalogue's order. */
export function auditResourceTypeOptions(): { value: string; label: string }[] {
  return Object.keys(AUDIT_RESOURCE_TYPE_LABELS).map((value) => ({
    value,
    label: auditResourceTypeLabel(value),
  }));
}

/** Options for the action filter: the given slugs, deduplicated, sorted by label. */
export function auditActionOptions(slugs: readonly string[]): { value: string; label: string }[] {
  const locale = intlTag();
  return [...new Set(slugs)]
    .map((value) => ({ value, label: auditActionLabel(value) }))
    .sort((a, b) => a.label.localeCompare(b.label, locale));
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Whether a string is a UUID — what a link to a fiche needs. */
export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_RE.test(value);
}

/**
 * Where an entry's resource can be opened in the console, or null. Only postes
 * have a fiche worth linking to. For `machine.merge` the id is the *kept*
 * record, which still exists — the merged one is gone, and stays text.
 */
export function auditResourceLink(
  resourceType: string,
  resourceId: string,
): { name: 'machine-detail'; params: { id: string } } | null {
  return resourceType === 'machine' && isUuid(resourceId)
    ? { name: 'machine-detail', params: { id: resourceId } }
    : null;
}

/** How the server records a test e-mail's outcome (`ok`): values, not text shown. */
const [OK_YES, OK_NO] = ['oui', 'non']; // i18n-ignore — stored values, worded by the catalogue

/**
 * One detail value as text: lists joined, booleans in words, objects as JSON.
 * `key` names the detail, for the few whose values have words of their own.
 */
export function auditDetailValue(value: unknown, key?: string): string {
  if (key === 'via' && typeof value === 'string' && hasText(CATALOGUE.values.via, [value])) {
    return t(`audit.values.via.${value}`);
  }
  // A test e-mail's outcome, stored in French words by the server.
  if (key === 'ok' && value === OK_YES) return t('audit.values.okYes');
  if (key === 'ok' && value === OK_NO) return t('audit.values.okNo');
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? t('audit.values.yes') : t('audit.values.no');
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return value.toLocaleString(intlTag());
  if (Array.isArray(value)) {
    if (!value.length) return '—';
    return value.every((v) => typeof v !== 'object' || v === null)
      ? value.map((v) => auditDetailValue(v)).join(', ')
      : JSON.stringify(value, null, 2);
  }
  return JSON.stringify(value, null, 2);
}

/** A string detail, or null. */
function text(details: Record<string, unknown>, key: string): string | null {
  const value = details[key];
  return typeof value === 'string' && value ? value : null;
}

/** A number detail, or null. */
function count(details: Record<string, unknown>, key: string): number | null {
  const value = details[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** `{count} …` in the reader's language, the plural chosen by `n`. */
function counted(key: string, n: number): string {
  return t(key, { count: n }, n);
}

/** What a bulk command was aimed at, in a few words; null when unreadable. */
function bulkTarget(details: Record<string, unknown>): string | null {
  switch (details.target) {
    case 'all':
      return t('audit.summary.target.all');
    case 'domain': {
      // "" is a real target: the postes that are in no domain.
      const domain = details.domain;
      if (typeof domain !== 'string') return null;
      return domain
        ? t('audit.summary.target.domain', { domain })
        : t('audit.summary.target.noDomain');
    }
    case 'location': {
      const location = text(details, 'location');
      return location ? t('audit.summary.target.location', { location }) : null;
    }
    case 'status': {
      const status = text(details, 'status');
      if (!status) return null;
      return hasText(CATALOGUE.summary.target.statuses, [status])
        ? t(`audit.summary.target.statuses.${status}`)
        : t('audit.summary.target.status', { status });
    }
    case 'machines': {
      const requested = count(details, 'requested');
      return requested === null ? null : counted('audit.summary.target.listed', requested);
    }
    default:
      return null;
  }
}

/** A lifetime in minutes, in the largest whole unit: 60 → 1 h, 2880 → 2 j. */
export function formatTtlMinutes(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) {
    return t('audit.ttl.days', { count: minutes / 1440 });
  }
  if (minutes >= 60 && minutes % 60 === 0) return t('audit.ttl.hours', { count: minutes / 60 });
  return t('audit.ttl.minutes', { count: minutes });
}

/** Keys the summary already spells out, or that only matter in the full view. */
const SUMMARY_SUBJECT_KEYS = ['hostname', 'email', 'name', 'title'];

/**
 * One line saying what an entry was about — the subject (poste, compte,
 * salle…) and what changed — for the table. The full `details` stay one click
 * away; this line is for scanning, and never has to be exhaustive.
 */
export function auditDetailsSummary(action: string, details: Record<string, unknown>): string {
  const parts: string[] = [];

  const subject = SUMMARY_SUBJECT_KEYS.map((k) => text(details, k)).find((v) => v !== null);
  if (subject) parts.push(subject);

  // Right after the subject: how many postes, before what happened to them.
  const machineIds = details.machine_ids;
  if (Array.isArray(machineIds)) parts.push(counted('audit.summary.machines', machineIds.length));

  if (action === 'machine.merge') {
    const source =
      text(details, 'source_hostname') ??
      text(details, 'source_machine_uuid') ??
      text(details, 'source_id');
    if (source) parts.push(t('audit.summary.absorbed', { source }));
    // A confined reader is not told which record a poste of its scope absorbed
    // when that record stood elsewhere (audit S17): say so rather than nothing.
    else if (details.source_withheld === true) {
      parts.push(t('audit.summary.absorbedWithheld'));
    }
  }

  if (action === 'user.reset_password' && typeof details.generated === 'boolean') {
    parts.push(
      details.generated ? t('audit.summary.passwordGenerated') : t('audit.summary.passwordTyped'),
    );
  }

  if (action === 'command.bulk') {
    const type = text(details, 'command_type');
    if (type) parts.push(commandTypeLabel(type));
    const target = bulkTarget(details);
    if (target) parts.push(target);
    const created = count(details, 'created');
    const skipped = count(details, 'skipped');
    const ttl = count(details, 'ttl_minutes');
    if (created !== null) parts.push(counted('audit.summary.created', created));
    // Only when some were: "0 ignorée(s)" on every line would be noise.
    if (skipped) parts.push(counted('audit.summary.skipped', skipped));
    if (ttl !== null) parts.push(t('audit.summary.validFor', { ttl: formatTtlMinutes(ttl) }));
  }

  if (action === 'machine.wake_bulk') {
    const woken = count(details, 'woken');
    const failed = count(details, 'failed');
    // In relay mode an "ok" is a wake handed to a poste of the site, not a
    // packet the server sent: the line must not promise more than that.
    if (woken !== null) {
      parts.push(
        details.relayed === true
          ? counted('audit.summary.wokenRelayed', woken)
          : counted('audit.summary.woken', woken),
      );
    }
    if (failed) parts.push(counted('audit.summary.wakeFailed', failed));
  }

  if (action === 'room.sync_directory') {
    const placed = count(details, 'placed');
    const unplaced = count(details, 'unplaced');
    const created = count(details, 'rooms_created');
    if (placed !== null) parts.push(counted('audit.summary.placed', placed));
    if (unplaced !== null) parts.push(counted('audit.summary.unplaced', unplaced));
    if (created !== null) parts.push(counted('audit.summary.roomsCreated', created));
  }

  if (action === 'settings.email_test') {
    // Who received it and whether it left: the two things an auditor asks.
    const to = details.to;
    if (typeof to === 'string' && to) parts.push(t('audit.summary.emailTo', { to }));
    if (details.ok === OK_YES) parts.push(t('audit.summary.emailSent'));
    else if (details.ok === OK_NO) parts.push(t('audit.summary.emailFailed'));
  }

  const fields = details.fields;
  if (Array.isArray(fields) && fields.length) {
    parts.push(t('audit.summary.fields', { fields: fields.map((f) => String(f)).join(', ') }));
  } else if (
    action === 'settings.update' ||
    action === 'maintenance.machine_settings' ||
    action === 'maintenance.room_settings'
  ) {
    // These record the changed values themselves, keyed by field.
    const changed = Object.keys(details).filter((k) => !SUMMARY_SUBJECT_KEYS.includes(k));
    if (changed.length) parts.push(t('audit.summary.fields', { fields: changed.join(', ') }));
  }

  return parts.length ? parts.join(' · ') : '—';
}
