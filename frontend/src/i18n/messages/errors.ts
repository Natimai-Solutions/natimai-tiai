import type { Translation } from './types';

/**
 * How an error's details are worded around its message (`services/errors`):
 * the field a validation error names, the groups or postes it lists.
 */
const fr = {
  generic: 'Une erreur est survenue',
  withDetail: '{label} : {detail}',
  field: 'champ « {field} »',
  fieldReason: 'champ « {field} » : {reason}',
  others: ' (et {count} autre(s))',
  groups: '{label} (groupe(s) : {groups})',
  quoted: '« {name} »',
  listSeparator: ', ',
  problemSeparator: ' ; ',
  /** The request fields a validation error most often names, as the forms call them. */
  fields: {
    name: 'nom',
    email: 'adresse e-mail',
    password: 'mot de passe',
    new_password: 'nouveau mot de passe',
    performed_at: 'date',
    note: 'note',
    title: 'titre',
    instructions: 'consignes',
    closed_at: 'date',
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
  },
};

const en: Translation<typeof fr> = {
  generic: 'Something went wrong',
  withDetail: '{label}: {detail}',
  field: 'field “{field}”',
  fieldReason: 'field “{field}”: {reason}',
  others: ' (and {count} more)',
  groups: '{label} (group(s): {groups})',
  quoted: '“{name}”',
  listSeparator: ', ',
  problemSeparator: '; ',
  fields: {
    name: 'name',
    email: 'e-mail address',
    password: 'password',
    new_password: 'new password',
    performed_at: 'date',
    note: 'note',
    title: 'title',
    instructions: 'instructions',
    closed_at: 'date',
    success_codes: 'accepted exit codes',
    install_args: 'install arguments',
    uninstall_args: 'uninstall arguments',
    winget_id: 'winget identifier',
    winget_version: 'winget version',
    version: 'version',
    detect_name: 'name in the inventory',
    ttl_minutes: 'validity',
    maintenance_cycle_days: 'maintenance cycle',
    smtp_host: 'SMTP server',
    smtp_port: 'SMTP port',
    mailgun_base_url: 'Mailgun API URL',
  },
};

export default { fr, en };
