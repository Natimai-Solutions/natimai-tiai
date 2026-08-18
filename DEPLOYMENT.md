# Tia'i — Déploiement & configuration

Comment lever la stack selon le niveau de TLS souhaité, quelles variables
d'environnement renseigner côté serveur et quels paramètres pousser côté agent.

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

### Alertes e-mail et e-mails de compte

Facultatif — désactivé si `MAILGUN_DOMAIN` ou `MAILGUN_API_KEY` est vide. Mailgun
sert aux alertes de supervision (envoyées à `ALERT_RECIPIENTS`) et au lien de
réinitialisation de mot de passe. Sans lui, le parcours « mot de passe oublié »
reste sans effet : c'est alors à un administrateur de réinitialiser le mot de
passe depuis la console.

| Variable | Défaut |
|---|---|
| `MAILGUN_API_BASE_URL` | `https://api.mailgun.net/v3` |
| `MAILGUN_DOMAIN` / `MAILGUN_API_KEY` | — |
| `MAILGUN_FROM_EMAIL` / `MAILGUN_FROM_NAME` | — / `Tiai` |
| `MAILGUN_TIMEOUT_SECONDS` | `10` |
| `ALERT_RECIPIENTS` | *(vide)* — liste séparée par des virgules |

### Hors Docker

| Variable | Portée | Rôle |
|---|---|---|
| `API_BASE_URL` | Build frontend | baseURL axios, injectée au build ; défaut `/api/v1` |
| `TIAI_TEST_DATABASE_URL` | Tests backend | DSN Postgres pour les tests d'API |

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
