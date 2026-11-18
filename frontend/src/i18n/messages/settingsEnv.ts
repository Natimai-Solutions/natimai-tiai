import type { Translation } from './types';

/**
 * Paramètres → serveur : les variables d’environnement (lot C1 du plan console
 * bilingue). The server sends each group with a stable `code` and each variable
 * with its raw value and a `format`; the console words them from here
 * (`utils/serverEnvironment.ts`). The French is the server's, word for word —
 * `backend/tests/data/settings_texts_fr.json` holds them to it.
 */
const fr = {
  groups: {
    fleet: 'Postes et seuils',
    maintenance: 'Maintenance',
    usage: 'Utilisation des postes',
    rooms: 'Salles',
    email: 'E-mails',
    wol: 'Réveil des postes (Wake-on-LAN)',
    console: 'Console et sécurité',
    packages: 'Paquets logiciels',
  },
  values: {
    yes: 'oui',
    no: 'non',
    listSeparator: ', ',
    // A value and what it means: « 4 (vendredi) », « manual (à la main…) ».
    withMeaning: '{raw} ({meaning})',
    bytes: '{raw} ({amount} {unit})',
    bytesOnly: '{raw} octets',
    gib: 'Gio',
    mib: 'Mio',
    unreadable: 'défini (illisible)',
    mailConfigured: "configuré dans l'environnement",
    mailIncomplete:
      "incomplet dans l'environnement : aucun e-mail ne part sans réglage dans la console",
  },
  roomSources: {
    manual: 'à la main, depuis la console',
    ad_ou: "par l'unité d'organisation de l'annuaire",
    ad_location: "par l'attribut Emplacement de l'annuaire",
  },
  descriptions: {
    SIGNATURE_MAX_AGE_DAYS:
      "Âge maximal des signatures antivirus, en jours, avant qu'un poste soit « base antivirus périmée » — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
    INACTIVE_AFTER_DAYS:
      "Jours sans contact de l'agent avant qu'un poste soit « inactif » — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
    OFFLINE_AFTER_SECONDS:
      "Secondes sans battement avant qu'un poste soit compté éteint (3 × l'intervalle de l'agent par défaut)",
    LOW_DISK_FREE_PERCENT:
      'Seuil « disque presque plein » : pourcentage libre sur le volume système en dessous duquel un poste est signalé — valeur initiale : le réglage enregistré ci-dessus prend le dessus',
    HARDWARE_AGING_YEARS:
      'Âge du poste (date du BIOS) à partir duquel il est compté à renouveler — valeur initiale : le réglage enregistré ci-dessus prend le dessus',
    AGENT_EXPECTED_VERSION:
      "Version d'agent de référence pour « agent obsolète » ; vide = la plus haute version remontée par le parc — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
    COMMAND_DEFAULT_TTL_MINUTES:
      "Durée de vie, en minutes, d'une commande encore en attente avant qu'elle soit périmée — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
    COMMAND_UNANSWERED_HOURS:
      "Heures laissées à un poste pour répondre d'une commande qu'il a reçue avant qu'elle soit close en échec « sans réponse du poste » (une réponse plus tardive l'emporte encore)",
    COMMAND_RETENTION_DAYS:
      "Jours de conservation de l'historique des commandes terminées (0 = indéfiniment)",
    AGENT_TOKEN_ROTATE_DAYS:
      "Âge, en jours, au-delà duquel le token d'un poste est renouvelé (0 = jamais)",
    AGENT_HEARTBEAT_MAX_PER_MINUTE:
      "Battements qu'un même poste peut envoyer par minute ; au-delà, le serveur répond 429 (l'agent en envoie un par intervalle, plus un au redémarrage)",
    SOFTWARE_NEW_ENTRIES_PER_DAY:
      "Nouvelles entrées du catalogue logiciel qu'un même poste peut créer par 24 heures ; au-delà, son inventaire est signalé partiel et redemandé quand le budget le permet",
    SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET:
      'Nouvelles entrées du catalogue logiciel que tous les postes réunis peuvent créer par 24 heures ; un poste reçoit le plus petit de ce qui reste de son budget et de celui-ci',
    AUDIT_RETENTION_DAYS: "Jours de conservation du journal d'audit (0 = indéfiniment)",
    MAINTENANCE_DEFAULT_CYCLE_DAYS:
      'Cycle par défaut, en jours — valeur initiale : le réglage enregistré ci-dessus prend le dessus',
    MAINTENANCE_DUE_SOON_DAYS: 'Fenêtre « à échéance », en jours — même règle',
    MAINTENANCE_REMINDER_WEEKDAY:
      "Jour du rappel hebdomadaire envoyé aux responsables (0 = lundi … 6 = dimanche), à l'heure du résumé — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
    USAGE_WINDOW_DAYS:
      "Fenêtre d'observation, en jours — valeur initiale : le réglage enregistré ci-dessus prend le dessus",
    USAGE_LOW_HOURS:
      'Heures allumées en dessous desquelles un poste est « peu utilisé » — même règle',
    USAGE_HIGH_HOURS:
      'Heures allumées au-dessus desquelles un poste est « toujours allumé » — même règle',
    USAGE_RETENTION_DAYS: "Durée de conservation, en jours, des compteurs horaires d'utilisation",
    ROOM_SOURCE:
      'Comment les postes sont rangés en salles : manual, ad_ou ou ad_location. Dans un mode annuaire, le rattachement manuel est verrouillé',
    EMAIL_PROVIDER:
      "Canal de sortie du courrier : l'API Mailgun ou un serveur SMTP — valeur initiale : la carte « Envoi des e-mails » prend le dessus",
    EMAIL_FROM_EMAIL:
      "Adresse d'expéditeur (ou MAILGUN_FROM_EMAIL pour un .env plus ancien) — valeur initiale : la carte « Envoi des e-mails » prend le dessus",
    EMAIL_FROM_NAME:
      "Nom d'expéditeur affiché — valeur initiale : la carte « Envoi des e-mails » prend le dessus",
    MAILGUN_DOMAIN:
      "Domaine d'envoi Mailgun ; vide = Mailgun non configuré — valeur initiale : la carte « Envoi des e-mails » prend le dessus",
    MAILGUN_API_BASE_URL:
      "Point d'entrée de l'API Mailgun (EU ou US) — valeur initiale : la carte « Envoi des e-mails » prend le dessus",
    MAILGUN_TIMEOUT_SECONDS: "Délai d'attente de l'API Mailgun, en secondes",
    MAILGUN_PROXY_URL:
      "Proxy HTTP par lequel passent les appels à Mailgun, et eux seuls ; vide = connexion directe. Seuls l'hôte et le port sont affichés, jamais un identifiant ni un mot de passe",
    DIGEST_HOUR_UTC:
      "Heure UTC d'envoi du résumé quotidien et du rappel de maintenance — valeur initiale : le réglage enregistré prend le dessus",
    THREAT_ALERT_MAX_AGE_HOURS:
      "Une détection plus ancienne que ce nombre d'heures ne déclenche pas d'alerte immédiate (historique d'un poste qui s'enrôle)",
    NOTIFICATION_MAX_ITEMS:
      'Nombre de postes ou de détections détaillés dans un e-mail avant « et N autres »',
    DEFAULT_LANGUAGE: "Langue des e-mails d'un compte qui n'a pas choisi la sienne (fr ou en)",
    EMAIL_MAX_ATTEMPTS:
      "Tentatives d'envoi d'un e-mail (de 1 min à 1 h d'écart) avant qu'il soit abandonné et gardé avec sa dernière erreur",
    EMAIL_OUTBOX_RETENTION_DAYS:
      'Jours de conservation des e-mails envoyés ou abandonnés dans la file de sortie',
    WOL_RELAY_ENABLED:
      'oui = le serveur confie le réveil à un poste allumé du même emplacement (serveur hébergé hors site) ; non = il émet lui-même',
    WOL_BROADCAST_ADDRESSES:
      "Adresses de diffusion explicites ; renseignées, elles remplacent l'adresse déduite du poste",
    WOL_SUBNET_PREFIXLEN:
      "Masque de repli pour déduire l'adresse de diffusion d'un poste dont l'agent n'a pas remonté le sien",
    WOL_ALLOWED_NETWORKS:
      "Réseaux (CIDR) sur lesquels le serveur peut émettre lui-même un réveil ; vide = les plages privées 10.0.0.0/8, 172.16.0.0/12 et 192.168.0.0/16. Une adresse de poste hors de ces réseaux n'est pas une destination",
    WOL_PORT: 'Port UDP du paquet magique',
    WOL_PACKET_COUNT: 'Nombre de copies du paquet émises',
    WOL_RELAY_TTL_MINUTES: 'Délai, en minutes, laissé à un poste relais pour prendre un réveil',
    WOL_RELAY_SUBNET_GRACE_SECONDS:
      'Avance laissée à un relais du même sous-réseau que la cible ; 0 = aucune',
    WOL_RELAY_MIN_AGE_MINUTES:
      "Ancienneté minimale, en minutes, d'un poste dans le parc avant qu'il puisse relayer un réveil",
    WOL_RELAY_MIN_AGENT_VERSION:
      "Version d'agent minimale d'un poste relais ; un agent plus ancien, ou sans version lisible, ne reçoit aucun réveil à relayer",
    WOL_RELAY_CLAIM_TIMEOUT_SECONDS:
      'Secondes sans réponse après lesquelles un réveil pris par un relais est remis en file pour un autre',
    ENVIRONMENT:
      'local, staging ou production ; hors local, les secrets de démonstration sont refusés et les erreurs internes masquées',
    TIAI_SERVER_NAME:
      'Nom sous lequel le serveur est joint (site de Caddy, nom du certificat) ; la console en déduit son URL publique',
    CONSOLE_BASE_URL:
      "URL publique de la console, dans les liens des e-mails ; déduite de TIAI_SERVER_NAME quand elle n'est pas renseignée. Vide = aucun e-mail de réinitialisation",
    ACCESS_TOKEN_EXPIRE_MINUTES:
      "Durée de vie, en minutes, du jeton d'accès console (renouvelé seul par la session)",
    REFRESH_TOKEN_EXPIRE_DAYS: "Jours sans usage avant qu'une session console se ferme (glissant)",
    SESSION_MAX_DAYS: "Durée maximale d'une session console depuis la connexion, en jours",
    PASSWORD_MIN_LENGTH: 'Longueur minimale imposée à tout mot de passe',
    PASSWORD_RESET_EXPIRE_MINUTES: "Validité, en minutes, d'un lien de réinitialisation",
    PASSWORD_RESET_COOLDOWN_MINUTES:
      "Minutes pendant lesquelles une même adresse ne fait pas envoyer de nouvel e-mail « mot de passe oublié » pour un compte après le précédent qu'elle a demandé",
    PASSWORD_RESET_MAX_LIVE_LINKS:
      "Nombre de liens de réinitialisation valides à la fois pour un même compte et une même adresse qui les demande ; une demande n'annule jamais un lien encore valide",
    PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS:
      "Plafond de liens valides à la fois pour un même compte, toutes adresses confondues ; une demande venue d'une adresse habituelle du compte n'y est pas soumise",
    LOGIN_MAX_FAILED_ATTEMPTS:
      "Échecs de connexion rapprochés (chacun à moins de LOGIN_LOCKOUT_MINUTES du précédent) avant qu'un compte soit verrouillé pour les adresses qui ont échoué",
    LOGIN_LOCKOUT_MINUTES:
      'Durée, en minutes, du verrouillage, et délai au-delà duquel un échec ancien ne compte plus ; une réinitialisation du mot de passe le lève',
    LOGIN_SIEGE_ADDRESSES:
      "Nombre d'adresses distinctes en échec sur un même compte, en LOGIN_LOCKOUT_MINUTES (sous le verrou des essais lents : depuis le début de sa fenêtre), à partir duquel le verrouillage écarte toutes les adresses sauf celles qui ont ouvert le compte récemment",
    LOGIN_KNOWN_ADDRESS_DAYS:
      "Jours pendant lesquels une adresse qui a ouvert un compte reste connue de lui, et n'est pas écartée par ce verrouillage étendu",
    LOGIN_SLOW_MAX_FAILED_ATTEMPTS:
      "Échecs de connexion, même espacés, en LOGIN_SLOW_WINDOW_HOURS heures qui verrouillent un compte pour ce nombre d'heures ; ce verrou ferme le compte aux adresses qui ont échoué pendant cette fenêtre. Non défini : 20, ou quatre fois LOGIN_MAX_FAILED_ATTEMPTS si c'est davantage",
    LOGIN_SLOW_WINDOW_HOURS:
      "Fenêtre, en heures, de ce second compteur, et durée du verrou qu'il pose ; seul un nouveau mot de passe le lève. Non défini : 24, ou le double de LOGIN_LOCKOUT_MINUTES si c'est davantage",
    ENROLLMENT_REENROLL_REQUIRES_APPROVAL:
      "Un poste déjà enrôlé qui redemande un token attend l'approbation d'un administrateur",
    RATE_LIMIT_ENABLED:
      "Limitation du débit par adresse (connexion, mot de passe oublié, enrôlement), par session (changement de mot de passe) et par poste (battements) ; non = tout cela est levé, à réserver à des opérateurs qui arrivent tous d'une même adresse. Ni le verrouillage des comptes ni le budget du catalogue logiciel n'en dépendent",
    TRUSTED_PROXIES:
      "Réseaux (CIDR) des proxys dont l'en-tête X-Forwarded-For est cru pour connaître l'adresse du client, en plus de la boucle locale",
    TRUSTED_PROXIES_ALLOW_WIDE:
      "oui = TRUSTED_PROXIES peut lister un réseau plus large qu'un /24 (IPv4) ou un /64 (IPv6) ; non = le serveur refuse de démarrer, car tout client de ce réseau pourrait choisir son adresse",
    TRUSTED_PROXY_HOSTS:
      "Noms d'hôte de ces proxys, résolus dans le réseau du serveur (le service caddy par défaut)",
    EXPOSE_OPENAPI:
      'oui = le schéma OpenAPI et ses pages (/docs, /redoc) sont servis hors développement local',
    POSTGRES_POOL_SIZE: 'Connexions à la base gardées ouvertes par processus (API, worker)',
    POSTGRES_MAX_OVERFLOW: "Connexions supplémentaires ouvertes au-delà, le temps d'un pic",
    POSTGRES_POOL_TIMEOUT: "Secondes d'attente d'une connexion libre avant qu'une requête échoue",
    PACKAGES_DIR:
      'Dossier du serveur où sont rangés les fichiers des paquets (un fichier par empreinte SHA-256)',
    PACKAGE_MAX_BYTES:
      "Taille maximale d'un fichier de paquet déposé, en octets ; le proxy devant le serveur est dimensionné en conséquence",
    PACKAGE_METHOD_A_MAX_GB:
      'Poids total, en Gio, au-delà duquel les postes refusent de télécharger un paquet non signé (méthode A) ; doit valoir le DeployMethodAMaxGB de la GPO des agents',
    SMTP_HOST:
      'Serveur SMTP ; vide = SMTP non configuré — valeur initiale : la carte « Envoi des e-mails » prend le dessus',
    SMTP_PORT:
      'Port du serveur SMTP — valeur initiale : la carte « Envoi des e-mails » prend le dessus',
    SMTP_SECURITY:
      'starttls (587), tls (465) ou none (relais interne sur 25) — valeur initiale : la carte « Envoi des e-mails » prend le dessus',
    SMTP_VERIFY_TLS:
      'Vérification du certificat du serveur ; non = relais à certificat privé — valeur initiale : la carte « Envoi des e-mails » prend le dessus',
    SMTP_TIMEOUT_SECONDS:
      "Délai d'attente du serveur SMTP, en secondes — valeur initiale : la carte « Envoi des e-mails » prend le dessus",
  },
};

const en: Translation<typeof fr> = {
  groups: {
    fleet: 'Computers and thresholds',
    maintenance: 'Maintenance',
    usage: 'Computer usage',
    rooms: 'Rooms',
    email: 'E-mails',
    wol: 'Waking computers (Wake-on-LAN)',
    console: 'Console and security',
    packages: 'Software packages',
  },
  values: {
    yes: 'yes',
    no: 'no',
    listSeparator: ', ',
    withMeaning: '{raw} ({meaning})',
    bytes: '{raw} ({amount} {unit})',
    bytesOnly: '{raw} bytes',
    gib: 'GiB',
    mib: 'MiB',
    unreadable: 'set (unreadable)',
    mailConfigured: 'configured in the environment',
    mailIncomplete:
      'incomplete in the environment: no e-mail goes out without settings in the console',
  },
  roomSources: {
    manual: 'by hand, from the console',
    ad_ou: 'by the directory’s organisational unit',
    ad_location: 'by the directory’s Location attribute',
  },
  descriptions: {
    SIGNATURE_MAX_AGE_DAYS:
      'Maximum age of the antivirus signatures, in days, before a computer has “outdated antivirus signatures” — initial value: the setting saved above takes precedence',
    INACTIVE_AFTER_DAYS:
      'Days without contact from the agent before a computer is “inactive” — initial value: the setting saved above takes precedence',
    OFFLINE_AFTER_SECONDS:
      'Seconds without a heartbeat before a computer counts as off (3 × the agent’s default interval)',
    LOW_DISK_FREE_PERCENT:
      '“Disk almost full” threshold: free percentage on the system volume below which a computer is flagged — initial value: the setting saved above takes precedence',
    HARDWARE_AGING_YEARS:
      'Age of the computer (BIOS date) from which it counts as due for renewal — initial value: the setting saved above takes precedence',
    AGENT_EXPECTED_VERSION:
      'Reference agent version for “outdated agent”; empty = the highest version the fleet reports — initial value: the setting saved above takes precedence',
    COMMAND_DEFAULT_TTL_MINUTES:
      'Lifetime, in minutes, of a command still waiting before it expires — initial value: the setting saved above takes precedence',
    COMMAND_UNANSWERED_HOURS:
      'Hours a computer is given to answer a command it has received before the command is closed as failed, “no answer from the computer” (a later answer still wins)',
    COMMAND_RETENTION_DAYS: 'Days the history of finished commands is kept (0 = indefinitely)',
    AGENT_TOKEN_ROTATE_DAYS: 'Age, in days, beyond which a computer’s token is renewed (0 = never)',
    AGENT_HEARTBEAT_MAX_PER_MINUTE:
      'Heartbeats one computer may send per minute; beyond that, the server answers 429 (the agent sends one per interval, plus one when it restarts)',
    SOFTWARE_NEW_ENTRIES_PER_DAY:
      'New software catalogue entries one computer may create per 24 hours; beyond that, its inventory is flagged as partial and asked for again when the budget allows',
    SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET:
      'New software catalogue entries all computers together may create per 24 hours; a computer gets the smaller of what is left of its own budget and of this one',
    AUDIT_RETENTION_DAYS: 'Days the audit log is kept (0 = indefinitely)',
    MAINTENANCE_DEFAULT_CYCLE_DAYS:
      'Default cycle, in days — initial value: the setting saved above takes precedence',
    MAINTENANCE_DUE_SOON_DAYS: '“Due soon” window, in days — same rule',
    MAINTENANCE_REMINDER_WEEKDAY:
      'Day of the weekly reminder sent to owners (0 = Monday … 6 = Sunday), at the time of the digest — initial value: the setting saved above takes precedence',
    USAGE_WINDOW_DAYS:
      'Observation window, in days — initial value: the setting saved above takes precedence',
    USAGE_LOW_HOURS: 'Hours switched on below which a computer is “little used” — same rule',
    USAGE_HIGH_HOURS: 'Hours switched on above which a computer is “always on” — same rule',
    USAGE_RETENTION_DAYS: 'How long the hourly usage counters are kept, in days',
    ROOM_SOURCE:
      'How computers are sorted into rooms: manual, ad_ou or ad_location. In a directory mode, assigning a room by hand is locked',
    EMAIL_PROVIDER:
      'How mail goes out: the Mailgun API or an SMTP server — initial value: the “Sending e-mails” card takes precedence',
    EMAIL_FROM_EMAIL:
      'Sender address (or MAILGUN_FROM_EMAIL for an older .env) — initial value: the “Sending e-mails” card takes precedence',
    EMAIL_FROM_NAME:
      'Sender name shown — initial value: the “Sending e-mails” card takes precedence',
    MAILGUN_DOMAIN:
      'Mailgun sending domain; empty = Mailgun not configured — initial value: the “Sending e-mails” card takes precedence',
    MAILGUN_API_BASE_URL:
      'Mailgun API endpoint (EU or US) — initial value: the “Sending e-mails” card takes precedence',
    MAILGUN_TIMEOUT_SECONDS: 'Mailgun API timeout, in seconds',
    MAILGUN_PROXY_URL:
      'HTTP proxy the calls to Mailgun go through, and only they; empty = direct connection. Only the host and port are shown, never a user name or a password',
    DIGEST_HOUR_UTC:
      'UTC hour the daily digest and the maintenance reminder are sent at — initial value: the saved setting takes precedence',
    THREAT_ALERT_MAX_AGE_HOURS:
      'A detection older than this many hours does not trigger an immediate alert (the history of a computer being enrolled)',
    NOTIFICATION_MAX_ITEMS:
      'Number of computers or detections listed in an e-mail before “and N more”',
    DEFAULT_LANGUAGE:
      'Language of the e-mails of an account that has not chosen its own (fr or en)',
    EMAIL_MAX_ATTEMPTS:
      'Attempts to send an e-mail (1 min to 1 h apart) before it is abandoned and kept with its last error',
    EMAIL_OUTBOX_RETENTION_DAYS: 'Days sent or abandoned e-mails are kept in the outbox',
    WOL_RELAY_ENABLED:
      'yes = the server hands the wake-up to a computer that is on in the same location (server hosted off-site); no = it sends it itself',
    WOL_BROADCAST_ADDRESSES:
      'Explicit broadcast addresses; when set, they replace the address worked out from the computer',
    WOL_SUBNET_PREFIXLEN:
      'Fallback mask to work out the broadcast address of a computer whose agent has not reported its own',
    WOL_ALLOWED_NETWORKS:
      'Networks (CIDR) on which the server may send a wake-up itself; empty = the private ranges 10.0.0.0/8, 172.16.0.0/12 and 192.168.0.0/16. A computer address outside these networks is not a destination',
    WOL_PORT: 'UDP port of the magic packet',
    WOL_PACKET_COUNT: 'Number of copies of the packet sent',
    WOL_RELAY_TTL_MINUTES: 'Time, in minutes, given to a relay computer to take a wake-up',
    WOL_RELAY_SUBNET_GRACE_SECONDS:
      'Head start given to a relay on the same subnet as the target; 0 = none',
    WOL_RELAY_MIN_AGE_MINUTES:
      'Minimum time, in minutes, a computer has been in the fleet before it may relay a wake-up',
    WOL_RELAY_MIN_AGENT_VERSION:
      'Minimum agent version of a relay computer; an older agent, or one without a readable version, gets no wake-up to relay',
    WOL_RELAY_CLAIM_TIMEOUT_SECONDS:
      'Seconds without an answer after which a wake-up taken by a relay is queued again for another',
    ENVIRONMENT:
      'local, staging or production; outside local, the demonstration secrets are refused and internal errors are hidden',
    TIAI_SERVER_NAME:
      'Name the server is reached under (Caddy site, certificate name); the console works out its public URL from it',
    CONSOLE_BASE_URL:
      'Public URL of the console, in the links of e-mails; worked out from TIAI_SERVER_NAME when not set. Empty = no password reset e-mail',
    ACCESS_TOKEN_EXPIRE_MINUTES:
      'Lifetime, in minutes, of the console access token (renewed by the session on its own)',
    REFRESH_TOKEN_EXPIRE_DAYS: 'Days without use before a console session closes (sliding)',
    SESSION_MAX_DAYS: 'Maximum length of a console session from sign-in, in days',
    PASSWORD_MIN_LENGTH: 'Minimum length required of any password',
    PASSWORD_RESET_EXPIRE_MINUTES: 'Validity, in minutes, of a password reset link',
    PASSWORD_RESET_COOLDOWN_MINUTES:
      'Minutes during which one address does not get a new “forgotten password” e-mail sent for an account after the previous one it asked for',
    PASSWORD_RESET_MAX_LIVE_LINKS:
      'Number of reset links valid at once for one account and one address asking for them; a request never cancels a link that is still valid',
    PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS:
      'Ceiling of links valid at once for one account, all addresses together; a request from an address the account usually signs in from is not subject to it',
    LOGIN_MAX_FAILED_ATTEMPTS:
      'Failed sign-ins close together (each less than LOGIN_LOCKOUT_MINUTES after the previous one) before an account is locked for the addresses that failed',
    LOGIN_LOCKOUT_MINUTES:
      'Length, in minutes, of the lock, and the time beyond which an old failure no longer counts; a password reset lifts it',
    LOGIN_SIEGE_ADDRESSES:
      'Number of distinct addresses failing on one account within LOGIN_LOCKOUT_MINUTES (under the lock of slow attempts: since the start of its window), from which the lock keeps out every address but those that signed in to the account recently',
    LOGIN_KNOWN_ADDRESS_DAYS:
      'Days during which an address that signed in to an account stays known to it, and is not kept out by this extended lock',
    LOGIN_SLOW_MAX_FAILED_ATTEMPTS:
      'Failed sign-ins, even spread out, within LOGIN_SLOW_WINDOW_HOURS hours that lock an account for that many hours; this lock closes the account to the addresses that failed during that window. Not set: 20, or four times LOGIN_MAX_FAILED_ATTEMPTS if that is more',
    LOGIN_SLOW_WINDOW_HOURS:
      'Window, in hours, of this second counter, and length of the lock it sets; only a new password lifts it. Not set: 24, or twice LOGIN_LOCKOUT_MINUTES if that is more',
    ENROLLMENT_REENROLL_REQUIRES_APPROVAL:
      'A computer already enrolled that asks for a token again waits for an administrator’s approval',
    RATE_LIMIT_ENABLED:
      'Rate limiting per address (sign-in, forgotten password, enrolment), per session (password change) and per computer (heartbeats); no = all of it is lifted, for operators who all come from one address. Neither the account lock nor the software catalogue budget depends on it',
    TRUSTED_PROXIES:
      'Networks (CIDR) of the proxies whose X-Forwarded-For header is trusted to know the client’s address, besides the loopback',
    TRUSTED_PROXIES_ALLOW_WIDE:
      'yes = TRUSTED_PROXIES may list a network wider than a /24 (IPv4) or a /64 (IPv6); no = the server refuses to start, since any client on that network could choose its address',
    TRUSTED_PROXY_HOSTS:
      'Host names of these proxies, resolved on the server’s network (the caddy service by default)',
    EXPOSE_OPENAPI:
      'yes = the OpenAPI schema and its pages (/docs, /redoc) are served outside local development',
    POSTGRES_POOL_SIZE: 'Database connections kept open per process (API, worker)',
    POSTGRES_MAX_OVERFLOW: 'Extra connections opened beyond that, for the length of a peak',
    POSTGRES_POOL_TIMEOUT: 'Seconds to wait for a free connection before a request fails',
    PACKAGES_DIR: 'Folder on the server where package files are stored (one file per SHA-256 hash)',
    PACKAGE_MAX_BYTES:
      'Maximum size of an uploaded package file, in bytes; the proxy in front of the server is sized to match',
    PACKAGE_METHOD_A_MAX_GB:
      'Total size, in GiB, beyond which computers refuse to download an unsigned package (method A); must equal the DeployMethodAMaxGB of the agents’ GPO',
    SMTP_HOST:
      'SMTP server; empty = SMTP not configured — initial value: the “Sending e-mails” card takes precedence',
    SMTP_PORT: 'SMTP server port — initial value: the “Sending e-mails” card takes precedence',
    SMTP_SECURITY:
      'starttls (587), tls (465) or none (internal relay on 25) — initial value: the “Sending e-mails” card takes precedence',
    SMTP_VERIFY_TLS:
      'Check of the server’s certificate; no = relay with a private certificate — initial value: the “Sending e-mails” card takes precedence',
    SMTP_TIMEOUT_SECONDS:
      'SMTP server timeout, in seconds — initial value: the “Sending e-mails” card takes precedence',
  },
};

export default { fr, en };
