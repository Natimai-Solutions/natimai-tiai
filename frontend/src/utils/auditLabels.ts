/**
 * Words for the audit log. The backend records stable slugs (`machine.merge`,
 * `user`) and a free-form `details` object; the console turns both into French
 * here, and falls back on the raw slug for anything it does not know yet — an
 * action added server-side must show up readable enough, never as a blank.
 */

import { commandTypeLabel } from 'src/services/commands';

/** Action slug → label. Mirrors the `audit.record(action=…)` calls of the backend. */
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  'building.create': "Création d'un bâtiment",
  'building.update': "Modification d'un bâtiment",
  'building.delete': "Suppression d'un bâtiment",
  'check.update': "Mise à jour d'une vérification",
  'command.bulk': 'Commande envoyée à plusieurs postes',
  'group.create': "Création d'un groupe",
  'group.update': "Modification d'un groupe",
  'group.delete': "Suppression d'un groupe",
  'intervention.update': "Modification d'une intervention",
  'intervention.delete': "Suppression d'une intervention",
  'machine.allow_reenroll': 'Ré-enrôlement autorisé',
  'machine.revoke_token': "Révocation du token d'un poste",
  'machine.merge': 'Fusion de deux fiches poste',
  'machine.wake_bulk': 'Réveil groupé de postes',
  'maintenance.machine_settings': "Réglage de maintenance d'un poste",
  'maintenance.room_settings': "Réglage de maintenance d'une salle",
  'room.create': "Création d'une salle",
  'room.update': "Modification d'une salle",
  'room.delete': "Suppression d'une salle",
  'room.place_machines': 'Affectation de postes à une salle',
  'room.sync_directory': "Synchronisation des salles avec l'annuaire",
  'room.unassign_machines': 'Retrait de postes de leur salle',
  'settings.update': 'Modification des paramètres',
  'settings.email_test': "Envoi d'un e-mail de test",
  'auth.session_revoked': "Fermeture d'une session console",
  'user.create': "Création d'un compte",
  'user.update': "Modification d'un compte",
  'user.delete': "Suppression d'un compte",
  'user.reset_password': "Réinitialisation d'un mot de passe",
};

/** Resource type → label, in the order the filter offers them. */
export const AUDIT_RESOURCE_TYPE_LABELS: Record<string, string> = {
  machine: 'Poste',
  command: 'Commande',
  room: 'Salle',
  building: 'Bâtiment',
  intervention: 'Intervention',
  check: 'Vérification',
  user: 'Compte',
  group: 'Groupe',
  settings: 'Paramètres',
};

/** Detail key → label, for the full view of an entry. */
export const AUDIT_DETAIL_KEY_LABELS: Record<string, string> = {
  to: 'Destinataire',
  current: 'Session en cours',
  user_agent: 'Appareil',
  ip: 'Adresse IP',
  created_at: 'Ouverte le',
  provider: 'Fournisseur',
  ok: 'Réussi',
  unsaved: 'Valeurs essayées sans être enregistrées',
  message: 'Résultat',
  hostname: 'Nom du poste',
  machine_uuid: 'UUID du poste',
  machine_id: 'Poste',
  machine_ids: 'Postes',
  source_id: 'Fiche fusionnée (id)',
  source_hostname: 'Fiche fusionnée (nom)',
  source_machine_uuid: 'Fiche fusionnée (UUID)',
  email: 'E-mail',
  generated: 'Mot de passe généré',
  group_ids: 'Groupes',
  permissions: 'Droits',
  name: 'Nom',
  location: 'Emplacement',
  building_id: 'Bâtiment',
  fields: 'Champs modifiés',
  title: 'Titre',
  kind: 'Type',
  author: 'Auteur',
  performed_at: "Date de l'intervention",
  assigned_to_id: 'Affectée à',
  source: 'Source',
  placed: 'Postes placés',
  unplaced: 'Postes non placés',
  rooms_created: 'Salles créées',
  command_type: 'Commande',
  target: 'Cible',
  domain: 'Domaine',
  status: 'Statut visé',
  requested: 'Postes demandés',
  created: 'Commandes créées',
  skipped: 'Postes ignorés (commande déjà en cours)',
  ttl_minutes: 'Durée de vie (minutes)',
  woken: 'Réveils émis ou confiés',
  failed: 'Échecs',
  relayed: 'Confié à un poste relais',
};

/** A readable label for an action slug; the slug itself when unknown. */
export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action;
}

/** A readable label for a resource type; the type itself when unknown. */
export function auditResourceTypeLabel(type: string): string {
  return AUDIT_RESOURCE_TYPE_LABELS[type] ?? type;
}

/** A readable label for a details key; the key itself when unknown. */
export function auditDetailKeyLabel(key: string): string {
  return AUDIT_DETAIL_KEY_LABELS[key] ?? key;
}

/** Options for the action filter: the given slugs, deduplicated, sorted by label. */
export function auditActionOptions(slugs: readonly string[]): { value: string; label: string }[] {
  return [...new Set(slugs)]
    .map((value) => ({ value, label: auditActionLabel(value) }))
    .sort((a, b) => a.label.localeCompare(b.label, 'fr'));
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

/** One detail value as text: lists joined, booleans in words, objects as JSON. */
export function auditDetailValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Oui' : 'Non';
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return value.toLocaleString('fr-FR');
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

/** The console's words for a status filter, as a bulk command's target. */
const TARGET_STATUS_LABELS: Record<string, string> = {
  up_to_date: 'à jour',
  outdated: 'non à jour',
  needs_verification: 'à vérifier',
  inactive: 'inactifs',
};

/** What a bulk command was aimed at, in a few words; null when unreadable. */
function bulkTarget(details: Record<string, unknown>): string | null {
  switch (details.target) {
    case 'all':
      return 'tout le parc';
    case 'domain': {
      // "" is a real target: the postes that are in no domain.
      const domain = details.domain;
      if (typeof domain !== 'string') return null;
      return domain ? `domaine « ${domain} »` : 'postes hors domaine';
    }
    case 'location': {
      const location = text(details, 'location');
      return location ? `emplacement « ${location} »` : null;
    }
    case 'status': {
      const status = text(details, 'status');
      return status ? `postes ${TARGET_STATUS_LABELS[status] ?? status}` : null;
    }
    case 'machines': {
      const requested = count(details, 'requested');
      return requested === null ? null : `${requested} poste(s) listé(s)`;
    }
    default:
      return null;
  }
}

/** A lifetime in minutes, in the largest whole unit: 60 → 1 h, 2880 → 2 j. */
export function formatTtlMinutes(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) return `${minutes / 1440} j`;
  if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60} h`;
  return `${minutes} min`;
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
  if (Array.isArray(machineIds)) parts.push(`${machineIds.length} poste(s)`);

  if (action === 'machine.merge') {
    const source =
      text(details, 'source_hostname') ??
      text(details, 'source_machine_uuid') ??
      text(details, 'source_id');
    if (source) parts.push(`a absorbé « ${source} »`);
  }

  if (action === 'user.reset_password' && typeof details.generated === 'boolean') {
    parts.push(details.generated ? 'mot de passe généré' : 'mot de passe saisi');
  }

  if (action === 'command.bulk') {
    const type = text(details, 'command_type');
    if (type) parts.push(commandTypeLabel(type));
    const target = bulkTarget(details);
    if (target) parts.push(target);
    const created = count(details, 'created');
    const skipped = count(details, 'skipped');
    const ttl = count(details, 'ttl_minutes');
    if (created !== null) parts.push(`${created} créée(s)`);
    // Only when some were: "0 ignorée(s)" on every line would be noise.
    if (skipped) parts.push(`${skipped} ignorée(s), déjà en cours`);
    if (ttl !== null) parts.push(`valable ${formatTtlMinutes(ttl)}`);
  }

  if (action === 'machine.wake_bulk') {
    const woken = count(details, 'woken');
    const failed = count(details, 'failed');
    // In relay mode an "ok" is a wake handed to a poste of the site, not a
    // packet the server sent: the line must not promise more than that.
    if (woken !== null) {
      parts.push(details.relayed === true ? `${woken} confié(s) à un relais` : `${woken} émis`);
    }
    if (failed) parts.push(`${failed} en échec`);
  }

  if (action === 'room.sync_directory') {
    const placed = count(details, 'placed');
    const unplaced = count(details, 'unplaced');
    const created = count(details, 'rooms_created');
    if (placed !== null) parts.push(`${placed} poste(s) placé(s)`);
    if (unplaced !== null) parts.push(`${unplaced} non placé(s)`);
    if (created !== null) parts.push(`${created} salle(s) créée(s)`);
  }

  if (action === 'settings.email_test') {
    // Who received it and whether it left: the two things an auditor asks.
    const to = details.to;
    if (typeof to === 'string' && to) parts.push(`à ${to}`);
    if (details.ok === 'oui') parts.push('envoyé');
    else if (details.ok === 'non') parts.push('échec');
  }

  const fields = details.fields;
  if (Array.isArray(fields) && fields.length) {
    parts.push(`champs : ${fields.map((f) => String(f)).join(', ')}`);
  } else if (
    action === 'settings.update' ||
    action === 'maintenance.machine_settings' ||
    action === 'maintenance.room_settings'
  ) {
    // These record the changed values themselves, keyed by field.
    const changed = Object.keys(details).filter((k) => !SUMMARY_SUBJECT_KEYS.includes(k));
    if (changed.length) parts.push(`champs : ${changed.join(', ')}`);
  }

  return parts.length ? parts.join(' · ') : '—';
}
