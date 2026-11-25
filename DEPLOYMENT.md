# Tia'i — Déploiement & configuration

Comment lever la stack selon le niveau de TLS souhaité, quelles variables
d'environnement renseigner côté serveur et quels paramètres pousser côté agent.

Seul prérequis côté serveur : [Docker](https://www.docker.com/), disponible sur
Windows, macOS et Linux
([instructions d'installation](https://docs.docker.com/get-started/get-docker/)).
Aucune connaissance de Docker n'est nécessaire pour suivre ce guide : une fois
installé, il télécharge et démarre tous les composants — base de données,
backend, console, reverse-proxy — avec les commandes données telles quelles
ci-dessous, sans rien d'autre à installer sur la machine.

Le TLS n'est pas une dépendance dure pour les agents : ils s'authentifient par
des en-têtes HTTP, jamais par un cookie `Secure` ou une redirection. On peut donc
démarrer les tests en HTTP pur et ajouter le certificat plus tard, sans toucher
au code. La console, elle, garde sa session dans un cookie `Secure` dès que
`ENVIRONMENT` n'est pas `local` : elle n'est de toute façon servie qu'en HTTPS,
par Caddy (cf. § « [Sessions de la console](#sessions-de-la-console) »).

## Obtenir les fichiers de déploiement

Toutes les commandes de ce guide partent du dossier `deploy/` du dépôt. Il
**fait partie du serveur** : outre le `docker-compose.yml`, il porte des
fichiers que les conteneurs lisent directement sur l'hôte — le `Caddyfile`, le
script de sauvegarde (`backup/backup.sh`), le script du rôle PostgreSQL
(`db/app-role.sh`). Ils se prennent à la **même version** que les images, sous
le tag de la release :

```bash
git clone https://github.com/Natimai-Solutions/natimai-tiai.git
cd natimai-tiai
git checkout v1.2.0          # le tag de la release : celle de TIAI_VERSION=1.2.0
```

Sans git, l'archive « Source code » de la release (page
[Releases](https://github.com/Natimai-Solutions/natimai-tiai/releases))
contient les mêmes fichiers. Ce qui est propre au serveur — `deploy/.env`,
`deploy/certs/`, `deploy/backups/` — n'est ni dans le dépôt ni dans l'archive :
changer de version n'y touche pas. Ces fichiers se mettent à jour **avec** les
images, à chaque montée de version (§ « [Mettre à jour le
serveur](#mettre-à-jour-le-serveur) »).

## Les trois modes

| Mode | TLS | Pour qui | Prérequis |
|---|---|---|---|
| **A — Sans certificat** | Aucun (HTTP pur, port 8800) | Premiers tests réseau, agents, `curl` | Aucun |
| **B — Auto-signé** | `tls internal` (AC locale Caddy) | Console web, validation de la chaîne HTTPS | Résolution du nom d'hôte |
| **C — AC interne** | Certificat AD CS | Production / pilote GPO | Certificat + clé dans `deploy/certs/` |

Les modes A et B sont fournis par le **même** override
[deploy/docker-compose.dev.yml](deploy/docker-compose.dev.yml) : il expose le
backend en clair *et* bascule Caddy en auto-signé. Les deux cohabitent — les
agents en HTTP sur 8800, la console en HTTPS sur 443.

---

## Mode A — sans certificat (HTTP pur)

```bash
cd deploy
cp .env.example .env    # renseigner les secrets ; laisser ENVIRONMENT=local
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
curl http://localhost:8800/health
```

L'override publie le backend en HTTP direct sur `127.0.0.1:8800` (Caddy
court-circuité), bascule Caddy en `tls internal` et force `ENVIRONMENT=local`,
ce qui neutralise la garde de démarrage qui refuse les secrets `changeme`.
Pour y brancher des postes du réseau, ajouter `TIAI_DEV_BACKEND_BIND=0.0.0.0`
dans `.env` : ce port est en clair, et l'en-tête `X-Forwarded-For` n'y est pas
cru (seul Caddy, ou `TRUSTED_PROXIES`, en est digne).

Côté poste, récupérer `tiai-agent-windows-amd64.exe` depuis la page
*Releases* du dépôt (ou le compiler : `go build -o tiai-agent.exe .` dans
`agent/`), puis le pointer directement sur le port HTTP — **pas** sur Caddy :

```powershell
.\tiai-agent.exe init-config --api-url http://192.168.1.50:8800 --allow-insecure-http
.\tiai-agent.exe run
```

`--allow-insecure-http` est indispensable : sans lui, l'agent refuse une URL
en `http://`. La commande `run` lancée au premier plan s'arrête alors
aussitôt, en disant pourquoi ; installé en service, l'agent reste « En cours
d'exécution » mais ne contacte pas le serveur (cf. § « Paramètres de l'agent
Windows »).

Ce port fait circuler en clair tout ce qu'échangent agents et serveur, **secret
d'enrôlement compris** (l'agent l'envoie en en-tête à chaque enrôlement) : un
`ENROLLMENT_SECRET` qui a servi dans ce mode est à tenir pour divulgué et doit
être **changé avant la production** (cf. § « Générer les secrets »).

**À savoir** : la console n'est pas exposée en HTTP (le service `frontend` n'est
joignable qu'à travers Caddy en 443) — pour une console sans TLS, utiliser le
serveur de dev Quasar. Et `ENVIRONMENT=local` renvoie les détails internes des
erreurs 500 : ce mode est réservé à un réseau de test.

---

## Mode B — certificat auto-signé (`tls internal`)

Même commande de démarrage que le mode A : Caddy génère son AC locale et émet le
certificat serveur tout seul, il n'y a aucun fichier à fournir.

**La résolution du nom d'hôte est obligatoire.** Le site Caddy est lié à
`{$TIAI_SERVER_NAME}` (défaut `tiai.natimai.local`) ; attaquer `https://<ip>` ne
matchera pas le site. Ajouter le nom au DNS ou au fichier `hosts` :

```
# Windows : C:\Windows\System32\drivers\etc\hosts
192.168.1.50   tiai.natimai.local
```

Le navigateur signalera un certificat non approuvé : accepter l'avertissement une
fois, ou importer l'AC locale de Caddy.

**Le nom court aussi.** Taper `tiai` dans la barre d'adresse envoie
`http://tiai/`, un hôte qui n'est pas le site : Caddy redirige tout ce qui
arrive en HTTP sous un autre nom (nom court, adresse IP) vers
`https://<TIAI_SERVER_NAME>/`, même chemin. Pour que `https://tiai` réponde
aussi (lien enregistré, HSTS), déclarer l'alias dans `TIAI_SERVER_ALIASES` :
Caddy le sert, et le renvoie vers le nom canonique — la console garde la
session dans le stockage du navigateur, propre à chaque origine, et deux noms
feraient deux sessions. Le nom court doit se résoudre côté client (suffixe DNS
du domaine, ou fichier `hosts`).

**L'auto-signé ne suffit pas pour l'agent**, dont le client HTTP n'offre aucune
option pour ignorer un certificat non approuvé. Deux choix : laisser les agents
en HTTP sur 8800 (mode A), ou importer la racine locale dans le magasin machine :

```powershell
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .
certutil -addstore Root root.crt
```

Le Caddyfile de dev omet volontairement `Strict-Transport-Security` : l'ajouter
épinglerait « HTTPS obligatoire » dans le navigateur et rendrait le mode A
inaccessible sur ce nom d'hôte. Les autres en-têtes de sécurité sont identiques à
la prod, pour valider la CSP dès le dev.

---

## Mode C — certificat de l'AC interne (production)

```bash
cd deploy
cp .env.example .env         # ENVIRONMENT=production + vrais secrets
chmod 600 .env               # tous les secrets du serveur : propriétaire seul
mkdir -p backups && chmod 700 backups   # dumps non chiffrés (§ « Sauvegardes »)
# déposer deploy/certs/tiai.crt et deploy/certs/tiai.key
docker compose up -d
```

- Le **CN/SAN du certificat doit correspondre à `TIAI_SERVER_NAME`**, sinon
  l'agent refuse la connexion. Un alias de `TIAI_SERVER_ALIASES` joint en
  HTTPS (`https://tiai`) doit figurer lui aussi dans les SAN — en HTTP, la
  redirection vers le nom canonique part en clair et n'a pas besoin de
  certificat.
- `deploy/certs/` est monté en lecture seule et ignoré par git, comme
  `deploy/.env`.
- `deploy/.env` (secrets) et `deploy/backups/` (dumps de la base, non chiffrés)
  sont réservés au propriétaire : `chmod 600 .env`, `chmod 700 backups`. Le
  service `db-backup` resserre aussi le dossier et ses dumps à chaque démarrage,
  mais seulement une fois lancé, et seulement si le système de fichiers le lui
  permet (§ « Sauvegardes et restauration ») — et rien ne protège le `.env` à
  sa place.
- Hors `ENVIRONMENT=local`, le backend **refuse de démarrer** si `SECRET_KEY`,
  `ENROLLMENT_SECRET`, `POSTGRES_PASSWORD` ou `FIRST_ADMIN_PASSWORD` est vide ou
  commence encore par `changeme`, ou si `SECRET_KEY` fait moins de 32 caractères,
  `ENROLLMENT_SECRET` moins de 16 (`openssl rand -hex 32` en produit un) ou
  `FIRST_ADMIN_PASSWORD` moins de `PASSWORD_MIN_LENGTH` (12 par défaut).
  `ENVIRONMENT` absent vaut `production` : un `.env` qui l'oublie reste gardé.
- Les postes du domaine font déjà confiance à l'AC racine : aucun import de
  certificat n'est nécessaire côté agent.

Repli sans certificat sur cette même stack : remplacer la ligne `tls ...` du
[Caddyfile](deploy/Caddyfile) par `tls internal`.

---

## Hôte Docker derrière un proxy

Le cas courant d'un établissement : le serveur ne sort sur Internet qu'à
travers un proxy. Docker se configure dans `~/.docker/config.json` (celui de
l'utilisateur qui lance `docker compose`) :

```json
{
  "proxies": {
    "default": {
      "httpProxy": "http://proxy.lycee.local:3128",
      "httpsProxy": "http://proxy.lycee.local:3128"
    }
  }
}
```

Cette configuration sert au **build** (téléchargement des dépendances), mais
Compose l'injecte aussi, en `HTTP_PROXY`/`HTTPS_PROXY` et leurs minuscules,
dans **tous les conteneurs** qu'il démarre. La stack est faite pour que ce
soit sans effet sur ses échanges internes, et le fichier peut rester en place
en production :

- **Caddy** joint `backend` et `frontend` sans proxy (`network_proxy none` sur
  chaque upstream du Caddyfile). Sans cela, il envoyait « `GET
  http://backend:8000/…` » au proxy de l'établissement, qui répondait par son
  portail : la console tournait en boucle de redirections (*too many
  redirects*), et le remède était de retirer `config.json` avant de lancer la
  stack.
- Les **contrôles de santé** sondent `127.0.0.1` sans proxy, et chaque service
  reçoit `NO_PROXY=localhost,127.0.0.1,backend,frontend,db,caddy` (les deux
  casses — une variable posée par Compose l'emporte sur `config.json` casse par
  casse).
- Le **backend** et le **worker** gardent `HTTPS_PROXY` : c'est ce qui permet à
  Mailgun de sortir par le proxy de l'établissement sans rien configurer
  d'autre. `MAILGUN_PROXY_URL` reste le réglage explicite si le proxy du build
  n'est pas celui du trafic sortant. SMTP ne passe pas par un proxy HTTP.

Un `noProxy` dans `config.json` n'atteint pas les services de la stack, dont
`NO_PROXY` est fixé par le compose.

---

## Générer les secrets

Quatre valeurs du `.env` doivent être générées aléatoirement — format recommandé
**32 octets en hexadécimal**, qui évite tout problème de quoting et d'encodage :

| Variable | Usage | Conséquence d'une valeur faible |
|---|---|---|
| `SECRET_KEY` | Signature des JWT console ; clé dont est dérivée celle qui chiffre les identifiants e-mail enregistrés dans la console | Tout JWT devient forgeable → accès admin |
| `ENROLLMENT_SECRET` | En-tête d'enrôlement des agents | N'importe qui peut enrôler une machine |
| `POSTGRES_PASSWORD` | Compte d'administration PostgreSQL (superutilisateur) | Accès total au serveur de base |
| `POSTGRES_APP_PASSWORD` | Rôle applicatif PostgreSQL, celui du backend | Accès aux tables de Tia'i |
| `FIRST_ADMIN_PASSWORD` | Premier compte console | Accès admin à la console |
| `TOTP_ENCRYPTION_KEY` (recommandé) | Clé qui chiffre les secrets de double authentification ; vide, elle est dérivée de `SECRET_KEY` | Une copie de la base et la clé permettent de calculer les codes |

```bash
# Linux / macOS / Git Bash
for v in SECRET_KEY ENROLLMENT_SECRET POSTGRES_PASSWORD POSTGRES_APP_PASSWORD FIRST_ADMIN_PASSWORD; do
  echo "$v=$(openssl rand -hex 32)"
done
```

```powershell
# Windows — générateur cryptographique .NET, pas Get-Random
'SECRET_KEY','ENROLLMENT_SECRET','POSTGRES_PASSWORD','POSTGRES_APP_PASSWORD','FIRST_ADMIN_PASSWORD' | ForEach-Object {
    $b = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    "$_=" + [System.BitConverter]::ToString($b).Replace('-','').ToLower()
}
```

**Points d'attention**

- `ENROLLMENT_SECRET` doit être **identique des deux côtés** : le `.env` du
  serveur et la configuration de chaque agent. Le faire tourner ne casse pas les
  agents déjà enrôlés — ils n'utilisent plus que leur token par poste — ce qui en
  fait une rotation peu coûteuse.
- Les **tokens par poste** se renouvellent d'eux-mêmes tous les
  `AGENT_TOKEN_ROTATE_DAYS` jours (cf. « Rotation des tokens agents »). Rien à
  faire côté serveur ; un token volé sur un poste cesse de fonctionner au plus
  tard à la rotation suivante, sans révocation. Les jetons de réinitialisation
  de mot de passe expirés ou utilisés depuis plus d'un jour sont purgés chaque
  matin, sans réglage.
- Changer `SECRET_KEY` invalide les jetons d'accès console en cours (15 min de
  vie) ; la console en obtient aussitôt de nouveaux par sa session, sans
  reconnexion. Pour déconnecter tout le monde — fuite de la clé, poste
  compromis —, fermer aussi les sessions : cf. § « [Sessions de la
  console](#sessions-de-la-console) ».
- `FIRST_ADMIN_PASSWORD` ne doit pas dépasser 72 octets (limite bcrypt) et n'est
  utilisé qu'au démarrage, pour créer le compte s'il n'existe pas.
- `POSTGRES_PASSWORD` n'est appliqué qu'à la **première** initialisation du
  volume de base. Le modifier ensuite casse la connexion : changer le mot de
  passe dans la base, ou repartir d'un volume neuf (`docker compose down -v`,
  **destructif**).
- Après modification du `.env`, recréer les conteneurs : `docker compose up -d`.

---

## Variables d'environnement (serveur)

Fichier `deploy/.env`, à créer depuis [deploy/.env.example](deploy/.env.example).
Il n'est jamais committé.

### Infrastructure

| Variable | Défaut | Rôle |
|---|---|---|
| `TIAI_SERVER_NAME` | `tiai.natimai.local` | Le nom du serveur : site Caddy, CN/SAN du certificat en mode C, et origine de `CONSOLE_BASE_URL` quand elle n'est pas renseignée |
| `TIAI_SERVER_ALIASES` | *(vide)* | Autres noms sous lesquels la console est tapée (nom court, IP), séparés par des espaces ; chacun est redirigé vers `TIAI_SERVER_NAME`. En HTTPS, l'alias doit être dans les SAN du certificat |
| `TIAI_VERSION` | `latest` | Version des images `tiai-backend` et `tiai-frontend` tirées de ghcr.io — à épingler en production (cf. § « Mettre à jour le serveur ») |
| `TIAI_DEV_BACKEND_PORT` | `8800` | Port hôte du backend en HTTP direct (override de dev uniquement) |
| `TIAI_DEV_BACKEND_BIND` | `127.0.0.1` | Adresse hôte sur laquelle ce port est publié (override de dev uniquement). `0.0.0.0` l'ouvre aux postes du réseau, en clair (cf. § « Mode A ») |
| `BACKUP_KEEP_DAYS` | `14` | Rétention des dumps quotidiens de `deploy/backups/` (cf. § « Sauvegardes et restauration ») |
| `BACKUP_ENCRYPT_RECIPIENT` | *(vide)* | Clé publique `age` (`age1…`), ou plusieurs séparées par des espaces : chaque dump quotidien est chiffré pour elles (`tiai-AAAAMMJJ-HHMMSS.dump.age`). Vide : dumps en clair. Jamais la clé privée (cf. § « [Chiffrer les sauvegardes](#chiffrer-les-sauvegardes) ») |

### Backend

| Variable | Défaut | Rôle |
|---|---|---|
| `ENVIRONMENT` | `production` | `local` / `staging` / `production`. Hors `local` : garde anti-placeholder et longueur minimale des secrets + masquage des erreurs 500. Absent, il vaut `production` : un `.env` qui l'oublie reste gardé |
| `SECRET_KEY` | `changeme` | 32 caractères minimum hors `local`. Signature des JWT console, et dérivation de la clé qui chiffre les identifiants e-mail enregistrés dans la console. **La changer oblige à ressaisir ces identifiants** (voir « Alertes e-mail ») |
| `TOTP_ENCRYPTION_KEY` | *(vide)* | Clé qui chiffre les secrets de double authentification (32 caractères minimum conseillés). Vide : dérivée de `SECRET_KEY`, et **changer `SECRET_KEY` rend alors illisibles tous les seconds facteurs** — chaque compte n'entre plus qu'avec un code de secours, ou après une réinitialisation par un administrateur. La renseigner une fois pour toutes, et la garder |
| `SECOND_FACTOR_MAX_FAILED_ATTEMPTS` | `5` | Codes faux de suite, sur n'importe quelles tentatives, avant que le second facteur du compte soit verrouillé : `LOGIN_LOCKOUT_MINUTES` minutes la première fois, puis deux fois plus à chaque nouvelle série de codes faux, 24 heures au plus. Seul un code juste remet le compte à zéro |
| `SECOND_FACTOR_CHALLENGE_MINUTES` | `5` | Temps laissé pour saisir le code une fois le mot de passe accepté (1 à 30) |
| `OIDC_ENABLED` | `false` | Connexion par l'annuaire (OpenID Connect, Entra ID d'abord) — cf. « Connexion par l'annuaire » |
| `OIDC_ISSUER` | *(vide)* | Émetteur : `https://login.microsoftonline.com/<ID de locataire>/v2.0` pour Entra ID. Un locataire, jamais `common` ni `organizations` |
| `OIDC_CLIENT_ID` | *(vide)* | ID d'application (client) de l'inscription |
| `OIDC_CLIENT_SECRET` | *(vide)* | Secret client de l'inscription. Jamais affiché par la console |
| `OIDC_LABEL` | `Microsoft` | Libellé du bouton « Se connecter avec … » |
| `OIDC_REDIRECT_URI` | *(dérivée)* | URI de redirection ; vide = `<URL de la console>/api/v1/auth/oidc/callback`, la valeur à déclarer chez le fournisseur |
| `OIDC_GROUPS_CLAIM` | `groups` | Revendication du jeton qui porte les groupes de l'annuaire |
| `OIDC_PROXY_URL` | *(vide)* | Proxy HTTP des seuls appels au fournisseur (découverte, clés, jeton), comme `MAILGUN_PROXY_URL` |
| `OIDC_TIMEOUT_SECONDS` | `10` | Délai d'attente des appels au fournisseur |
| `WEBHOOK_ALLOWED_HOSTS` | *(vide)* | Hôtes de webhook admis bien qu'internes, séparés par des virgules (`chat.lycee.local`) : un Mattermost du réseau de l'établissement. Pour eux seuls, `http://` est aussi accepté — cf. « Webhooks et jetons d'API » |
| `WEBHOOK_PROXY_URL` | *(vide)* | Proxy HTTP des seuls envois de webhooks, comme `MAILGUN_PROXY_URL` |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | Délai d'attente d'un envoi |
| `WEBHOOK_MAX_ATTEMPTS` | `30` | Tentatives avant abandon (1 min, doublé jusqu'à 1 h entre deux : environ une journée à 30, deux heures à 8) |
| `WEBHOOK_DELIVERY_RETENTION_DAYS` | `30` | Durée de conservation de l'historique des envois ; ceux encore en attente ne sont jamais purgés |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Durée de vie du jeton d'accès console (1 à 1 440). Court à dessein : c'est lui que la page garde en mémoire et envoie à chaque appel, et la console le renouvelle seule par sa session. Ancien défaut : 480 — une valeur `480` restée dans un `.env` reste acceptée mais n'a plus de raison d'être |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Une session console non utilisée pendant ce nombre de jours se ferme. **Glissante** : chaque renouvellement repousse l'échéance, un opérateur qui ouvre la console chaque semaine ne se reconnecte pas |
| `SESSION_MAX_DAYS` | `30` | Durée **absolue** d'une session, comptée depuis la connexion, glissement compris : au-delà, reconnexion obligatoire. Borne ce que vaut un jeton de session volé |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` | — | Compte admin créé au démarrage s'il n'existe pas |
| `PASSWORD_MIN_LENGTH` | `12` | Longueur minimale imposée à tout mot de passe |
| `PASSWORD_RESET_EXPIRE_MINUTES` | `60` | Validité d'un lien « mot de passe oublié », en minutes (5 à 10 080) |
| `PASSWORD_RESET_COOLDOWN_MINUTES` / `PASSWORD_RESET_MAX_LIVE_LINKS` | `5` / `3` | « Mot de passe oublié », compté **par compte et par adresse qui demande** : pas de nouveau courriel dans ce délai (0 à 60 min) après le précédent demandé depuis la même adresse, et au plus ce nombre de liens valides à la fois demandés depuis elle (1 à 10). Un tiers qui épuise son budget laisse donc entier celui du titulaire, qui demande depuis son poste. Une demande n'annule jamais un lien encore valide ; utiliser un lien annule les autres. La réponse (204) arrive après le même délai (une demi-seconde) quelle que soit l'issue : ni son contenu ni sa durée ne disent si le compte existe |
| `PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS` | `10` | Plafond de liens valides à la fois pour un même compte, **toutes adresses confondues** (1 à 100, au moins `PASSWORD_RESET_MAX_LIVE_LINKS`) : contre l'inondation d'une boîte depuis de nombreuses adresses. Une demande venue d'une adresse habituelle du compte (cf. `LOGIN_KNOWN_ADDRESS_DAYS`) n'y est pas soumise ; aucune ne l'est tant que le compte est sous le verrou des essais lents (voir *Verrouillage des comptes*), où ce lien est la sortie du titulaire — seul le budget de chaque adresse compte alors |
| `CONSOLE_BASE_URL` | `https://<TIAI_SERVER_NAME>` | URL publique de la console, dans les liens des e-mails (réinitialisation, fiche d'un poste). À renseigner seulement si la console est jointe sous une autre URL (autre port, proxy devant Caddy). Si ni elle ni `TIAI_SERVER_NAME` n'est connue, aucun e-mail de réinitialisation n'est envoyé |
| `ENROLLMENT_SECRET` | `changeme-enrollment-secret` | Secret partagé d'enrôlement ; n'autorise que l'enregistrement d'un poste — 16 caractères minimum hors `local` |
| `ENROLLMENT_SECRET_PREVIOUS` | *(vide)* | Ancien secret, encore accepté pendant une rotation (cf. « Enrôlement : approbation et rotation du secret ») |
| `ENROLLMENT_REENROLL_REQUIRES_APPROVAL` | `true` | Un poste déjà enrôlé qui redemande un token attend l'approbation d'un administrateur |
| `LOGIN_MAX_FAILED_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` | `5` / `15` | Verrouillage d'un compte après N échecs de connexion espacés de moins de cette durée, pour cette durée (voir *Verrouillage des comptes*). Une connexion réussie ou une réinitialisation du mot de passe le lève |
| `LOGIN_SIEGE_ADDRESSES` / `LOGIN_KNOWN_ADDRESS_DAYS` | `10` / `30` | Pendant un verrou, dès que ce nombre d'adresses distinctes (2 à 1 000) ont échoué sur le compte en `LOGIN_LOCKOUT_MINUTES` (sous le verrou des essais lents : depuis le début de sa fenêtre), seules les adresses qui ont ouvert ce compte depuis ce nombre de jours (1 à 365) restent admises (voir *Verrouillage des comptes*) |
| `LOGIN_SLOW_MAX_FAILED_ATTEMPTS` / `LOGIN_SLOW_WINDOW_HOURS` | `20` / `24` | Essais lents : ce nombre d'échecs (au-dessus de `LOGIN_MAX_FAILED_ATTEMPTS`, jusqu'à 1 000), même espacés, en ce nombre d'heures (1 à 168, plus long que `LOGIN_LOCKOUT_MINUTES`) depuis le premier verrouille le compte pour ce même nombre d'heures : ce verrou ferme le compte aux adresses qui ont échoué pendant cette fenêtre, et une connexion réussie ne le lève pas (voir *Verrouillage des comptes*). **Non définies**, elles suivent le verrou rapide qu'elles doivent dépasser : 20 échecs, ou quatre fois `LOGIN_MAX_FAILED_ATTEMPTS` si c'est davantage ; 24 heures, ou le double de `LOGIN_LOCKOUT_MINUTES` si c'est davantage — un `.env` qui ne règle que le verrou rapide démarre donc toujours. Le backend ne **refuse de démarrer** que sur une valeur écrite ici qui contredit l'autre, en nommant les deux |
| `RATE_LIMIT_ENABLED` | `true` | Limitation de débit par adresse (connexion, « mot de passe oublié », enrôlement, e-mail de test). À `false`, elle est coupée, et avec elle le plafond de heartbeats par poste et la limite des changements de mot de passe — **pas** le verrouillage des comptes, ni les cinq essais du mot de passe actuel par session (comptés en base), ni les quotas de logiciels. Une issue de secours, pas un réglage : réservée à un déploiement dont tous les opérateurs arrivent par la même adresse (VPN, proxy) |
| `AGENT_HEARTBEAT_MAX_PER_MINUTE` | `12` | Heartbeats acceptés par poste et par minute (2 à 600) ; au-delà, 429. L'agent en envoie un par `heartbeat_interval_seconds` (60 s par défaut), plus un au redémarrage : relever cette limite si l'intervalle est abaissé sous 10 s |
| `SOFTWARE_NEW_ENTRIES_PER_DAY` | `2000` | Nouveaux logiciels qu'un poste peut ajouter au catalogue par 24 h (100 à 1 000 000) ; les logiciels déjà connus ne comptent pas. Une liste coupée par ce quota est signalée sur la fiche du poste (« Relevé partiel »), et le serveur redemande l'inventaire à l'agent dès que le budget le permet (agents à partir de la v1.2.1 ; un agent plus ancien le complète à son prochain redémarrage ou au prochain changement de son inventaire). En dessous de 2 000 (le plus qu'un inventaire transporte), le premier inventaire d'un poste sur un catalogue vide est donc d'abord partiel |
| `SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET` | `50000` | Nouveaux logiciels que **tous les postes réunis** peuvent ajouter au catalogue par 24 h (1 000 à 10 000 000). Même règle : les logiciels déjà connus ne comptent pas, et une liste coupée est signalée puis redemandée. Les deux budgets sont comptés dans PostgreSQL : ils valent pour tous les processus de l'API ensemble et un redémarrage ne les remet pas à zéro ; ce qu'un battement en échec avait réservé est rendu. La réservation passe par une connexion à part (cf. `POSTGRES_POOL_SIZE`) : si elle n'aboutit pas en quelques secondes — connexion refusée (`max_connections` atteint) ou sans réponse, verrou des budgets tenu par un processus figé — le battement répond quand même, rien n'est accordé et la liste est coupée comme si le budget était épuisé (« Relevé partiel », puis redemandée). Le journal du backend le dit par une ligne `budgets unreachable` (une au début, puis une par dix minutes au plus tant que cela dure) |
| `AGENT_TOKEN_ROTATE_DAYS` | `30` | Âge, en jours (0 à 3650), au-delà duquel le token d'un poste est renouvelé à son prochain heartbeat — seulement pour un agent qui sait stocker le nouveau ; un agent plus ancien garde le sien. `0` = jamais. Voir « Rotation des tokens agents » ci-dessous |
| `BACKEND_CORS_ORIGINS` | *(vide)* | Origines autorisées, séparées par des virgules. Inutile avec la stack Compose (console et API sous la même origine) : seulement pour le serveur de dev Quasar |
| `TRUSTED_PROXIES` | *(vide)* | Réseaux (CIDR, séparés par des virgules) dont l'en-tête `X-Forwarded-For` est cru, en plus de la boucle locale et de `TRUSTED_PROXY_HOSTS`. Toutes les lignes de l'en-tête sont alors lues bout à bout, dans l'ordre, et l'adresse retenue est l'entrée la plus à droite qui n'est pas elle-même un proxy de confiance ; chaque entrée est lue comme une adresse (port et crochets retirés), et une entrée illisible ramène à l'adresse de la connexion. Pour tout autre pair, l'en-tête est ignoré et l'adresse du client — limitation de débit, journal d'audit — est celle de la connexion. À renseigner seulement si un autre proxy que le Caddy de la stack joint directement le backend, et **n'y lister que les proxys** : une plage large (tout le réseau local) laisse un client qui s'y trouve choisir l'adresse sous laquelle il apparaît, ou ramène tous les clients à l'adresse du proxy. Le backend **refuse de démarrer** sur une entrée plus large qu'un `/24` (IPv4) ou un `/64` (IPv6), en la nommant, sauf `TRUSTED_PROXIES_ALLOW_WIDE=true` |
| `TRUSTED_PROXIES_ALLOW_WIDE` | `false` | `true` accepte dans `TRUSTED_PROXIES` un réseau plus large qu'un `/24` ou un `/64`. À réserver à un réseau qui ne contient **que** des proxys : tout autre client qui s'y trouverait choisirait l'adresse sous laquelle la limitation de débit, le verrouillage et le journal d'audit le voient |
| `TRUSTED_PROXY_HOSTS` | `caddy` | Noms d'hôte dont l'en-tête `X-Forwarded-For` est cru, séparés par des virgules, résolus dans le réseau Compose (au plus une fois par minute). Un nom qui ne se résout pas (hors Docker) n'accorde rien. Le défaut désigne le service Caddy de la stack |
| `EXPOSE_OPENAPI` | `false` | Sert le schéma OpenAPI (`/api/v1/openapi.json`) et ses pages `/docs` et `/redoc` hors `ENVIRONMENT=local`, où ils le sont toujours. Derrière Caddy, seul `/api/*` atteint le backend : seul le schéma JSON devient joignable, les pages ne le sont que sur le port direct de l'override de dev. Le schéma décrit chaque route et chaque champ : laisser à `false` en production |
| `POSTGRES_SERVER` / `POSTGRES_PORT` | `db` / `5432` | Forcés par le compose |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `tiai` / — / `tiai` | Compte d'administration (superutilisateur) : initialisation du volume, sauvegardes |
| `POSTGRES_APP_USER` / `POSTGRES_APP_PASSWORD` | `tiai_app` / — | Rôle applicatif du backend et du worker, sans superutilisateur (cf. § « Rôle applicatif PostgreSQL »). Le compose les passe au backend comme `POSTGRES_USER` / `POSTGRES_PASSWORD` |
| `POSTGRES_POOL_SIZE` / `POSTGRES_MAX_OVERFLOW` / `POSTGRES_POOL_TIMEOUT` | `20` / `10` / `30` | Pool async, le même réglage pour le backend et le worker : chaque processus garde jusqu'à `POOL_SIZE` + `MAX_OVERFLOW` connexions (30). Le backend en ouvre en plus **hors pool**, le temps d'une réservation, pour chaque battement en cours qui ajoute un logiciel au catalogue (budgets `SOFTWARE_NEW_ENTRIES_PER_DAY*`) : au pire autant que son pool, soit 2 × (`POOL_SIZE` + `MAX_OVERFLOW`) = 60 connexions par processus d'API. `max_connections` de PostgreSQL (100 par défaut, dont 3 réservées au superutilisateur) doit couvrir ce total — 60 pour l'API + 30 pour le worker = 90 avec les valeurs par défaut — plus les sauvegardes et les sessions d'administration ; avec plusieurs processus d'API, ou un pool agrandi, relever `max_connections` d'autant (ou réduire le pool). Une réservation qui n'obtient pas sa connexion ne fait pas échouer le battement : voir `SOFTWARE_NEW_ENTRIES_PER_DAY_FLEET` |
| `SIGNATURE_MAX_AGE_DAYS` | `3` | Seuil « signatures à jour », en jours. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage ; un changement est appliqué aussitôt à tout le parc, postes éteints compris |
| `INACTIVE_AFTER_DAYS` | `30` | Seuil « poste inactif », en jours sans contact. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |
| `LOW_DISK_FREE_PERCENT` | `10` | Seuil « disque presque plein » : pourcentage d'espace libre sur le volume système. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |
| `HARDWARE_AGING_YEARS` | `5` | Âge du poste (date d'achat de sa fiche matériel, à défaut date du BIOS), en années, à partir duquel il est compté à renouveler. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |
| `OFFLINE_AFTER_SECONDS` | `180` | Seuil « poste allumé » : 3 × l'intervalle de heartbeat de l'agent, pour qu'un battement manqué n'éteigne pas le parc. À relever avec lui sur un parc plus lent |
| `COMMAND_DEFAULT_TTL_MINUTES` | `60` | Durée de vie d'une commande mise en file. Passé ce délai, une commande **encore en attente** est périmée et n'est plus remise à un agent — un poste rallumé trois semaines plus tard ne rejoue pas ce qu'on lui avait demandé. À allonger sur un parc dont les postes ne sont allumés que par intermittence. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |
| `COMMAND_RETENTION_DAYS` | `365` | Conservation de l'historique des commandes, en jours (0 à 3650). Chaque matin, le worker supprime les commandes **terminées** (réussies, échouées, périmées) et les commandes délivrées restées sans réponse dont le dernier événement est plus ancien. Jamais une commande en attente ou en cours. `0` = conserver indéfiniment |
| `COMMAND_UNANSWERED_HOURS` | `24` | Une commande remise au poste, ou annoncée en cours, sans verdict au-delà de ce délai (en heures, 1 à 720) est close en **échec « sans réponse du poste »** par le worker : agent arrêté ou mis à jour, poste éteint pendant l'exécution, agent trop ancien. Le serveur ne remet jamais une commande deux fois ; un verdict qui arrive plus tard remplace celui-ci |
| `AUDIT_RETENTION_DAYS` | `730` | Conservation du journal d'audit, en jours (0 à 3650), purgé chaque matin par le worker. `0` = conserver indéfiniment, si la politique de l'établissement l'exige |
| `MAINTENANCE_DEFAULT_CYCLE_DAYS` | `90` | Cycle de maintenance par défaut du parc, en jours, **valeur initiale seulement** : la page Paramètres de la console peut en écrire une autre, qui prend alors le dessus. Une salle ou un poste peuvent surcharger le cycle (0 = exclu de la maintenance) et le responsable ; le plus précis gagne |
| `MAINTENANCE_DUE_SOON_DAYS` | `14` | Fenêtre « à échéance » : un poste est signalé ce nombre de jours avant sa date — au plus la moitié de son cycle, pour qu'un cycle court reste « à jour » après une visite. Même règle : valeur initiale, modifiable dans Paramètres |
| `USAGE_WINDOW_DAYS` | `7` | Fenêtre glissante, en jours (1 à 90), sur laquelle sont comptées les heures allumées des postes. **Valeur initiale seulement**, modifiable dans Paramètres |
| `USAGE_LOW_HOURS` | `10` | En dessous de ce nombre d'heures sur la fenêtre, un poste est « peu utilisé ». Un poste enrôlé pendant la fenêtre ne l'est jamais. Valeur initiale, modifiable dans Paramètres |
| `USAGE_HIGH_HOURS` | `30` | Au-dessus, un poste est « toujours allumé ». Valeur initiale, modifiable dans Paramètres |
| `USAGE_RETENTION_DAYS` | `400` | Conservation des compteurs horaires d'utilisation, purgés chaque jour par le worker. Environ 7 200 lignes par jour pour 300 postes |
| `TREND_RETENTION_DAYS` | `760` | Conservation des photos quotidiennes du tableau de bord (page Tendances), en jours (400 à 3650), purgées chaque matin par le worker. 25 mois par défaut : douze mois affichés et les douze d'avant pour comparer. Une ligne par jour et par cellule (site de l'agent, salle), quelques centaines par jour |
| `ALERT_REBOOT_PENDING_DAYS` | `7` | Alerte « redémarrage en attente » : un redémarrage demandé par Windows Update et toujours pas fait au bout de ce nombre de jours (1 à 365). **Valeur initiale seulement**, modifiable dans Paramètres, comme la liste des règles actives, les logiciels interdits et les règles qui ouvrent une vérification |
| `ALERT_UNENCRYPTED_SCOPE` | `laptops` | Alerte « volume système non chiffré » : `laptops` ne regarde que les portables et tablettes, `all` tous les postes. Valeur initiale, modifiable dans Paramètres |
| `ALERT_WARRANTY_DAYS` | `30` | Alerte « garantie bientôt terminée » : ce nombre de jours avant la fin de garantie saisie sur la fiche d'actif d'un poste (1 à 365). Valeur initiale, modifiable dans Paramètres |
| `ALERT_RETENTION_DAYS` | `400` | Conservation des alertes **résolues**, purgées chaque matin par le worker. Une alerte ouverte n'est jamais purgée |
| `COMPLIANCE_PATCH_GRACE_DAYS` | `14` | Conformité des postes : une mise à jour Windows **critique ou importante** en attente depuis plus de ce nombre de jours (0 à 365) fait échouer le contrôle « correctifs ». Évite qu'un mardi de correctifs fasse passer tout le parc au rouge. **Valeur initiale seulement**, modifiable dans Paramètres, comme la liste des administrateurs locaux acceptés |
| `LICENSE_EXPIRY_DAYS` | `60` | Licences logicielles : une licence est signalée « bientôt échue » ce nombre de jours (1 à 365) avant son échéance, sur la page Logiciels, au tableau de bord et dans le résumé quotidien. **Valeur initiale seulement**, modifiable dans Paramètres |
| `CONSOLE_TIMEZONE` | `Pacific/Tahiti` | Fuseau (nom IANA) dans lequel la console **planifie** : « mercredi à 18 h » est 18 h dans ce fuseau, pas en UTC. Les plages interdites s'y lisent aussi. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |
| `SCHEDULE_COMMAND_TTL_MINUTES` | `180` | Durée d'attente par défaut d'une commande créée par une planification (10 à 1 440 min) : un poste réveillé met quelques minutes à contacter le serveur. Réglable par planification |
| `REPORTS_ENABLED` | `false` | Le QR de l'étiquette d'un poste ouvre, à qui le scanne **sans compte**, un formulaire de signalement (catégorie, texte, contact facultatif). Désactivé par défaut : c'est le premier point d'entrée non authentifié qui ne soit pas l'agent ; borné par adresse et par étiquette, il ne renvoie rien sur le poste. Joignable seulement depuis le réseau de l'établissement si la console l'est. Le contact laissé est une donnée personnelle, à porter au registre des traitements. Les bornes sont comptées **par adresse** (10 envois et 60 lectures du formulaire par heure) : si la console est derrière un proxy, il doit figurer dans `TRUSTED_PROXIES` / `TRUSTED_PROXY_HOSTS`, sans quoi tout l'établissement partage une seule adresse et un seul quota ; l'adresse de l'émetteur est conservée dans le journal d'audit (`AUDIT_RETENTION_DAYS`), à porter au registre aussi. **Valeur initiale seulement** : modifiable dans Paramètres |
| `REPORT_RETENTION_DAYS` | `90` | Conservation d'un signalement traité — et du contact qu'il porte — avant sa purge du matin. Un signalement à trier n'est jamais purgé |
| `SCHEDULE_RUN_RETENTION_DAYS` | `180` | Conservation de l'historique des exécutions de planifications, purgé chaque matin. Les commandes créées restent dans l'historique des postes |
| `APPROVAL_ENABLED` | `false` | Approbation à deux des actions de masse (C10) : au-delà de `APPROVAL_THRESHOLD` postes, une commande à risque (ou une planification à risque) n'est pas mise en file mais attend l'accord d'un second compte — cf. « Approbation à deux ». **Valeur initiale seulement** : modifiable dans Paramètres, où elle ne s'active pas avec moins de deux comptes capables d'approuver |
| `APPROVAL_THRESHOLD` | `40` | Nombre de postes (2 à 10 000) au-delà duquel l'approbation s'applique, compté par envoi sur les postes réellement visés. **Valeur initiale seulement** |
| `APPROVAL_TTL_HOURS` | `24` | Durée (1 à 168 h) pendant laquelle une demande attend sa décision avant d'expirer. **Valeur initiale seulement** |
| `APPROVAL_RETENTION_DAYS` | `180` | Conservation d'une demande d'approbation close, purgée chaque matin ; le journal d'audit en garde la trace au-delà |
| `DIRECTORY_VERIFY` | `off` | `relay` : des postes désignés lisent l'annuaire de leur domaine avec leur compte machine, et le serveur range les salles et vérifie la déclaration des agents d'après cette lecture (voir « Lire l'annuaire au lieu de croire les agents »). `off` : la déclaration des agents est crue. `ldap` n'existe pas encore |
| `DIRECTORY_SYNC_MINUTES` | `60` | Intervalle entre deux lectures demandées à chaque lecteur (5 à 1 440) |
| `DIRECTORY_STALE_HOURS` | `72` | Au-delà, un domaine non relu ne vérifie plus rien : ses postes passent « périmés » |
| `DIRECTORY_CONFIRM_MOVES` | `20` | Une lecture qui déplacerait plus de postes que ce seuil attend la confirmation d'un administrateur (Paramètres → Annuaire) |
| `ROOM_SOURCE` | `manual` | Comment les postes sont rangés en salles. `manual` : depuis la console, à la main. `ad_ou` : par l'**unité d'organisation** qui contient l'objet ordinateur — l'agent lit son propre DN dans le registre, sans interroger l'annuaire — une salle par OU, nommée comme elle. `ad_location` : par l'attribut **Emplacement** de l'objet ordinateur (onglet Emplacement d'ADUC), que l'agent lit via ADSI. Dans les deux modes annuaire, le rattachement manuel est verrouillé ; les salles créées gardent nom, bâtiment et notes modifiables. Après un changement de ce réglage, « Resynchroniser depuis l'annuaire » sur la page Salles reclasse tout le parc d'un coup |
| `AGENT_EXPECTED_VERSION` | *(vide)* | Version d'agent de référence pour le filtre « agent obsolète », la carte du tableau de bord et l'alerte de la fiche. Vide : la référence est la **plus haute version remontée par le parc** — juste le lendemain d'un déploiement, sans appel à GitHub. À fixer quand on déploie d'abord sur un groupe pilote, pour ne pas voir tout le reste du parc signalé en retard. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |

### Sessions de la console

Une connexion à la console ouvre une **session côté serveur** (table
`auth_sessions`), vue à travers deux jetons :

- un **jeton d'accès** (JWT, `ACCESS_TOKEN_EXPIRE_MINUTES`, 15 min), que la page
  garde en mémoire — jamais dans le stockage du navigateur — et envoie à chaque
  appel. Le serveur vérifie à chaque requête que sa session est encore ouverte :
  une déconnexion ou une révocation prend effet **à la requête suivante** ;
- un **jeton de session**, dans un cookie `HttpOnly; SameSite=Strict;
  Path=/api/v1/auth`, et `Secure` hors `ENVIRONMENT=local`. Aucun script de la
  page ne peut le lire ; il ne sert qu'à obtenir un nouveau jeton d'accès, et
  **change à chaque usage**. Un jeton de session déjà échangé qui se représente
  signifie qu'une copie circule : la session est fermée pour tout le monde et
  l'évènement journalisé (`app.security`, « presumed theft »).

Ferment toutes les sessions d'un compte : le changement de son mot de passe, sa
réinitialisation (par lien ou par un administrateur), sa désactivation, sa
suppression. Chacun voit et ferme ses propres sessions depuis « Mon compte » —
fermeture tracée dans le journal d'audit (`auth.session_revoked`).

**À la mise à jour vers cette version**, les jetons émis auparavant ne portent
pas de session et sont refusés : chaque opérateur se reconnecte une fois. La même
migration (`0024`) rend les adresses e-mail **insensibles à la casse** — elles
sont passées en minuscules — et **s'interrompt sans rien modifier** si deux
comptes ne diffèrent que par la casse de leur adresse, en les nommant : renommer
ou supprimer l'un des deux (page Utilisateurs de la version précédente, ou en
base), puis relancer.

**Verrouillage des comptes.** Après `LOGIN_MAX_FAILED_ATTEMPTS` échecs (5),
chacun à moins de `LOGIN_LOCKOUT_MINUTES` minutes (15) du précédent, un compte
est **verrouillé** pour `LOGIN_LOCKOUT_MINUTES` minutes. Un échec plus ancien ne
compte plus : quelques fautes de frappe étalées sur la semaine ne verrouillent
pas. Le verrou ne ferme le compte qu'aux **adresses qui ont échoué dessus**
pendant cette durée : le bon mot de passe saisi depuis un autre poste ouvre la
session et lève le verrou, si bien qu'échouer exprès ne bloque pas un
administrateur. Pendant un verrou, la console répond le même 401 qu'à un
mauvais mot de passe : la réponse ne dit pas quels comptes existent.

Si les essais viennent de nombreuses adresses — dès que
`LOGIN_SIEGE_ADDRESSES` adresses distinctes (10) ont échoué sur le compte en
`LOGIN_LOCKOUT_MINUTES` — le verrou s'étend à toutes les adresses sauf les
**adresses habituelles** du compte : celles qui l'ont ouvert depuis
`LOGIN_KNOWN_ADDRESS_DAYS` jours (30). Répartir les essais sur un réseau entier
n'en donne donc pas davantage. Une adresse devient habituelle par une connexion
réussie, le reste tant qu'une session y est utilisée, et le devient aussi quand
un lien « mot de passe oublié » y est utilisé. Un changement de mot de passe
efface les adresses habituelles de l'ancien, sauf celle d'où le nouveau vient
d'être choisi.

**Essais lents.** Des échecs espacés de plus de `LOGIN_LOCKOUT_MINUTES` ne
s'additionnent pas pour le verrou ci-dessus. Un second compteur les prend :
`LOGIN_SLOW_MAX_FAILED_ATTEMPTS` échecs (20), même espacés, en
`LOGIN_SLOW_WINDOW_HOURS` heures (24) depuis le premier posent un second
verrou, pour `LOGIN_SLOW_WINDOW_HOURS` heures. Il suit la règle du premier, sur
sa propre fenêtre : il ferme le compte aux **adresses qui ont échoué dessus
depuis le début de cette fenêtre**, jusqu'à sa fin et quel que soit le temps
qu'elles laissent entre deux essais — pas aux adresses que le compte n'a jamais
vues. Le bon mot de passe saisi depuis une adresse qui n'a pas échoué ouvre la
session, habituelle ou non : compte neuf, nouveau poste, mot de passe tout juste
réinitialisé par un administrateur. Une seule adresse extérieure ne tient donc
personne dehors. Une adresse qui échoue pendant le verrou rejoint celles qu'il
écarte ; et dès que `LOGIN_SIEGE_ADDRESSES` adresses distinctes (10) ont échoué
depuis le début de la fenêtre, il s'étend comme ci-dessus à toutes les adresses
sauf les **adresses habituelles**.

Une connexion réussie lève le verrou ordinaire, **pas celui-ci**, et ne remet
pas son compteur à zéro : sinon le titulaire qui se connecte chaque matin
rendrait chaque jour un budget neuf à qui devine lentement. La fenêtre dure au
moins autant que le verrou qu'elle a posé ; le premier échec qui suit la fin du
verrou en ouvre une nouvelle, avec un nouveau budget. Seul un **nouveau mot de
passe** — lien « Mot de passe oublié », réinitialisation par un administrateur,
changement par le titulaire — efface le compteur, la fenêtre et le verrou. Ce
verrou figure au journal d'audit (`user.locked`, avec `via: slow_attempts`), une
fois par fenêtre, et la page Utilisateurs affiche le compte « Verrouillé »
jusqu'à sa fin.

Adresses en échec et adresses habituelles sont **en base**
(`user_login_addresses`, purgée chaque matin de ce qu'aucun verrou ne peut plus
lire) : un redémarrage de l'API ne lève pas un verrou et n'oublie pas les postes
habituels.

Trois limites à connaître :

- Le titulaire qui se présente depuis une adresse **jamais vue**, pendant que
  des essais arrivent de `LOGIN_SIEGE_ADDRESSES` adresses ou plus, est refusé
  comme les autres — pour `LOGIN_LOCKOUT_MINUTES` sous le verrou ordinaire,
  jusqu'à la fin du verrou (`LOGIN_SLOW_WINDOW_HOURS` heures) sous celui des
  essais lents, que dix adresses suffisent donc à étendre ainsi. Sa sortie :
  « Mot de passe oublié » depuis ce poste — le lien utilisé rend l'adresse
  habituelle — ou une réinitialisation par un administrateur suivie d'une
  connexion rapide (elle efface les adresses habituelles : le poste du
  titulaire redevient une adresse jamais vue). Sous le verrou des essais lents,
  le plafond de liens du compte (`PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS`) ne
  s'applique pas : un tiers qui le tient plein ne ferme pas cette sortie, au
  prix de davantage de courriels possibles dans la boîte du titulaire (au plus
  `PASSWORD_RESET_MAX_LIVE_LINKS` par adresse qui demande). Une session déjà
  ouverte n'est pas touchée.
- Pendant un verrou, **une adresse qui échoue est écartée comme les autres**,
  celle du titulaire comprise. Sous le verrou des essais lents, une faute de
  frappe écarte un poste habituel pour `LOGIN_LOCKOUT_MINUTES` et une adresse
  non habituelle jusqu'à la fin du verrou ; de même une adresse non habituelle
  qui avait échoué plus tôt dans la fenêtre sans connexion réussie depuis (une
  connexion réussie efface l'échec de l'adresse). La réponse reste le 401 d'un
  mauvais mot de passe. Sortie : « Mot de passe oublié » depuis ce poste, ou un
  administrateur. En contrepartie, des essais faits depuis une adresse
  habituelle du compte ne sont ralentis par ce verrou qu'à un essai par
  `LOGIN_LOCKOUT_MINUTES`.
- Des opérateurs qui sortent tous par la **même adresse** (NAT, VPN, proxy
  absent de `TRUSTED_PROXIES`) partagent le verrou de l'adresse fautive ; et
  derrière un proxy non déclaré, toutes les requêtes semblent venir de lui.
  Déclarer le proxy (`TRUSTED_PROXIES`, `TRUSTED_PROXY_HOSTS`) avant tout.

La page Utilisateurs affiche « Verrouillé » ; une réinitialisation du mot de
passe par un administrateur lève les deux verrous. Le verrouillage et la
réinitialisation figurent au journal d'audit, chaque entrée avec l'adresse
source de la requête.

**Double authentification** (C7). Chacun l'active depuis « Mon compte » : un
code QR à scanner avec une application d'authentification (Microsoft
Authenticator, Google Authenticator, FreeOTP, Aegis…), un premier code pour
confirmer, puis **dix codes de secours** affichés une seule fois, à imprimer.
Un groupe peut l'**imposer** (case « Double authentification obligatoire » de
la page Groupes) : un membre qui ne l'a pas encore n'obtient qu'une session
d'enrôlement, qui ne donne accès qu'à « Mon compte » tant qu'il ne l'a pas
activée.

- La réponse de connexion ne dit qu'un code est attendu qu'**après** un mot de
  passe exact ; le mot de passe seul ne remet pas à zéro le compteur d'échecs et
  ne rend pas l'adresse « habituelle ».
- Un code ne sert qu'une fois ; l'horloge du serveur doit être juste à 30
  secondes près (NTP sur l'hôte Docker).
- `SECOND_FACTOR_MAX_FAILED_ATTEMPTS` codes faux de suite verrouillent le
  second facteur du compte `LOGIN_LOCKOUT_MINUTES` minutes ; chaque nouvelle
  série de codes faux double la durée, jusqu'à 24 heures, et seul un code juste
  remet le compteur à zéro (journal d'audit : `user.second_factor_locked`).
  Un administrateur lève le verrou en réinitialisant la double authentification.
- **Téléphone perdu** : un code de secours ; sinon un administrateur
  « Réinitialise la double authentification » du compte (page Utilisateurs) —
  ses sessions sont fermées, il en active une nouvelle à sa connexion suivante.
- **Ne pas s'enfermer dehors** : gardez un compte administrateur de secours dont
  les codes de secours sont imprimés et rangés, ou qui n'est dans aucun groupe
  à double authentification obligatoire.
- Les secrets sont chiffrés en base sous `TOTP_ENCRYPTION_KEY` (à défaut, une
  clé dérivée de `SECRET_KEY`) ; les codes de secours n'y sont que hachés.
  Renseigner `TOTP_ENCRYPTION_KEY` sur une installation où des comptes ont déjà
  un second facteur ne les efface pas : chaque secret est relu sous l'ancienne
  clé et rechiffré sous la nouvelle **à sa prochaine utilisation**. Tant qu'un
  compte ne s'est pas reconnecté, son secret dépend encore de `SECRET_KEY` :
  ne changer `SECRET_KEY` qu'après que tous l'ont fait, ou réinitialiser la
  double authentification des retardataires.

**Connexion par l'annuaire** (C7, OpenID Connect ; désactivée par défaut). Un
bouton « Se connecter avec Microsoft » s'ajoute à la page de connexion ; le mot
de passe reste toujours possible.

1. **Inscription d'application** dans Entra ID (Microsoft Entra, « Inscriptions
   d'applications », « Nouvelle inscription ») : comptes de ce seul annuaire ;
   URI de redirection de type **Web** égale à `OIDC_REDIRECT_URI`, soit
   `https://<serveur>/api/v1/auth/oidc/callback`.
2. **Certificats et secrets** : un secret client → `OIDC_CLIENT_SECRET` (noter
   son échéance : un secret expiré coupe la connexion par l'annuaire, pas
   celle par mot de passe).
3. **Configuration du jeton** : « Ajouter une revendication de groupes »,
   *groupes affectés à l'application*, émis en **ID de groupe**. Affecter à
   l'application (« Applications d'entreprise », « Utilisateurs et groupes »)
   les groupes qui doivent entrer. Sans cette restriction, un compte membre de
   plus de 200 groupes reçoit un jeton sans la liste, et sa connexion est
   refusée (`auth.oidc.too_many_groups`).
4. `.env` : `OIDC_ENABLED=true`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`,
   `OIDC_CLIENT_SECRET`, puis redémarrer le backend.
5. **Page Groupes** : dans chaque groupe de Tia'i, « Groupes de l'annuaire »
   reçoit l'ID d'objet des groupes Entra correspondants.

À la première connexion, un compte est créé si le jeton porte au moins un
groupe relié ; sinon la connexion est refusée. Ensuite, à chaque connexion, les
groupes reliés sont recalculés d'après l'annuaire ; ceux donnés à la main dans
la console restent. Un compte de l'annuaire n'a pas de mot de passe dans la
console ni de double authentification de la console : elle se règle chez Entra
(accès conditionnel). Un **compte local existant** de même adresse n'est jamais
rattaché d'office : son titulaire l'associe depuis « Mon compte », connecté par
mot de passe ; il garde alors son mot de passe et ses groupes.

**Réseau** : le serveur doit joindre `login.microsoftonline.com` en HTTPS
(directement ou par `OIDC_PROXY_URL`). **Secours** : la console refuse de
désactiver, de priver de « Comptes : gérer » ou de supprimer le dernier compte
**local** qui gère les comptes ; un annuaire injoignable ne ferme donc jamais la
console.

**Webhooks et jetons d'API** (C8).

*Webhooks* — Paramètres, carte « Webhooks » (droits « Webhooks : consulter »
et « Webhooks : gérer », administrateurs par défaut, avec « Paramètres :
consulter » pour atteindre la page, et un compte sans limite de lieux : les
évènements portent sur tout le parc). Un webhook envoie à une adresse les
évènements choisis : menace détectée (récente : l'historique de Defender
remonté par un premier inventaire n'en est pas une, comme pour l'e-mail),
alerte ouverte ou résolue, vérification demandée ou close, commande échouée
(verdict du poste, ou commande restée sans réponse ; pas les commandes que le
serveur clôt lui-même après un geste d'opérateur : fusion de postes, paquet
supprimé, retiré ou modifié après la mise en file, lecture de l'annuaire qui
n'est plus permise au poste ; ni un réveil refusé sur-le-champ, que la console
montre à qui l'a demandé). Une évaluation des
alertes, une demande de vérification pour plusieurs postes ou les
vérifications ouvertes par les alertes font **un** envoi, qui les liste ;
chaque vérification y porte son `check_id`, que reprend `check.closed`. Trois formats : **JSON signé** (pour un script ou un
outil de tickets), **Microsoft Teams** et **Mattermost** (« Webhooks
entrants » ; Slack comprend le même format). Ces deux derniers reçoivent un
corps `{"text": "…"}` rédigé dans la langue du webhook : c'est ce qu'attend le
connecteur « Incoming Webhook » d'un canal Teams ; un flux Power Automate
(« Workflows ») qui le remplace doit lire ce champ `text`. Les envois passent par une file en
base, envoyée par le worker : une destination en panne est réessayée pendant
environ une journée (`WEBHOOK_MAX_ATTEMPTS`), puis l'envoi est abandonné et
noté dans l'historique du webhook ; un destinataire en panne ne retarde pas les
autres. Un envoi dure au plus `WEBHOOK_TIMEOUT_SECONDS` en tout, et la réponse
n'est pas lue : seul son code compte. Désactiver un webhook abandonne ses envois
en attente. Le bouton « Envoyer un essai » envoie aussitôt un évènement `test`.

Chaque envoi porte `X-Tiai-Event`, `X-Tiai-Delivery` (identifiant, à utiliser
pour ignorer un doublon) et `X-Tiai-Signature: t=<horodatage>,v1=<signature>`,
où la signature est le HMAC-SHA256, en hexadécimal, de `<horodatage>.<corps>`
avec le secret du webhook (montré à la création et au renouvellement
seulement). Le destinataire recalcule la signature et refuse un horodatage
trop ancien (cinq minutes, par exemple) :

```python
import hashlib, hmac, time

def verifie(secret: str, entete: str, corps: bytes) -> bool:
    parts = dict(p.split("=", 1) for p in entete.split(","))
    attendu = hmac.new(secret.encode(), parts["t"].encode() + b"." + corps,
                       hashlib.sha256).hexdigest()
    return (hmac.compare_digest(attendu, parts["v1"])
            and abs(time.time() - int(parts["t"])) < 300)
```

**Destinations refusées** : un webhook fait émettre au serveur des requêtes
vers l'adresse qu'on lui donne. Seul `https://` est accepté, sans identifiant
dans l'adresse ; une adresse qui se résout vers le réseau interne (privée, de
bouclage, lien-local — dont le service de métadonnées des clouds —, partagée
(CGNAT), site-local, multicast ou réservée, y compris écrite en IPv6 :
NAT64, 6to4, Teredo) est refusée, à l'enregistrement **et** à chaque envoi. La
connexion va à l'adresse vérifiée, et non à une nouvelle résolution du nom : un
serveur DNS qui répondrait autrement la seconde fois (*DNS rebinding*) n'y gagne
rien ; le nom reste dans l'en-tête `Host` et la négociation TLS, et le
certificat est vérifié pour lui. Le nom est lu comme le client HTTP l'envoie
(IDNA 2008 : `straße` est `xn--strae-oqa`). Aucune redirection n'est suivie.
Par un proxy — `WEBHOOK_PROXY_URL`, ou à défaut celui de l'environnement
(`HTTPS_PROXY`, transmis par Docker, `NO_PROXY` respecté) —, c'est le proxy qui
résout le nom et se connecte : le contrôle porte sur la résolution du serveur,
et le proxy doit lui-même refuser le réseau interne. Le journal d'audit ne garde que l'hôte d'un webhook, pas son
chemin, qui est le secret des webhooks entrants de Teams ou Mattermost. Un outil du réseau de l'établissement (un Mattermost
interne) se déclare dans `WEBHOOK_ALLOWED_HOSTS` ; `http://` est alors admis
pour lui. Le serveur doit pouvoir joindre la destination en HTTPS (directement
ou par `WEBHOOK_PROXY_URL`).

**Approbation à deux** (C10). Désactivée par défaut (`APPROVAL_ENABLED`,
puis Paramètres). Activée, une commande **à risque** (redémarrage, extinction,
mises à jour Windows, réparations, installation ou désinstallation d'un paquet)
envoyée à **plus de** `APPROVAL_THRESHOLD` postes — comptés dans la portée de
l'auteur, jetons révoqués exclus — n'est pas mise en file : elle devient une
**demande** qu'un **autre compte**, détenant les mêmes droits (« Commandes :
exécuter » et « Commandes à risque : exécuter », plus « Planifications :
gérer » pour une planification) et voyant **tous** les postes visés, approuve
ou refuse depuis la page « Approbations ». L'approbation exécute la liste figée
à la demande (moins les postes supprimés ou sortis de la portée de l'auteur
depuis), au nom de l'auteur, après avoir tout revérifié : compte et droits de
l'auteur, paquet (un paquet modifié depuis fait échouer la demande), plages
interdites à l'heure de l'approbation. Une demande expire après
`APPROVAL_TTL_HOURS` ; son auteur peut l'annuler ; un auteur a au plus vingt
demandes en attente. Une planification à risque au-delà du seuil est
approuvée **une fois**, à l'écriture, pour son auteur et son nombre de postes :
une modification, une réactivation par un autre compte ou une cible devenue
plus large redemande une approbation (la planification est suspendue au
départ d'une exécution qui dépasserait ce qui a été approuvé). Les comptes
capables d'approuver reçoivent un e-mail (sauf préférence « rien ») ; un
webhook peut s'abonner à `approval.requested`.

L'approbation **ne s'active pas** avec moins de deux comptes capables
d'approuver : dans un établissement à un seul administrateur, elle bloquerait
tout. Ce nombre, affiché dans Paramètres, **ne tient pas compte des lieux** :
un approbateur limité à des sites doit couvrir **tous** les postes d'une
demande, et deux comptes limités à deux sites différents ne s'approuvent pas
l'un l'autre. Une demande que personne d'autre ne pourrait approuver est
refusée à sa création (« aucun approbateur possible ») plutôt que d'attendre
son expiration ; retirer un droit ou désactiver un compte n'est jamais bloqué
pour autant. Approuver ou refuser demande une session de la console : un jeton
d'API est refusé. Ce que l'approbation ne protège pas : le seuil s'applique
**par envoi** — une action découpée en lots de `APPROVAL_THRESHOLD` postes ou
moins (console, script, plusieurs planifications) n'est pas arrêtée, chaque
lot laissant sa ligne `command.bulk` au journal ; une même personne disposant
de deux comptes (local de secours et annuaire) peut s'approuver elle-même ; un
compte qui détient « Paramètres : gérer » peut désactiver l'approbation puis
agir seul (`settings.update` au journal).

Dans la console : carte « Approbation à deux » de Paramètres (interrupteur,
seuil, validité, nombre de comptes capables d'approuver ; l'interrupteur reste
grisé sous deux) ; page « Approbations » dans le menu, après « Planifications »,
pour les comptes qui détiennent « Commandes à risque : exécuter », tant que
l'approbation est activée ou qu'il reste des demandes — onglets « À approuver »
(badge orange dans le menu) et « Mes demandes » (statut, motif d'un refus,
cause d'un échec, annulation). L'approbateur voit les postes de la demande
qu'il couvre et, à l'heure d'une plage interdite, la même confirmation que
l'auteur. Un envoi en masse ou un déploiement mis en attente le dit (« Demande
d'approbation envoyée pour N postes… », avec « Voir ») ; une planification en
attente apparaît « À approuver » sur la page Planifications.

*Jetons d'API* — « Mon compte », carte « Jetons d'API » (droit « Jetons d'API :
créer des jetons », administrateurs par défaut). Créer un jeton demande le mot
de passe du compte, et un code s'il a la double authentification ; un compte de
l'annuaire doit s'être connecté depuis moins de dix minutes. Une session volée
ne peut donc pas se donner un accès qui survive à la reprise du compte. Un
jeton `tiai_pat_…` permet à un script d'appeler l'API, dans l'en-tête
`Authorization: Bearer <jeton>` :

```bash
curl -H "Authorization: Bearer tiai_pat_…" https://<serveur>/api/v1/machines
```

Il agit avec les droits et la portée de son compte **au moment de l'appel** ;
en **lecture seule** sauf si l'écriture a été cochée à sa création ; il expire
(1 à 365 jours, 90 par défaut) ; il n'atteint jamais le compte lui-même (mot de
passe, sessions, second facteur, jetons, annuaire — seul `GET /auth/me` répond,
pour qu'un script sache au nom de qui il agit), ni depuis « Mon compte » ni
depuis la page des comptes (`/users/<son propre id>` : adresse, mot de passe,
groupes, désactivation). Un compte dont un groupe exige la double
authentification et qui ne l'a pas activée n'a pas d'accès par jeton tant
qu'il ne l'a pas fait. Il n'est montré qu'une fois ;
seul son hachage est gardé. Création et révocation sont au journal d'audit ; la
carte montre la dernière utilisation. Tous les jetons d'un compte sont révoqués
quand un administrateur le désactive, réinitialise son mot de passe ou son
second facteur.

Avec l'approbation à deux activée, `POST /api/v1/commands` peut répondre
**202** : rien n'est parti, une demande attend un second compte. Le corps
porte alors `approval_id` (la demande), `approval_expires_at` et
`pending_approval` (les postes en attente) ; `count` y vaut 0 et ne veut **pas**
dire « rien à faire ». Un script lit `approval_id` (et le statut HTTP), pas
`count`. Renvoyer la même requête tant qu'elle attend redonne la même demande.

Pour **déconnecter tout le monde** d'un coup (clé `SECRET_KEY` divulguée, poste
compromis), changer `SECRET_KEY` puis fermer toutes les sessions — sans
`TOTP_ENCRYPTION_KEY`, cela efface aussi en pratique tous les seconds facteurs
(cf. ci-dessus), et les secrets des webhooks deviennent illisibles : leurs
envois échouent (« signing secret unreadable ») jusqu'à « Nouveau secret » sur
chacun, à reporter chez le destinataire. Les jetons d'API ne dépendent pas de
`SECRET_KEY` : les révoquer, s'il le faut, depuis « Mon compte » de chacun ou
en désactivant le compte :

```bash
cd deploy
docker compose exec db-backup sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
   -c "UPDATE auth_sessions SET revoked_at = now() WHERE revoked_at IS NULL"'
```

### Réveil des postes (Wake-on-LAN)

Voir la section « [Réveil des postes](#réveil-des-postes-wake-on-lan-1) » plus
bas pour ce qui doit être vrai du poste, du réseau et de l'hôte Docker — les
variables ci-dessous ne décrivent que la destination du paquet.

| Variable | Défaut | Rôle |
|---|---|---|
| `WOL_SUBNET_PREFIXLEN` | `24` | **Repli seulement.** Le masque vient normalement du poste lui-même : son agent le lit sur la carte et le remonte avec l'adresse, ce qui est la seule source juste sur un parc où cohabitent des /16 et des /24. Ce réglage ne sert qu'aux postes dont l'agent est antérieur à cette remontée, ou dont la carte n'a pas exposé de masque |
| `WOL_BROADCAST_ADDRESSES` | *(vide)* | Adresses de diffusion explicites, séparées par des virgules. Renseignées, elles **remplacent** l'adresse déduite et servent pour *tous* les postes — la réponse pour un serveur qui doit joindre des segments où il n'a pas d'adresse, et le seul moyen de réveiller un poste qui n'a jamais remonté d'IP |
| `WOL_ALLOWED_NETWORKS` | *(vide)* | Réseaux (CIDR, séparés par des virgules) vers lesquels le serveur accepte de diffuser un réveil déduit de l'adresse d'un poste. Vide : les plages privées RFC 1918 (10/8, 172.16/12, 192.168/16), et elles seules. Renseignée, la liste **remplace** ces plages, elle ne s'y ajoute pas : y remettre celles du parc qui doivent rester joignables. Une entrée qui n'est pas un réseau IPv4 lisible est refusée au démarrage du backend, qui la nomme. Le sous-réseau déduit (adresse et masque remontés) doit tenir entièrement dans l'un de ces réseaux ; sinon le préfixe par défaut est essayé, sinon le poste n'a pas de destination. Un masque hors de /16 à /30 n'est pas retenu |
| `WOL_PORT` | `9` | Port UDP du paquet magique. Indifférent au matériel (la carte reconnaît le motif n'importe où dans la trame) ; ne compte que pour un pare-feu sur le trajet |
| `WOL_PACKET_COUNT` | `3` | Nombre de copies émises. Une diffusion UDP n'accuse rien et se perd sans bruit ; trois copies coûtent trois datagrammes |
| `WOL_RELAY_ENABLED` | `false` | **Serveur distant.** À `true`, le serveur n'émet plus rien lui-même : il confie le réveil au premier poste allumé du **même emplacement** que la cible (à défaut d'emplacement, du même domaine) qui le contacte, et c'est l'agent de ce poste qui diffuse le paquet magique sur ses propres sous-réseaux. Voir le point 4 de la section « Réveil des postes » |
| `WOL_RELAY_TTL_MINUTES` | `10` | Délai laissé à un poste relais pour prendre un réveil en attente ; passé ce délai, il expire. Court à dessein : un réveil relayé une heure plus tard rencontre un poste que quelqu'un a déjà rallumé à la main |
| `WOL_RELAY_SUBNET_GRACE_SECONDS` | `90` | Un poste du **même sous-réseau** que la cible prend le réveil aussitôt ; un poste d'un autre VLAN du même emplacement attend ce délai — un cycle d'agent — pour laisser la priorité au mieux placé. `0` supprime la préférence |
| `WOL_RELAY_MIN_AGE_MINUTES` | `60` | Un poste enrôlé depuis moins longtemps ne relaie pas de réveil ; un poste « identité à confirmer », au token révoqué, ou d'agent plus ancien que `WOL_RELAY_MIN_AGENT_VERSION` non plus |
| `WOL_RELAY_MIN_AGENT_VERSION` | `1.0.0` | Version d'agent minimale d'un poste relais : un agent plus ancien, qui garderait le réveil sans savoir l'émettre, n'en reçoit aucun. Comparée champ par champ (`1.10.0` > `1.9.0`), une pré-version (`1.0.0-dev.…`) passant sous la version qu'elle précède. Un poste qui ne remonte aucune version, ou une version illisible (`dev`), **ne relaie pas** non plus : rien ne dit que son agent connaît la commande |
| `WOL_RELAY_CLAIM_TIMEOUT_SECONDS` | `180` | Un réveil pris par un relais qui ne rend pas de verdict dans ce délai retourne dans la file, pour qu'un autre poste le prenne |

### Alertes e-mail et e-mails de compte

Facultatif. L'envoi d'e-mails sert aux notifications de supervision et au lien
de réinitialisation de mot de passe. Sans fournisseur configuré, le parcours
« mot de passe oublié » reste sans effet : c'est alors à un administrateur de
réinitialiser le mot de passe depuis la console.

Le courrier part par l'un de deux canaux, au choix de `EMAIL_PROVIDER` :

- **`mailgun`** *(défaut)* — l'API HTTP de Mailgun. Un compte se crée facilement
  sur [mailgun.com](https://www.mailgun.com/) ; le domaine d'envoi et la clé API
  à reporter ci-dessous se trouvent ensuite dans son tableau de bord. Désactivé
  tant que `MAILGUN_DOMAIN` ou `MAILGUN_API_KEY` est vide.
- **`smtp`** — n'importe quel serveur SMTP : le relais de l'établissement, un
  compte Microsoft 365 (`smtp.office365.com:587`, STARTTLS) ou Google Workspace
  (`smtp.gmail.com:587`, STARTTLS, mot de passe d'application), un fournisseur
  transactionnel qui expose un point d'entrée SMTP. Désactivé tant que
  `SMTP_HOST` ou l'adresse d'expéditeur est vide.

Seules les variables du fournisseur choisi sont lues ; celles de l'autre sont
ignorées. L'expéditeur (`EMAIL_FROM_EMAIL` / `EMAIL_FROM_NAME`) est commun aux
deux — les anciens noms `MAILGUN_FROM_EMAIL` / `MAILGUN_FROM_NAME` restent
acceptés, un `.env` écrit avant l'arrivée de SMTP n'a rien à renommer.

**Tout cela se règle aussi depuis la console**, carte « Envoi des e-mails » de la
page Paramètres (permission `settings:write`) : fournisseur, expéditeur, serveur
SMTP, port, sécurité, identifiants, vérification du certificat, délai, domaine,
clé et adresse de l'API Mailgun. Comme pour les seuils, les variables du `.env`
ne sont plus que des **valeurs initiales** : un champ enregistré dans la console
prend le dessus, champ par champ, et un champ laissé vide reprend la valeur du
serveur. Le changement s'applique au prochain envoi, sans redémarrage — le
worker relit la configuration à chaque passage sur la file. Seuls
`MAILGUN_PROXY_URL` et `MAILGUN_TIMEOUT_SECONDS`, qui décrivent le réseau du
serveur et non le compte d'envoi, restent dans le `.env`.

Le bouton **« Envoyer un e-mail de test »** envoie aussitôt un message — sans
passer par la file — à votre adresse ou à celle indiquée, avec les valeurs du
formulaire, *même pas encore enregistrées* : on vérifie un serveur et un mot de
passe avant de les adopter. La réponse dit en clair ce qui coince
(identifiants refusés, port ou mode de sécurité incohérents, certificat non
vérifiable, domaine Mailgun inconnu…). Chaque test est inscrit au journal
d'audit (`settings.email_test`), comme chaque modification (`settings.update`)
— où un mot de passe ou une clé n'apparaît jamais, seulement « modifié » ou
« effacé ».

> **Sécurité — identifiants enregistrés dans la console.** Le mot de passe SMTP
> et la clé API Mailgun saisis dans la console sont **chiffrés** en base
> (Fernet, clé dérivée de `SECRET_KEY` par HKDF, distincte de celle qui signe
> les sessions) et ne sont jamais réaffichés : la page indique seulement
> « enregistré ». Une sauvegarde de la base ne suffit donc pas à les lire, mais
> **changer `SECRET_KEY` les rend illisibles** : ils sont alors ignorés (la
> valeur du `.env` s'applique, s'il y en a une) et la page les signale « à
> ressaisir ». Après une rotation de `SECRET_KEY`, ressaisissez-les dans la
> carte « Envoi des e-mails ». Une restauration de la base sur un autre serveur
> demande la même `SECRET_KEY` pour les conserver.

**Qui reçoit quoi se règle par compte**, page « Mon compte » de la console, et un
administrateur voit et modifie le réglage des autres comptes depuis la page
Utilisateurs. Quatre cadences :

| Cadence | Ce qui part |
|---|---|
| Aucun e-mail | rien (les e-mails de compte, comme la réinitialisation, continuent d'arriver) |
| Alerte immédiate à chaque menace | un e-mail dès qu'un poste signale une menace **nouvellement** détectée |
| Résumé quotidien, seulement s'il y a du nouveau | un e-mail les jours où il y a à traiter : menace active, mise à jour critique ou importante en attente, poste à vérifier |
| Résumé quotidien, tous les jours *(défaut)* | un e-mail chaque matin, même sans incident : état du parc, antivirus périmés, postes à mettre à jour |

Chaque e-mail est d'abord une ligne dans la table `email_outbox`, écrite dans la
même transaction que ce qui le motive — détection, résumé, lien de
réinitialisation — puis envoyée par le worker, avec de nouvelles tentatives
espacées en cas d'échec. Une panne du fournisseur ou du proxy sortant retarde donc
un e-mail au lieu de le perdre, et ne fait jamais échouer la remontée d'un poste.

Il n'y a **aucune liste de destinataires dans la configuration** : le courrier
ne part qu'aux comptes de la console, selon la cadence de chacun. Une nouvelle
installation n'est pas pour autant sans surveillance — le premier admin, créé au
démarrage à partir de `FIRST_ADMIN_EMAIL`, arrive sur le résumé quotidien, à une
adresse réelle et modifiable depuis la console.

| Variable | Défaut | Rôle |
|---|---|---|
| `EMAIL_PROVIDER` | `mailgun` | `mailgun` ou `smtp` : le canal par lequel le courrier part. **Valeur initiale** de cette variable et des suivantes, jusqu'à `SMTP_TIMEOUT_SECONDS` (sauf `MAILGUN_TIMEOUT_SECONDS` et `MAILGUN_PROXY_URL`) : la console peut les remplacer |
| `DEFAULT_LANGUAGE` | `fr` | Langue des e-mails d'un compte qui n'a pas choisi la sienne dans « Mon compte » (l'e-mail de test part dans la langue de l'administrateur qui l'envoie, sinon dans celle-ci) : `fr` ou `en`. Les exports suivent la langue de la console. La console suit le choix du compte, sinon la langue du navigateur |
| `EMAIL_FROM_EMAIL` / `EMAIL_FROM_NAME` | — / `Tia'i` | Expéditeur, commun aux deux canaux. Avec un compte SMTP authentifié, l'adresse doit en général être celle du compte ou un alias autorisé. `MAILGUN_FROM_EMAIL` / `MAILGUN_FROM_NAME` restent acceptés en repli |
| `MAILGUN_API_BASE_URL` | `https://api.mailgun.net/v3` | |
| `MAILGUN_DOMAIN` / `MAILGUN_API_KEY` | — | Vides = aucun e-mail n'est envoyé avec `EMAIL_PROVIDER=mailgun` |
| `MAILGUN_TIMEOUT_SECONDS` | `10` | |
| `MAILGUN_PROXY_URL` | — | Proxy HTTP sortant pour le seul client Mailgun (ex. `http://10.0.0.1:3128`), utile derrière le proxy d'un établissement. Volontairement distinct de `HTTP_PROXY`/`HTTPS_PROXY`, que tous les processus honoreraient — Caddy compris |
| `SMTP_HOST` / `SMTP_PORT` | — / `587` | Serveur SMTP. Hôte vide = aucun e-mail n'est envoyé avec `EMAIL_PROVIDER=smtp` |
| `SMTP_SECURITY` | `starttls` | `starttls` (connexion en clair puis chiffrée, port 587 — le cas général), `tls` (TLS implicite, port 465) ou `none` (en clair, pour un relais interne sur le port 25 qui authentifie par adresse source) |
| `SMTP_USER` / `SMTP_PASSWORD` | — | Identifiants, si le serveur en demande. Vides = pas d'authentification |
| `SMTP_VERIFY_TLS` | `true` | Vérification du certificat du serveur : la chaîne doit aboutir à une AC connue du conteneur, et le certificat porter le nom du serveur. Une AC interne « faite maison » (`openssl req -x509`, sans extension d'usage de clé) est acceptée comme en v1.2.0 : la lecture stricte de la RFC 5280, que Python applique par défaut depuis la 3.13, n'est pas demandée au serveur SMTP. À `false` seulement pour un relais interne dont le certificat n'est pas vérifiable depuis le conteneur (auto-signé, AC privée non montée) |
| `SMTP_TIMEOUT_SECONDS` | `10` | |
| `MAINTENANCE_REMINDER_WEEKDAY` | `0` | Jour du rappel hebdomadaire des maintenances à chaque responsable, à `DIGEST_HOUR_UTC` : `0` = lundi … `6` = dimanche. Un responsable sans rien de dû ne reçoit rien ; un compte sur « aucun e-mail » non plus. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |
| `DIGEST_HOUR_UTC` | `18` | Heure UTC du résumé quotidien. Le parc visé est à UTC-10, où 18:00 UTC = 08:00 sur place. **Valeur initiale seulement** : modifiable dans Paramètres, sans redémarrage |
| `THREAT_ALERT_MAX_AGE_HOURS` | `24` | Une détection plus ancienne ne déclenche pas d'alerte immédiate : un poste qui s'enrôle remonte tout l'historique Defender d'un coup |
| `NOTIFICATION_MAX_ITEMS` | `10` | Postes détaillés dans un e-mail avant « … et N autres » |
| `EMAIL_MAX_ATTEMPTS` | `20` | Tentatives d'envoi avant abandon d'un e-mail (délai doublé de 1 min à 1 h entre chacune, soit ≈ 14 h — de quoi traverser une nuit de panne du proxy) |
| `EMAIL_OUTBOX_RETENTION_DAYS` | `30` | Durée de conservation des lignes réglées (envoyées ou abandonnées) de `email_outbox`, pour consultation |

Les liens des e-mails (fiche d'un poste, vos tâches) pointent sur
`CONSOLE_BASE_URL`, donc par défaut sur `https://<TIAI_SERVER_NAME>`.

### Hors Docker

| Variable | Portée | Rôle |
|---|---|---|
| `API_BASE_URL` | Build frontend | baseURL axios, injectée au build ; défaut `/api/v1` |
| `TIAI_TEST_DATABASE_URL` | Tests backend | DSN Postgres pour les tests d'API |

---

## Rôle applicatif PostgreSQL

Le backend et le worker se connectent avec un rôle **sans superutilisateur**,
propriétaire des seules tables de Tia'i (`POSTGRES_APP_USER`, `tiai_app` par
défaut). Le compte `POSTGRES_USER` de l'image, superutilisateur, ne sert plus
qu'à l'initialisation et aux sauvegardes. Un superutilisateur peut lire et
écrire n'importe quel fichier du serveur de base et y lancer un programme : une
injection SQL ou une dépendance compromise côté backend vaudrait la main sur
l'hôte de la base. Hors `ENVIRONMENT=local`, le backend et le worker
**refusent de démarrer** s'ils se retrouvent superutilisateurs.

**Installation neuve** : renseigner `POSTGRES_APP_PASSWORD` dans le `.env` ;
le script [deploy/db/app-role.sh](deploy/db/app-role.sh) crée le rôle à la
première initialisation du volume.

**Base existante** (montée depuis une version sans ce rôle), une seule fois :

```bash
cd deploy
# 1. Ajouter POSTGRES_APP_PASSWORD au .env (openssl rand -hex 32).
# 2. Recréer db pour qu'il voie la variable, puis créer le rôle et lui donner
#    la base et ses tables (le script est idempotent) :
docker compose up -d db
docker compose exec db sh /docker-entrypoint-initdb.d/10-app-role.sh
# 3. Lever le reste de la stack, qui se connecte désormais avec ce rôle :
docker compose pull && docker compose up -d
```

Sans `POSTGRES_APP_PASSWORD`, `docker compose up` s'arrête avec un message qui
renvoie ici.

## Déploiement logiciel

Installer et désinstaller des logiciels depuis la console : par **winget**,
par **paquet signé** par l'administrateur (méthode B) ou par **exécutable d'un
éditeur approuvé** (méthode A). Chaque méthode est coupée tant qu'une GPO ne
l'ouvre pas sur les postes. **Le guide d'activation et d'utilisation est
[deploy/packages/README.md](deploy/packages/README.md)**, avec le script de
signature [Sign-TiaiPackage.ps1](deploy/packages/Sign-TiaiPackage.ps1).

Côté serveur :

| Variable | Défaut | Rôle |
|---|---|---|
| `PACKAGES_DIR` | `/data/packages` | Où les fichiers des paquets sont stockés, un par empreinte SHA-256. Monté sur le volume Docker `packages`. Le ménage des fichiers orphelins respecte un dépôt en cours, même mené par un autre processus de l'API (verrou dans PostgreSQL) |
| `PACKAGE_MAX_BYTES` | `2147483648` (2 Gio) | Taille maximale d'un fichier déposé, en octets (de 1 Mio à 8 Gio) ; au-delà, l'API répond un 413 qui nomme la limite. La console envoie un fichier par requête, et Caddy borne la requête entière sur la seule route de dépôt (cf. « Relever la taille maximale » ci-dessous) |
| `PACKAGE_METHOD_A_MAX_GB` | `8` | Taille totale, en Gio (1 à 1 024), qu'un paquet **non signé** (méthode A) peut annoncer. À tenir égale à la valeur de registre `DeployMethodAMaxGB` des postes : au-delà, le serveur et la console refusent le déploiement, au lieu de le laisser échouer sur chaque poste |
| `PACKAGE_MAX_CONCURRENT_DOWNLOADS` | `20` | Téléchargements servis en même temps par le processus de l'API. Au-delà, l'agent est prié de revenir (429) sans que sa commande échoue |

**Relever la taille maximale.** Le [Caddyfile](deploy/Caddyfile) plafonne la
route de dépôt à `max_size 2050MiB`, soit 2 Mio **au-dessus** du défaut de
`PACKAGE_MAX_BYTES` (2 Gio = 2 048 Mio). L'écart est voulu : Caddy compte toute
la requête, en-têtes du formulaire compris, et à égalité un fichier juste sous
la limite recevrait le 413 nu de Caddy au lieu de celui de l'API, qui dit
laquelle. La règle, pour un autre plafond : la limite de Caddy reste
**légèrement au-dessus** de `PACKAGE_MAX_BYTES`, jamais égale ni en dessous.
Pour 8 Gio, le plus que le backend accepte :

```bash
cd deploy
# 1. .env :      PACKAGE_MAX_BYTES=8589934592        (8 Gio = 8 192 Mio)
# 2. Caddyfile : max_size 8194MiB                    (bloc @package_upload)
docker compose up -d                          # backend et worker relisent le .env
docker compose up -d --force-recreate caddy   # Caddy relit son fichier
docker compose exec caddy grep max_size /etc/caddy/Caddyfile
```

`up -d` seul ne recrée pas `caddy` : son fichier est monté depuis l'hôte, et
Compose ne voit pas qu'il a changé. Le Caddyfile ainsi modifié est un fichier
local : le reporter à chaque mise à jour (§ « Mettre à jour le serveur »).

Le volume `packages` **n'est pas dans le dump PostgreSQL** (voir ci-dessous) :
le sauvegarder à part, ou garder les installateurs d'origine pour pouvoir les
redéposer.

## Sauvegardes et restauration

Toute la mémoire de Tia'i — postes, historique des menaces, commandes (qui a
redémarré quoi), comptes de la console, file d'e-mails — vit dans un seul
volume PostgreSQL. Le service `db-backup` du compose la sauvegarde **sans rien
configurer** : un dump à chaque démarrage du service (premier lancement,
redémarrage du serveur), puis un par 24 h, au format custom de `pg_dump` (`-Fc`,
compressé), dans `deploy/backups/` sur l'hôte. La rétention est de
`BACKUP_KEEP_DAYS` jours (défaut 14) et la purge n'a lieu qu'après un dump
réussi : une base en panne ne fait jamais disparaître les sauvegardes
existantes. Seuls les dumps quotidiens (`tiai-AAAAMMJJ-HHMMSS.dump`, ou
`.dump.age` chiffrés) sont purgés : un dump manuel sous un autre nom
(`tiai-avant-operation.dump`, ci-dessous) ou rangé dans un sous-dossier n'est
jamais supprimé.

Le service tourne sur une image construite par Compose depuis
`deploy/backup/Dockerfile` : celle de `db` (`postgres:16-alpine`, donc un
`pg_dump` de la même version que le serveur) plus l'outil de chiffrement
[`age`](https://age-encryption.org), installé une fois au build depuis le dépôt
signé d'Alpine. Le premier `docker compose up` la construit : il faut alors
joindre le registre Docker et `dl-cdn.alpinelinux.org` (derrière un proxy,
§ « Hôte Docker derrière un proxy »). `docker compose pull` ne la concerne pas.

**Hôte qui ne joint pas `dl-cdn.alpinelinux.org`** (miroir de registre seul,
filtrage sortant) : la construction échoue, et avec elle `docker compose up`
tout entier — les anciens conteneurs continuent de tourner, rien n'est mis à
jour. L'image se construit alors ailleurs et se dépose sur le serveur, sous le
nom que Compose lui donne : `deploy-db-backup` (`<projet>-db-backup` ; le
projet est le nom du dossier, sauf `COMPOSE_PROJECT_NAME` ou `-p` —
`docker compose config --images` l'affiche).

```bash
# Sur une machine qui joint Docker Hub et dl-cdn.alpinelinux.org, de même
# architecture que le serveur (sinon : --platform linux/amd64), depuis la
# racine du dépôt à la version visée :
docker build --pull -t deploy-db-backup deploy/backup
docker save deploy-db-backup | gzip > tiai-db-backup.tar.gz

# Sur le serveur, après y avoir copié le fichier :
docker load -i tiai-db-backup.tar.gz     # « Loaded image: deploy-db-backup:latest »
cd deploy
docker compose up -d                     # l'image existe : Compose ne la construit pas
```

À refaire à chaque mise à jour du serveur, à la place de
`docker compose build --pull db-backup` (étape 5 de § « Mettre à jour le
serveur »), qui échouerait de la même façon : l'image embarque le `pg_dump` de
`postgres:16-alpine`, à tenir à la version du service `db`.

Vérifier que ça tourne :

```bash
docker compose logs db-backup     # « sauvegarde OK : tiai-20260825-... »
sudo ls -lh backups/              # dumps en -rw------- (root), dossier en drwx------
```

Les dumps sont lisibles du seul propriétaire (`umask 077`, `chmod 600`), et le
dossier `deploy/backups/` est ramené en `700` à chaque démarrage du service, si
le système de fichiers le permet ; sinon (Docker en *userns-remap* ou sans
root, partage NFS en *root squash*) le service l'écrit dans son journal
(`docker compose logs db-backup`), et c'est le `chmod 700 backups` fait sur
l'hôte qui ferme le dossier. Les dumps contiennent les hachés des mots de passe
et tout l'inventaire du parc. Les
commandes de dump manuel ci-dessous posent elles aussi `umask 077` — un `sh -c`
lancé par `docker compose exec` n'hérite pas de celui du script de sauvegarde.
Par défaut, les dumps sont **en clair** : quiconque lit le dossier, le
disque ou une copie lit la base. Les chiffrer est un réglage, décrit au
paragraphe suivant ; sans lui, la copie hors de la machine **doit** être
chiffrée par d'autres moyens (archive chiffrée, coffre de sauvegarde,
`gpg --symmetric`…).

**Un dump sur le serveur ne protège pas du serveur.** Copier régulièrement
`deploy/backups/` hors de la machine (rsync, robocopy, tâche planifiée — peu
importe le moyen, l'important est qu'il existe), chiffré par `age` ou à la
copie. Pour pouvoir reconstruire le serveur de zéro, trois choses doivent
exister ailleurs (quatre avec le chiffrement) :

1. un dump récent de `deploy/backups/` ;
2. le fichier `deploy/.env` (les secrets ne sont dans aucun dump) ;
3. le certificat `deploy/certs/` (mode C) ;
4. avec le chiffrement, la **clé privée** `age` — et jamais sur le serveur.

### Chiffrer les sauvegardes

Optionnel, et recommandé dès que les dumps quittent la machine. Avec
`BACKUP_ENCRYPT_RECIPIENT`, chaque dump est chiffré **pour une clé publique**
`age` au moment où il est écrit : `pg_dump` sort dans un tube, `age` chiffre,
aucun octet en clair ne touche le disque. Le fichier s'appelle
`tiai-AAAAMMJJ-HHMMSS.dump.age`. Le serveur n'a que la clé publique, qui sait
chiffrer mais pas déchiffrer : un serveur volé, un disque récupéré, une copie
hors site interceptée ne livrent rien. La clé privée reste ailleurs, et ne sert
qu'à restaurer.

> **Le revers : perdre la clé privée, c'est perdre toutes les sauvegardes
> chiffrées pour elle.** Personne — ni Tia'i, ni l'éditeur d'`age` — ne peut
> les rouvrir. D'où deux clés, ci-dessous, et un exercice de restauration une
> fois la clé rangée.

**1. Créer les clés, sur une autre machine que le serveur** (poste
d'administration). `age` s'installe par `apt install age`, `brew install age`,
`winget install FiloSottile.age`, ou depuis les
[releases](https://github.com/FiloSottile/age/releases) :

```bash
age-keygen -o tiai-sauvegardes.key           # affiche « Public key: age1… »
age-keygen -o tiai-sauvegardes-secours.key   # une seconde, pour le coffre
```

Chaque fichier `.key` contient une clé privée (`AGE-SECRET-KEY-1…`, une ligne)
et, en commentaire, sa clé publique (`age-keygen -y fichier.key` la réaffiche).
**Ranger les clés privées** hors du serveur et hors des copies de sauvegarde :
gestionnaire de mots de passe de l'équipe, coffre, clé USB au coffre, voire
imprimée — la ligne tient sur une feuille. La seconde clé couvre la perte de la
première (départ d'un administrateur, poste perdu).

**2. Configurer.** Dans `deploy/.env`, les **clés publiques** seules, séparées
par une espace :

```bash
BACKUP_ENCRYPT_RECIPIENT=age1… age1…
```

puis `docker compose up -d db-backup` (la variable change : Compose recrée le
service, qui fait aussitôt un dump). Le journal le dit :

```bash
docker compose logs --tail 5 db-backup   # « sauvegarde OK : tiai-….dump.age (…, chiffrée) »
```

Si le chiffrement est demandé mais impossible — clé illisible, clé privée
collée par erreur (refusée : la retirer, et la tenir pour compromise), image
sans `age` —, le service **n'écrit aucun dump**, ni en clair ni chiffré, ne
purge rien, s'arrête sur une ligne `ECHEC : …` qui dit pourquoi, et redémarre
en boucle (`docker compose ps` : *Restarting*) jusqu'à correction. Les dumps
en clair d'avant le réglage restent : les quotidiens partent à leur échéance
(`BACKUP_KEEP_DAYS`), les manuels sont à effacer à la main, ainsi que leurs
copies hors site.

**3. Vérifier une sauvegarde.** Sur le serveur, sans clé, on ne peut que voir
qu'un fichier est chiffré (`head -c 21 backups/tiai-….dump.age` affiche
`age-encryption.org/v1`). La vraie vérification se fait là où est la clé, de
préférence sur la copie hors site : `age` authentifie le contenu, un fichier
tronqué ou altéré est refusé.

```bash
age -d -i tiai-sauvegardes.key tiai-AAAAMMJJ-HHMMSS.dump.age > /dev/null && echo intègre
# avec les outils PostgreSQL sur ce poste, la liste des objets du dump :
age -d -i tiai-sauvegardes.key tiai-AAAAMMJJ-HHMMSS.dump.age | pg_restore -l | head
```

Pour revenir aux dumps en clair : vider `BACKUP_ENCRYPT_RECIPIENT`, puis
`docker compose up -d db-backup`.

### Restaurer

Sur une stack levée (la base peut être vide ou pleine — `--clean` remet à
plat). Un dump chiffré (`.dump.age`) se déchiffre d'abord, voir plus bas.

```bash
cd deploy
docker compose stop backend worker      # plus personne n'écrit dans la base
docker compose exec db-backup sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h db -U "$POSTGRES_USER" \
   -d "$POSTGRES_DB" --clean --if-exists --no-owner --role="$POSTGRES_APP_USER" \
   /backups/tiai-AAAAMMJJ-HHMMSS.dump'
docker compose start backend worker
```

`--no-owner --role` rend les objets restaurés au rôle applicatif, y compris
depuis un dump antérieur à ce rôle : sans eux, les tables reviendraient au
superutilisateur et le backend ne pourrait plus y écrire.

**Dump chiffré.** Le déchiffrer dans le conteneur, la clé privée passée par
l'entrée standard — collée dans le terminal puis Entrée et Ctrl-D, ou
redirigée (`… < tiai-sauvegardes.key`, à travers `ssh` depuis le poste qui la
détient) : elle n'est jamais écrite sur le serveur. Puis restaurer le fichier
obtenu avec la commande ci-dessus, et l'effacer : c'est un dump en clair, et
aucune purge ne le retirera.

```bash
docker compose exec -T db-backup sh -c 'umask 077 && age -d -i - \
   -o /backups/restauration-en-clair.dump /backups/tiai-AAAAMMJJ-HHMMSS.dump.age'
# … pg_restore de /backups/restauration-en-clair.dump (commande ci-dessus) …
docker compose exec db-backup rm /backups/restauration-en-clair.dump
```

Sur un serveur reconstruit de zéro : déposer d'abord la copie hors site du
`.dump.age` dans `deploy/backups/`, et le `.env` d'origine (sa
`BACKUP_ENCRYPT_RECIPIENT` comprise).

> **Renommer le dump déposé avant de démarrer la stack** (clair ou chiffré) :
> `mv backups/tiai-AAAAMMJJ-HHMMSS.dump.age backups/tiai-a-restaurer.dump.age`.
> Sous son nom de dump quotidien, une copie qui a gardé sa date et a plus de
> `BACKUP_KEEP_DAYS` jours est **purgée** par `db-backup` dès son premier
> dump réussi — celui de la base encore vide, quelques secondes après
> `docker compose up -d`, avant toute restauration. Un autre nom n'est jamais
> purgé ; l'effacer à la main une fois la restauration vérifiée.

Au redémarrage, le backend rejoue les migrations Alembic si le dump vient
d'une version plus ancienne du schéma — restaurer un dump d'hier après une
montée de version fonctionne donc sans étape supplémentaire. L'inverse (un
dump plus récent que le code) n'est pas supporté.

Un dump manuel avant une opération risquée :

```bash
docker compose exec db-backup sh -c \
  'umask 077 && PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" \
   -d "$POSTGRES_DB" -Fc -f /backups/tiai-avant-operation.dump'
```

Chiffrement activé : la même chose chiffrée pour les clés de
`BACKUP_ENCRYPT_RECIPIENT`, sans passage en clair sur le disque. Contrôler
qu'aucune erreur de `pg_dump` ne s'affiche : dans un tube, son échec ne fait
pas échouer la commande.

```bash
docker compose exec db-backup sh -c \
  'umask 077 && PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" \
   -d "$POSTGRES_DB" -Fc | age $(printf " -r %s" $BACKUP_ENCRYPT_RECIPIENT) \
   -o /backups/tiai-avant-operation.dump.age'
```

> **Faire l'exercice une fois.** Une procédure de restauration jamais jouée
> n'existe pas : sur la stack de dev (`docker-compose.dev.yml`), restaurer un
> dump et vérifier que la console retrouve ses postes prend dix minutes, et
> c'est le seul moyen de savoir que la chaîne complète fonctionne.

---

## Mettre à jour le serveur

Chaque release publie, en plus des binaires de l'agent, les deux images du
serveur sur le registre GitHub, sous le numéro de la release :

```
ghcr.io/natimai-solutions/tiai-backend:<version>    # API et worker
ghcr.io/natimai-solutions/tiai-frontend:<version>   # console
```

`latest` désigne la dernière version stable (jamais une `-rc`). La version que
la stack démarre est `TIAI_VERSION` dans `deploy/.env` : **l'épingler** en
production (`TIAI_VERSION=1.2.0`), pour qu'une mise à jour soit une décision et
pas l'effet de bord du prochain `docker compose pull`.

**Une version, ce sont les images *et* les fichiers de `deploy/`.** Le
`Caddyfile` et le script de sauvegarde (`backup/backup.sh`) ne sont pas dans
les images : les conteneurs `caddy` et `db-backup` les lisent sur l'hôte
(§ « [Obtenir les fichiers de déploiement](#obtenir-les-fichiers-de-déploiement) »),
et leurs propres images ne viennent pas du registre de Tia'i — `caddy` est
tirée telle quelle, `db-backup` construite sur place depuis
`backup/Dockerfile`. Changer `TIAI_VERSION` puis lancer `docker compose pull`
et `docker compose up -d` ne met donc à jour que le backend, le worker et la
console : le serveur garderait l'ancien Caddyfile, l'ancien script et l'image
de sauvegarde, sans les corrections que la release y apporte. D'où les
étapes 2 et 5 ci-dessous, à faire à **chaque** mise à jour — ici de la 1.2.0
vers la 1.2.1 :

```bash
cd deploy
# 1. Un dump juste avant. db-backup en refait un à l'étape 5, mais après les
#    migrations : celui-ci est le seul qui permette de revenir en arrière.
#    Chiffrement activé : la variante chiffrée (§ « Restaurer »).
docker compose exec db-backup sh -c \
  'umask 077 && PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" \
   -d "$POSTGRES_DB" -Fc -f /backups/tiai-avant-mise-a-jour.dump'

# 2. Les fichiers de déploiement, à la version visée. `.env`, `certs/` et
#    `backups/` ne sont pas suivis par git : ils restent tels quels.
git status --short .                # un fichier suivi modifié sur place ? (voir plus bas)
git fetch --tags
git checkout v1.2.1                 # le tag de la release

# 3. Le .env face au nouveau .env.example. La première commande montre ce que
#    la release y a changé (variables ajoutées ou retirées, défauts, consignes) ;
#    la seconde nomme les variables de l'exemple absentes du .env (lignes « < »)
#    et celles du .env que l'exemple ne connaît plus (lignes « > »).
git diff v1.2.0 v1.2.1 -- .env.example
diff <(grep -oE '^#?[A-Z][A-Z0-9_]*=' .env.example | tr -d '#=' | sort -u) \
     <(grep -oE '^#?[A-Z][A-Z0-9_]*=' .env         | tr -d '#=' | sort -u)

# 4. Dans .env : TIAI_VERSION=1.2.1, et ce que l'étape 3 a fait apparaître.
#    Puis les droits — à poser aussi sur un serveur installé avant que ce
#    guide ne les demande (sudo si Docker a créé le dossier, donc en root) :
chmod 600 .env
chmod 700 backups

# 5. Les images, puis les services.
docker compose pull                 # télécharge les images de cette version
docker compose build --pull db-backup   # postgres:16-alpine à jour (celle de db) + age
docker compose up -d                # recrée backend, worker et console
docker compose up -d --force-recreate caddy db-backup   # relisent Caddyfile et backup.sh

# 6. Vérifier.
docker compose ps                   # tous les services « healthy » en 2 min
docker compose exec caddy grep max_size /etc/caddy/Caddyfile   # celui de la release (v1.2.1 : 2050MiB et 8MB)
docker compose logs --tail 5 db-backup   # « sauvegarde OK : … » (« , chiffrée » si configuré), sans « ATTENTION » ni « ECHEC »
ls -ld .env backups                 # -rw------- et drwx------
```

Le backend rejoue les migrations Alembic à son démarrage.

**Pourquoi `--force-recreate`.** `docker compose up -d` ne recrée un service
que si son image ou sa définition dans le compose a changé ; le contenu d'un
fichier monté n'en fait pas partie. Et un fichier monté seul reste, dans le
conteneur, celui qui existait à sa création : git le remplace sur l'hôte, le
conteneur garde l'ancien. Sans cette commande, ni `caddy` ni `db-backup` ne
voient les fichiers de l'étape 2. La recréation de `caddy` coupe la console et
les agents quelques secondes (les agents réessaient d'eux-mêmes) ; celle de
`db-backup` déclenche un dump (deux si l'image a changé à l'étape 5 : `up -d`
l'a déjà recréé).

**Pourquoi `build --pull db-backup`.** L'image de sauvegarde n'est pas tirée
mais construite, et `docker compose up` ne la reconstruit pas d'elle-même
quand elle existe déjà. `--pull` la refait sur la `postgres:16-alpine` que
`docker compose pull` vient d'apporter à `db` (même version de `pg_dump` que
le serveur, correctifs de sécurité compris), avec le `Dockerfile` de la
version visée. Il faut joindre le registre Docker et `dl-cdn.alpinelinux.org` ;
sur un hôte qui ne le peut pas, l'image se construit ailleurs et se charge
(§ « Sauvegardes et restauration », « Hôte qui ne joint pas… ») **avant**
`docker compose up -d`.

**Les notes de version** (`dev/notes-de-version-v<version>.md`, section « À
faire avant de mettre à jour ») disent ce qu'une release demande de plus : une
variable devenue obligatoire, une opération à faire une fois. Les lire avant
l'étape 4.

**Fichier suivi modifié sur place** — le Caddyfile, pour `tls internal` ou un
autre `max_size` (§ « Déploiement logiciel ») : `git status` le signale à
l'étape 2, et `git checkout` refuse de l'écraser s'il a changé entre les deux
versions. Mettre la modification de côté (`git stash`), changer de version,
puis la reposer (`git stash pop`) et relire le fichier obtenu avant l'étape 5.

**Sans git** (dossier venu de l'archive « Source code » d'une release) :
extraire l'archive de la nouvelle version par-dessus le dossier existant, à la
place de l'étape 2. `.env`, `certs/` et `backups/` n'y figurent pas et restent
en place ; un fichier modifié sur place, lui, est écrasé — le comparer avant.

```bash
# depuis la racine du dépôt (le dossier qui contient deploy/)
curl -L https://github.com/Natimai-Solutions/natimai-tiai/archive/refs/tags/v1.2.1.tar.gz \
  | tar -xz --strip-components=1
```

> **Montée vers la v1.2.0, qui introduit le rôle applicatif PostgreSQL** : créer
> le rôle après l'étape 4 et avant l'étape 5 (§ « Rôle applicatif
> PostgreSQL ») — il faut les fichiers de la v1.2.0 et `POSTGRES_APP_PASSWORD`
> dans le `.env`. Sans lui, le backend refuse de démarrer.

**Revenir en arrière** : remettre l'ancienne valeur de `TIAI_VERSION` **et**
les fichiers de déploiement de l'ancienne version (`git checkout v1.2.0`),
puis :

```bash
# Seulement si la version de retour construit db-backup — son
# docker-compose.yml porte un `build:` sous `db-backup`, à partir de la
# v1.2.1 : refaire cette image, et elle seule, avec le Dockerfile de cette
# version. Sans objet pour un retour à la v1.2.0, qui tire postgres:16-alpine.
docker compose build db-backup
docker compose up -d                                    # backend, worker et console de l'ancienne version
docker compose up -d --force-recreate caddy db-backup   # relisent l'ancien Caddyfile et l'ancien backup.sh
```

Jamais `up --build` ici : `--build` reconstruit toutes les images des services
démarrés, dépendances comprises — `caddy` dépend de `backend` et de
`frontend`, qui seraient reconstruits depuis les sources (plusieurs minutes,
PyPI, npm et Docker Hub à joindre en plein incident), à la place des images
publiées de l'ancienne version ; et un échec de construction laisserait
`caddy` sur le Caddyfile de la version quittée. Si les images de l'ancienne
version ne sont plus sur l'hôte (`docker image ls`), `docker compose pull`
d'abord.

Cela vaut tant que la version quittée n'a pas migré la base. Si elle l'a fait,
restaurer le dump pris avant la montée (§ « Restaurer ») *puis* redémarrer sur
l'ancienne version : un schéma plus récent que le code n'est pas supporté.

**Construire depuis les sources** plutôt que tirer les images (dépôt modifié,
serveur sans accès à ghcr.io) : `docker compose up -d --build`. Compose
construit alors les images localement et les nomme comme les images publiées.
Sans accès au registre, il les construit aussi de lui-même au premier
démarrage.

> Les paquets d'un dépôt public sont privés à leur première publication sur
> ghcr.io : rendre `tiai-backend` et `tiai-frontend` publics une fois, dans les
> réglages de chaque paquet (*Package settings → Change visibility*), pour
> qu'un serveur puisse les tirer sans identifiants.

### État de santé et journaux

Chaque service a un contrôle de santé, lu par `docker compose ps` (colonne
*STATUS* : `healthy` / `unhealthy`) :

| Service | Sain quand |
|---|---|
| `db` | `pg_isready` répond |
| `backend` | `/health` répond **et** signale la base joignable (`"database": true`) |
| `worker` | sa boucle a terminé un tour il y a moins de 5 min (fichier témoin touché toutes les 30 s) |
| `frontend` | nginx sert la console |
| `caddy` | son API d'administration répond |

Docker ne redémarre pas un conteneur `unhealthy` de lui-même (seulement un
conteneur arrêté, via `restart: unless-stopped`) : l'état sert au diagnostic et
à une supervision externe (`docker inspect --format '{{.State.Health.Status}}'
deploy-backend-1`).

Les journaux de chaque conteneur tournent à 5 fichiers de 10 Mio
(`docker compose logs <service>`), au lieu de grossir jusqu'à remplir le disque.

---

## Signature de l'agent (Authenticode)

La chaîne de release signe les `.exe` **avant** de construire les `.msi` autour
d'eux (le service installé sur chaque poste est donc le binaire signé), puis les
`.msi` eux-mêmes, avec horodatage RFC 3161 : la signature reste valide après
l'expiration du certificat. Le certificat est fourni par les **secrets du
dépôt** (*Settings → Secrets and variables → Actions*) :

| Nom | Type | Contenu |
|---|---|---|
| `SIGNING_CERT_PFX_BASE64` | secret | Le certificat de signature de code **avec sa clé privée**, export PFX, encodé en base64 |
| `SIGNING_CERT_PASSWORD` | secret | Mot de passe du PFX |
| `SIGNING_TIMESTAMP_URL` | variable | Horodateur RFC 3161 (défaut : `http://timestamp.digicert.com`) |
| `REQUIRE_SIGNING` | variable | `true` : une release taguée sans certificat échoue au lieu de partir non signée |

Sans ces secrets, la release se construit comme avant, non signée, avec un
avertissement dans le résumé du workflow.

**Certificat de l'AC interne** (le cas prévu) : demander à l'AD CS un
certificat sur le modèle *Signature de code* (*Code Signing*), l'exporter avec
sa clé privée en `.pfx`, puis l'encoder :

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('tiai-signing.pfx')) | Set-Clipboard
```

Le coller dans le secret `SIGNING_CERT_PFX_BASE64`, puis supprimer le `.pfx` du
poste qui l'a exporté. Pour que Windows reconnaisse l'éditeur, déployer le
certificat (sans la clé, en `.cer`) dans le magasin **Éditeurs approuvés** des
postes par GPO (*Configuration ordinateur → Stratégies → Paramètres Windows →
Paramètres de sécurité → Stratégies de clé publique*). La racine de l'AC est
déjà approuvée sur les postes du domaine.

**Certificat public** (OV/EV d'une autorité commerciale, utile hors domaine) :
depuis 2023 leur clé privée doit rester dans un module matériel et ne s'exporte
plus en PFX. Il faut alors signer par le service de l'autorité ou par Azure
Trusted Signing, ce que ce script ne fait pas : remplacer l'étape « Signer » du
workflow par l'action de l'éditeur.

**Essayer sans publier** : *Actions → Release → Run workflow* construit et signe
les binaires en artefacts de build, sans créer de release. Sur un poste,
vérifier un binaire téléchargé :

```powershell
Get-AuthenticodeSignature .\tiai-agent-windows-amd64.exe | Format-List Status, SignerCertificate, TimeStamperCertificate
```

`Status` vaut `Valid` sur un poste qui approuve l'AC. Une signature ne remplace
pas `-ExpectedHash` du script GPO : la première dit qui a produit le binaire, le
second qu'il s'agit exactement de celui que la GPO a choisi.

---

## Réveil des postes (Wake-on-LAN)

Le réveil est la **seule action que le serveur exécute lui-même**, et c'est la
seule qui puisse l'être : le poste est éteint, il n'a plus d'agent à qui parler.
Ce qui le rallume est une trame que sa carte réseau reconnaît pendant que le
reste du matériel dort — six octets `0xFF` suivis de son adresse MAC répétée
seize fois — et seule une machine du même domaine de diffusion peut la déposer
sur le fil.

Trois conditions, toutes en dehors du logiciel. Aucune n'est vérifiable depuis la
console : le protocole n'accuse rien, donc Tia'i annonce toujours « paquet émis »
et jamais « poste réveillé ». Un poste réveillé se constate à sa remontée d'agent,
une minute après son démarrage.

### 1. Le poste

- **BIOS/UEFI** : activer *Wake on LAN* (parfois *Power On By PCI-E*, *Resume by
  LAN*). Sur un poste où l'option est absente ou grisée, rien d'autre ne servira.
- **Carte réseau**, dans le gestionnaire de périphériques : onglet *Gestion de
  l'alimentation* → « Autoriser ce périphérique à sortir l'ordinateur du mode
  veille », et *Avancé* → « Wake on Magic Packet » à *Activé*. Ces deux réglages
  se pilotent par GPO ou par script, comme le reste du déploiement.
- **Démarrage rapide de Windows désactivé** (`powercfg /h off`, ou la stratégie
  correspondante). Avec le démarrage rapide, « arrêter » est en réalité une mise
  en veille prolongée, qui laisse la carte dans un état où le réveil est
  aléatoire. C'est la cause n°1 d'un parc qui se réveille à moitié — et la raison
  pour laquelle la commande `shutdown` de Tia'i n'utilise pas `/hybrid`.
- **En filaire.** Le réveil par Wi-Fi (WoWLAN) dépend du couple carte/pilote et
  fonctionne rarement sur un poste éteint.
- Le poste doit avoir **remonté au moins une fois son adresse MAC**, ce que fait
  tout agent à partir de cette version — avec le masque de son sous-réseau, qui
  détermine l'adresse de diffusion visée. Les deux sont visibles sur sa fiche,
  auprès de l'adresse IP ; un tiret sur la MAC signifie que le réveil n'a rien à
  viser, et la console le dit plutôt que de prétendre avoir émis.

### 2. Le réseau

Le paquet est diffusé sur l'adresse de diffusion du sous-réseau **du poste** —
déduite de sa dernière adresse connue **et du masque que le poste a lui-même
remonté** : `10.4.7.9 /16` donne `10.4.255.255`, `192.168.1.42 /24` donne
`192.168.1.255`. Rien à configurer, donc, y compris sur un parc mêlant plusieurs
tailles de sous-réseaux ; `WOL_SUBNET_PREFIXLEN` ne sert que de repli pour un
poste dont l'agent est trop ancien pour remonter son masque. Le masque retenu est
visible sur la fiche du poste, à côté de son adresse.

Sur un réseau plat, il n'y a rien d'autre à faire. Si le serveur est sur un autre VLAN que les postes,
le routeur doit relayer la diffusion dirigée (`ip directed-broadcast` chez Cisco)
— ce que la plupart refusent par défaut, et à raison. Là où ce relais n'est pas
envisageable, le réveil ne peut pas venir de ce serveur : il faut un émetteur sur
le segment concerné.

### 3. L'hôte Docker

C'est le point qui surprend, et il n'apparaît qu'au déploiement : le backend
tourne dans un conteneur sur un *pont* Docker (`br-xxxx`, créé par compose). Le
datagramme part vers l'adresse de diffusion du sous-réseau du poste, entre dans
l'hôte **par ce pont** — et **Linux ne relaie pas une diffusion dirigée d'une
interface vers une autre par défaut** (RFC 2644). Sans le réglage ci-dessous,
le paquet meurt sur l'hôte et la console annonce pourtant une émission réussie,
puisqu'elle l'a bien émise.

Le noyau ne relaie que si `bc_forwarding` vaut 1 **sur `all` et sur l'interface
par laquelle le paquet entre** — le pont Docker, donc, pas la carte LAN, qui
n'est que la sortie. Un réglage posé sur la seule carte LAN (ce que ce guide
indiquait auparavant) ne change rien : le réveil reste muet. Et le nom du pont
(`br-<id>`) change à chaque recréation du réseau compose, d'où le passage par
`default`, dont héritent les ponts créés ensuite. Le script fourni fait tout
cela, et le persiste dans `/etc/sysctl.d/` :

```bash
sudo sh deploy/wol/enable-directed-broadcast.sh
```

À la main, c'est l'équivalent de :

```bash
printf 'net.ipv4.conf.all.bc_forwarding = 1\nnet.ipv4.conf.default.bc_forwarding = 1\n' \
  | sudo tee /etc/sysctl.d/99-tiai-wol.conf
sudo sysctl -p /etc/sysctl.d/99-tiai-wol.conf
# les ponts déjà créés n'ont pas hérité du nouveau `default`
for f in /proc/sys/net/ipv4/conf/br-*/bc_forwarding; do echo 1 | sudo tee "$f"; done
```

**Docker Desktop (Windows, macOS)** : les conteneurs y tournent dans une machine
virtuelle derrière un NAT que l'hôte ne traverse pas pour une diffusion, et le
`sysctl` ci-dessus n'y est ni accessible ni suffisant. Le réveil ne peut alors
pas partir de la stack : il faut un hôte Linux sur le segment des postes, ou un
autre émetteur.

L'alternative sur Linux est de donner au service `backend` le réseau de l'hôte
(`network_mode: host`) : la pile réseau du conteneur devient celle de l'hôte et
la question disparaît, mais `db` n'est plus joignable par son nom de service et
le proxy Caddy est à revoir. À réserver aux déploiements qui ne peuvent pas
toucher aux `sysctl`.

**Vérifier**, sur l'hôte Docker, pendant qu'on appuie sur « Réveiller le poste »
dans la console — deux captures qui disent chacune où le paquet s'arrête :

```bash
# 1. Le paquet sort-il du conteneur ? (le pont compose : docker network ls, puis br-<12 premiers hex de l'id>)
sudo tcpdump -ni br-xxxx udp port 9
# 2. Sort-il de l'hôte vers le LAN ? (<iface> = l'interface LAN : ip -br addr)
sudo tcpdump -ni <iface> udp port 9
```

`WOL_PACKET_COUNT` trames doivent apparaître dans chaque capture, la seconde
avec l'adresse IP de l'hôte en source et `ff:ff:ff:ff:ff:ff` en destination
Ethernet (`-e` pour l'afficher). Rien en 1 : le backend n'a pas émis, la fiche
de commande dit pourquoi (MAC ou IP inconnue). En 1 mais pas en 2 : c'est ce
§3, `bc_forwarding` manque sur `all` ou sur le pont. En 2 mais le poste ne
démarre pas : c'est le §1 — ou le §2 si le poste est sur un autre segment.

### 4. Serveur distant : le réveil relayé par un agent

Tout ce qui précède suppose un serveur **sur le réseau des postes**. Un serveur
hébergé ailleurs — dans un autre établissement, chez un hébergeur — n'a aucun
moyen de déposer une trame sur leur fil : aucune route ne transporte une
diffusion à travers Internet, et aucun routeur ne relaie une diffusion dirigée
vers le VLAN d'un lycée. Ce que ce serveur a, en revanche, c'est le parc
lui-même : chaque poste encore allumé sur le site est une machine du bon
domaine de diffusion.

`WOL_RELAY_ENABLED=true` change donc ce que fait le bouton « Réveiller » :

1. le serveur **n'émet plus rien** ; il met le réveil en file, sur la fiche du
   poste visé, comme une commande ordinaire (`wake_on_lan`, statut « en
   attente ») ;
2. **le premier poste éligible à contacter le serveur** — au rythme du
   heartbeat, donc dans la minute — reçoit l'instruction avec l'adresse MAC à
   réveiller, et son agent diffuse le paquet magique sur les sous-réseaux IPv4
   de ses propres cartes (UDP/9, trois copies). Le poste visé lui-même n'est
   jamais servi : il est éteint, et s'il ne l'est pas, le réveil est clos comme
   réussi à sa première remontée ;
3. le relais rend compte sur la fiche du poste visé — « Relayé par POSTE-12 —
   paquet magique émis vers … » — et le poste réveillé se constate, comme
   avant, à la remontée de son agent.

**Éligible** veut dire *sur le même fil*, et le serveur en juge d'après ce que
remontent les agents :

- l'**emplacement** d'abord (`location` dans la configuration de l'agent, ou
  `Location` dans le registre — voir « Paramètres de l'agent Windows ») : c'est
  le réglage fait pour ça. Un domaine couvre tous les sites d'une académie, un
  nom de site non. Un parc **multi-sites sans emplacements** relaierait depuis
  n'importe quel poste du domaine, c'est-à-dire souvent depuis le mauvais site ;
- le **domaine** à défaut, pour un poste dont l'agent n'a pas d'emplacement —
  juste sur un parc à site unique, et la raison de renseigner les emplacements
  partout ailleurs ;
- au sein d'un site, un poste du **même sous-réseau IPv4** que la cible (d'après
  les adresses et masques remontés) prend le réveil aussitôt : sa diffusion
  atteint la cible à coup sûr. Les postes d'un autre VLAN du même site attendent
  `WOL_RELAY_SUBNET_GRACE_SECONDS` — un cycle d'agent — avant de le prendre à
  leur tour, au cas où rien ne serait allumé sur le bon segment.

Si **aucun poste éligible n'est allumé** au moment du clic, le réveil est refusé
sur-le-champ (« Aucun poste allumé sur l'emplacement … ») plutôt que laissé en
file jusqu'à son expiration : un site où tout est éteint n'a rien pour relayer,
et il faut alors un poste allumé à la main — ou un poste qu'on ne s'autorise
jamais à éteindre, ce qui est la configuration recommandée pour un site qui
compte sur cette fonction.

Ce mode **remplace** l'émission par le serveur, il ne s'y ajoute pas : un serveur
distant qui émettrait dans le vide annoncerait un succès qu'il ne peut pas avoir.
Le § 3 (`bc_forwarding`) ne s'applique plus ; le § 1 (BIOS, carte, démarrage
rapide) reste entier.

**Sécurité.** C'est la seule commande du catalogue qui transporte un argument —
l'adresse MAC de la cible — là où toutes les autres ne sont qu'un nom de type.
L'agent le borne : la valeur est lue comme une adresse EUI-48 et rien d'autre
(six octets ou refus, jamais une chaîne qui atteint un shell ou le registre),
et **la destination n'est jamais prise au serveur** — le paquet part sur les
sous-réseaux du poste relais, sur UDP/9, et nulle part ailleurs. Un serveur
compromis peut au pire faire réveiller des machines du segment d'un relais, ce
qui est la fonction. Le mode reste désactivé par défaut parce qu'il change ce
que fait le bouton, pas parce qu'il ouvre quelque chose.

---

## Paramètres de l'agent Windows

### Fichier de configuration

`C:\ProgramData\Tiai\config.yaml` (chemin surchargeable par `--config`) :

```yaml
api_base_url: https://tiai.lycee.local    # https:// exige un certificat approuvé
allow_insecure_http: false                # true seulement pour viser le port HTTP direct
enrollment_secret: <secret partagé>       # préférer le registre (voir plus bas)
machine_uuid: ""                          # vide = résolution auto
heartbeat_interval_seconds: 60
request_timeout_seconds: 10
backoff_max_seconds: 300
queue_max_items: 1000
wu_collect_interval_seconds: 21600        # cycle Windows Update (6 h) — jamais dans le heartbeat
wu_install_timeout_seconds: 7200          # budget d'une installation de MAJ (2 h)
defender_full_scan_timeout_seconds: 28800 # budget d'une analyse complète Defender (8 h)
inventory_collect_interval_seconds: 86400 # cycle inventaire matériel/logiciel (24 h)
log_level: INFO                           # DEBUG logge aussi les heartbeats silencieux
proxy_url: direct                         # direct (défaut) | environment | http://proxy:3128
report_session_username: true             # false = remonter la présence sans le nom
report_software: true                     # false = inventaire matériel seul, sans les logiciels
location: ""                              # emplacement du poste ("Lycée de Taravao") ; vide = aucun
```

`defender_full_scan_timeout_seconds` borne une analyse complète Defender : le
worker de commandes de l'agent est séquentiel, et un scan qui ne rendait jamais
la main bloquait toutes les commandes suivantes du poste, redémarrage compris.
Huit heures couvrent un gros disque mécanique ; à relever sur un parc dont les
analyses complètes sont légitimement plus longues (le message d'échec le dit).
L'analyse rapide (1 h) et la mise à jour des signatures (30 min) ont des délais
fixes : ce sont des détecteurs de blocage, pas des estimations. Au délai, la
commande échoue mais le scan peut se poursuivre dans le service Defender.

`location` est un texte libre choisi par le déploiement — rien sur un poste ne
dit dans quel bâtiment il se trouve — et vide par défaut. La console filtre et
trie le parc par emplacement, et le relais Wake-on-LAN s'en sert pour désigner
un poste voisin (section « Réveil des postes », point 4). Une valeur vide
**efface** l'emplacement mémorisé côté serveur : un poste déplacé, ou dont la GPO
a retiré le réglage, ne reste pas classé sous l'ancien.

**Proxy.** L'agent joint le serveur **en direct** par défaut, quoi que dise
l'environnement du poste. Ce n'est pas le comportement natif de Go, et c'est
voulu : le client HTTP de Go ne lit que les variables `HTTP_PROXY`,
`HTTPS_PROXY` et `NO_PROXY`, jamais les paramètres proxy de Windows (Options
Internet, `netsh winhttp`) ni leur liste d'exceptions — la case « Ne pas utiliser
de serveur proxy pour les adresses locales » n'a aucun effet sur lui. Un
établissement qui pousse `HTTPS_PROXY` en variable **système** (celle qu'hérite
un service `LocalSystem`) voyait donc chaque heartbeat partir vers son proxy, qui
répondait `407 Proxy Authentication Required` : `tick failed ... Proxy
Authentication Required` dans `agent.log`, et aucun poste enrôlé. Trois valeurs :

| `proxy_url` | Effet |
|---|---|
| vide ou `direct` | Connexion directe, l'environnement est ignoré (défaut) |
| `environment` | Honore `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` du service, comme les agents antérieurs |
| `http://proxy:3128` | Passe par ce proxy pour toutes les requêtes ; `http://user:mdp@proxy:3128` pour un proxy authentifié (le mot de passe n'apparaît jamais dans le journal) ; `socks5://` accepté |

Une valeur invalide est journalisée au démarrage et l'agent se connecte en
direct : un service qui refuserait de démarrer sur une faute de frappe de GPO
serait injoignable depuis la console.

**Annuaire.** Sans aucun réglage, l'agent d'un poste joint à un domaine remonte
aussi, avec l'inventaire quotidien, ce que l'annuaire dit de lui : le DN de
l'objet ordinateur (lu dans le cache des stratégies de groupe, sous
`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine`),
l'unité d'organisation qui le contient, et l'attribut *Emplacement* de l'objet,
lu via ADSI avec le compte machine. Ces trois valeurs s'affichent sur la fiche
du poste et, selon `ROOM_SOURCE` côté serveur, rangent le poste dans une salle.
Un poste hors domaine, ou dont le contrôleur est injoignable, remonte ce qu'il
peut : l'OU sans l'attribut, ou rien — jamais une erreur. Le bloc n'est envoyé
que lorsqu'il change, comme le reste de l'inventaire ; « Rafraîchir
l'inventaire » depuis la console force une relecture.

Toute valeur absente ou non positive retombe sur son défaut : un YAML partiel
reste utilisable, et **le fichier lui-même est facultatif** — c'est le mode
nominal d'un déploiement par GPO, qui n'a alors rien à déposer ni à mettre à jour
sur les postes. Seul `api_base_url` doit venir de l'une des deux sources. Le
token du poste n'est jamais dans ce fichier : il est chiffré via DPAPI dans
`token.dat`, à côté du YAML.

### Surcharge par le registre (GPO)

Les valeurs présentes sous `HKLM\SOFTWARE\Tiai` **priment sur le YAML**, ce qui
permet à une GPO de pousser un seul réglage. C'est l'emplacement recommandé pour
le secret d'enrôlement, plutôt qu'en clair dans le YAML.

| Valeur registre | Type | Équivalent YAML |
|---|---|---|
| `ApiBaseURL` | `REG_SZ` | `api_base_url` |
| `AllowInsecureHTTP` | `REG_DWORD` | `allow_insecure_http` (`1` accepte une `ApiBaseURL` en `http://` ; cf. plus bas) |
| `EnrollmentSecret` | `REG_SZ` | `enrollment_secret` |
| `MachineUUID` | `REG_SZ` | `machine_uuid` |
| `LogLevel` | `REG_SZ` | `log_level` |
| `ProxyURL` | `REG_SZ` | `proxy_url` |
| `HeartbeatIntervalSeconds` | `REG_DWORD` | `heartbeat_interval_seconds` |
| `WUCollectIntervalSeconds` | `REG_DWORD` | `wu_collect_interval_seconds` |
| `WUInstallTimeoutSeconds` | `REG_DWORD` | `wu_install_timeout_seconds` |
| `DefenderFullScanTimeoutSeconds` | `REG_DWORD` | `defender_full_scan_timeout_seconds` |
| `InventoryCollectIntervalSeconds` | `REG_DWORD` | `inventory_collect_interval_seconds` |
| `ReportSessionUsername` | `REG_DWORD` | `report_session_username` |
| `ReportSoftware` | `REG_DWORD` | `report_software` |
| `ReportLocalAdmins` | `REG_DWORD` | `report_local_admins` (désactivé si absent) |
| `ReportWingetPackages` | `REG_DWORD` | `report_winget_packages` (désactivé si absent) |
| `Location` | `REG_SZ` | `location` |
| `DeployWinget` | `REG_DWORD` | — (registre seulement) |
| `DeployWingetAllow` | `REG_MULTI_SZ` | — (registre seulement) |
| `DeploySigners` | `REG_MULTI_SZ` | — (registre seulement) |
| `DeployPublishers` | `REG_MULTI_SZ` | — (registre seulement) |
| `DeployMethodAMaxGB` | `REG_DWORD` | — (registre seulement) |
| `DeployCacheMaxGB` | `REG_DWORD` | — (registre seulement) |

Pour les intervalles, `0` est ignoré et signifie « laisser le défaut ». Une
`ProxyURL` vide est ignorée de même : pour annuler par GPO un proxy qu'un YAML
nomme, écrire le mot-clé `direct`. Pour
`ReportSessionUsername` et `ReportSoftware`, c'est la **présence de la clé** qui
l'emporte : `0` coupe la remontée, `1` la rétablit. Même règle pour `Location` :
une valeur présente et vide retire l'emplacement, y compris celui du YAML — c'est
ce qui permet à une GPO liée à l'OU d'un site de poser le nom du site sur tous
ses postes, et à une autre de le retirer.

`ReportSessionUsername` à `0` coupe la remontée du nom de l'utilisateur connecté
(la console affiche alors la présence sans identité). `ReportSoftware` à `0`
coupe l'inventaire **logiciel** : le registre n'est plus lu, l'inventaire
matériel continue de remonter, et la liste déjà stockée côté serveur est
**effacée** au cycle suivant — c'est ce qui rend la garantie vérifiable plutôt
que déclarative. Les deux réglages sont à arbitrer avec le DPO / le CSE : croiser
« quels logiciels sont installés » et « qui est connecté » porte sur une personne
nommée.

`ReportLocalAdmins` et `ReportWingetPackages` (conformité, C5) sont au contraire
**désactivés tant que la clé est absente** : `1` les active, `0` les coupe à
nouveau. Le premier remonte les membres du groupe Administrateurs local (noms de
comptes et SID) — à arbitrer avec le DPO comme le nom de session ; coupé, la
liste stockée côté serveur est effacée au cycle suivant. Le second lance
`winget list --source winget` une fois par cycle d'inventaire (quelques
secondes, et une mise à jour de l'index winget, donc un accès à
`cdn.winget.microsoft.com`) pour remonter les logiciels connus de winget et la
version disponible : **à valider sur un poste réel** avant de l'activer sur le
parc — le comportement de winget sous `LocalSystem` varie selon la version
d'App Installer. Le pare-feu (état des trois profils, réglage GPO prioritaire)
remonte toujours : ce n'est pas une donnée personnelle.

```powershell
New-Item -Path 'HKLM:\SOFTWARE\Tiai' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Tiai' -Name 'ApiBaseURL' -Value 'https://tiai.lycee.local'
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Tiai' -Name 'EnrollmentSecret' -Value '<secret>'
```

**`http://` est refusé par défaut** (agent publié après la v1.1.0) : le secret de flotte, puis le
token, passeraient en clair sur le réseau. Une installation qui vise le port
HTTP direct du backend doit le dire explicitement, par la valeur
`AllowInsecureHTTP` (`REG_DWORD` 1) ou `allow_insecure_http: true` dans le YAML ;
l'agent le rappelle alors à chaque démarrage dans son journal. **À poser avant
de mettre à jour l'agent** sur un parc installé en `http://`, sinon les postes
cessent de joindre le serveur. L'agent ne suit plus non plus les redirections
(le 301 de Caddy de `http://` vers `https://` répond une erreur).

Sans l'option, **le service ne s'arrête pas** : il reste « En cours
d'exécution » dans le gestionnaire de services, ne contacte pas le serveur, et
relit sa configuration toutes les 1 à 15 minutes en écrivant chaque fois dans
`agent.log` la ligne `agent: cannot run yet (api_base_url "http://…" is
http://: …)`. Un poste dans cet état se reconnaît donc à son journal, pas à
l'état du service. Poser la valeur ensuite le répare à l'essai suivant, sans
redémarrer le service. Seule la commande `run` lancée au premier plan s'arrête
sur cette erreur. À l'inverse, un agent **déjà en marche** ne relit le registre
qu'au démarrage du service : retirer l'autorisation (`AllowInsecureHTTP` à 0)
ne prend effet qu'au prochain redémarrage du service ou du poste.

**Par le script GPO** ([deploy/gpo/](deploy/gpo/README.md)), la valeur se passe
en `-AllowInsecureHttp true` ou `false` ; par le MSI, en propriété
`ALLOWINSECUREHTTP=1` ou `0`. Le script `Install-TiaiAgent.ps1` n'est pas
publié avec les releases (elles ne portent que les `.exe`, les `.msi` et
`SHA256SUMS.txt`) : il se copie à la main sur le partage. **Y déposer le
nouveau script avant d'ajouter le paramètre à la GPO** : face à l'ancien
script, PowerShell rejette le paramètre inconnu avant la première ligne —
rien dans `deploy.log`, et aucun poste installé ni mis à jour, à chaque
démarrage, tant que l'ancien script reste en place.

Les six valeurs `Deploy*` règlent le **déploiement logiciel** sur le poste ;
`DeployMethodAMaxGB` borne la taille d'un paquet non signé et se
tient égale à `PACKAGE_METHOD_A_MAX_GB` côté serveur. `DeployCacheMaxGB`
(16 par défaut, de 1 à 1 024 Gio) borne la place que les téléchargements
interrompus ou refusés gardent ensemble dans `C:\ProgramData\Tiai\packages` :
au démarrage du service et avant chaque téléchargement, l'agent retire les plus
anciens au-delà de ce plafond (jamais le paquet en cours), en plus de ceux
inutilisés depuis 7 jours, et note chaque retrait dans `agent.log`. Une valeur
inutilisable (0, au-delà de 1 024, une chaîne) est signalée dans le journal et
le défaut s'applique.
Elles ne se lisent **que dans le registre**, jamais dans le YAML, et sont
relues à chaque commande. Absentes, tout déploiement est refusé. Leur rôle et
la façon de les poser sont décrits dans
[deploy/packages/README.md](deploy/packages/README.md).

### Commandes

```powershell
.\tiai-agent.exe init-config --api-url <url> [--allow-insecure-http] [--machine-uuid <uuid>] [--config <chemin>]
.\tiai-agent.exe run [--config <chemin>]   # premier plan (Ctrl+C), ou sous le SCM
.\tiai-agent.exe install [--config <chemin>]  # + DACL SYSTEM/Administrateurs sur la clé et le dossier
.\tiai-agent.exe repair [--config <chemin>]   # réapplique démarrage auto + relance sur échec + DACL
.\tiai-agent.exe start | stop | status | uninstall | version
```

`repair` s'adresse aux postes installés par une version antérieure : elle posait
« relance, relance, **rien** » comme actions de récupération, et le SCM répète la
dernière action à chaque panne suivante — un poste tombé trois fois dans la même
journée restait donc arrêté jusqu'à une relance manuelle, type de démarrage
toujours affiché en *Automatique*. La commande remet les trois relances (15 s,
30 s, 2 min) et le démarrage automatique, sans toucher au binaire ni à
l'enrôlement. Le script GPO l'appelle à chaque démarrage.

`install` et `repair` restreignent aussi `HKLM\SOFTWARE\Tiai` et le dossier de
données (`C:\ProgramData\Tiai`) à SYSTEM + Administrateurs, avec les mêmes
DACL protégées que le MSI et le script GPO
(`D:P(A;CI;KA;;;SY)(A;CI;KA;;;BA)` pour la clé,
`D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)` pour le dossier) : un poste installé à la
main ne laisse plus le secret d'enrôlement, l'entropie du token ni `token.dat`
lisibles par les utilisateurs. Un emplacement déjà restreint n'est pas réécrit ;
un échec est signalé par un avertissement sans faire échouer la commande. Un
dossier `--config` personnalisé qui existait déjà n'est pas modifié (il est
signalé) : seul le dossier par défaut, ou un dossier que la commande vient de
créer, est restreint.

L'agent s'auto-enrôle au premier démarrage, stocke le token reçu, puis n'utilise
plus que celui-ci. `uninstall` ne retire que l'enregistrement du service : le
binaire, `C:\ProgramData\Tiai` et `HKLM\SOFTWARE\Tiai` restent en place.

### Enrôlement : approbation et rotation du secret

Le secret d'enrôlement est lisible sur chaque poste (registre ou fichier de la
GPO). Il permet de **créer** un poste, pas de **prendre la place** d'un poste
établi : quand un `machine_uuid` qui détient déjà un token valide redemande
à s'enrôler, le serveur ne délivre rien. La demande est notée (date, adresse
source), le token en place continue de fonctionner, et la fiche du poste
affiche un bandeau « Ré-enrôlement demandé ».

**Une seule exception : la réponse d'enrôlement perdue.** Un agent dont la
réponse à l'enrôlement s'est perdue en route n'a pas reçu son token et
redemande à s'enrôler. Ce second enrôlement est servi **sans approbation** —
le token précédent est annulé, un nouveau délivré — seulement si toutes ces
conditions sont réunies :

- le token délivré par l'enrôlement précédent **n'a encore authentifié aucune
  requête** — heartbeat, résultat de commande, téléchargement de paquet, que
  la requête ait ensuite été acceptée ou refusée. Le serveur l'enregistre
  comme un fait à l'enrôlement et l'efface à la première requête authentifiée ;
  un token renouvelé par rotation (ci-dessous) n'est jamais « non utilisé » ;
- cet enrôlement date de **moins d'une heure** ;
- la demande présente **exactement la même empreinte** que lui (MachineGuid,
  UUID SMBIOS, hachage TPM — une composante en plus ou en moins compte comme
  une différence) ;
- le poste n'est pas révoqué.

Dans tout autre cas la demande attend une approbation. La reprise figure au
journal d'audit (« Enrôlement d'un poste repris (réponse perdue) »).
Conséquence à connaître : entre l'enrôlement d'un poste et sa première
requête — quelques secondes en temps normal, une heure au plus — qui détient
le secret, le `machine_uuid` et l'empreinte du poste peut se faire délivrer
le token à sa place. Le poste réel, dont le token est alors refusé, redemande
à s'enrôler : il reprend la main si le token usurpé n'a pas servi, et sinon
sa demande apparaît en « Ré-enrôlement demandé », ce qui rend la substitution
visible. Dès qu'un poste a parlé une fois au serveur, le secret ne suffit
plus. Les postes déjà enrôlés au moment de la mise à jour vers la v1.2.1 sont
tous considérés comme ayant utilisé leur token.

- **Poste réinstallé** (image refaite, agent réinstallé, token perdu) : le
  bandeau propose **Autoriser le ré-enrôlement**. L'ancien token est annulé et
  l'agent, qui retente de lui-même, revient avec un token neuf dans les minutes
  qui suivent.
- **Demande inattendue** (adresse inconnue, poste qui fonctionne normalement) :
  ne rien autoriser. Le poste réel garde son token ; changer le secret
  d'enrôlement coupe court aux nouvelles tentatives.

Chaque demande et chaque autorisation figurent au journal d'audit.
`ENROLLMENT_REENROLL_REQUIRES_APPROVAL=false` rétablit l'ancien comportement
(le secret suffit) pour un parc ré-imagé très souvent, en connaissance du
risque.

**Changer le secret** sans interrompre les enrôlements : mettre le nouveau dans
`ENROLLMENT_SECRET`, l'ancien dans `ENROLLMENT_SECRET_PREVIOUS`, redémarrer
le backend, pousser le nouveau par GPO. Les deux sont acceptés le temps que le
parc le reçoive ; vider ensuite `ENROLLMENT_SECRET_PREVIOUS`. Les postes déjà
enrôlés ne sont pas concernés : ils n'utilisent que leur token.

### Rotation des tokens agents

Le token d'un poste n'est plus émis une fois pour toutes : passé
`AGENT_TOKEN_ROTATE_DAYS` jours (30 par défaut), le serveur en propose un
nouveau dans la réponse au heartbeat. L'agent l'écrit dans `token.dat` (DPAPI,
écriture atomique), puis s'en sert dès la requête suivante — c'est ce premier
usage qui fait refuser l'ancien par le serveur. Jusque-là l'ancien reste
valide : une réponse perdue ou un `token.dat` impossible à écrire (disque
plein, antivirus) ne coupent pas le poste ; l'agent garde son token, le
journalise (`agent.log`), et le serveur en repropose un autre au heartbeat
suivant.

- Seuls les agents qui l'annoncent (`supports_token_rotation`) sont concernés :
  un parc en cours de mise à jour mélange sans risque anciens et nouveaux
  agents, les anciens gardant leur token.
- À la mise à jour du serveur, la migration date tous les tokens existants du
  jour de son passage : les premières rotations ont lieu 30 jours plus tard,
  au fil des heartbeats, pas toutes le même matin.
- Une révocation, « autoriser le ré-enrôlement » et un ré-enrôlement annulent
  une rotation en cours : le token proposé meurt avec l'ancien.
- Les rotations sont tracées dans le journal applicatif du backend
  (`app.security` : « token rotation offered », « token rotated »), pas dans le
  journal d'audit de la console, réservé aux actions des opérateurs.
- **Restauration d'une sauvegarde** : un poste dont le token a tourné depuis
  le dump présente un token que la base restaurée ne connaît pas. Il reçoit un
  401, abandonne son token et se ré-enrôle de lui-même avec le secret du parc —
  le même chemin qu'après une restauration plus ancienne que son enrôlement.

**Mettre à jour un poste** ne passe pas par `uninstall` / `install` — le service
pointe sur un chemin, pas sur une version. Arrêter, remplacer le binaire,
redémarrer : le token, l'identité et la file locale sont conservés, donc pas de
ré-enrôlement.

```powershell
.\tiai-agent.exe stop
Copy-Item .\tiai-agent-windows-amd64.exe 'C:\Program Files\Tiai\tiai-agent.exe' -Force
.\tiai-agent.exe start
```

### Logs

`C:\ProgramData\Tiai\agent.log` (rotation en `.old` au-delà de 5 Mio), en plus de
stderr. Passer `log_level` à `DEBUG` pour tracer chaque heartbeat — le moyen le
plus direct de vérifier qu'un poste poll bien pendant les tests.

Le fichier est ouvert **avant** la lecture de la configuration : un poste dont
l'agent ne démarre pas y écrit pourquoi, là où auparavant le service s'arrêtait
sans laisser de trace nulle part (sous le SCM, stderr ne va nulle part). Les
lignes à chercher, dans l'ordre d'un cycle :

| Ligne | Ce qu'elle dit |
|---|---|
| `agent: cannot run yet (...)` | Configuration inutilisable ; le service réessaie et se répare seul dès qu'elle arrive |
| `agent: first heartbeat accepted by the server` | Le serveur est joint : « identity » n'est plus la dernière ligne d'un agent en bonne santé |
| `agent: wmi: "..." has not returned after 1m30s` | Un fournisseur WMI ne répond plus. Les lectures WMI sont sautées, **les heartbeats continuent** (présence, commandes) sans état Defender ni inventaire, jusqu'à `WMI reads resume` |
| `agent: no poll has completed for 10m0s — the current one is stuck in "..."` | Le cycle de poll ne rend plus la main ; la phase nommée est celle à examiner |
| `panic:` suivi d'une pile Go | Le processus s'est arrêté brutalement ; la pile est maintenant écrite dans ce fichier, là où elle partait dans stderr, invisible sous le SCM |
| `agent: inventory collected in ...` | L'inventaire a été lu sur le poste |
| `agent: inventory reported to the server` | …et accepté par le serveur : la fiche est à jour |
| `agent: the heartbeat carrying the inventory failed` | Lu mais pas transmis — regarder le serveur, pas le poste |
| `agent: inventory: ...` | La lecture elle-même a échoué (WMI) |

---

## Organisation du parc : groupes, salles, tâches, maintenance

Tout se règle depuis la console ; rien à déployer sur les postes. La seule
variable d'environnement qui reste à choisir à l'installation est
`ROOM_SOURCE` ; le cycle, la fenêtre « à échéance » et le jour du rappel ont
une valeur initiale dans l'environnement, puis se changent dans la page
Paramètres (section « Backend » ci-dessus).

**Ce qui se règle dans la console, sans redémarrage** (page Paramètres) : les
défauts de maintenance, les seuils d'utilisation, les seuils de supervision
(signatures périmées, poste inactif, disque presque plein, poste à
renouveler, version d'agent de référence, durée de vie d'une commande) et
l'heure des e-mails programmés. L'environnement n'en donne que la valeur de
départ ; une valeur enregistrée dans la console prend le dessus, et chaque
changement est inscrit au journal d'audit. Le worker relit l'heure du résumé
à chaque tour (30 s) et ne renvoie jamais deux fois le résumé du jour, ni le
rappel de la semaine, quand on déplace leur heure ou qu'il redémarre. Un worker
démarré après l'heure du résumé (mise à jour, redémarrage de l'hôte) l'envoie
aussitôt s'il n'est pas déjà parti ce jour-là ; il ne rattrape jamais celui de
la veille. Il en va de même d'une heure déplacée vers une heure déjà passée :
le résumé du jour part aussitôt s'il n'est pas déjà parti.

**Utilisation des postes.** Le serveur compte les heures où chaque poste est
allumé, à partir des battements de l'agent : un écart entre deux battements
plus court que `OFFLINE_AFTER_SECONDS` est compté comme allumé, un écart plus
long comme éteint. Le comptage commence à la mise à jour du serveur, sans rien
déployer sur les postes ; tant que la fenêtre n'est pas pleine, les cartes du
tableau de bord le signalent (« comptage depuis le … »). La fenêtre et les
seuils se règlent dans Paramètres, carte « Utilisation des postes » ; les
variables `USAGE_*` n'en donnent que les valeurs initiales.

**Groupes de droits.** Un compte peut ce que ses groupes lui accordent. Trois
groupes existent d'emblée : *Administrateurs* (tous les droits, implicites),
*Lecture seule*, *Techniciens* (lecture + commandes, courantes et à risque +
saisie des interventions, vérifications et maintenances). Page « Groupes » pour
en composer d'autres — par exemple « exécute les commandes courantes mais pas
les commandes à risque, et ne gère pas les postes ». Le premier compte est dans
*Administrateurs* ; une base migrée depuis une version à deux rôles y range ses
anciens `admin`, les autres dans *Lecture seule*.

**Bâtiments et salles.** Un bâtiment porte l'emplacement, dans les mots que les
agents remontent (réglage `location` de l'agent) ; une salle en hérite. La
console range les postes à la main (`ROOM_SOURCE=manual`) ou depuis l'annuaire :
`ad_ou` crée une salle par unité d'organisation contenant l'objet ordinateur,
`ad_location` une par valeur de l'attribut *Emplacement* de l'objet. Les deux
lectures viennent de l'agent, sans rien configurer (voir « Paramètres de l'agent
Windows », paragraphe *Annuaire*). Après un changement de `ROOM_SOURCE`,
« Resynchroniser depuis l'annuaire » sur la page Salles reclasse tout le parc.

La resynchronisation range chaque poste dans la salle que nomme sa dernière
lecture de l'annuaire (son OU, ou son attribut *Emplacement*), en créant les
salles qui manquent ; une salle créée à la main du même nom — dans un bâtiment
ou non — est reprise plutôt que doublée, si une majorité des postes qui la
réclament s'accordent sur la même OU (sinon ils restent où ils sont et la salle
est signalée). Un poste dont la lecture ne nomme aucune salle est retiré de la
sienne ; un poste dont l'agent n'a **jamais** transmis de lecture d'annuaire
(agent ancien, poste hors domaine) reste où il est, comme lors d'un simple
inventaire. Elle ne s'exécute pas d'un clic : la console calcule d'abord, sans
rien écrire, combien de postes changeront de salle et combien de salles seront
créées, et demande confirmation avant de lancer le reclassement (tracé dans le
journal d'audit).

**Lire l'annuaire au lieu de croire les agents** (`DIRECTORY_VERIFY=relay`).
Par défaut, l'OU, le DN et l'emplacement qui rangent un poste sont ceux que son
agent déclare : un poste forgé avec le secret du parc peut donc se ranger dans
la salle d'un autre. En mode `relay`, des postes **désignés** dans la console
(fiche du poste, onglet Identité, « Désigner comme lecteur d'annuaire » ; droit
`settings:write`) lisent les objets ordinateurs de leur domaine, avec leur
**compte machine** (aucun compte de service ni mot de passe à fournir), et le
serveur range les salles d'après cette lecture.

- **Qui désigner** : un serveur membre ou un poste d'administration toujours
  allumé, jamais un poste élève. Un lecteur par domaine au moins ; deux, et leurs
  lectures sont comparées (un désaccord gèle les déplacements du domaine et est
  signalé dans Paramètres → Annuaire). La désignation tombe d'elle-même si le
  poste est ré-enrôlé, si son jeton est révoqué ou s'il passe en « Identité à
  confirmer ». Seuls les lecteurs ont besoin d'un agent récent.
- **Ce que le lecteur lit** : toutes les `DIRECTORY_SYNC_MINUTES` (60 min par
  défaut), le serveur lui envoie la commande « Lecture de l'annuaire » avec la
  liste des noms des postes de son domaine ; le lecteur lit, en lecture seule
  (`System.DirectoryServices` par PowerShell), `sAMAccountName`,
  `dNSHostName`, `objectGUID`, `distinguishedName`, `location` et l'état
  désactivé de chaque objet, plus l'identité du domaine (nom DNS, nom NetBIOS,
  SID) et la table sous-réseaux → sites. Le serveur refuse une lecture d'un poste
  non désigné ou d'un autre domaine que le sien. Le compte machine lit ces
  attributs avec les droits par défaut d'Active Directory ; rien n'est à
  déléguer.
- **Ce qui change** : chaque poste reçoit un statut — **vérifié** (sa
  déclaration est ce que dit l'annuaire), **écart** (il déclare autre chose :
  signalé, pas bloquant ; un poste déplacé dans AD et pas encore redémarré est
  dans ce cas), **inconnu** (aucun objet de ce nom ; il reste où il est et ne
  crée pas de salle) ou **périmé** (objet désactivé ou supprimé, ou domaine non
  relu depuis `DIRECTORY_STALE_HOURS`). Avec `ROOM_SOURCE=ad_ou` ou
  `ad_location`, la salle suit la lecture ; sa clé porte désormais le SID du
  domaine, pour que deux établissements aient chacun leur « Salle 101 », et les
  salles existantes sont reprises à la première lecture. Une lecture qui
  déplacerait plus de `DIRECTORY_CONFIRM_MOVES` postes attend une confirmation
  dans Paramètres → Annuaire. La liste des postes se filtre par statut
  (« Annuaire : écart » depuis Paramètres) et la fiche montre côte à côte ce que
  l'agent déclare et ce que l'annuaire dit.
- **Ce qui borne un lecteur** : sa désignation est liée au domaine qu'il
  déclarait quand il a été désigné et au SID de sa première lecture ; un nom
  NetBIOS ne désigne qu'**un seul domaine** sur le serveur (deux domaines de
  même nom NetBIOS ne sont pas pris en charge ; un domaine reconstruit sous un
  autre SID se retire par « Oublier ce domaine »). Deux postes qui portent le
  même nom dans un domaine sont « contestés » jusqu'à ce que l'un soit
  fusionné, supprimé ou révoqué. Désigner un lecteur et confirmer des
  déplacements sont réservés aux comptes sans limite de lieu. Une lecture ne
  reprend pas une salle créée à la main : c'est « Resynchroniser depuis
  l'annuaire », page Salles, qui le fait, après confirmation.
- **Limite** : lire l'annuaire prouve ce qu'il dit d'un nom, pas que le poste
  *est* ce nom. Un poste forgé qui prend le nom d'un poste réel pas encore
  enrôlé est rangé à sa place ; un lecteur compromis ment pour tout son domaine.
- **Dépannage** : le résultat de la commande « Lecture de l'annuaire » dans
  l'historique du lecteur donne le nombre d'objets lus, ou l'erreur (contrôleur
  de domaine injoignable, délai de 5 minutes dépassé, lecture refusée par le
  serveur). Le mode `ldap` (le serveur interroge lui-même un contrôleur de
  domaine) n'existe pas encore.

**Vérifications et maintenance.** « Mes tâches » réunit, pour chaque compte, les
vérifications qu'on lui a affectées et les salles et postes dont il est
responsable de la maintenance. Le cycle et le responsable se règlent au niveau
du parc (page Paramètres), d'une salle ou d'un poste, le plus précis gagnant ;
un cycle de 0 exclut. Une séance de maintenance se saisit pour toute une salle
depuis sa fiche ou depuis « Mes tâches », quelle que soit sa taille (la console
l'envoie par parts de 250 postes, une seule séance) ; une séance où aucun poste
n'a été fait s'enregistre si elle dit pourquoi, sans toucher les échéances.
Les e-mails suivent le réglage de
chaque compte (page « Mon compte »).

**Tendances, indicateurs et pannes récurrentes.** La page « Tendances » (menu,
juste sous le tableau de bord, et lien « Évolution » de sa barre de titre)
montre, sur 3, 12 ou 24 mois :

- **L'évolution du parc** : les compteurs du tableau de bord, photographiés
  toutes les heures par le worker (le dernier passage d'un jour, dans le fuseau
  de la console, est le chiffre de ce jour) et gardés par lieu, de sorte qu'un
  compte limité à des lieux ne voit que la somme des siens. **L'historique
  commence au déploiement** : rien n'est reconstitué, et la page le dit
  (« Suivi depuis le … »). Un jour où le worker était arrêté est un trou dans la
  courbe, pas un zéro. Les changements de seuil (disque presque plein, cycle de
  maintenance…) sont signalés sous la courbe. Conservation :
  `TREND_RETENTION_DAYS` (25 mois par défaut).
- **Les indicateurs**, mois par mois : délai de clôture des vérifications
  (médiane et 9e décile), maintenances faites à l'heure (jugées avec le cycle
  d'aujourd'hui), réussite des commandes et des déploiements (les commandes
  expirées ou sans réponse sont comptées à part, hors du taux). Ils sont
  calculés sur l'historique déjà en base, donc limités par sa conservation :
  `COMMAND_RETENTION_DAYS` (365 jours) et `SCHEDULE_RUN_RETENTION_DAYS`
  (180 jours) ; la page avertit quand la période demandée est plus longue.
- **Les pannes récurrentes** : les interventions de type « incident » par
  modèle ou par salle actuelle du poste, rapportées au nombre de postes en parc
  (« pour 100 postes ») ; les postes réformés sont comptés à part.
- **Le rapport Excel** : la page sur la période choisie, dans la langue de la
  console, téléchargé à la demande (pas d'envoi périodique).

Droits : la page s'ouvre avec la lecture des postes ; chaque indicateur demande
en plus la lecture de sa source (vérifications, maintenance, commandes,
paquets), et les pannes la lecture des interventions. Rien à configurer, aucune
action d'audit : la page ne fait que lire.

## Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| `curl` HTTPS renvoie un code `000` | Certificat auto-signé non approuvé | `curl -k`, ou importer la racine Caddy |
| L'agent journalise une erreur TLS x509 | Auto-signé, que le client de l'agent refuse | Importer la racine Caddy dans le magasin machine du poste (§ « Mode B »). Sur la stack de production (mode C, repliée sur `tls internal`), c'est le seul correctif : elle n'a pas de port HTTP. Avec l'override de dev seulement (`docker-compose.dev.yml`), on peut à défaut viser le port HTTP direct `http://...:8800` **avec** `AllowInsecureHTTP` = 1 (registre) ou `--allow-insecure-http` à `init-config` ; ce port n'est publié que sur `127.0.0.1` tant que `TIAI_DEV_BACKEND_BIND=0.0.0.0` n'est pas posé dans le `.env` (§ « Mode A ») |
| Le poste n'apparaît pas (ou plus) dans la console, service `TiaiAgent` pourtant « En cours d'exécution » ; `agent.log` répète `agent: cannot run yet (api_base_url "http://..." is http://: …)` toutes les 1 à 15 minutes | Agent publié après la v1.1.0 : une URL en `http://` est refusée sauf déclaration explicite. Le service ne s'arrête pas, il attend une configuration utilisable sans contacter le serveur (la commande `run` au premier plan, elle, s'arrête sur cette erreur) | Passer en `https://`, ou poser `AllowInsecureHTTP` = 1 (registre) / `allow_insecure_http: true` (YAML) en connaissance de cause (cf. § « Surcharge par le registre (GPO) »). L'agent repart à l'essai suivant, sans redémarrage |
| Depuis un changement des paramètres de la GPO, aucun poste n'est installé ni mis à jour ; `deploy.log` n'a plus de ligne nouvelle | Le script du partage ne connaît pas un paramètre ajouté à la GPO (`-AllowInsecureHttp` face à un script antérieur), ou une valeur hors de celles qu'il admet (`1` au lieu de `true`) : PowerShell rejette la ligne avant la première instruction du script | Copier sur le partage le `Install-TiaiAgent.ps1` de la release visée (il n'est pas dans ses fichiers : le prendre dans le dépôt, `deploy/gpo/`), **puis** modifier les paramètres ; cf. [deploy/gpo/README.md](deploy/gpo/README.md) |
| L'agent échoue sur `http://<serveur>` (port 80, sans `:8800`), réponse 301 | Caddy redirige `http://` vers `https://`, et l'agent ne suit aucune redirection | Viser directement `https://<TIAI_SERVER_NAME>` |
| `https://<ip>` ne répond pas / mauvais certificat | Le site Caddy est lié à un nom d'hôte ; `http://<ip>` redirige, `https://<ip>` n'a pas de certificat | Taper le nom (`TIAI_SERVER_NAME`, ou un alias déclaré), résolu par le DNS ou le fichier `hosts` |
| Le nom court (`http://tiai`) donne une page blanche ou une erreur, le nom complet marche | Stack antérieure à la redirection des autres hôtes, ou nom court non résolu | Mettre à jour la stack ; vérifier `nslookup tiai` depuis un poste ; pour `https://tiai`, déclarer l'alias dans `TIAI_SERVER_ALIASES` et le mettre dans les SAN du certificat |
| La console boucle en redirections (*too many redirects*) sur un hôte Docker derrière un proxy | Compose injecte le proxy de `~/.docker/config.json` dans les conteneurs, et une version antérieure de Caddy l'empruntait pour joindre backend et frontend | Mettre à jour la stack (cf. § « Hôte Docker derrière un proxy ») ; `config.json` peut rester en place |
| Le navigateur force HTTPS et refuse le HTTP | Cache HSTS d'un accès antérieur au Caddyfile de prod | Purger le HSTS pour ce nom d'hôte, ou utiliser un autre nom en test |
| Erreur CORS dans la console | Origine absente de `BACKEND_CORS_ORIGINS` | Ajouter l'origine dans `.env`, ou passer par Caddy |
| `413` sur une requête de l'agent ou de la console | Corps de requête au-delà de 8 Mo, refusé par Caddy (`request_body` du Caddyfile) | Aucun envoi légitime n'en approche : chercher l'agent défaillant dans les journaux de Caddy |
| `docker compose ps` montre `unhealthy` | Voir § « État de santé et journaux » | `docker compose logs <service>` ; pour le backend, vérifier que `db` est sain |
| Le backend refuse de démarrer, message « `changeme` placeholder » | `ENVIRONMENT` ≠ `local` avec des secrets d'exemple | Renseigner les vrais secrets, ou utiliser l'override de dev |
| Caddy ne démarre pas en mode C | `deploy/certs/tiai.crt` ou `.key` absent | Déposer le certificat, ou passer la ligne `tls` à `tls internal` |
| `401 auth.enrollment_secret.invalid` à l'enrôlement | Secret agent ≠ `ENROLLMENT_SECRET` serveur | Aligner YAML/registre sur le `.env` du serveur |
| `agent.log` montre `panic: reflect: call of reflect.Value.Uint on int32 Value` environ 4 min après le démarrage, puis le service repart (ou reste arrêté sur un agent antérieur) | La première collecte d'inventaire faisait planter la bibliothèque WMI sur `Win32_SystemEnclosure.ChassisTypes` (tableau livré en int32, lu en uint16). Cause racine des deux symptômes d'origine : aucun inventaire ne remontait, et le service mourait sur tout le parc | Corrigé (v0.0.9) ; tout panic de la bibliothèque est en outre rattrapé et rendu comme une erreur de la classe concernée |
| Le service `TiaiAgent` est arrêté, sans message, démarrage pourtant *Automatique* | Le processus s'est arrêté (configuration illisible, WMI pas encore prêt au démarrage…) et les anciennes actions de récupération — « relance, relance, rien » — étaient épuisées | `tiai-agent repair` (ou le script GPO au démarrage suivant) ; à partir de cette version le service réessaie de lui-même et le SCM le relance indéfiniment. Cause : `agent.log` |
| `agent.log` répète `tick failed ... Proxy Authentication Required` (ou `407`), aucun poste ne s'enrôle | Le poste pousse `HTTPS_PROXY` en variable système et l'agent, antérieur à `proxy_url`, la suivait ; les exclusions des paramètres proxy Windows ne le concernent pas | Mettre à jour l'agent : il se connecte désormais en direct par défaut. Sur un agent antérieur, poser `NO_PROXY=<hôte du serveur>` en variable système et redémarrer le service |
| Une fiche poste reste sans matériel ni logiciels | L'inventaire est lu mais le heartbeat qui le porte n'aboutit pas | Chercher `the heartbeat carrying the inventory failed` dans `agent.log` : le budget de ce heartbeat est passé à 2 min, un échec restant vient du serveur (ou d'un proxy) |
| Un poste affiché éteint alors qu'il est allumé, `agent.log` s'arrête après `identity`, service encore *En cours* | Une requête WMI qui ne revient jamais tenait le verrou global de la bibliothèque : tous les heartbeats bloquaient derrière, sans erreur ni ligne de journal | Corrigé : lecture WMI bornée à 90 s, puis sautée tant qu'elle n'est pas revenue ; le poste reste joignable et redémarrable depuis la console. Le journal nomme la classe fautive |
| Un poste apparaît deux fois, l'un des deux muet | UUID SMBIOS illisible au démarrage (WMI pas encore prêt) : l'agent était reparti sur une identité de repli | Supprimer la fiche fantôme ; la lecture est désormais retentée avant tout repli, et le repli est journalisé |
