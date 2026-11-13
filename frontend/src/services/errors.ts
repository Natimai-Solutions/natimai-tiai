import type { AxiosError } from 'axios';

/** Standard API error envelope (mirrors the backend, plan §2.14). */
export interface ApiErrorBody {
  error: {
    code: string;
    message?: string;
    details?: Record<string, unknown>;
  };
}

/**
 * Code → localized message. The backend catalog (app/core/errors.py,
 * ErrorCode) is the source of truth; keep this table in sync. The console maps
 * the stable `code` — never the backend text — so messages stay localizable.
 */
export const ERROR_MESSAGES: Record<string, string> = {
  'auth.credentials.invalid': 'Identifiants invalides',
  'auth.required': 'Authentification requise',
  'auth.permission.denied': "Vous n'avez pas la permission requise",
  'auth.permission.escalation':
    'Refusé : vous ne pouvez accorder que les droits que vous détenez vous-même, sur les emplacements qui vous sont ouverts, et ne pouvez pas modifier un compte ou un groupe qui en détient davantage, ni les droits d’un groupe dont un membre en détient davantage (ni les administrateurs)',
  'auth.scope.restricted':
    'Refusé : votre compte est limité à certains emplacements, et cette action en sort',
  'auth.session.invalid': 'Votre session a pris fin : reconnectez-vous',
  'auth.session.not_found': 'Session introuvable ou déjà fermée',
  'auth.token.missing': 'Jeton manquant',
  'auth.token.invalid': 'Jeton invalide',
  'auth.token.revoked': 'Jeton révoqué',
  'auth.enrollment_secret.invalid': "Secret d'enrôlement invalide",
  'password.current.invalid': 'Mot de passe actuel incorrect',
  'password.reset_token.invalid': 'Ce lien de réinitialisation est invalide ou a expiré',
  'machine.not_found': 'Poste introuvable',
  'machine.merge.self': 'Un poste ne peut pas être fusionné avec lui-même',
  'machine.enrollment.approval_required':
    'Ce poste est déjà enrôlé : son ré-enrôlement attend l’approbation d’un administrateur',
  'machine.enrollment.revoked':
    "Poste révoqué : autorisez le ré-enrôlement depuis sa fiche pour qu'il revienne",
  'user.not_found': 'Compte introuvable',
  'user.email.taken': 'Cette adresse e-mail est déjà utilisée',
  'user.self.forbidden': 'Vous ne pouvez pas appliquer cette action à votre propre compte',
  'user.lockout': 'Refusé : plus aucun compte actif ne pourrait gérer les comptes',
  'group.not_found': 'Groupe introuvable',
  'group.name.taken': 'Un groupe porte déjà ce nom',
  'group.builtin.protected': 'Ce groupe intégré ne peut pas être supprimé, ni ses droits modifiés',
  'group.permission.unknown': 'Permission inconnue',
  'group.scope.unknown': 'Bâtiment ou salle inconnus dans la restriction',
  'settings.email.secret_required':
    'Le serveur d’envoi a changé : ressaisissez le mot de passe SMTP ou la clé API Mailgun, qui ne sont jamais envoyés à un serveur pour lequel ils n’ont pas été saisis',
  'package.not_found': 'Paquet introuvable',
  'package.file.not_found': 'Fichier introuvable dans ce paquet : il a peut-être déjà été retiré',
  'package.invalid': 'Paquet invalide',
  'package.file.too_large': 'Fichier trop volumineux',
  'package.file.name_invalid':
    'Nom de fichier refusé : lettres, chiffres, espaces et . _ - ( ) + seulement',
  'package.signature.invalid': 'Signature refusée',
  'package.not_ready': "Ce paquet n'est pas encore déployable",
  'package.retired': 'Ce paquet est retiré : il ne peut plus être installé',
  'package.required': 'Choisissez le paquet à déployer',
  'building.not_found': 'Bâtiment introuvable',
  'building.name.taken': 'Un bâtiment porte déjà ce nom sur cet emplacement',
  'room.not_found': 'Salle introuvable',
  'room.name.taken': 'Une salle porte déjà ce nom dans ce bâtiment',
  'intervention.not_found': 'Intervention introuvable',
  'check.not_found': 'Vérification introuvable',
  'check.already_open': 'Une vérification est déjà ouverte sur ce poste',
  'check.closed': 'Cette vérification est déjà close',
  'check.assignee.out_of_reach':
    'Ce compte ne voit pas ce poste (ou ne lit pas les vérifications) : choisissez quelqu’un dont le périmètre le couvre',
  'maintenance.not_found': 'Séance de maintenance introuvable',
  'room.placement.locked':
    "Les postes sont rangés par l'annuaire (ROOM_SOURCE) : le rattachement manuel est désactivé",
  'request.validation_error': 'Requête invalide',
  'request.rate_limited': 'Trop de tentatives : réessayez dans quelques minutes',
  'http.not_found': 'Ressource introuvable',
  'http.error': 'Erreur',
  'internal.server_error': 'Erreur interne du serveur',
};

/** Extract the stable error code from an API error, if present. */
export function apiErrorCode(err: unknown): string | null {
  const body = (err as AxiosError<ApiErrorBody>)?.response?.data;
  return body?.error?.code ?? null;
}

/**
 * Codes whose backend message is written for the console user, in French, and
 * says what to correct: shown after the label rather than dropped (audit U03).
 */
const USER_FACING_MESSAGES = new Set(['package.invalid']);

/** The request fields a validation error most often names, as the forms call them. */
const FIELD_LABELS: Record<string, string> = {
  name: 'nom',
  email: 'adresse e-mail',
  password: 'mot de passe',
  new_password: 'nouveau mot de passe',
  performed_at: 'date',
  note: 'note',
  title: 'titre',
  instructions: 'consignes',
  success_codes: 'codes de sortie acceptés',
  install_args: 'arguments d’installation',
  uninstall_args: 'arguments de désinstallation',
  winget_id: 'identifiant winget',
  winget_version: 'version winget',
  version: 'version',
  detect_name: 'nom dans l’inventaire',
  ttl_minutes: 'durée de validité',
  maintenance_cycle_days: 'cycle de maintenance',
  smtp_host: 'serveur SMTP',
  smtp_port: 'port SMTP',
  mailgun_base_url: 'URL de l’API Mailgun',
};

interface ValidationItem {
  loc?: (string | number)[];
  msg?: string;
}

/** « champ — raison » for the first field a 422 names, in the console's words. */
function validationDetail(details: Record<string, unknown> | undefined): string | null {
  const errors = details?.errors;
  if (!Array.isArray(errors) || errors.length === 0) return null;
  const first = errors[0] as ValidationItem;
  // The location starts with where the field was (body, query); the last
  // name in it is the field, past any list index.
  const names = (first.loc ?? []).filter(
    (p): p is string => typeof p === 'string' && !['body', 'query', 'path'].includes(p),
  );
  const field = names[names.length - 1];
  const label = field ? (FIELD_LABELS[field] ?? field) : null;
  // A ValueError raised by the backend in French reads « Value error, … ».
  const reason = (first.msg ?? '').replace(/^Value error, /, '');
  const more = errors.length > 1 ? ` (et ${errors.length - 1} autre(s))` : '';
  if (label && reason) return `champ « ${label} » : ${reason}${more}`;
  if (label) return `champ « ${label} »${more}`;
  return reason || null;
}

/**
 * Resolve a user-facing message for an API error: the localized message for the
 * code — completed, where the backend says what to correct, by its own words
 * or by the field a validation error names — else the backend-provided message,
 * else the caller's fallback.
 */
export function apiErrorMessage(err: unknown, fallback = 'Une erreur est survenue'): string {
  const response = (err as AxiosError<ApiErrorBody>)?.response;
  const body = response?.data;
  const code = body?.error?.code;
  // Refused by the proxy in front of the API, which answers without the
  // error envelope (audit U16).
  if (!code && response?.status === 413)
    return ERROR_MESSAGES['package.file.too_large'] ?? fallback;
  if (code && ERROR_MESSAGES[code]) {
    const label = ERROR_MESSAGES[code];
    if (USER_FACING_MESSAGES.has(code) && body?.error?.message) {
      return `${label} : ${body.error.message}`;
    }
    if (code === 'request.validation_error') {
      const detail = validationDetail(body?.error?.details);
      if (detail) return `${label} : ${detail}`;
    }
    if (code === 'package.not_ready') {
      const problems = body?.error?.details?.problems;
      if (Array.isArray(problems) && problems.length) {
        return `${label} : ${problems.join(' ; ')}`;
      }
    }
    return label;
  }
  return body?.error?.message ?? fallback;
}
