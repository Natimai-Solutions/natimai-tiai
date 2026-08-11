# Tiai — Déploiement & configuration TLS

Ce document décrit les trois manières de lever la stack selon le niveau de TLS
souhaité, les variables d'environnement du serveur et les paramètres du client
(agent Windows).

**Le TLS n'est pas une dépendance dure** : le backend n'impose ni HTTPS, ni
cookie `Secure`, ni redirection — l'authentification est portée par des en-têtes
(`X-Enrollment-Secret` puis `Authorization: Bearer`). On peut donc démarrer les
tests en HTTP pur et ajouter le certificat plus tard, sans toucher au code.

## Les trois modes

| Mode | TLS | Pour qui | Prérequis |
|---|---|---|---|
| **A — Sans certificat** | Aucun (HTTP pur, port 8800) | Premiers tests réseau, agents, `curl` | Aucun |
| **B — Auto-signé** | `tls internal` (AC locale Caddy) | Console web, validation de la chaîne HTTPS | Résolution du nom d'hôte |
| **C — AC interne** | Certificat AD CS | Production / pilote GPO | Certificat + clé dans `deploy/certs/` |

Les modes A et B sont fournis par le **même** override
[deploy/docker-compose.dev.yml](deploy/docker-compose.dev.yml) : il expose le
backend en clair *et* bascule Caddy en auto-signé. On peut donc utiliser les
deux en parallèle — les agents en HTTP sur 8800, la console en HTTPS sur 443.

---

## Mode A — sans certificat (HTTP pur)

### Serveur

```bash
cd deploy
cp .env.example .env    # renseigner les secrets ; laisser ENVIRONMENT=local
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

L'override change trois choses par rapport à la prod :

- le backend est publié en HTTP direct sur `0.0.0.0:8800` (donc joignable depuis
  le réseau, pas seulement en local), Caddy court-circuité ;
- Caddy monte [Caddyfile.dev](deploy/Caddyfile.dev) à la place du Caddyfile de
  prod → `tls internal`, plus rien à déposer dans `deploy/certs/` ;
- `ENVIRONMENT=local` est forcé sur `backend` et `worker`, ce qui neutralise la
  garde de démarrage qui refuse les secrets `changeme` (cf. `_refuse_placeholder_secrets`
  dans [config.py](backend/app/core/config.py)).

### Vérification

```bash
curl http://localhost:8800/health
# {"status":"ok","timestamp":"...","database":true}
```

### Agent Windows

Récupérer `tiai-agent-<version>-windows-amd64.exe` depuis la page *Releases* du
dépôt (publication : cf. [agent/README.md](agent/README.md#publier-un-exe-sur-github)),
ou le compiler avec `go build -o tiai-agent.exe .` dans `agent/`.

Pointer l'agent directement sur le port HTTP — **pas** sur Caddy :

```powershell
.\tiai-agent.exe init-config --api-url http://192.168.1.50:8800
# puis renseigner le secret d'enrôlement (cf. « Paramètres du client »)
.\tiai-agent.exe run
```

Rien ne valide le schéma de l'URL côté agent : `http://` passe sans réserve, et
tout le parcours (enrôlement → heartbeat → résultat de commande) fonctionne en
clair.

### Limites du mode A

- **La console n'est pas exposée en HTTP.** Le service `frontend` n'a pas de port
  hôte ; il n'est joignable qu'à travers Caddy en 443. Pour une console sans TLS
  du tout, lancer le dev server Quasar (`cd frontend && npm run dev`, port 9000),
  qui proxifie `/api` vers `http://localhost:8000` — utilisable uniquement depuis
  la machine de dev.
- **CORS.** `BACKEND_CORS_ORIGINS` vaut `https://tiai.natimai.local` par défaut.
  Tant que la console passe par Caddy, il n'y a pas de CORS (même origine, axios
  utilise la baseURL relative `/api/v1`). Servir la console depuis une autre
  origine impose d'ajouter cette origine dans le `.env`.
- **Surface d'exposition.** `ENVIRONMENT=local` renvoie aussi les détails
  internes des erreurs 500 ([errors.py](backend/app/core/errors.py)). Combiné au
  port 8800 en clair, réservé à un réseau de test.

---

## Mode B — certificat auto-signé (`tls internal`)

Même commande de démarrage que le mode A : [Caddyfile.dev](deploy/Caddyfile.dev)
demande à Caddy de générer sa propre AC locale et d'émettre le certificat serveur
tout seul. Aucun fichier à fournir.

### Résolution du nom d'hôte — obligatoire

Le bloc Caddy est lié au nom `{$TIAI_SERVER_NAME}` (défaut
`tiai.natimai.local`). Attaquer `https://<ip>` **ne matchera pas le site** : il
faut que le nom résolve sur chaque machine de test, via DNS ou le fichier
`hosts` :

```
# Windows : C:\Windows\System32\drivers\etc\hosts
192.168.1.50   tiai.natimai.local
```

### Navigateur

Le certificat n'est pas approuvé : accepter l'avertissement une fois. Pour le
supprimer proprement, importer l'AC locale de Caddy (voir ci-dessous).

### Agent — l'auto-signé ne suffit pas tel quel

Le client HTTP de l'agent ([client.go](agent/internal/api/client.go)) utilise le
`http.Client` par défaut de Go, **sans `InsecureSkipVerify`** : il n'existe
aucune option pour lui faire ignorer un certificat non approuvé. Deux choix :

1. laisser les agents en HTTP sur 8800 (mode A) ;
2. importer la racine locale de Caddy dans le magasin machine :

```powershell
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .
certutil -addstore Root root.crt
```

### Pas de HSTS en dev — volontaire

Le Caddyfile de dev omet `Strict-Transport-Security` (présent en prod avec
`max-age=31536000`) pour ne pas épingler « HTTPS obligatoire » pendant un an
dans le cache du navigateur sur ce nom d'hôte. Ne pas le rajouter en test : cela
rendrait le mode A inaccessible depuis le même navigateur sur ce nom. Les autres
en-têtes de sécurité (CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`) sont
identiques à la prod, pour valider la CSP dès le dev.

---

## Mode C — certificat de l'AC interne (production)

```bash
cd deploy
cp .env.example .env         # ENVIRONMENT=production + vrais secrets
# déposer le certificat et sa clé :
#   deploy/certs/tiai.crt
#   deploy/certs/tiai.key
docker compose up -d
```

Points d'attention :

- le **CN/SAN du certificat doit correspondre à `TIAI_SERVER_NAME`**, sinon Caddy
  sert un certificat pour le mauvais nom et l'agent refuse la connexion ;
- `deploy/certs/` est monté en lecture seule (`./certs:/etc/caddy/certs:ro`) ;
  il est dans le `.gitignore`, comme `deploy/.env` ;
- hors `ENVIRONMENT=local`, le backend **refuse de démarrer** si `SECRET_KEY`,
  `ENROLLMENT_SECRET`, `POSTGRES_PASSWORD` ou `FIRST_ADMIN_PASSWORD` est vide ou
  commence encore par `changeme` ;
- les postes du domaine font déjà confiance à l'AC racine : aucun import de
  certificat n'est nécessaire côté agent.

Repli sans certificat sur cette même stack : remplacer la ligne `tls ...` du
[Caddyfile](deploy/Caddyfile) par `tls internal`.

---

## Générer les secrets

Quatre valeurs du `.env` doivent être générées aléatoirement. Hors
`ENVIRONMENT=local`, le backend **refuse de démarrer** tant qu'elles sont vides
ou commencent encore par `changeme` :

| Variable | Usage | Conséquence d'une valeur faible |
|---|---|---|
| `SECRET_KEY` | Clé HMAC de signature des JWT console (HS256) | Tout JWT devient forgeable → accès admin à la console |
| `ENROLLMENT_SECRET` | En-tête `X-Enrollment-Secret` de `POST /agent/enroll` | N'importe qui peut enrôler une machine et obtenir un token |
| `POSTGRES_PASSWORD` | Compte PostgreSQL | Accès direct à la base |
| `FIRST_ADMIN_PASSWORD` | Mot de passe du premier compte console | Accès admin à la console |

Format recommandé : **32 octets en hexadécimal** (64 caractères). L'hexadécimal
évite tout problème de quoting dans le YAML de l'agent et d'encodage dans
l'en-tête HTTP.

### Linux / macOS

```bash
openssl rand -hex 32
# 4d8d6d6df7d32978757da57c5ee7d8babc453784ec106b76e5b46ca29844bccc

# Sans openssl :
head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; echo
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Générer directement les quatre valeurs :

```bash
for v in SECRET_KEY ENROLLMENT_SECRET POSTGRES_PASSWORD FIRST_ADMIN_PASSWORD; do
  echo "$v=$(openssl rand -hex 32)"
done
```

### Windows (PowerShell)

Utiliser le générateur cryptographique de .NET — **pas `Get-Random`**, qui n'est
pas cryptographiquement sûr et ne convient pas pour un secret :

```powershell
$b = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
[System.BitConverter]::ToString($b).Replace('-','').ToLower()
# 60089076177d07b295226e2734106a3a330b88caa6b058aec4cad18b7f62610d
```

Les quatre valeurs d'un coup :

```powershell
'SECRET_KEY','ENROLLMENT_SECRET','POSTGRES_PASSWORD','FIRST_ADMIN_PASSWORD' | ForEach-Object {
    $b = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    "$_=" + [System.BitConverter]::ToString($b).Replace('-','').ToLower()
}
```

Si Git pour Windows est installé, `openssl rand -hex 32` fonctionne aussi tel
quel depuis Git Bash.

### Points d'attention

- **`ENROLLMENT_SECRET` doit être identique des deux côtés** : le `.env` du
  serveur et le `enrollment_secret` de chaque agent (YAML ou valeur registre
  `EnrollmentSecret`). La comparaison est faite en temps constant
  (`hmac.compare_digest` dans [deps.py](backend/app/api/deps.py)) : tout jeu de
  caractères est accepté, mais l'hexadécimal évite les échappements.
- **Le faire tourner ne casse pas les agents déjà enrôlés** : ils n'utilisent
  plus que leur token par poste (`Authorization: Bearer`). Seuls les *nouveaux*
  enrôlements sont concernés — ce qui en fait une rotation peu coûteuse.
- **Changer `SECRET_KEY` invalide tous les JWT console** en circulation : les
  opérateurs devront se reconnecter.
- **`FIRST_ADMIN_PASSWORD` ne doit pas dépasser 72 octets** — bcrypt ignore
  au-delà. Une valeur hexadécimale de 64 caractères passe sans problème. Ce mot
  de passe n'est utilisé qu'au démarrage, pour créer le compte s'il n'existe pas
  encore.
- **`POSTGRES_PASSWORD` n'est appliqué qu'à la première initialisation** du
  volume `db_data`. Le modifier ensuite dans le `.env` ne change rien côté
  Postgres et casse la connexion du backend : il faut soit changer le mot de
  passe dans la base (`ALTER USER`), soit repartir d'un volume neuf
  (`docker compose down -v`, **destructif**).
- Après modification du `.env`, recréer les conteneurs : `docker compose up -d`.
- `deploy/.env` est dans le `.gitignore` — ne jamais le committer.

---

## Variables d'environnement (serveur)

Fichier `deploy/.env`, à créer depuis [deploy/.env.example](deploy/.env.example)
et chargé par `docker compose` (`env_file`). Il n'est jamais committé.

### Infrastructure / compose

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
| `FIRST_ADMIN_EMAIL` | — | Compte admin créé au démarrage s'il n'existe pas |
| `FIRST_ADMIN_PASSWORD` | — | Idem |
| `ENROLLMENT_SECRET` | `changeme-enrollment-secret` | Secret partagé de l'en-tête `X-Enrollment-Secret` ; n'autorise que `/agent/enroll` |
| `BACKEND_CORS_ORIGINS` | *(vide)* | Origines autorisées, séparées par des virgules. Inutile si la console passe par Caddy |
| `POSTGRES_SERVER` | `db` | Forcé à `db` par le compose |
| `POSTGRES_PORT` | `5432` | |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `tiai` / — / `tiai` | |
| `POSTGRES_POOL_SIZE` | `20` | Pool async partagé backend + worker |
| `POSTGRES_MAX_OVERFLOW` | `10` | |
| `POSTGRES_POOL_TIMEOUT` | `30` | |
| `REDIS_SERVER` | `redis` | File ARQ ; forcé à `redis` par le compose |
| `REDIS_PORT` | `6379` | |
| `SIGNATURE_MAX_AGE_DAYS` | `3` | Seuil « signatures à jour » |
| `INACTIVE_AFTER_DAYS` | `30` | Seuil « poste inactif » |

### Alertes e-mail (facultatif — les alertes sont désactivées si `MAILGUN_DOMAIN` ou `MAILGUN_API_KEY` est vide)

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
| `API_BASE_URL` | Build frontend | baseURL axios, injectée au build ; défaut `/api/v1` (relatif → même origine) |
| `TIAI_TEST_DATABASE_URL` | Tests backend | DSN Postgres pour les tests d'API (`pytest`) |

---

## Paramètres du client (agent Windows)

### Fichier de configuration

`C:\ProgramData\Tiai\config.yaml` (chemin surchargeable par `--config`) :

```yaml
api_base_url: http://192.168.1.50:8800   # http:// accepté ; https:// exige un certificat approuvé
enrollment_secret: <secret partagé>       # préférer le registre (voir plus bas)
machine_uuid: ""                          # vide = résolution auto (SMBIOS UUID, repli UUID agent)
heartbeat_interval_seconds: 60
telemetry_interval_seconds: 900
request_timeout_seconds: 10
backoff_max_seconds: 300
queue_max_items: 1000
log_level: INFO                           # DEBUG logge aussi les heartbeats silencieux
```

Toute valeur absente ou non positive retombe sur son défaut, donc un YAML
partiel reste utilisable. Le token par poste n'est **jamais** dans ce fichier :
il est chiffré via DPAPI (scope machine) dans `token.dat`, à côté du YAML.

### Surcharge par le registre (GPO)

Les valeurs présentes sous `HKLM\SOFTWARE\Tiai` **priment sur le YAML**, ce qui
permet à une GPO de pousser un seul réglage sans réécrire le fichier. C'est
l'emplacement recommandé pour le secret d'enrôlement, plutôt qu'en clair dans le
YAML.

| Valeur registre | Type | Équivalent YAML |
|---|---|---|
| `ApiBaseURL` | `REG_SZ` | `api_base_url` |
| `EnrollmentSecret` | `REG_SZ` | `enrollment_secret` |
| `MachineUUID` | `REG_SZ` | `machine_uuid` |
| `LogLevel` | `REG_SZ` | `log_level` |
| `HeartbeatIntervalSeconds` | `REG_DWORD` | `heartbeat_interval_seconds` |
| `TelemetryIntervalSeconds` | `REG_DWORD` | `telemetry_interval_seconds` |

Exemple de bascule d'un poste de test vers le serveur HTTP, sans toucher au YAML :

```powershell
New-Item -Path 'HKLM:\SOFTWARE\Tiai' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Tiai' -Name 'ApiBaseURL' -Value 'http://192.168.1.50:8800'
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Tiai' -Name 'EnrollmentSecret' -Value '<secret>'
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Tiai' -Name 'LogLevel' -Value 'DEBUG'
```

### Commandes

```powershell
.\tiai-agent.exe init-config --api-url <url> [--machine-uuid <uuid>] [--config <chemin>]
.\tiai-agent.exe run [--config <chemin>]   # premier plan (Ctrl+C), ou sous le SCM
.\tiai-agent.exe install [--config <chemin>]
.\tiai-agent.exe start | stop | status | uninstall | version
```

L'agent s'auto-enrôle au premier démarrage, stocke le token reçu (DPAPI), puis
n'utilise plus que `Authorization: Bearer <token>`.

### Logs

`C:\ProgramData\Tiai\agent.log` (rotation en `.old` au-delà de 5 Mio), en plus de
stderr. Passer `log_level` à `DEBUG` pour tracer chaque heartbeat — c'est le
moyen le plus direct de vérifier qu'un poste poll bien pendant les tests.

---

## Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| `curl` HTTPS renvoie un code `000` | Certificat auto-signé non approuvé | `curl -k`, ou importer la racine Caddy |
| L'agent journalise une erreur TLS x509 | Auto-signé + pas d'`InsecureSkipVerify` dans le client | Basculer sur `http://...:8800`, ou importer la racine Caddy |
| `https://<ip>` ne répond pas / mauvais certificat | Le site Caddy est lié à un nom d'hôte | Ajouter `TIAI_SERVER_NAME` au DNS ou au fichier `hosts` |
| Le navigateur force HTTPS et refuse le HTTP | Cache HSTS d'un accès antérieur au Caddyfile de prod | Purger le HSTS pour ce nom d'hôte, ou utiliser un autre nom en test |
| Erreur CORS dans la console | Origine absente de `BACKEND_CORS_ORIGINS` | Ajouter l'origine dans `.env`, ou passer par Caddy (même origine) |
| Le backend refuse de démarrer, message « `changeme` placeholder » | `ENVIRONMENT` ≠ `local` avec des secrets d'exemple | Renseigner les vrais secrets, ou utiliser l'override de dev |
| Caddy ne démarre pas en mode C | `deploy/certs/tiai.crt` ou `.key` absent | Déposer le certificat, ou passer la ligne `tls` à `tls internal` |
| `401 auth.enrollment_secret.invalid` à l'enrôlement | Secret agent ≠ `ENROLLMENT_SECRET` serveur | Aligner YAML/registre sur le `.env` du serveur |
