import type { Translation } from './types';

/**
 * What the server says of a package, worded here from its codes and
 * parameters (`utils/packageText`). The French is, word for word, the
 * sentence the server writes in `message` — the console reads the same in
 * French before and after the update.
 *
 * Literal braces are written `{'{'}` and `{'}'}`: vue-i18n reads a bare brace
 * as a placeholder.
 */
const fr = {
  /** `problems[].code`, and `untrusted` by its `params.reason`. */
  problems: {
    no_files: 'Aucun fichier déposé',
    no_install: 'Fichier à lancer non choisi',
    install_missing: "« {file} » n'est pas dans le paquet",
    install_removes:
      "L'installation lance une désinstallation (msiexec /x, /uninstall ou REMOVE=) : placez cette commande dans la désinstallation du paquet",
    uninstall_missing: "« {file} » n'est pas dans le paquet",
    duplicate_names:
      'Fichiers dont le nom ne diffère que par la casse (un seul fichier sous Windows, les postes refusent le paquet) : {groups} — retirez ceux en trop',
    file_missing_in_store:
      'Fichier absent du stockage du serveur : {files} — déposez-le de nouveau',
    method_a_too_large:
      "Plus de {gib} Gio de fichiers : sans signature de l'administrateur, aucun poste ne les téléchargera (plafond de la méthode A). Signez le paquet.",
    no_uninstall: 'Pas de désinstallation définie',
    untrusted: {
      msiexec_uninstall:
        "Paquet non signé, et sa désinstallation lance msiexec sans code produit {'{'}…{'}'} parmi ses arguments : la méthode A ne lance msiexec que pour « /x {'{'}code produit{'}'} » : aucun poste ne l'exécutera. Signez le paquet.",
      msiexec_install:
        "Paquet non signé, et son installation lance msiexec : la méthode A ne lance qu'un exécutable (.exe) signé par un éditeur : aucun poste ne l'exécutera. Signez le paquet.",
      not_exe:
        "Paquet non signé, et « {file} » n'est pas un exécutable (.exe) : la méthode A ne lance qu'un .exe signé par un éditeur : aucun poste ne l'exécutera. Signez le paquet.",
      no_publisher:
        "Paquet non signé, et « {file} » ne porte pas de signature d'éditeur (Authenticode) : la méthode A ne le lance pas : aucun poste ne l'exécutera. Signez le paquet.",
      loadable:
        "Paquet non signé, et {files} est à côté de « {file} » : la méthode A refuse tout fichier que Windows pourrait charger ou lancer (.dll, .exe, .msi, scripts…) à côté de l'exécutable — retirez-le du paquet, ou signez-le : en l'état, aucun poste ne l'exécutera. | Paquet non signé, et {files} sont à côté de « {file} » : la méthode A refuse tout fichier que Windows pourrait charger ou lancer (.dll, .exe, .msi, scripts…) à côté de l'exécutable — retirez-les du paquet, ou signez-le : en l'état, aucun poste ne l'exécutera.",
      other:
        "Paquet non signé, et la méthode A ne le lance pas : aucun poste ne l'exécutera. Signez le paquet.",
    },
  },
  /** `package.invalid`: `details.cause.code`. */
  invalid: {
    winget_id_invalid: 'Identifiant winget invalide (ex. Mozilla.Firefox)',
    winget_version_invalid: 'Version winget invalide',
    winget_runs_file: 'Un paquet winget ne lance pas de fichier',
    files_with_winget_id: "Un paquet de fichiers n'a pas d'identifiant winget",
    run_file_refused: 'Fichier à lancer « {file} » refusé : {refusal}',
    msiexec_uninstall_args_required:
      "Désinstallation par msiexec : indiquer les arguments (ex. /x {'{'}code produit{'}'} /qn)",
    msiexec_install_args_required:
      "Installation par msiexec : indiquer les arguments (ex. /i {'{'}dir{'}'}\\app.msi /qn)",
    install_removes:
      "L'installation lance une désinstallation (msiexec /x, /uninstall ou REMOVE=) : placez cette commande dans la désinstallation du paquet",
    winget_has_no_files: "Ce paquet est un paquet winget : il n'a pas de fichiers",
  },
  /** A refused file name (`package.file.name_invalid`, `run_file_refused`). */
  fileName: {
    refused: '« {name} » refusé : {reason}',
    reasons: {
      empty: 'nom vide',
      forbidden_characters:
        'caractère interdit {characters} (permis : lettres sans accent, chiffres, espaces et . _ - ( ) +) | caractères interdits {characters} (permis : lettres sans accent, chiffres, espaces et . _ - ( ) +)',
      too_long: 'plus de {max} caractères',
      bad_first_character: 'le nom doit commencer par une lettre sans accent ou un chiffre',
      reserved:
        "nom réservé par Windows (CON, PRN, AUX, NUL, COM1 à COM9, LPT1 à LPT9, quelle que soit l'extension)",
      bad_ending: 'le nom ne doit finir ni par un point ni par une espace',
      refused: 'nom refusé par les postes',
      same_name_but_case:
        'même nom que « {other} » à la casse près (un seul fichier sous Windows) : envoyez-en un seul',
    },
  },
  /** `package.signature.invalid`: `details.cause.code`. */
  signature: {
    missing_field: {
      signature: 'La signature est absent du fichier de signature.',
      certificate: 'Le certificat est absent du fichier de signature.',
    },
    bad_base64: {
      signature:
        "La signature n'est pas encodé en base64 valide : le fichier a-t-il été modifié après sa production ?",
      certificate:
        "Le certificat n'est pas encodé en base64 valide : le fichier a-t-il été modifié après sa production ?",
    },
    not_json: "Le fichier de signature n'est pas du JSON.",
    not_object:
      "Le fichier de signature n'est pas un objet JSON ({'{'} … {'}'}) : déposez le fichier .sig.json produit par Sign-TiaiPackage.ps1.",
    unknown_format:
      "Format de signature inconnu (« {expected} » attendu) : ce fichier n'a pas été produit par Sign-TiaiPackage.ps1.",
    unsupported_algorithm:
      'Algorithme de signature non pris en charge : seuls « rsa-pkcs1-sha256 » et « ecdsa-sha256 » sont acceptés.',
    unreadable_certificate:
      'Certificat illisible : le champ « certificate » ne contient pas un certificat X.509 (DER encodé en base64).',
    algorithm_key_mismatch:
      "L'algorithme annoncé (« {algorithm} ») ne correspond pas à la clé du certificat ({key}) : la signature a été produite pour un autre certificat ou modifiée à la main.",
    keys: {
      rsa: 'clé RSA',
      ecdsa: 'clé ECDSA',
      other: "clé d'un type non pris en charge",
    },
    stale_manifest:
      'La signature ne correspond pas au manifeste actuel : le paquet a changé depuis le téléchargement du manifeste signé. Téléchargez de nouveau le manifeste et signez-le.',
    other_certificate:
      "La signature n'a pas été faite avec la clé du certificat joint : signée avec un autre certificat que celui du fichier.",
    mismatch:
      "La signature ne correspond pas : soit le manifeste a changé depuis qu'il a été signé (téléchargez-le de nouveau et signez-le), soit elle a été faite avec un autre certificat que celui du fichier.",
  },
  quoted: '« {name} »',
  listSeparator: ', ',
  groupSeparator: ' ; ',
};

const en: Translation<typeof fr> = {
  problems: {
    no_files: 'No file uploaded',
    no_install: 'No file to run chosen',
    install_missing: '“{file}” is not in the package',
    install_removes:
      'The installation runs an uninstallation (msiexec /x, /uninstall or REMOVE=): put this command in the package’s uninstallation',
    uninstall_missing: '“{file}” is not in the package',
    duplicate_names:
      'Files whose names differ only by case (one single file on Windows, the computers refuse the package): {groups} — remove the extra ones',
    file_missing_in_store: 'File missing from the server’s storage: {files} — upload it again',
    method_a_too_large:
      'More than {gib} GiB of files: without the administrator’s signature, no computer will download them (method A’s cap). Sign the package.',
    no_uninstall: 'No uninstallation defined',
    untrusted: {
      msiexec_uninstall:
        "Unsigned package, and its uninstallation runs msiexec without a product code {'{'}…{'}'} among its arguments: method A runs msiexec only for “/x {'{'}product code{'}'}”: no computer will run it. Sign the package.",
      msiexec_install:
        'Unsigned package, and its installation runs msiexec: method A only runs an executable (.exe) signed by a publisher: no computer will run it. Sign the package.',
      not_exe:
        'Unsigned package, and “{file}” is not an executable (.exe): method A only runs an .exe signed by a publisher: no computer will run it. Sign the package.',
      no_publisher:
        'Unsigned package, and “{file}” bears no publisher signature (Authenticode): method A does not run it: no computer will run it. Sign the package.',
      loadable:
        'Unsigned package, and {files} is next to “{file}”: method A refuses any file Windows could load or run (.dll, .exe, .msi, scripts…) next to the executable — remove it from the package, or sign it: as it stands, no computer will run it. | Unsigned package, and {files} are next to “{file}”: method A refuses any file Windows could load or run (.dll, .exe, .msi, scripts…) next to the executable — remove them from the package, or sign it: as it stands, no computer will run it.',
      other:
        'Unsigned package, and method A does not run it: no computer will run it. Sign the package.',
    },
  },
  invalid: {
    winget_id_invalid: 'Invalid winget identifier (e.g. Mozilla.Firefox)',
    winget_version_invalid: 'Invalid winget version',
    winget_runs_file: 'A winget package runs no file',
    files_with_winget_id: 'A files package has no winget identifier',
    run_file_refused: 'File to run “{file}” refused: {refusal}',
    msiexec_uninstall_args_required:
      "Uninstallation by msiexec: give the arguments (e.g. /x {'{'}product code{'}'} /qn)",
    msiexec_install_args_required:
      "Installation by msiexec: give the arguments (e.g. /i {'{'}dir{'}'}\\app.msi /qn)",
    install_removes:
      'The installation runs an uninstallation (msiexec /x, /uninstall or REMOVE=): put this command in the package’s uninstallation',
    winget_has_no_files: 'This package is a winget package: it has no files',
  },
  fileName: {
    refused: '“{name}” refused: {reason}',
    reasons: {
      empty: 'empty name',
      forbidden_characters:
        'forbidden character {characters} (allowed: unaccented letters, digits, spaces and . _ - ( ) +) | forbidden characters {characters} (allowed: unaccented letters, digits, spaces and . _ - ( ) +)',
      too_long: 'more than {max} characters',
      bad_first_character: 'the name must start with an unaccented letter or a digit',
      reserved:
        'name reserved by Windows (CON, PRN, AUX, NUL, COM1 to COM9, LPT1 to LPT9, whatever the extension)',
      bad_ending: 'the name must end with neither a dot nor a space',
      refused: 'name refused by the computers',
      same_name_but_case:
        'same name as “{other}” but for case (one single file on Windows): send only one',
    },
  },
  signature: {
    missing_field: {
      signature: 'The signature is missing from the signature file.',
      certificate: 'The certificate is missing from the signature file.',
    },
    bad_base64: {
      signature: 'The signature is not valid base64: was the file changed after it was produced?',
      certificate:
        'The certificate is not valid base64: was the file changed after it was produced?',
    },
    not_json: 'The signature file is not JSON.',
    not_object:
      "The signature file is not a JSON object ({'{'} … {'}'}): upload the .sig.json file produced by Sign-TiaiPackage.ps1.",
    unknown_format:
      'Unknown signature format (“{expected}” expected): this file was not produced by Sign-TiaiPackage.ps1.',
    unsupported_algorithm:
      'Unsupported signature algorithm: only “rsa-pkcs1-sha256” and “ecdsa-sha256” are accepted.',
    unreadable_certificate:
      'Unreadable certificate: the “certificate” field does not hold an X.509 certificate (DER, base64-encoded).',
    algorithm_key_mismatch:
      'The announced algorithm (“{algorithm}”) does not match the certificate’s key ({key}): the signature was produced for another certificate or edited by hand.',
    keys: {
      rsa: 'RSA key',
      ecdsa: 'ECDSA key',
      other: 'key of an unsupported type',
    },
    stale_manifest:
      'The signature does not match the current manifest: the package has changed since the signed manifest was downloaded. Download the manifest again and sign it.',
    other_certificate:
      'The signature was not made with the key of the attached certificate: signed with another certificate than the file’s.',
    mismatch:
      'The signature does not match: either the manifest changed since it was signed (download it again and sign it), or it was made with another certificate than the file’s.',
  },
  quoted: '“{name}”',
  listSeparator: ', ',
  groupSeparator: '; ',
};

export default { fr, en };
