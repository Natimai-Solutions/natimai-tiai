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
  /**
   * A refusal of ours in a 422 (`details.errors[].type` = `tiai_<code>`), by
   * its code: the French is, word for word, the server's `msg` after
   * « Value error, » (shared cases: backend/tests/data/validation_texts_fr.json).
   */
  validation: {
    name_blank: "le nom ne peut pas être vide ou fait seulement d'espaces",
    name_too_long: 'le nom ne doit pas dépasser {max} caractères (reçu : {length})',
    null_refused: '{fields} : valeur requise (null refusé)',
    password_too_long:
      'le mot de passe ne doit pas dépasser {max_bytes} octets ({max_bytes} caractères sans accent, moins avec des accents ou des symboles) : au-delà, la fin ne serait pas prise en compte',
    name_empty: 'le nom ne peut pas être vide',
    date_in_future: 'la date ne peut pas être dans le futur',
    control_character: 'caractère de contrôle refusé',
    too_long: '{max} caractères au plus',
    too_many_arguments: 'au plus {max} arguments',
    argument_refused: 'argument trop long ou contenant un caractère de contrôle',
    arguments_required: "liste d'arguments requise (vide pour aucun argument)",
    success_codes_count: 'entre {min} et {max} codes de succès',
    exit_code_out_of_range: 'code de sortie hors limites',
    name_required: 'nom requis',
    date_before_request: 'la date ne peut pas précéder la demande',
    nul_refused: 'Caractère nul refusé',
    too_nested: 'Corps JSON trop imbriqué',
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
  validation: {
    name_blank: 'the name cannot be empty or made only of spaces',
    name_too_long: 'the name must not exceed {max} characters (received: {length})',
    null_refused: '{fields}: value required (null refused)',
    password_too_long:
      'the password must not exceed {max_bytes} bytes ({max_bytes} unaccented characters, fewer with accents or symbols): beyond that, the end would not count',
    name_empty: 'the name cannot be empty',
    date_in_future: 'the date cannot be in the future',
    control_character: 'control character refused',
    too_long: '{max} characters at most',
    too_many_arguments: 'at most {max} arguments',
    argument_refused: 'argument too long or holding a control character',
    arguments_required: 'list of arguments required (empty for no argument)',
    success_codes_count: 'between {min} and {max} success codes',
    exit_code_out_of_range: 'exit code out of range',
    name_required: 'name required',
    date_before_request: 'the date cannot be before the request',
    nul_refused: 'Null character refused',
    too_nested: 'JSON body nested too deeply',
  },
};

export default { fr, en };
