import type { Translation } from './types';

/**
 * La page Paramètres (lot C1 du plan console bilingue). The e-mail card's
 * « il manque … » and the test e-mail's outcome are worded here from the codes
 * the server sends (`utils/emailSettings.ts`); their French is the server's,
 * word for word — `backend/tests/data/settings_texts_fr.json` holds them to it.
 */
const fr = {
  title: 'Paramètres',
  save: 'Enregistrer',
  saved: 'Paramètres enregistrés',
  saveFailed: 'Enregistrement impossible',
  loadFailed: 'Chargement impossible',
  units: {
    days: 'jours',
    hours: 'heures',
    percentFree: '% libres',
    years: 'ans',
    minutes: 'minutes',
  },
  // 0 = Monday … 6 = Sunday, as the server numbers them.
  weekdays: {
    monday: 'lundi',
    tuesday: 'mardi',
    wednesday: 'mercredi',
    thursday: 'jeudi',
    friday: 'vendredi',
    saturday: 'samedi',
    sunday: 'dimanche',
  },
  maintenance: {
    title: 'Maintenance',
    caption:
      'Les défauts du parc. Une salle ou un poste peut les remplacer ; la valeur la plus précise gagne.',
    cycle: 'Cycle par défaut',
    cycleHint: "0 = aucune maintenance par défaut · variable d'environnement : {days} jours",
    owner: 'Responsable par défaut',
    ownerHint:
      "Reçoit dans « Mes tâches » les salles et postes qui n'ont pas de responsable propre",
    ownerDeactivated: 'Compte désactivé : {name}',
    dueSoon: 'Fenêtre « à échéance »',
    dueSoonHint:
      "Un poste est signalé à échéance ce nombre de jours avant sa date — au plus la moitié de son cycle · variable d'environnement : {days} jours",
  },
  usage: {
    title: 'Utilisation des postes',
    caption:
      'Ce que comptent les cartes « Peu utilisés » et « Toujours allumés » du tableau de bord, et le filtre Utilisation de la liste des postes.',
    windowDays: "Fenêtre d'observation",
    windowHint:
      "Les heures sont comptées sur ce nombre de jours glissants · variable d'environnement : {days} jours",
    lowHours: 'Poste peu utilisé en dessous de',
    lowHint:
      "Un poste enrôlé pendant la fenêtre n'est jamais compté peu utilisé · variable d'environnement : {hours} heures",
    highHours: 'Poste toujours allumé au-dessus de',
    highHint: "variable d'environnement : {hours} heures",
  },
  alerts: {
    title: 'Alertes',
    caption:
      'Les règles que le serveur vérifie toutes les cinq minutes sur ce que les postes remontent. Une alerte s’ouvre et se résout toute seule.',
    rules: 'Règles actives',
    autoCheck: 'Ouvrir une vérification',
    autoCheckHint:
      'Une nouvelle alerte de ces règles ouvre une vérification sur le poste, s’il n’en a pas déjà une.',
    rebootDays: 'Redémarrage en attente au-delà de',
    rebootHint: "variable d'environnement : {days} jours",
    warrantyDays: 'Fin de garantie signalée',
    warrantyHint:
      "Jours avant la fin de garantie d'un poste · variable d'environnement : {days} jours",
    unencryptedScope: 'Volume système non chiffré : postes concernés',
    scopeLaptops: 'Portables et tablettes seulement',
    scopeAll: 'Tous les postes',
    forbidden: 'Logiciels interdits',
    forbiddenHint:
      'Un morceau du nom du programme, deux caractères au moins (Entrée pour ajouter) · insensible à la casse',
  },
  reports: {
    title: 'Signalements des utilisateurs',
    caption:
      'Le QR de l’étiquette d’un poste ouvre, à qui le scanne sans compte, un formulaire pour signaler un problème. Les signalements arrivent dans une file à trier.',
    enabled: 'Ouvrir le formulaire de signalement',
    hint: "Fermé, le QR mène à la connexion, comme avant · variable d'environnement : {value}",
    on: 'ouvert',
    off: 'fermé',
    privacy:
      'Le contact laissé est facultatif et supprimé avec le signalement : à porter au registre des traitements.',
  },
  planning: {
    title: 'Planifications',
    caption:
      'Le fuseau dans lequel la console planifie, et les plages où rien de risqué ne part sur plusieurs postes (les heures de cours).',
    timezone: 'Fuseau horaire',
    timezoneHint: "Nom IANA, par exemple Pacific/Tahiti · variable d'environnement : {zone}",
    windows: 'Plages interdites',
    windowsHint:
      'Une planification à risque n’y est pas acceptée ; une commande à risque envoyée à plusieurs postes y demande une confirmation de plus. Une commande sur un seul poste reste libre.',
    windowDays: 'Jours',
    windowStart: 'De',
    windowEnd: 'À',
    addWindow: 'Ajouter une plage',
    removeWindow: 'Retirer la plage',
    windowInvalid: 'Des jours, et une fin après le début',
  },
  fleet: {
    title: 'Supervision du parc',
    caption:
      'Les seuils qui décident de ce que la console signale sur un poste. Appliqués aussitôt, sans redémarrer le serveur.',
    signatureMaxAge: 'Base antivirus périmée au-delà de',
    signatureMaxAgeHint:
      "Âge des signatures ; recalculé aussitôt pour tout le parc, postes éteints compris · variable d'environnement : {days} jours",
    inactiveAfter: 'Poste inactif après',
    inactiveAfterHint: "Jours sans contact de l'agent · variable d'environnement : {days} jours",
    lowDisk: 'Disque presque plein en dessous de',
    lowDiskHint: "Sur le volume système · variable d'environnement : {percent} %",
    hardwareAging: 'Poste à renouveler à partir de',
    hardwareAgingHint:
      "Âge compté depuis la date d’achat, à défaut la date du BIOS · variable d'environnement : {years} ans",
    agentVersion: "Version d'agent de référence",
    agentVersionPlaceholder: 'Automatique',
    agentVersionError: 'Une version comme 1.2.0 ou v1.2.0-rc.1, ou vide pour automatique',
    agentVersionHint:
      "Vide = automatique, la plus haute version remontée par le parc · variable d'environnement : {version}",
    automatic: 'automatique',
    commandTtl: "Durée de vie d'une commande en attente",
    commandTtlHint:
      "Au-delà, une commande jamais remise à son poste est périmée · variable d'environnement : {minutes} minutes",
  },
  schedule: {
    title: 'E-mails programmés',
    caption:
      "L'heure du résumé quotidien et le jour du rappel hebdomadaire des maintenances. Pris en compte en moins d'une minute, sans redémarrer le serveur.",
    digestHour: 'Heure du résumé quotidien (UTC)',
    digestHint: "Arrive {when} · variable d'environnement : {hour} h UTC",
    reminderDay: 'Jour du rappel des maintenances (UTC)',
    reminderHint: "À l'heure du résumé : arrive {when} · variable d'environnement : {day}",
    hourOption: '{hour} h UTC',
    digestSummary: 'chaque jour à {time} ({zone})',
    reminderSummary: 'le {day} à {time} ({zone})',
  },
  email: {
    title: 'Envoi des e-mails',
    // Around « deploy/.env », shown as code.
    captionBefore:
      'Le chemin des alertes, des résumés et des liens « mot de passe oublié ». Un champ laissé vide reprend la valeur du serveur (',
    captionAfter: '), rappelée en dessous.',
    saved: 'Envoi des e-mails enregistré',
    provider: 'Fournisseur',
    providers: {
      smtp: 'Serveur SMTP',
      mailgun: 'Mailgun',
    },
    // The provider inside a sentence: « valeur du serveur : serveur SMTP ».
    providerInline: {
      smtp: 'serveur SMTP',
      mailgun: 'Mailgun',
    },
    serverValue: 'valeur du serveur : {value}',
    serverValueSeconds: 'valeur du serveur : {value} s',
    notSetFeminine: 'non définie',
    yes: 'oui',
    no: 'non',
    fromEmail: "Adresse d'expéditeur",
    fromEmailHint:
      "Avec un compte SMTP authentifié, en général l'adresse du compte · valeur du serveur : {value}",
    fromName: "Nom d'expéditeur",
    smtpHost: 'Serveur SMTP',
    smtpHostHint:
      "Relais de l'établissement, Microsoft 365, Google Workspace… · valeur du serveur : {value}",
    security: 'Sécurité',
    securityOptions: {
      starttls: 'STARTTLS (port 587)',
      tls: 'TLS implicite (port 465)',
      none: 'Aucune (relais interne, port 25)',
    },
    port: 'Port',
    user: 'Utilisateur',
    userHint:
      "Vide = pas d'authentification (relais qui reconnaît le serveur) · valeur du serveur : {value}",
    userSet: 'définie',
    userNone: 'aucune',
    password: 'Mot de passe',
    clearPasswordAria: 'Effacer le mot de passe SMTP',
    keepPasswordAria: 'Garder le mot de passe SMTP',
    clearPassword: 'Effacer le mot de passe enregistré',
    keepPassword: 'Garder le mot de passe enregistré',
    verifyTls: 'Vérifier le certificat du serveur',
    verifyTlsHint:
      'À ne désactiver que pour un relais interne à certificat privé : sans vérification, une interception du trafic SMTP (et du mot de passe) passe inaperçue · valeur du serveur : {value}',
    timeout: "Délai d'attente",
    mailgunDomain: "Domaine d'envoi Mailgun",
    mailgunDomainPlaceholder: 'mg.exemple.fr',
    mailgunApiKey: 'Clé API Mailgun',
    clearKeyAria: 'Effacer la clé Mailgun',
    keepKeyAria: 'Garder la clé Mailgun',
    clearKey: 'Effacer la clé enregistrée',
    keepKey: 'Garder la clé enregistrée',
    mailgunBaseUrl: "Adresse de l'API Mailgun",
    mailgunBaseUrlHint: 'Région EU : https://api.eu.mailgun.net/v3 · valeur du serveur : {value}',
    secret: {
      unreadable: 'à ressaisir',
      stored: 'enregistré',
      env: 'valeur du serveur',
      unset: 'non défini',
    },
    secretHint: {
      clearing: "Sera effacé à l'enregistrement : la valeur du serveur s'appliquera.",
      unreadable: 'Enregistré avec une autre clé SECRET_KEY du serveur, illisible : à ressaisir.',
      stored: 'Laisser vide pour garder la valeur enregistrée.',
      other: 'Chiffré dans la base, jamais réaffiché.',
    },
    status: {
      viaSmtp: 'Les e-mails partent par un serveur SMTP.',
      viaMailgun: 'Les e-mails partent par Mailgun.',
      none: 'Aucun e-mail ne part.',
      missing: 'Aucun e-mail ne part : il manque {missing}.',
    },
    listSeparator: ', ',
    // What the chosen provider lacks, by the server's code (`missing_codes`).
    missing: {
      smtp_host: 'le serveur SMTP',
      from_email: "l'adresse d'expéditeur",
      mailgun_domain: 'le domaine Mailgun',
      mailgun_api_key: 'la clé API Mailgun',
      smtp_password_retype:
        'le mot de passe SMTP (celui du .env ne sert que pour le serveur du .env : à ressaisir ici)',
    },
    errors: {
      fromEmail: "L'adresse d'expéditeur n'est pas une adresse e-mail.",
      smtpHost: 'Le serveur SMTP est un nom ou une adresse, sans « smtp:// » ni chemin.',
      port: 'Le port est un entier entre 1 et 65535.',
      timeout: 'Le délai est un entier entre 1 et 120 secondes.',
      mailgunDomain: 'Le domaine Mailgun est un nom de domaine, sans chemin.',
      mailgunBaseUrl: "L'adresse de l'API Mailgun commence par https://.",
      recipient: "Ce n'est pas une adresse e-mail.",
    },
  },
  test: {
    recipient: 'Destinataire du test',
    recipientHint:
      'Vide = votre adresse. Le test essaie les valeurs du formulaire, même non enregistrées.',
    send: 'Envoyer un e-mail de test',
    failed: 'Envoi du test impossible',
    // A refused recipient as the server lists them: « a@x.fr : 550 no such user ».
    refusedRecipient: '{address} : {code} {text}',
    refusedRecipientSeparator: '; ',
    // The outcome of the test, by the server's code (`probe.py`).
    results: {
      sent_smtp: 'E-mail de test envoyé à {to} par le serveur SMTP {host}:{port}.',
      sent_mailgun: 'E-mail de test envoyé à {to} par Mailgun (domaine {domain}).',
      incomplete: 'Configuration incomplète : il manque {missing}.',
      not_sent: "Aucun e-mail n'est parti.",
      smtp_starttls_required:
        'Le serveur {where} exige une connexion chiffrée avant tout envoi — choisissez la sécurité « STARTTLS » (réponse : {response})',
      smtp_auth_required_user:
        "Le serveur {where} exige une authentification — le compte configuré n'a pas suffi : vérifiez l'utilisateur (réponse : {response})",
      smtp_auth_required:
        "Le serveur {where} exige une authentification — renseignez l'utilisateur et le mot de passe SMTP (réponse : {response})",
      smtp_silent:
        "Le serveur {where} a accepté la connexion mais n'a pas répondu dans les {seconds} s. Est-ce bien un serveur SMTP, et le mode de sécurité correspond-il au port (TLS sur 465) ?",
      smtp_auth_failed:
        "Identifiants refusés par le serveur SMTP — vérifiez l'utilisateur et le mot de passe (réponse : {response})",
      smtp_sender_refused:
        "Adresse d'expéditeur {from_email} refusée par le serveur — avec un compte authentifié, elle doit en général être celle du compte (réponse : {response})",
      smtp_recipients_refused: 'Destinataire refusé par le serveur SMTP ({details})',
      smtp_not_supported:
        'Le serveur SMTP ne propose pas ce que la configuration lui demande (STARTTLS ou authentification) : {error}. Essayez une autre sécurité.',
      smtp_disconnected:
        'Le serveur {where} a fermé la connexion. Le mode de sécurité correspond-il au port (STARTTLS sur 587, TLS sur 465) ?',
      smtp_error_response: 'Le serveur SMTP a répondu par une erreur : {response}',
      smtp_error: 'Erreur SMTP : {error}',
      tls_certificate_refused:
        'Certificat du serveur {where} refusé ({reason}). Pour un relais interne à certificat privé, désactivez la vérification.',
      tls_failed:
        'Échec de la négociation TLS avec {where} ({reason}). Le mode de sécurité correspond-il au port (STARTTLS sur 587, TLS sur 465) ?',
      smtp_host_unknown: 'Serveur SMTP introuvable : {host} ne se résout pas',
      mailgun_key_refused: 'Clé API Mailgun refusée (401)',
      mailgun_domain_unknown:
        "Mailgun ne connaît pas le domaine {domain} ({status}) — vérifiez le domaine et la région de l'API (EU ou US)",
      mailgun_status: 'Mailgun a répondu {status}',
      mailgun_status_body: 'Mailgun a répondu {status} : {body}',
      mailgun_timeout: "Mailgun n'a pas répondu dans le délai imparti",
      mailgun_unreachable: 'Impossible de joindre Mailgun : {error}',
      smtp_handshake_silent:
        "Le serveur {where} a accepté la connexion mais n'a pas répondu dans les {seconds} s. Est-ce bien un serveur SMTP, et le mode de sécurité correspond-il au port (STARTTLS sur 587, TLS sur 465) ?",
      timeout: "Le serveur {where} n'a pas répondu dans le délai imparti ({seconds} s)",
      connection_refused: 'Connexion refusée par {where} — le port est-il le bon ?',
      unreachable: 'Impossible de joindre {where} : {error}',
      unexpected: 'Erreur inattendue : {error}',
    },
  },
  unsaved: {
    title: 'Modifications non enregistrées',
    message: "Les changements de « {cards} » n'ont pas été enregistrés. Quitter la page les perd.",
    cardSeparator: ' », « ',
    stay: 'Rester sur la page',
    leave: 'Quitter sans enregistrer',
    cards: {
      maintenance: 'Maintenance',
      usage: 'Utilisation',
      alerts: 'Alertes',
      compliance: 'Conformité des postes',
      fleet: 'Seuils du parc',
      schedule: 'Calendrier des e-mails',
      planning: 'Planifications',
      email: 'Envoi des e-mails',
    },
  },
  environment: {
    title: 'Réglages du serveur',
    // Around « deploy/.env », shown as code.
    captionBefore: "Variables d'environnement du serveur (",
    captionAfter:
      "), en lecture seule ici. Une valeur se change dans ce fichier, puis en redémarrant le serveur — sauf celles marquées « valeur initiale », que les réglages ci-dessus remplacent dès qu'ils sont enregistrés.",
    search: 'Rechercher un réglage',
    searchPlaceholder: 'Rechercher un réglage…',
    notSet: '— non défini',
    noMatch: 'Aucun réglage ne correspond.',
  },
  // Checks of a whole number typed in a field (`utils/numberField.ts`).
  number: {
    required: 'Valeur requise',
    integer: 'Un nombre entier',
    between: 'Entre {min} et {max}',
  },
};

const en: Translation<typeof fr> = {
  title: 'Settings',
  save: 'Save',
  saved: 'Settings saved',
  saveFailed: 'Could not save',
  loadFailed: 'Could not load',
  units: {
    days: 'days',
    hours: 'hours',
    percentFree: '% free',
    years: 'years',
    minutes: 'minutes',
  },
  weekdays: {
    monday: 'Monday',
    tuesday: 'Tuesday',
    wednesday: 'Wednesday',
    thursday: 'Thursday',
    friday: 'Friday',
    saturday: 'Saturday',
    sunday: 'Sunday',
  },
  maintenance: {
    title: 'Maintenance',
    caption:
      'The fleet’s defaults. A room or a computer can replace them; the most specific value wins.',
    cycle: 'Default cycle',
    cycleHint: '0 = no maintenance by default · environment variable: {days} days',
    owner: 'Default owner',
    ownerHint: 'Gets the rooms and computers without an owner of their own in “My tasks”',
    ownerDeactivated: 'Deactivated account: {name}',
    dueSoon: '“Due soon” window',
    dueSoonHint:
      'A computer is flagged as due soon this many days before its date — at most half of its cycle · environment variable: {days} days',
  },
  usage: {
    title: 'Computer usage',
    caption:
      'What the dashboard’s “Rarely used” and “Always on” cards count, and the Usage filter of the computer list.',
    windowDays: 'Observation window',
    windowHint: 'Hours are counted over this many rolling days · environment variable: {days} days',
    lowHours: 'Computer rarely used below',
    lowHint:
      'A computer enrolled during the window is never counted as rarely used · environment variable: {hours} hours',
    highHours: 'Computer always on above',
    highHint: 'environment variable: {hours} hours',
  },
  alerts: {
    title: 'Alerts',
    caption:
      'The rules the server checks every five minutes over what the computers report. An alert opens and resolves by itself.',
    rules: 'Active rules',
    autoCheck: 'Open a check',
    autoCheckHint:
      'A new alert of these rules opens a check on the computer, unless it already has one.',
    rebootDays: 'Restart pending for more than',
    rebootHint: 'environment variable: {days} days',
    warrantyDays: 'Warranty end raised',
    warrantyHint: "Days before a computer's warranty ends · environment variable: {days} days",
    unencryptedScope: 'System volume not encrypted: computers covered',
    scopeLaptops: 'Laptops and tablets only',
    scopeAll: 'All computers',
    forbidden: 'Forbidden software',
    forbiddenHint:
      'Part of the program name, two characters at least (Enter to add) · case-insensitive',
  },
  reports: {
    title: 'Users’ reports',
    caption:
      'A computer’s label QR code opens, to whoever scans it without an account, a form to report a problem. The reports land in a queue to sort.',
    enabled: 'Open the report form',
    hint: 'Closed, the QR leads to the sign-in, as before · environment variable: {value}',
    on: 'open',
    off: 'closed',
    privacy:
      'The contact left is optional and deleted with the report: to be listed in the record of processing.',
  },
  planning: {
    title: 'Schedules',
    caption:
      'The zone the console plans in, and the windows when nothing at risk runs on several computers (class hours).',
    timezone: 'Time zone',
    timezoneHint: 'IANA name, for instance Pacific/Tahiti · environment variable: {zone}',
    windows: 'Forbidden windows',
    windowsHint:
      'A schedule at risk is not accepted in them; a risky command sent to several computers asks for one more confirmation. A command on one computer stays free.',
    windowDays: 'Days',
    windowStart: 'From',
    windowEnd: 'To',
    addWindow: 'Add a window',
    removeWindow: 'Remove the window',
    windowInvalid: 'Days, and an end after the start',
  },
  fleet: {
    title: 'Fleet monitoring',
    caption:
      'The thresholds that decide what the console flags on a computer. Applied at once, without restarting the server.',
    signatureMaxAge: 'Antivirus signatures outdated after',
    signatureMaxAgeHint:
      'Age of the signatures; recalculated at once for the whole fleet, computers that are off included · environment variable: {days} days',
    inactiveAfter: 'Computer inactive after',
    inactiveAfterHint: 'Days without contact from the agent · environment variable: {days} days',
    lowDisk: 'Disk almost full below',
    lowDiskHint: 'On the system volume · environment variable: {percent}%',
    hardwareAging: 'Computer due for renewal from',
    hardwareAgingHint:
      'Age counted from the purchase date, else the BIOS date · environment variable: {years} years',
    agentVersion: 'Reference agent version',
    agentVersionPlaceholder: 'Automatic',
    agentVersionError: 'A version such as 1.2.0 or v1.2.0-rc.1, or empty for automatic',
    agentVersionHint:
      'Empty = automatic, the highest version the fleet reports · environment variable: {version}',
    automatic: 'automatic',
    commandTtl: 'Lifetime of a waiting command',
    commandTtlHint:
      'Beyond it, a command never delivered to its computer expires · environment variable: {minutes} minutes',
  },
  schedule: {
    title: 'Scheduled e-mails',
    caption:
      'The time of the daily digest and the day of the weekly maintenance reminder. Taken into account within a minute, without restarting the server.',
    digestHour: 'Time of the daily digest (UTC)',
    digestHint: 'Arrives {when} · environment variable: {hour}:00 UTC',
    reminderDay: 'Day of the maintenance reminder (UTC)',
    reminderHint: 'At the time of the digest: arrives {when} · environment variable: {day}',
    hourOption: '{hour}:00 UTC',
    digestSummary: 'every day at {time} ({zone})',
    reminderSummary: 'on {day} at {time} ({zone})',
  },
  email: {
    title: 'Sending e-mails',
    captionBefore:
      'The way out for alerts, digests and “forgotten password” links. A field left empty takes the server’s value (',
    captionAfter: '), shown below it.',
    saved: 'E-mail sending saved',
    provider: 'Provider',
    providers: {
      smtp: 'SMTP server',
      mailgun: 'Mailgun',
    },
    providerInline: {
      smtp: 'SMTP server',
      mailgun: 'Mailgun',
    },
    serverValue: 'server value: {value}',
    serverValueSeconds: 'server value: {value} s',
    notSetFeminine: 'not set',
    yes: 'yes',
    no: 'no',
    fromEmail: 'Sender address',
    fromEmailHint:
      'With an authenticated SMTP account, usually the account’s address · server value: {value}',
    fromName: 'Sender name',
    smtpHost: 'SMTP server',
    smtpHostHint: 'The school’s relay, Microsoft 365, Google Workspace… · server value: {value}',
    security: 'Security',
    securityOptions: {
      starttls: 'STARTTLS (port 587)',
      tls: 'Implicit TLS (port 465)',
      none: 'None (internal relay, port 25)',
    },
    port: 'Port',
    user: 'User name',
    userHint:
      'Empty = no authentication (a relay that recognises the server) · server value: {value}',
    userSet: 'set',
    userNone: 'none',
    password: 'Password',
    clearPasswordAria: 'Delete the SMTP password',
    keepPasswordAria: 'Keep the SMTP password',
    clearPassword: 'Delete the saved password',
    keepPassword: 'Keep the saved password',
    verifyTls: 'Check the server’s certificate',
    verifyTlsHint:
      'Turn off only for an internal relay with a private certificate: without the check, an interception of the SMTP traffic (and of the password) goes unnoticed · server value: {value}',
    timeout: 'Timeout',
    mailgunDomain: 'Mailgun sending domain',
    mailgunDomainPlaceholder: 'mg.example.com',
    mailgunApiKey: 'Mailgun API key',
    clearKeyAria: 'Delete the Mailgun key',
    keepKeyAria: 'Keep the Mailgun key',
    clearKey: 'Delete the saved key',
    keepKey: 'Keep the saved key',
    mailgunBaseUrl: 'Mailgun API address',
    mailgunBaseUrlHint: 'EU region: https://api.eu.mailgun.net/v3 · server value: {value}',
    secret: {
      unreadable: 'to type again',
      stored: 'saved',
      env: 'server value',
      unset: 'not set',
    },
    secretHint: {
      clearing: 'Will be deleted on save: the server’s value will apply.',
      unreadable: 'Saved under another SECRET_KEY of the server, unreadable: type it again.',
      stored: 'Leave empty to keep the saved value.',
      other: 'Encrypted in the database, never shown again.',
    },
    status: {
      viaSmtp: 'E-mails go out through an SMTP server.',
      viaMailgun: 'E-mails go out through Mailgun.',
      none: 'No e-mail goes out.',
      missing: 'No e-mail goes out: missing {missing}.',
    },
    listSeparator: ', ',
    missing: {
      smtp_host: 'the SMTP server',
      from_email: 'the sender address',
      mailgun_domain: 'the Mailgun domain',
      mailgun_api_key: 'the Mailgun API key',
      smtp_password_retype:
        'the SMTP password (the one in .env only serves the server in .env: type it again here)',
    },
    errors: {
      fromEmail: 'The sender address is not an e-mail address.',
      smtpHost: 'The SMTP server is a name or an address, without “smtp://” or a path.',
      port: 'The port is a whole number between 1 and 65535.',
      timeout: 'The timeout is a whole number between 1 and 120 seconds.',
      mailgunDomain: 'The Mailgun domain is a domain name, without a path.',
      mailgunBaseUrl: 'The Mailgun API address starts with https://.',
      recipient: 'This is not an e-mail address.',
    },
  },
  test: {
    recipient: 'Test recipient',
    recipientHint:
      'Empty = your own address. The test tries the values of the form, even unsaved ones.',
    send: 'Send a test e-mail',
    failed: 'Could not send the test',
    refusedRecipient: '{address}: {code} {text}',
    refusedRecipientSeparator: '; ',
    results: {
      sent_smtp: 'Test e-mail sent to {to} through the SMTP server {host}:{port}.',
      sent_mailgun: 'Test e-mail sent to {to} through Mailgun (domain {domain}).',
      incomplete: 'Incomplete settings: missing {missing}.',
      not_sent: 'No e-mail went out.',
      smtp_starttls_required:
        'The server {where} requires an encrypted connection before sending anything — choose the “STARTTLS” security (answer: {response})',
      smtp_auth_required_user:
        'The server {where} requires authentication — the configured account was not enough: check the user name (answer: {response})',
      smtp_auth_required:
        'The server {where} requires authentication — fill in the SMTP user name and password (answer: {response})',
      smtp_silent:
        'The server {where} accepted the connection but did not answer within {seconds} s. Is it really an SMTP server, and does the security mode match the port (TLS on 465)?',
      smtp_auth_failed:
        'Credentials refused by the SMTP server — check the user name and password (answer: {response})',
      smtp_sender_refused:
        'Sender address {from_email} refused by the server — with an authenticated account, it usually has to be the account’s own (answer: {response})',
      smtp_recipients_refused: 'Recipient refused by the SMTP server ({details})',
      smtp_not_supported:
        'The SMTP server does not offer what the settings ask of it (STARTTLS or authentication): {error}. Try another security mode.',
      smtp_disconnected:
        'The server {where} closed the connection. Does the security mode match the port (STARTTLS on 587, TLS on 465)?',
      smtp_error_response: 'The SMTP server answered with an error: {response}',
      smtp_error: 'SMTP error: {error}',
      tls_certificate_refused:
        'Certificate of the server {where} refused ({reason}). For an internal relay with a private certificate, turn the check off.',
      tls_failed:
        'TLS negotiation with {where} failed ({reason}). Does the security mode match the port (STARTTLS on 587, TLS on 465)?',
      smtp_host_unknown: 'SMTP server not found: {host} does not resolve',
      mailgun_key_refused: 'Mailgun API key refused (401)',
      mailgun_domain_unknown:
        'Mailgun does not know the domain {domain} ({status}) — check the domain and the API region (EU or US)',
      mailgun_status: 'Mailgun answered {status}',
      mailgun_status_body: 'Mailgun answered {status}: {body}',
      mailgun_timeout: 'Mailgun did not answer in time',
      mailgun_unreachable: 'Cannot reach Mailgun: {error}',
      smtp_handshake_silent:
        'The server {where} accepted the connection but did not answer within {seconds} s. Is it really an SMTP server, and does the security mode match the port (STARTTLS on 587, TLS on 465)?',
      timeout: 'The server {where} did not answer in time ({seconds} s)',
      connection_refused: 'Connection refused by {where} — is the port right?',
      unreachable: 'Cannot reach {where}: {error}',
      unexpected: 'Unexpected error: {error}',
    },
  },
  unsaved: {
    title: 'Unsaved changes',
    message: 'The changes to “{cards}” have not been saved. Leaving the page loses them.',
    cardSeparator: '”, “',
    stay: 'Stay on the page',
    leave: 'Leave without saving',
    cards: {
      maintenance: 'Maintenance',
      usage: 'Usage',
      alerts: 'Alerts',
      compliance: 'Computer compliance',
      fleet: 'Fleet thresholds',
      schedule: 'E-mail schedule',
      planning: 'Schedules',
      email: 'Sending e-mails',
    },
  },
  environment: {
    title: 'Server settings',
    captionBefore: 'The server’s environment variables (',
    captionAfter:
      '), read-only here. A value is changed in that file, then by restarting the server — except those marked “initial value”, which the settings above replace as soon as they are saved.',
    search: 'Search the settings',
    searchPlaceholder: 'Search the settings…',
    notSet: '— not set',
    noMatch: 'No setting matches.',
  },
  number: {
    required: 'Value required',
    integer: 'A whole number',
    between: 'Between {min} and {max}',
  },
};

export default { fr, en };
