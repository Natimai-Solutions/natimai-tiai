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

Le TLS n'est pas une dépendance dure : l'authentification passe par des en-têtes
HTTP, jamais par un cookie `Secure` ou une redirection. On peut donc démarrer les
tests en HTTP pur et ajouter le certificat plus tard, sans toucher au code.

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

L'override publie le backend en HTTP direct sur `0.0.0.0:8800` (Caddy
court-circuité), bascule Caddy en `tls internal` et force `ENVIRONMENT=local`,
ce qui neutralise la garde de démarrage qui refuse les secrets `changeme`.

Côté poste, récupérer `tiai-agent-<version>-windows-amd64.exe` depuis la page
*Releases* du dépôt (ou le compiler : `go build -o tiai-agent.exe .` dans
`agent/`), puis le pointer directement sur le port HTTP — **pas** sur Caddy :

```powershell
.\tiai-agent.exe init-config --api-url http://192.168.1.50:8800
.\tiai-agent.exe run
```

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
# déposer deploy/certs/tiai.crt et deploy/certs/tiai.key
docker compose up -d
```

- Le **CN/SAN du certificat doit correspondre à `TIAI_SERVER_NAME`**, sinon
  l'agent refuse la connexion.
- `deploy/certs/` est monté en lecture seule et ignoré par git, comme
  `deploy/.env`.
- Hors `ENVIRONMENT=local`, le backend **refuse de démarrer** si `SECRET_KEY`,
  `ENROLLMENT_SECRET`, `POSTGRES_PASSWORD` ou `FIRST_ADMIN_PASSWORD` est vide ou
  commence encore par `changeme`.
- Les postes du domaine font déjà confiance à l'AC racine : aucun import de
  certificat n'est nécessaire côté agent.

Repli sans certificat sur cette même stack : remplacer la ligne `tls ...` du
[Caddyfile](deploy/Caddyfile) par `tls internal`.

---

## Générer les secrets

Quatre valeurs du `.env` doivent être générées aléatoirement — format recommandé
**32 octets en hexadécimal**, qui évite tout problème de quoting et d'encodage :

| Variable | Usage | Conséquence d'une valeur faible |
|---|---|---|
| `SECRET_KEY` | Signature des JWT console | Tout JWT devient forgeable → accès admin |
| `ENROLLMENT_SECRET` | En-tête d'enrôlement des agents | N'importe qui peut enrôler une machine |
| `POSTGRES_PASSWORD` | Compte PostgreSQL | Accès direct à la base |
| `FIRST_ADMIN_PASSWORD` | Premier compte console | Accès admin à la console |

```bash
# Linux / macOS / Git Bash
for v in SECRET_KEY ENROLLMENT_SECRET POSTGRES_PASSWORD FIRST_ADMIN_PASSWORD; do
  echo "$v=$(openssl rand -hex 32)"
done
```

```powershell
# Windows — générateur cryptographique .NET, pas Get-Random
'SECRET_KEY','ENROLLMENT_SECRET','POSTGRES_PASSWORD','FIRST_ADMIN_PASSWORD' | ForEach-Object {
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
- Changer `SECRET_KEY` invalide tous les JWT console : les opérateurs devront se
  reconnecter.
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
| `TIAI_SERVER_NAME` | `tiai.natimai.local` | Nom du site Caddy ; doit correspondre au CN/SAN du certificat en mode C |
| `TIAI_DEV_BACKEND_PORT` | `8800` | Port hôte du backend en HTTP direct (override de dev uniquement) |

### Backend

| Variable | Défaut | Rôle |
|---|---|---|
| `ENVIRONMENT` | `local` | `local` / `staging` / `production`. Hors `local` : garde anti-placeholder + masquage des erreurs 500 |
| `SECRET_KEY` | `changeme` | Signature des JWT console |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Durée de vie du JWT console |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` | — | Compte admin créé au démarrage s'il n'existe pas |
| `PASSWORD_MIN_LENGTH` | `12` | Longueur minimale imposée à tout mot de passe |
| `PASSWORD_RESET_EXPIRE_MINUTES` | `60` | Validité d'un lien « mot de passe oublié » |
| `CONSOLE_BASE_URL` | — | URL publique de la console, pour le lien de réinitialisation. **Sans elle, aucun e-mail de réinitialisation n'est envoyé** |
| `ENROLLMENT_SECRET` | `changeme-enrollment-secret` | Secret partagé d'enrôlement ; n'autorise que l'enregistrement d'un poste |
| `BACKEND_CORS_ORIGINS` | *(vide)* | Origines autorisées, séparées par des virgules. Inutile si la console passe par Caddy |
| `POSTGRES_SERVER` / `POSTGRES_PORT` | `db` / `5432` | Forcés par le compose |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `tiai` / — / `tiai` | |
| `POSTGRES_POOL_SIZE` / `POSTGRES_MAX_OVERFLOW` / `POSTGRES_POOL_TIMEOUT` | `20` / `10` / `30` | Pool async partagé backend + worker |
| `REDIS_SERVER` / `REDIS_PORT` | `redis` / `6379` | File ARQ ; forcés par le compose |
| `SIGNATURE_MAX_AGE_DAYS` | `3` | Seuil « signatures à jour » |
| `INACTIVE_AFTER_DAYS` | `30` | Seuil « poste inactif » |
| `OFFLINE_AFTER_SECONDS` | `180` | Seuil « poste allumé » : 3 × l'intervalle de heartbeat de l'agent, pour qu'un battement manqué n'éteigne pas le parc. À relever avec lui sur un parc plus lent |

### Réveil des postes (Wake-on-LAN)

Voir la section « [Réveil des postes](#réveil-des-postes-wake-on-lan-1) » plus
bas pour ce qui doit être vrai du poste, du réseau et de l'hôte Docker — les
variables ci-dessous ne décrivent que la destination du paquet.

| Variable | Défaut | Rôle |
|---|---|---|
| `WOL_SUBNET_PREFIXLEN` | `24` | **Repli seulement.** Le masque vient normalement du poste lui-même : son agent le lit sur la carte et le remonte avec l'adresse, ce qui est la seule source juste sur un parc où cohabitent des /16 et des /24. Ce réglage ne sert qu'aux postes dont l'agent est antérieur à cette remontée, ou dont la carte n'a pas exposé de masque |
| `WOL_BROADCAST_ADDRESSES` | *(vide)* | Adresses de diffusion explicites, séparées par des virgules. Renseignées, elles **remplacent** l'adresse déduite et servent pour *tous* les postes — la réponse pour un serveur qui doit joindre des segments où il n'a pas d'adresse, et le seul moyen de réveiller un poste qui n'a jamais remonté d'IP |
| `WOL_PORT` | `9` | Port UDP du paquet magique. Indifférent au matériel (la carte reconnaît le motif n'importe où dans la trame) ; ne compte que pour un pare-feu sur le trajet |
| `WOL_PACKET_COUNT` | `3` | Nombre de copies émises. Une diffusion UDP n'accuse rien et se perd sans bruit ; trois copies coûtent trois datagrammes |

### Alertes e-mail et e-mails de compte

Facultatif — désactivé si `MAILGUN_DOMAIN` ou `MAILGUN_API_KEY` est vide. Mailgun
sert aux notifications de supervision et au lien de réinitialisation de mot de
passe. Sans lui, le parcours « mot de passe oublié » reste sans effet : c'est
alors à un administrateur de réinitialiser le mot de passe depuis la console.

Un compte Mailgun se crée facilement sur [mailgun.com](https://www.mailgun.com/) ;
le domaine d'envoi et la clé API à reporter ci-dessous se trouvent ensuite dans
son tableau de bord.

**Qui reçoit quoi se règle par compte**, page « Mon compte » de la console, et un
administrateur voit et modifie le réglage des autres comptes depuis la page
Utilisateurs. Quatre cadences :

| Cadence | Ce qui part |
|---|---|
| Aucun e-mail | rien (les e-mails de compte, comme la réinitialisation, continuent d'arriver) |
| Alerte immédiate à chaque menace | un e-mail dès qu'un poste signale une menace **nouvellement** détectée |
| Résumé quotidien, seulement s'il y a du nouveau | un e-mail les jours où il y a à traiter : menace active, mise à jour critique ou importante en attente, poste à vérifier |
| Résumé quotidien, tous les jours *(défaut)* | un e-mail chaque matin, même sans incident : état du parc, antivirus périmés, postes à mettre à jour |

Le résumé est envoyé par le worker ARQ ; les alertes immédiates partent du
serveur d'API, en tâche de fond, une fois le heartbeat répondu — une panne
Mailgun ne fait jamais échouer la remontée d'un poste.

Il n'y a **aucune liste de destinataires dans la configuration** : le courrier
ne part qu'aux comptes de la console, selon la cadence de chacun. Une nouvelle
installation n'est pas pour autant sans surveillance — le premier admin, créé au
démarrage à partir de `FIRST_ADMIN_EMAIL`, arrive sur le résumé quotidien, à une
adresse réelle et modifiable depuis la console.

| Variable | Défaut | Rôle |
|---|---|---|
| `MAILGUN_API_BASE_URL` | `https://api.mailgun.net/v3` | |
| `MAILGUN_DOMAIN` / `MAILGUN_API_KEY` | — | Vides = aucun e-mail n'est envoyé |
| `MAILGUN_FROM_EMAIL` / `MAILGUN_FROM_NAME` | — / `Tiai` | |
| `MAILGUN_TIMEOUT_SECONDS` | `10` | |
| `MAILGUN_PROXY_URL` | — | Proxy HTTP sortant pour le seul client Mailgun (ex. `http://10.0.0.1:3128`), utile derrière le proxy d'un établissement. Volontairement distinct de `HTTP_PROXY`/`HTTPS_PROXY`, que tous les processus honoreraient — Caddy compris |
| `DIGEST_HOUR_UTC` | `18` | Heure UTC du résumé quotidien. Le parc visé est à UTC-10, où 18:00 UTC = 08:00 sur place |
| `THREAT_ALERT_MAX_AGE_HOURS` | `24` | Une détection plus ancienne ne déclenche pas d'alerte immédiate : un poste qui s'enrôle remonte tout l'historique Defender d'un coup |
| `NOTIFICATION_MAX_ITEMS` | `10` | Postes détaillés dans un e-mail avant « … et N autres » |

`CONSOLE_BASE_URL` mérite d'être renseignée ici aussi : c'est ce qui met dans
chaque e-mail le lien vers la fiche du poste concerné.

### Hors Docker

| Variable | Portée | Rôle |
|---|---|---|
| `API_BASE_URL` | Build frontend | baseURL axios, injectée au build ; défaut `/api/v1` |
| `TIAI_TEST_DATABASE_URL` | Tests backend | DSN Postgres pour les tests d'API |

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
tourne dans un conteneur sur le *bridge* Docker. Le datagramme part vers
l'adresse de diffusion du sous-réseau du poste, arrive à l'hôte qui sert de
passerelle — et **Linux ne relaie pas une diffusion dirigée par défaut**
(RFC 2644). Sans l'un des deux réglages ci-dessous, le paquet meurt sur l'hôte et
la console annonce pourtant une émission réussie, puisqu'elle l'a bien émise.

Le moins invasif — le `docker-compose.yml` reste inchangé :

```bash
# <iface> = l'interface LAN de l'hôte (ip -br addr)
sudo sysctl -w net.ipv4.conf.<iface>.bc_forwarding=1
echo "net.ipv4.conf.<iface>.bc_forwarding = 1" | sudo tee /etc/sysctl.d/99-tiai-wol.conf
```

L'alternative est de donner au service `backend` le réseau de l'hôte
(`network_mode: host`) : la pile réseau du conteneur devient celle de l'hôte et
la question disparaît, mais `db` et `redis` ne sont plus joignables par leur nom
de service et le proxy Caddy est à revoir. À réserver aux déploiements qui ne
peuvent pas toucher aux `sysctl`.

**Vérifier**, depuis une machine du même segment que les postes, pendant qu'on
appuie sur « Réveiller le poste » dans la console :

```bash
sudo tcpdump -ni <iface> udp port 9
```

Une trame par `WOL_PACKET_COUNT` doit apparaître. Si rien ne sort de l'hôte,
c'est le §3 ; si les trames sortent mais que le poste ne démarre pas, c'est le §1.

---

## Paramètres de l'agent Windows

### Fichier de configuration

`C:\ProgramData\Tiai\config.yaml` (chemin surchargeable par `--config`) :

```yaml
api_base_url: http://192.168.1.50:8800   # http:// accepté ; https:// exige un certificat approuvé
enrollment_secret: <secret partagé>       # préférer le registre (voir plus bas)
machine_uuid: ""                          # vide = résolution auto
heartbeat_interval_seconds: 60
request_timeout_seconds: 10
backoff_max_seconds: 300
queue_max_items: 1000
wu_collect_interval_seconds: 21600        # cycle Windows Update (6 h) — jamais dans le heartbeat
wu_install_timeout_seconds: 7200          # budget d'une installation de MAJ (2 h)
log_level: INFO                           # DEBUG logge aussi les heartbeats silencieux
report_session_username: true             # false = remonter la présence sans le nom
```

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
| `EnrollmentSecret` | `REG_SZ` | `enrollment_secret` |
| `MachineUUID` | `REG_SZ` | `machine_uuid` |
| `LogLevel` | `REG_SZ` | `log_level` |
| `HeartbeatIntervalSeconds` | `REG_DWORD` | `heartbeat_interval_seconds` |
| `WUCollectIntervalSeconds` | `REG_DWORD` | `wu_collect_interval_seconds` |
| `WUInstallTimeoutSeconds` | `REG_DWORD` | `wu_install_timeout_seconds` |
| `ReportSessionUsername` | `REG_DWORD` | `report_session_username` |

Pour les intervalles, `0` est ignoré et signifie « laisser le défaut ». Pour
`ReportSessionUsername`, c'est la **présence de la clé** qui l'emporte : `0`
coupe la remontée du nom de l'utilisateur connecté (la console affiche alors la
présence sans identité), `1` la rétablit.

```powershell
New-Item -Path 'HKLM:\SOFTWARE\Tiai' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Tiai' -Name 'ApiBaseURL' -Value 'http://192.168.1.50:8800'
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Tiai' -Name 'EnrollmentSecret' -Value '<secret>'
```

### Commandes

```powershell
.\tiai-agent.exe init-config --api-url <url> [--machine-uuid <uuid>] [--config <chemin>]
.\tiai-agent.exe run [--config <chemin>]   # premier plan (Ctrl+C), ou sous le SCM
.\tiai-agent.exe install [--config <chemin>]
.\tiai-agent.exe start | stop | status | uninstall | version
```

L'agent s'auto-enrôle au premier démarrage, stocke le token reçu, puis n'utilise
plus que celui-ci. `uninstall` ne retire que l'enregistrement du service : le
binaire, `C:\ProgramData\Tiai` et `HKLM\SOFTWARE\Tiai` restent en place.

**Mettre à jour un poste** ne passe pas par `uninstall` / `install` — le service
pointe sur un chemin, pas sur une version. Arrêter, remplacer le binaire,
redémarrer : le token, l'identité et la file locale sont conservés, donc pas de
ré-enrôlement.

```powershell
.\tiai-agent.exe stop
Copy-Item .\tiai-agent-<version>-windows-amd64.exe 'C:\Program Files\Tiai\tiai-agent.exe' -Force
.\tiai-agent.exe start
```

### Logs

`C:\ProgramData\Tiai\agent.log` (rotation en `.old` au-delà de 5 Mio), en plus de
stderr. Passer `log_level` à `DEBUG` pour tracer chaque heartbeat — le moyen le
plus direct de vérifier qu'un poste poll bien pendant les tests.

---

## Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| `curl` HTTPS renvoie un code `000` | Certificat auto-signé non approuvé | `curl -k`, ou importer la racine Caddy |
| L'agent journalise une erreur TLS x509 | Auto-signé, que le client de l'agent refuse | Basculer sur `http://...:8800`, ou importer la racine Caddy |
| `https://<ip>` ne répond pas / mauvais certificat | Le site Caddy est lié à un nom d'hôte | Ajouter `TIAI_SERVER_NAME` au DNS ou au fichier `hosts` |
| Le navigateur force HTTPS et refuse le HTTP | Cache HSTS d'un accès antérieur au Caddyfile de prod | Purger le HSTS pour ce nom d'hôte, ou utiliser un autre nom en test |
| Erreur CORS dans la console | Origine absente de `BACKEND_CORS_ORIGINS` | Ajouter l'origine dans `.env`, ou passer par Caddy |
| Le backend refuse de démarrer, message « `changeme` placeholder » | `ENVIRONMENT` ≠ `local` avec des secrets d'exemple | Renseigner les vrais secrets, ou utiliser l'override de dev |
| Caddy ne démarre pas en mode C | `deploy/certs/tiai.crt` ou `.key` absent | Déposer le certificat, ou passer la ligne `tls` à `tls internal` |
| `401 auth.enrollment_secret.invalid` à l'enrôlement | Secret agent ≠ `ENROLLMENT_SECRET` serveur | Aligner YAML/registre sur le `.env` du serveur |
