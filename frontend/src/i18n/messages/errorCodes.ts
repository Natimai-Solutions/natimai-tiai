/**
 * API error code → message, in each language of the console.
 *
 * The backend catalogue (`backend/app/core/errors.py`, `ErrorCode`) is the
 * source of the codes; `backend/tests/test_errors_unit.py` checks that each
 * has its line here, and the type of `en` that each French line has its
 * English one. The console maps the stable `code` — never the backend's text.
 *
 * A plain table rather than a vue-i18n catalogue: a code holds dots, which
 * vue-i18n reads as a path, and these texts are shown as they are, never
 * interpolated.
 */
const fr = {
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
  'password.unchanged': 'Le nouveau mot de passe doit être différent de l’actuel',
  'machine.not_found': 'Poste introuvable',
  'machine.merge.self': 'Un poste ne peut pas être fusionné avec lui-même',
  'machine.enrollment.approval_required':
    'Ce poste est déjà enrôlé : son ré-enrôlement attend l’approbation d’un administrateur',
  'machine.enrollment.revoked':
    "Poste révoqué : autorisez le ré-enrôlement depuis sa fiche pour qu'il revienne",
  'machine.token_revoked': "Ce poste a un jeton révoqué : autorisez d'abord son ré-enrôlement",
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
  'asset.not_found': 'Actif introuvable',
  'asset.inventory_number.taken': 'Ce numéro d’inventaire est déjà celui d’un autre actif',
  'asset.machine.taken': 'Ce poste a déjà sa fiche d’actif',
  'asset.import.unreadable':
    'Fichier illisible : un CSV ou un classeur Excel avec une colonne de numéros de série est attendu',
  'asset.import.too_large': 'Fichier trop volumineux pour un import',
  'command.forbidden_window': 'Plage interdite : confirmez pour envoyer quand même',
  'schedule.not_found': 'Planification introuvable',
  'schedule.forbidden_window': 'Cette planification tomberait dans une plage interdite',
  'schedule.in_past': 'Cette date et cette heure sont passées',
  'room.name.taken': 'Une salle porte déjà ce nom dans ce bâtiment',
  'intervention.not_found': 'Intervention introuvable',
  'check.not_found': 'Vérification introuvable',
  'check.already_open': 'Une vérification est déjà ouverte sur ce poste',
  'check.closed': 'Cette vérification est déjà close',
  'check.assignee.out_of_reach':
    'Ce compte ne voit pas ce poste (ou ne lit pas les vérifications) : choisissez quelqu’un dont le périmètre le couvre',
  'maintenance.not_found': 'Séance de maintenance introuvable',
  'maintenance.owner.out_of_reach':
    'Ce compte ne peut pas suivre cette maintenance (droits de maintenance ou périmètre insuffisants) : choisissez quelqu’un dont le périmètre couvre ces postes',
  'room.placement.locked':
    "Les postes sont rangés par l'annuaire (ROOM_SOURCE) : le rattachement manuel est désactivé",
  'room.in_group_scope':
    'Le périmètre d’un groupe nomme ce lieu : retirez-le du groupe avant de le supprimer',
  'maintenance.items.not_in_room': 'Ces postes ne sont pas dans la salle de la séance',
  'maintenance.session.empty':
    'Aucun poste fait : dites pourquoi, par une observation générale ou la note d’un poste non fait',
  'maintenance.session.not_author': 'Seul l’auteur de la séance peut lui ajouter des postes',
  'maintenance.session.id_taken':
    'Cet identifiant de séance est déjà celui de la séance d’un autre compte : enregistrez-la de nouveau',
  'request.validation_error': 'Requête invalide',
  'request.rate_limited': 'Trop de tentatives : réessayez dans quelques minutes',
  'http.not_found': 'Ressource introuvable',
  'http.error': 'Erreur',
  'internal.server_error': 'Erreur interne du serveur',
};

const en: Record<keyof typeof fr, string> = {
  'auth.credentials.invalid': 'Invalid credentials',
  'auth.required': 'Authentication required',
  'auth.permission.denied': 'You do not have the required permission',
  'auth.permission.escalation':
    'Refused: you can only grant the rights you hold yourself, on the places open to you, and you cannot change an account or a group that holds more, nor the rights of a group one of whose members holds more (nor the administrators)',
  'auth.scope.restricted':
    'Refused: your account is limited to some places, and this action goes beyond them',
  'auth.session.invalid': 'Your session has ended: please log in again',
  'auth.session.not_found': 'Session not found or already closed',
  'auth.token.missing': 'Missing token',
  'auth.token.invalid': 'Invalid token',
  'auth.token.revoked': 'Revoked token',
  'auth.enrollment_secret.invalid': 'Invalid enrolment secret',
  'password.current.invalid': 'Current password is incorrect',
  'password.reset_token.invalid': 'This reset link is invalid or has expired',
  'password.unchanged': 'The new password must differ from the current one',
  'machine.not_found': 'Computer not found',
  'machine.merge.self': 'A computer cannot be merged with itself',
  'machine.enrollment.approval_required':
    'This computer is already enrolled: its re-enrolment awaits an administrator’s approval',
  'machine.enrollment.revoked':
    'Computer revoked: allow its re-enrolment from its page for it to come back',
  'machine.token_revoked': 'This computer’s token is revoked: allow its re-enrolment first',
  'user.not_found': 'Account not found',
  'user.email.taken': 'This e-mail address is already in use',
  'user.self.forbidden': 'You cannot apply this action to your own account',
  'user.lockout': 'Refused: no active account would be left to manage accounts',
  'group.not_found': 'Group not found',
  'group.name.taken': 'A group already has this name',
  'group.builtin.protected': 'This built-in group cannot be deleted, nor its rights changed',
  'group.permission.unknown': 'Unknown permission',
  'group.scope.unknown': 'Unknown building or room in the restriction',
  'settings.email.secret_required':
    'The sending server has changed: enter the SMTP password or the Mailgun API key again, which are never sent to a server they were not entered for',
  'package.not_found': 'Package not found',
  'package.file.not_found': 'File not found in this package: it may already have been removed',
  'package.invalid': 'Invalid package',
  'package.file.too_large': 'File too large',
  'package.file.name_invalid': 'File name refused: letters, digits, spaces and . _ - ( ) + only',
  'package.signature.invalid': 'Signature refused',
  'package.not_ready': 'This package cannot be deployed yet',
  'package.retired': 'This package is retired: it can no longer be installed',
  'package.required': 'Choose the package to deploy',
  'building.not_found': 'Building not found',
  'building.name.taken': 'A building already has this name at this location',
  'room.not_found': 'Room not found',
  'asset.not_found': 'Asset not found',
  'asset.inventory_number.taken': 'This inventory number already belongs to another asset',
  'asset.machine.taken': 'This computer already has its asset record',
  'asset.import.unreadable':
    'Unreadable file: a CSV or an Excel workbook with a serial number column is expected',
  'asset.import.too_large': 'File too large for an import',
  'command.forbidden_window': 'Forbidden window: confirm to send it anyway',
  'schedule.not_found': 'Schedule not found',
  'schedule.forbidden_window': 'This schedule would run inside a forbidden window',
  'schedule.in_past': 'This date and time are past',
  'room.name.taken': 'A room already has this name in this building',
  'intervention.not_found': 'Intervention not found',
  'check.not_found': 'Check not found',
  'check.already_open': 'A check is already open on this computer',
  'check.closed': 'This check is already closed',
  'check.assignee.out_of_reach':
    'This account does not see this computer (or does not read checks): choose someone whose scope covers it',
  'maintenance.not_found': 'Maintenance session not found',
  'maintenance.owner.out_of_reach':
    'This account cannot follow this maintenance (insufficient maintenance rights or scope): choose someone whose scope covers these computers',
  'room.placement.locked':
    'Computers are filed by the directory (ROOM_SOURCE): manual placement is disabled',
  'room.in_group_scope':
    'A group’s scope names this place: remove it from the group before deleting it',
  'maintenance.items.not_in_room': 'These computers are not in the session’s room',
  'maintenance.session.empty':
    'No computer done: say why, with a general note or the note of a computer not done',
  'maintenance.session.not_author': 'Only the author of the session can add computers to it',
  'maintenance.session.id_taken':
    'This session identifier already belongs to another account’s session: save it again',
  'request.validation_error': 'Invalid request',
  'request.rate_limited': 'Too many attempts: try again in a few minutes',
  'http.not_found': 'Resource not found',
  'http.error': 'Error',
  'internal.server_error': 'Internal server error',
};

export default { fr, en };
