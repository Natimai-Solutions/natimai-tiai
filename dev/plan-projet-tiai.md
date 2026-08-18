# Tiai — Console de gestion de parc informatique (Natimai)

> Plateforme centralisée de pilotage du parc Windows.
> **Phase 1 (urgente)** : Microsoft Defender. **Phases ultérieures (fin d'année)** : Windows Update, déploiement logiciel, inventaire.
>
> *« Tīa'i » — en reo tahiti : gardien, vigile, garder, protéger.

---

## 1. Vision & périmètre

Construire un agent léger déployé par GPO sur les postes Windows, un backend central qui collecte l'état des postes et orchestre des actions, et une console web de supervision. Le produit est pensé **générique et réutilisable sur d'autres parcs** : rien de spécifique à un réseau dans le code, tout le déploiement-spécifique passe par la configuration (cf. §2.12).

| Module | Priorité | Horizon |
|---|---|---|
| **Defender** : état, scans à distance, mise à jour des signatures | 🔴 Urgent | Maintenant |
| Windows Update | 🟠 Moyen | Fin d'année |
| Déploiement logiciel | 🟡 Bas | Fin d'année |
| Inventaire matériel/logiciel | 🟡 Bas | Fin d'année |

Tout le projet est pensé pour que l'ajout des modules suivants réutilise **le même agent, le même canal de communication et le même modèle de commandes** — seuls les types de commandes et les données remontées changent.

---

## 2. Décisions structurantes

Synthèse des décisions techniques structurantes. Le détail est repris dans les sections suivantes.

### 2.1 — Modèle de communication : polling

La communication agent↔serveur est de type **polling** : l'agent interroge le serveur à intervalle régulier ; le serveur ne se connecte jamais aux postes.

1. l'agent appelle le serveur (heartbeat) → remonte son état Defender ;
2. **la même réponse** lui renvoie les commandes en attente (scan rapide / complet / update) ;
3. l'agent exécute, puis poste le résultat.

Le serveur met les commandes en file ; les agents les récupèrent. Ce modèle traverse NAT et pare-feu sans configuration et gère naturellement les postes hors-ligne.

Deux intervalles : un long pour la remontée d'état (ex. 15 min) et un court pour la récupération de commandes (ex. 1 min). Une action « lancer un scan sur tous les postes » s'applique à chaque poste lors de son prochain *poll*. Si du quasi-temps-réel devient nécessaire → SSE ou WebSocket en option.

### 2.2 — Dimensionnement

Un seul conteneur backend + un **worker** suffisent pour l'instant. Pas de Kafka, pas de cluster : les requêtes sont brèves et étalées dans le temps (~1 à 3 req/s pour 1000 postes), le volume ne le justifie pas. Le seul point d'attention est le réglage du pool de connexions PostgreSQL (asyncpg).

**File de tâches : ARQ retenu, broker (RabbitMQ) écarté.** ARQ ne sert qu'aux tâches **serveur internes** (cron d'expiration des commandes, détection des postes inactifs, alertes Mailgun) — pas au canal des agents, qui est en **polling + Postgres** (commandes durables et requêtables, source de vérité). Un broker AMQP serait inadapté sur les deux plans : il réintroduirait des **connexions persistantes** côté postes (NAT/pare-feu/hors-ligne, cf. §2.1) et **ne fait pas de planification native** alors que le besoin de fond est surtout du cron. Ses atouts (routage fin, fan-out, fort débit, DLQ) ne servent pas à cette échelle, et Redis est déjà présent. **À réévaluer en Phase 2/3** si la mesure révèle du temps réel/push, des flux d'événements volumineux ou un fan-out multi-consommateurs. Alternative « plus standard » sans broker si besoin un jour : Celery sur Redis.

### 2.3 — Identité stable des postes & empreinte

On **sépare** deux besoins : l'**identité** (clé stable pour retrouver le poste) et l'**empreinte** (jeu d'attributs pour détecter un changement). Le `MachineGuid` est écarté comme identité : sur des postes **clonés/ré-imagés sans Sysprep `/generalize`**, il est **dupliqué** (collision sur la clé unique, partage de token).

**Identité (`machine_uuid`)**, résolue par l'agent dans cet ordre :
1. **SMBIOS / System UUID** (`Win32_ComputerSystemProduct.UUID`) — unique par carte mère, stable au renommage, au changement de domaine **et** à une ré-image de l'OS. Ancre principale pour le parc physique. Validé contre une **denylist** (nul `0000…`, `FFFF…`, constantes OEM dupliquées connues).
2. **Repli** si SMBIOS invalide/absent : UUID **généré par l'agent** au 1er run et persisté (`HKLM\SOFTWARE\Tiai`, ACL `SYSTEM`).
3. **TPM 2.0 (EK public)** : ancre la plus robuste si le parc en dispose ; ici lu en **bonus d'empreinte** (parc mixte, on n'en dépend pas).

**Empreinte** = composants stockés **séparément, jamais hashés** (`machine_guid`, `smbios_uuid`, `tpm_ek_hash`, `hostname`, `domain`). À chaque enrôlement/heartbeat, le serveur **diffe** avec des règles par attribut :

| Constat | Lecture | Action |
|---|---|---|
| hostname/domaine/MachineGuid changent, ancre identique | renommage / ré-image bénigne | maj silencieuse |
| `smbios_uuid` ou `tpm_ek_hash` changent | swap matériel / clone / vol de token | **`needs_verification`** |
| même `smbios_uuid` sous un **autre** `machine_uuid` actif | ré-image du même poste ou clone | flag + fusion manuelle (§8) |

> Un **hash** des identifiants serait un mauvais choix : il change dès qu'un seul composant bouge (donc instable comme clé) et ne dit jamais **lequel** a changé (un renommage bénin déclencherait « à vérifier »). Stocker les composants permet la décision fine.

Le `hostname` et le `domain` restent de simples **attributs**. La collision clone est aussi évitée en pratique en installant l'agent **après** déploiement (GPO sur poste individualisé).

### 2.4 — Authentification : auto-enrôlement + token par poste

Enrôlement automatique (zéro validation manuelle) avec un **token unique par poste** — et non une clé partagée unique, dont la fuite permettrait d'usurper n'importe quel poste. Deux secrets distincts :

- un **secret d'enrôlement** partagé, déployé par GPO (registre ACL `SYSTEM` ou DPAPI), qui ne sert **qu'à** s'enregistrer ;
- un **token unique par poste**, émis automatiquement au premier contact.

Flux (*trust on first use*) :
1. Au 1er démarrage, l'agent **résout son identité** (SMBIOS UUID validé, sinon UUID agent persisté) et son empreinte, puis appelle `POST /enroll` avec l'en-tête `X-Enrollment-Secret`.
2. Le serveur valide le secret, crée le poste, génère un token aléatoire fort, en stocke **seulement le hash**, et renvoie le token **une seule fois**.
3. L'agent stocke le token chiffré (DPAPI) ; tous les appels suivants utilisent `Authorization: Bearer <token>`. Le secret d'enrôlement ne resservira plus.

Le secret partagé n'autorise que l'*enrôlement*, jamais le *contrôle* : une fuite permet au pire de créer de faux postes (bruit détectable), pas d'usurper un poste réel ni de lancer un scan. **Garde-fous** : auditer tout ré-enrôlement d'un `machine_uuid` connu (poste réinstallé vs vol de token) ; bouton de **révocation** de token côté console (force un ré-enrôlement). Implémenté dès **M1/M2**.

### 2.5 — TLS dès le départ via Caddy + AC interne

Le TLS est en place **dès le MVP** : un service **Caddy** en frontal (reverse-proxy) termine le TLS et sert backend + frontend. Pas de Traefik (utile surtout pour du routage dynamique multi-services).

Le certificat serveur est émis par l'**AC interne** (AD CS) pour le nom du serveur (ex. `tiai.natimai.local`). Les postes du domaine font **déjà confiance** à cette AC racine → aucun avertissement, et le client HTTP de Go sous Windows utilise le **magasin système** (validation sans config côté agent). À défaut d'AD CS : certificat auto-signé + racine poussée par GPO. Let's Encrypt seulement si le serveur a un nom DNS public (rare en interne).

### 2.6 — Accès à Defender via WMI

L'agent interroge directement **WMI** dans l'espace de noms `ROOT\Microsoft\Windows\Defender`, plutôt que de lancer un processus `powershell.exe` à chaque cycle (coûteux, fragile) :

| Donnée | Source WMI | Équivalent PowerShell |
|---|---|---|
| État (signatures, RTP, scans) | classe `MSFT_MpComputerStatus` | `Get-MpComputerStatus` |
| Historique des menaces | `MSFT_MpThreatDetection` / `MSFT_MpThreat` | `Get-MpThreatDetection` |
| Lancer un scan | méthode `Start` de `MSFT_MpScan` | `Start-MpScan -ScanType Quick/Full` |
| MAJ signatures | méthode `Update` de `MSFT_MpSignature` | `Update-MpSignature` |

En Go : `github.com/yusufpapurcu/wmi` (+ `go-ole`). Repli PowerShell pour les opérations non exposées en WMI.

### 2.7 — Déduplication des menaces

Chaque détection Defender porte un `DetectionID` unique. **Contrainte d'unicité `(machine_id, detection_id)`** en base + `INSERT ... ON CONFLICT DO NOTHING` (upsert) → aucun doublon, même si l'agent remonte plusieurs fois la même menace.

### 2.8 — Expiration des commandes

**Chaque commande porte un `expires_at`** ; passé ce délai, elle est marquée `expired` et n'est plus distribuée. Ainsi un portable éteint 3 semaines ne déclenche pas, à son retour, un scan demandé 20 jours plus tôt.

### 2.9 — Robustesse de l'agent

- File locale : si le serveur est injoignable, l'agent garde ses remontées et réessaie (back-off).
- Commandes idempotentes.
- **Signature de code** du binaire (détail en M6) : un certificat de **signature de code émis par l'AC interne**, distribué en *Éditeurs approuvés* par GPO, suffit pour un outil interne — inutile d'acheter un certificat public. Réduit les faux positifs Defender/SmartScreen et active le listage par publisher (AppLocker/WDAC).
- Compte de service : `LocalSystem` (droits admin nécessaires pour piloter Defender).

### 2.10 — Configuration : fichier **et** registre

Source principale : fichier `C:\ProgramData\Tiai\config.yaml`, **surchargé** par des clés de registre si présentes (GPO sait déployer les deux ; utile pour pousser un réglage ponctuel sans réécrire le fichier). La clé sensible passe par registre/DPAPI plutôt qu'en clair dans le YAML.

### 2.11 — Impact sur la stack

L'usage d'**ARQ implique Redis**. La stack docker-compose côté serveur devient donc : PostgreSQL + Redis + backend + worker + frontend + **Caddy** (reverse-proxy + TLS). **Les agents Windows ne sont pas dans Docker** (ils tournent sur les postes).

### 2.12 — Produit réutilisable (multi-parc) & TLS optionnel

L'outil doit pouvoir être **réutilisé sur d'autres parcs** : rien d'absolument spécifique au réseau Natimai dans le code. Tout ce qui est propre à un déploiement (nom de serveur, domaine, secret d'enrôlement, identifiants Mailgun, recipients) passe par la **configuration / variables d'environnement**, jamais en dur.

Le **TLS/les certificats ne sont pas une dépendance dure** de l'agent ni du backend :
- le **backend** parle HTTP en interne (le TLS est terminé par Caddy en frontal) ; il fonctionne sans certificat ;
- l'**agent** utilise le client HTTP de Go (magasin système) ; il peut viser une URL `http://` pour les tests, sans certificat ;
- pour un déploiement HTTPS **sans certificat fourni**, Caddy peut générer un certificat local auto-signé (`tls internal`) ; en prod on bascule sur le certificat de l'AC interne.

Objectif : on peut lever la stack et lancer l'agent **sans gérer de certificat** (dev/tests), puis activer le TLS « AC interne » en production par simple configuration.

### 2.13 — Tests

Le **backend** et le **frontend** font l'objet de tests, écrits **au fil de l'eau** sur les fonctionnalités existantes (pas reportés en fin de projet) :
- backend : `pytest` — tests unitaires sans base (sécurité/tokens, permissions, empreinte) + tests d'API sur base PostgreSQL de test (`TIAI_TEST_DATABASE_URL`, *skippés* sinon) ;
- frontend : `vitest` — services et composants.

### 2.14 — Contrat d'erreurs API (codes stables backend↔frontend)

Les erreurs API suivent un **contrat partagé** entre backend et frontend (comme dans `fastapi-ecommerce`), pour que les messages restent **alignés et localisables** sans dépendre du texte.

- **Enveloppe standardisée** : toute erreur renvoie `{"error": {"code", "message", "details"}}`.
- **`code` stable et namespacé**, machine-readable (ex. `auth.credentials.invalid`, `auth.token.revoked`, `machine.not_found`, `command.forbidden`, `internal.server_error`). C'est le **`code`** (jamais le texte) que le frontend mappe vers ses messages **i18n**.
- **Centralisé** : une exception applicative `AppError(code, status_code, message, details)` + des *exception handlers* enregistrés produisent l'enveloppe de façon uniforme ; les 500 **masquent les détails** hors environnement local.
- **Source unique des codes** : maintenir la liste des codes côté backend et la **refléter côté frontend** (table de correspondance code → message), pour éviter la divergence.

État actuel : **migré** ✅. Le backend lève des `AppError(code, status_code, message, details)` ([app/core/errors.py](backend/app/core/errors.py)) ; quatre handlers (AppError, validation 422, HTTPException framework, 500 masqué hors `local`) produisent l'enveloppe `{"error": {code, message, details}}`. Catalogue stable `ErrorCode` côté backend, reflété côté frontend ([frontend/src/services/errors.ts](frontend/src/services/errors.ts)) en table `code → message` (FR) consommée par les pages via `apiErrorMessage`. Reste : une vraie lib i18n (vue-i18n) si le multilingue devient nécessaire.

---

## 3. Architecture cible

```
   POSTES WINDOWS (hors Docker)                 SERVEUR (docker compose)
 ┌───────────────────────────┐         ┌─────────────────────────────────────┐
 │  Agent Tiai (Go)        │  HTTPS  │  Caddy : reverse-proxy + TLS         │
 │  • Service Windows        │ ──────► │            │                        │
 │  • lit WMI Defender       │ ◄────── │     ┌──────┴──────┐                  │
 │  • poll heartbeat         │ cmds    │     │  Backend    │  FastAPI         │
 │  • exécute scans/update   │         │     │  (uvicorn)  │                  │
 └───────────────────────────┘         │     └──┬───────┬──┘                  │
            ▲                           │        │       │                    │
            │ déploiement GPO           │   ┌────┴───┐ ┌─┴──────┐             │
            │ (MSI/EXE + config)        │   │Postgres│ │ Redis  │             │
            └───────────────────────────┘   └────────┘ └───┬────┘             │
                                            │      ┌────────┴────────┐         │
                                            │      │ Worker (ARQ)    │         │
                                            │      │ nettoyage+alerts│         │
                                            │      └─────────────────┘         │
                                            │  ┌──────────────┐                │
                                            │  │ Frontend     │ Quasar/Vue     │
                                            │  └──────────────┘                │
                                            └─────────────────────────────────┘
```

**Services docker-compose (côté serveur)**

| Service | Rôle |
|---|---|
| `caddy` | Reverse-proxy + **terminaison TLS** (certificat AC interne) ; route le backend et sert le build Quasar |
| `backend` | API FastAPI (uvicorn/gunicorn) |
| `worker` | Tâches ARQ (nettoyage postes inactifs, envoi d'alertes) |
| `db` | PostgreSQL (volume persistant) |
| `redis` | File ARQ + cache léger |
| `frontend` | Build Quasar statique servi par nginx |

---

## 4. Modèle de données (esquisse)

```text
machines
  id                uuid    PK (généré serveur)
  machine_uuid      text    UNIQUE   -- identité stable (SMBIOS UUID validé, sinon UUID agent)
  -- empreinte (composants séparés, non hashés) pour détecter clone/altération
  machine_guid      text             -- MachineGuid Windows (dupliqué sur clones sans Sysprep)
  smbios_uuid       text             -- Win32_ComputerSystemProduct.UUID (ancre)
  tpm_ek_hash       text             -- hash de l'EK TPM 2.0, si présent
  needs_verification bool            -- empreinte divergente → à vérifier (admin)
  hostname          text             -- attribut, peut changer
  domain            text
  ip_address        text             -- adresse principale élue par l'agent (NULL = jamais remontée)
  os_version        text
  agent_version     text
  -- état Defender (dérivé de MSFT_MpComputerStatus)
  rtp_enabled              bool
  av_enabled               bool
  signature_version        text
  signature_last_updated   timestamptz
  signature_age_days       int
  last_quick_scan          timestamptz
  last_full_scan           timestamptz
  running_mode             text       -- AMRunningMode : Normal / Passive / SxS Passive Mode / EDR Block Mode
  is_up_to_date            bool       -- calculé (Defender à jour OU antivirus tiers actif)
  -- antivirus enregistré au Security Center (root\SecurityCenter2) : seule source
  -- qui voie un produit tiers. NULL = jamais remonté (agent ancien, SKU Serveur) ;
  -- '' = registre lu et vide, donc aucun antivirus installé — un constat, pas un trou
  av_product_name                  text
  av_product_enabled               bool
  av_product_signatures_up_to_date bool
  av_product_is_defender           bool   -- tranché par l'agent (instanceGuid), pas par nom côté serveur
  -- session ouverte (API WTS, rafraîchie à chaque heartbeat)
  session_user_present     bool       -- NULL = jamais remonté ≠ false = personne
  session_username         text       -- NULL si la remontée du nom est coupée (GPO)
  session_state            text       -- active / disconnected
  session_is_remote        bool       -- session Bureau à distance
  first_seen        timestamptz
  last_seen         timestamptz       -- = date de dernière connexion (UI)
  created_at, updated_at timestamptz
  INDEX (hostname), (domain), (last_seen), (is_up_to_date), (needs_verification), (smbios_uuid)

threats
  id              bigserial PK
  machine_id      uuid    FK → machines.id
  detection_id    text             -- identifiant unique Defender
  threat_name     text
  severity        text
  category        text
  status          text             -- active / quarantined / removed / allowed
  action_taken    text
  detected_at     timestamptz
  raw             jsonb
  UNIQUE (machine_id, detection_id)   -- déduplication
  INDEX (machine_id), (detected_at), (status)

commands               -- file de commandes (une ligne par poste, même en broadcast)
  id              uuid    PK
  machine_id      uuid    FK → machines.id
  type            text             -- quick_scan / full_scan / update_signatures
  status          text             -- pending / delivered / running / succeeded / failed / expired
  created_by      text
  created_at      timestamptz
  expires_at      timestamptz
  delivered_at    timestamptz
  started_at, finished_at timestamptz
  result_output   text
  error           text
  INDEX (machine_id, status), (expires_at)
```

> Toujours stocker en **UTC (`timestamptz`)**. Le « scan demandé sur tous les postes » crée N lignes `commands` en une insertion groupée.

---

## 5. Contrat d'API (esquisse)

**Côté agent** (auth : secret d'enrôlement pour `/enroll`, puis `Authorization: Bearer <token-poste>`)

| Méthode | Endpoint | Rôle |
|---|---|---|
| `POST` | `/api/v1/agent/enroll` | 1er contact, en-tête `X-Enrollment-Secret` : `machine_uuid`, `hostname`, `domain`, `os`, `agent_version` → **renvoie le token unique du poste** (une seule fois). Idempotent. |
| `POST` | `/api/v1/agent/heartbeat` | Remonte l'état Defender + menaces + la session ouverte (bloc `session` optionnel : `user_present`, `username` selon la politique de confidentialité, `state`, `is_remote`) + `ip_address` (attribut optionnel, adresse déjà élue par l'agent ; une valeur non analysable est ignorée, pas rejetée) + l'antivirus enregistré (bloc `av_product` optionnel : `name`, `enabled`, `signatures_up_to_date`, `is_defender` ; bloc absent = l'agent n'a pas pu lire, `name` vide = aucun antivirus). **Renvoie les commandes en attente.** |
| `POST` | `/api/v1/agent/commands/{id}/result` | Résultat d'exécution d'une commande. |

**Côté console** (auth : **JWT utilisateur**, email + mot de passe — sauf les deux routes `password-reset/*`, publiques par nature ; les routes `admin` exigent le rôle admin)

| Méthode | Endpoint | Rôle |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Email + mot de passe (OAuth2 password) → JWT. |
| `GET` | `/api/v1/auth/me` | Utilisateur courant. |
| `POST` | `/api/v1/auth/password` | Changement de son propre mot de passe (preuve : mot de passe actuel). Ferme les autres sessions. |
| `POST` | `/api/v1/auth/password-reset/request` | **Public.** Envoie un lien de réinitialisation par e-mail (Mailgun). Répond 204 quoi qu'il arrive (anti-énumération). |
| `POST` | `/api/v1/auth/password-reset/confirm` | **Public.** Consomme le jeton (usage unique, expirant) et définit le nouveau mot de passe. |
| `GET` | `/api/v1/machines?search=&domain=&antivirus=&status=&page=` | Liste filtrable/paginée (`search` couvre hostname / UUID / IP / nom d'antivirus ; `antivirus` filtre par sous-chaîne). |
| `GET` | `/api/v1/machines/antivirus-products` | Antivirus présents dans le parc + nombre de postes (alimente le filtre de la console ; déclarée **avant** `/{id}`, sinon interprétée comme un id). |
| `GET` | `/api/v1/machines/{id}` | Détail d'un poste + menaces. |
| `GET` | `/api/v1/machines/{id}/duplicates` | Doublons candidats (même ancre SMBIOS, cf. §8). |
| `POST` | `/api/v1/machines/{id}/revoke-token` | *Admin.* Kill-switch : révoque le token du poste (ré-enrôlement requis). |
| `POST` | `/api/v1/machines/{id}/merge` | *Admin.* Fusionne un doublon dans ce poste (menaces et commandes rattachées). |
| `GET` | `/api/v1/stats/overview` | KPIs dashboard. |
| `GET` | `/api/v1/threats?...` | Menaces actives du parc. |
| `POST`| `/api/v1/commands` | Crée une/des commande(s) : cible (ids ou filtre) + type. |
| `GET` | `/api/v1/commands?status=` | Suivi des commandes. |
| `GET` | `/api/v1/users?search=&page=` | *Admin.* Liste des comptes console. |
| `POST` | `/api/v1/users` | *Admin.* Création d'un compte (mot de passe transmis hors bande). |
| `GET` | `/api/v1/users/{id}` | *Admin.* Détail d'un compte. |
| `PATCH` | `/api/v1/users/{id}` | *Admin.* E-mail, nom, rôle, activation. Refusé sur son propre compte pour rôle/désactivation → il reste toujours ≥ 1 admin. |
| `DELETE` | `/api/v1/users/{id}` | *Admin.* Suppression définitive (préférer la désactivation). Refusé sur son propre compte. |
| `POST` | `/api/v1/users/{id}/reset-password` | *Admin.* Nouveau mot de passe (fourni ou généré), renvoyé une seule fois. Ferme les sessions du compte. |

> Fusionner *heartbeat* et *récupération de commandes* en **un seul appel** divise par deux le trafic agent.

---

## 6. Plan par étapes (jalons)

> Estimations indicatives en jours-homme pour **un développeur expérimenté**, à ajuster selon l'équipe. La priorité est de sortir une **tranche verticale fonctionnelle** au plus vite (M1) pour valider le contrat agent↔serveur avant d'épaissir chaque couche.

### M0 — Fondations *(2–3 j)*
- Mono-repo : `/agent` (Go), `/backend` (FastAPI), `/frontend` (Quasar), `/deploy` (compose, **Caddyfile**).
- `docker-compose` squelette : db + redis + backend + frontend + **caddy** qui démarrent, **HTTPS dès le départ** (Caddy + certificat de l'AC interne).
- Migrations de schéma (Alembic) avec les 3 tables.
- Préparer en amont le **certificat de signature de code** (modèle « Code Signing » sur l'AC interne) pour la chaîne de build.
- Conventions : logs structurés, `/health`, versionnement d'API (`/api/v1`).
- **DoD** : `docker compose up` lève la stack en **HTTPS**, `/health` répond, migrations OK.

### M1 — Tranche verticale minimale *(3–5 j)* 🎯
- Agent Go : service Windows minimal, lit `MSFT_MpComputerStatus` via WMI, envoie un heartbeat **en HTTPS**.
- Backend : `enroll` (valide le secret d'enrôlement, **émet le token par poste**) + `heartbeat` (upsert machine, met à jour `last_seen`, auth par token).
- Agent : stockage **chiffré du token** (DPAPI), réutilisé aux appels suivants.
- Frontend : une page listant les postes connus avec leur `last_seen`.
- **DoD** : un poste réel s'auto-enrôle, apparaît dans l'UI et son état se rafraîchit, le tout en HTTPS.

### M2 — Agent Defender complet *(5–8 j)*
- Lecture complète de l'état (signatures, RTP, dates de scans) + remontée des menaces (`MSFT_MpThreatDetection`) avec `detection_id`.
- Récupération + exécution des commandes : `quick_scan`, `full_scan`, `update_signatures`.
- Remontée du résultat d'exécution.
- Config YAML + surcharge registre ; identité stable (`MachineGuid`).
- File locale + back-off si serveur injoignable.
- **DoD** : depuis un appel API, on déclenche un scan/MAJ sur un poste réel et le résultat remonte.

### M3 — Backend complet *(5–7 j)*
- Déduplication menaces (contrainte + upsert).
- File de commandes : création unitaire et **groupée** (« tous » / par filtre), `expires_at`, transitions d'état.
- Endpoints stats (`/stats/overview`) : total parc, à jour / non à jour, postes avec menaces, postes inactifs depuis X.
- Recherche/filtrage `/machines` (nom, domaine, statut), pagination.
- Garde-fou de ré-enrôlement (`machine_uuid` déjà connu → signalé) + **révocation de token** (kill-switch) côté API.
- Réglage du pool asyncpg pour la charge.
- **DoD** : KPIs cohérents, recherche fonctionnelle, commande de masse distribuée correctement.

### M4 — Console (Frontend) *(6–9 j)*
- Dashboard : cartes KPI + liste d'alertes (postes non à jour, menaces actives).
- Recherche/filtres (nom, domaine, statut, inactivité).
- Vue détail poste : état Defender, historique menaces, dernières commandes.
- Sélection multiple → actions de masse (scan rapide/complet, MAJ) avec suivi du statut des commandes.
- **DoD** : un admin pilote tout le cycle depuis l'UI sans toucher à l'API.

### M5 — Durcissement *(4–6 j)*
- *(TLS et token par poste sont déjà en place depuis M0–M1.)*
- Authentification de la console (login admin / JWT) + **journal d'audit** (qui a lancé quel scan).
- **ARQ** : job de nettoyage (postes inactifs depuis X mois → archivage/suppression) + notification des alertes **par e-mail (API Mailgun)**.
- Rotation des tokens + limitation de débit côté API.
- **DoD** : console authentifiée, alertes envoyées automatiquement, actions tracées.

### M6 — Packaging, signature & déploiement GPO *(3–5 j)*
- Build de l'agent en **MSI** (ou EXE + script d'installation de service).
- **Signature du binaire et du MSI** dans le pipeline, avec le certificat de signature de l'AC interne :
  `signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 agent.exe`
  (`/tr` + `/td` = horodatage RFC 3161 : la signature survit à l'expiration du certificat).
- **GPO** : distribuer le certificat de signature dans le magasin *Éditeurs approuvés* des postes ; déployer le paquet + la configuration (fichier/registre) ; pousser la racine de l'AC interne si nécessaire.
- Documentation d'exploitation (mise à jour de l'agent, désinstallation, dépannage).
- **DoD** : agent signé déployé et reconnu de confiance sur un OU pilote.

➡️ **Fin de la Phase 1 (Defender).** Les jalons suivants relèvent de la fin d'année.

### Phase 2 — Windows Update *(fin d'année)* · 🟢 implémentée
Cadrée et livrée : cf. `plan-phase2-windows-update.md`. Réutilise l'agent et la file de commandes — quatre nouveaux types (`wu_scan`, `wu_install`, `wu_install_full`, `reboot`) et un bloc `windows_update` optionnel sur le heartbeat. **Jamais d'auto-redémarrage** : le poste signale qu'il en attend un, la commande est déclenchée à part. L'historique des KB installés et les fenêtres de maintenance restent hors périmètre de cette itération (§4 du plan de phase : le design les absorbe sans refonte).

### Phase 3 — Déploiement logiciel + inventaire *(fin d'année)*
- Inventaire : remontée matériel/logiciel (réutilise heartbeat avec un nouveau bloc de données).
- Déploiement : nouveau type de commande « installer un paquet » + dépôt de paquets (à concevoir : stockage, intégrité, versions).

---

## Suivi d'avancement

> Coché = fait. Mis à jour au fil du travail.

**Instantané — 2026-06-26** · Phase 1 (Defender). Agent Defender complet (M2) implémenté : WMI (état + menaces), PowerShell (scans/MAJ), identité réelle (SMBIOS/MachineGuid), DPAPI, service Windows, file locale + back-off. Validé sur poste réel (identité/WMI/sysinfo) ; reste la boucle end-to-end API→scan→résultat contre un serveur déployé. Tests Go de logique pure + builds Windows/Linux verts.
> Backend complet (M3) implémenté : broadcast de commandes par filtre + suivi + expiration, stats `/overview`, recherche/filtrage `/machines`, listing `/threats`, révocation de token, calcul `is_up_to_date`, pool DB configurable. 34 tests backend verts sur Postgres (ruff + mypy OK).
> Console (M4) implémentée : login JWT (store Pinia + interceptor + guard), dashboard KPI/alertes, filtres postes, vue détail (état Defender + menaces + commandes), actions de masse, révocation. Typecheck + build SPA OK, 18 tests vitest (couverture 100 % services).
> Contrat d'erreurs (§2.14) **migré** : `AppError` + handlers (enveloppe stable), catalogue `ErrorCode` reflété côté frontend (`errors.ts`) et consommé par les pages.
> Fusion de postes (§8) **implémentée** : merge backend (rattachement menaces/commandes + dédup + suppression du doublon) + découverte des doublons par SMBIOS + dialog UI. **46 tests backend** (dont 8 de contrat + 4 de fusion) + **20 vitest** (couverture 100 % services) verts ; ruff/mypy/typecheck/build SPA OK. Phase 1 backend + console fonctionnellement complètes ; reste M6 (packaging/GPO) et la validation end-to-end sur stack déployée.

**Instantané — 2026-07-08** · Durcissement (M5, tranche 1) : garde de démarrage refusant les secrets placeholder hors `local` (validator `Settings`, testé), comparaison timing-safe du secret d'enrôlement, en-têtes de sécurité HTTP au reverse-proxy (HSTS, CSP, nosniff, frame-ancestors). CI étendue : job agent Go (gofmt + vet + tests + build croisé Windows), typecheck `vue-tsc` frontend, action de couverture épinglée par SHA. **Bugfix heartbeat** : la livraison de commandes levait `MissingGreenlet` (accès aux ORM expirés après `commit`) → réponse construite avant le commit ; suite complète verte sur Postgres (**83 tests**).
> **`docker compose up` validé de bout en bout** (override dev `docker-compose.dev.yml` : backend HTTP direct :8800 + Caddy `tls internal`) : migrations + seed admin au boot, en-têtes/CSP vérifiés sur la SPA (aucun script inline, `script-src 'self'` compatible), cycle complet login → enroll (401 sans/mauvais secret) → heartbeat → commande → résultat → vues console (11 vérifications). Corrigé au passage : **Dockerfile frontend** (le `postinstall: quasar prepare` cassait `npm install` avant la copie des sources → `npm ci --ignore-scripts` + `quasar prepare` post-copie + `.dockerignore`).

**Instantané — 2026-08-17** · **Session utilisateur** livrée de bout en bout (cf. `plan-session-utilisateur.md`) : la console indique si un poste est occupé, dans la liste et sur la fiche détail. Agent : nouveau collecteur WTS (`collector/session*.go`), élection d'une session parmi plusieurs, bloc `session` optionnel sur le heartbeat. Backend : quatre colonnes nullables sur `machines` (migration `0005_session`), patch conditionnel comme le bloc Defender — un heartbeat sans le bloc n'écrase rien, un `user_present:false` efface le nom. `session_user_present` est **tri-état** (`NULL` = jamais remonté), ce qui permet de distinguer « nom masqué par politique » de « agent trop ancien ».
> **Confidentialité par construction** : la remontée du nom est désactivable par GPO et agit **à la source** — le nom est lu localement pour distinguer une session utilisateur de l'écran de connexion, puis abandonné avant sérialisation. Jamais journalisé. Test dédié côté agent (`reportUsername=false` → présence conservée, nom vide) et côté backend (déconnexion → nom effacé).
> Vérifications : **119 tests backend** verts sur Postgres (98 % de couverture) + migration `upgrade`/`downgrade`/`upgrade` rejouée sur base vierge (les migrations n'étant pas exercées par pytest) ; **41 vitest** (100 % sur `src/services` + `src/utils`) ; Go `gofmt`/`vet`/`test` verts, builds croisés `windows/amd64` et `windows/arm64`, binaires de test compilés pour la cible Linux de la CI. **Plomberie Win32 validée sur poste réel** : deux sessions détectées (une active en console, une déconnectée), élection correcte, nom bien supprimé quand l'option est coupée.

**Instantané — 2026-08-17 (2)** · **Adresse IP du poste** livrée de bout en bout, sans ouvrir le chantier inventaire : un attribut, une colonne, pas de table d'interfaces réseau. Agent : collecteur `collector/network*.go` sur `GetAdaptersAddresses`, relu à chaque heartbeat (une adresse mise en cache au démarrage serait fausse au premier renouvellement de bail). Backend : colonne `ip_address` (migration `0006_ip_address`), patch conditionnel comme `hostname` — champ absent = adresse conservée, ce qui couvre l'agent trop ancien comme la lecture ratée. Une valeur non analysable est **ignorée**, jamais renvoyée en 422 : un champ malformé ne doit pas coûter l'état Defender et les menaces du même heartbeat.
> **Le cas « plusieurs adresses » est la règle, pas l'exception** — un portable sur station d'accueil, un poste avec Hyper-V/WSL, un VPN monté. L'élection est donc explicite et ordonnée : IPv4 avant IPv6, adaptateur avec passerelle par défaut avant adaptateur sans (c'est ce qui écarte `vEthernet`/VirtualBox **sans** filtrer sur le nom des cartes), puis métrique d'interface la plus basse (l'ordre de routage de Windows lui-même), puis index d'interface — un départage arbitraire mais *stable*, pour que l'adresse affichée ne clignote pas d'un poll à l'autre. Exclus d'office : loopback, 169.254.0.0/16 (APIPA = bail DHCP échoué, ne joint rien), fe80::/10, adaptateurs non `IfOperStatusUp` et pseudo-interfaces tunnel.
> Vérifications : **126 tests backend** verts sur Postgres 16 + migration `upgrade`/`downgrade`/`upgrade` rejouée sur base vierge ; 41 vitest, `vue-tsc` et `prettier` verts ; Go `gofmt`/`vet`/`test` verts, builds croisés `windows/amd64` et `windows/arm64`, binaire de test compilé pour la cible Linux de la CI. **Plomberie Win32 validée sur poste réel** : 5 adresses APIPA sur cartes déconnectées, 2 commutateurs Hyper-V adressés mais sans passerelle, 1 Wi-Fi — c'est bien le Wi-Fi qui est élu.

**Instantané — 2026-08-17 (3)** · **Antivirus tiers** visible de bout en bout, en lecture seule. Les classes Defender ne décrivent que Defender : un poste sous ESET ou Bitdefender y lit « antivirus éteint » et nulle part « protégé ». L'agent lit donc aussi le **Security Center** (`root\SecurityCenter2`, `AntiVirusProduct`), où tout antivirus doit s'enregistrer pour que Windows cesse d'alerter — nom affiché + deux bits de `productState`. Ni version de signatures, ni date, ni déclenchement de mise à jour n'y sont exposés : le périmètre s'arrête donc là, et les commandes restent spécifiques à Defender. Backend : quatre colonnes + `running_mode` (migration `0007_av_product`), filtre `antivirus`, `av_product_name` ajouté à la recherche libre, et `GET /machines/antivirus-products` (valeurs distinctes + compte) qui alimente le sélecteur de la console et sert d'inventaire d'un parc mixte.
> **`is_up_to_date` gagne une seconde voie**, et ce n'est pas une complaisance : installer un antivirus tiers met Defender en mode passif, ce qui met `av_enabled`/`rtp_enabled` à faux — sans cette voie, *tout* poste sous antivirus tiers comptait comme non protégé à vie et les KPI du dashboard étaient faux par construction. Elle est volontairement plus faible que la voie Defender (aucune date derrière elle) : un antivirus tiers **actif** dont la fraîcheur est *inconnue* qualifie, un « périmé » explicite non. L'entrée de Defender dans ce registre est ignorée — ses propres colonnes disent la même chose avec de vraies dates. Recalcul déclenché dès que **l'un** des deux blocs bouge : une désinstallation d'antivirus change l'état sans que le bloc Defender change.
> **Trois états, pas deux** : bloc omis = l'agent n'a pas pu lire (état **permanent** sur un SKU Serveur, qui n'a pas de Security Center — d'où l'échec journalisé une seule fois puis rétrogradé en DEBUG) ; nom vide = registre lu et vide, donc aucun antivirus, ce qui est un constat à afficher ; un nom = le produit élu. Élection explicite quand plusieurs coexistent (le cas normal : Defender reste inscrit à côté du tiers) : actif > état illisible > arrêté, puis tiers avant Defender, puis nom — départage stable. `productState` n'étant documenté nulle part, le décodage ne traduit que les valeurs observées et remonte le reste comme inconnu.
> **Bug attrapé par ses propres tests** : le repli d'identification de Defender par le nom matchait « defender » — que « Bit**defender** » contient. Resserré sur les noms qualifiés Microsoft, avec le cas en test.
> Vérifications : **143 tests backend** verts sur Postgres 16 + migration `upgrade`/`downgrade`/`upgrade` rejouée sur base vierge ; **54 vitest** (100 % sur `src/services` + `src/utils`), `vue-tsc`, `prettier` et build SPA verts ; Go `gofmt`/`vet`/`test` verts, builds croisés `windows/amd64` et `windows/arm64`. **Reste à valider sur poste réel** avec un antivirus tiers installé (décodage de `productState` et `AMRunningMode` en conditions).

**Instantané — 2026-08-17 (4)** · **Commandes de maintenance à distance** livrées (cf. `plan-commandes-distantes.md`) : onze nouveaux types de commandes — `gpo_update`, `flush_dns`, `time_resync`, `cert_pulse`, `spooler_reset`, `sfc_scan`, `dism_restore_health`, `dism_component_cleanup`, `chkdsk_scan` + deux diagnostics `gpo_report` / `net_config`. Le backend n'a coûté qu'une extension d'énumération (`type` stocké en `str` nu ⇒ **aucune migration**) : c'est la récompense de la file de commandes de M3.
> **Le catalogue est le modèle de sécurité.** Le serveur n'envoie qu'un identifiant de type ; **aucun argument ne traverse le réseau**. L'exécutable et ses arguments fixes vivent dans une table du binaire de l'agent, donc un serveur compromis ne peut déclencher que ces onze actions, jamais du code arbitraire. Deux corollaires appliqués : chaque exécutable est résolu en **chemin absolu sous `System32`** et jamais via le `PATH` (l'agent est `LocalSystem` : un répertoire inscriptible en tête de `PATH` serait une exécution SYSTEM offerte), et l'endpoint de résultat n'accepte plus que `running` / `succeeded` / `failed` — un agent qui pouvait poster `pending` ou `expired` réécrivait la file qu'il est seulement censé vider.
> **Statut intermédiaire `running` câblé** (brique partagée avec la Phase 2, spécifiée à son J1 et implémentée ici) : les quatre commandes longues l'annoncent avant de démarrer, le serveur écrit `started_at` **sans clore** la commande, et refuse un `running` arrivé après un verdict. Sans lui la console afficherait « transmise » pendant vingt minutes de `sfc`.
> **Le piège du chantier était l'encodage, et il n'y a pas *une* réponse mais quatre** — mesurées sur poste réel, pas supposées : `ipconfig`/`w32tm` écrivent en **OEM** (CP850), `certutil` en **ANSI** (CP1252), `gpresult`/`dism` en **UTF-8**, `sfc` en **UTF-16LE** entrelacé de nuls. Ce n'est pas la page de codes de la console : `GetConsoleOutputCP()` répondait 65001 pendant qu'`ipconfig` émettait du CP850 — ce qui compte est que la sortie soit *redirigée*, et en service il n'y a de toute façon aucune console. L'UTF-8 s'auto-identifie (une lettre accentuée CP850 ou CP1252 isolée n'est jamais une séquence multi-octets valide), ce qui limite la table par outil aux deux cas restants. La progression de `dism`/`sfc` est réduite en rejouant les retours chariot comme le ferait une console — indépendant de la langue, là où filtrer sur « % » ne l'est pas.
> **Console** : les deux tableaux d'actions dupliqués (page détail / actions de masse) sont **factorisés** en un catalogue unique `commandActions` (libellé, icône, groupe, confirmation, éligibilité au masse) — la factorisation prévue au J4 de la Phase 2 est donc faite. Menu en sections (Defender / Maintenance / Diagnostic), confirmation `$q.dialog` avec le **nombre de postes** pour les actions coûteuses, et **dialog « Résultat »** (bouton loupe + copie) sans lequel `gpo_report` et `net_config` n'auraient aucune valeur. Les deux diagnostics restent hors actions de masse : leur intérêt est la lecture d'un poste, en masse ils ne produisent que du bruit.
> Vérifications : **160 tests backend** verts sur Postgres 16 ; Go `gofmt`/`vet`/`test` verts (30 tests collector), builds croisés `windows/amd64` et `windows/arm64` ; **63 vitest** (100 % sur `src/services` + `src/utils`), `vue-tsc`, `prettier` et build SPA verts. **Boucle end-to-end validée sur poste réel** (backend local + agent réel) : enrôlement, livraison au heartbeat, exécution, résultat en base — `net_config` et `flush_dns` en succès avec accents corrects vérifiés directement en base, `gpo_report`/`time_resync`/`dism` en échec « accès refusé » lisible et actionnable (agent lancé sans élévation), `started_at` renseigné par le `running` d'une commande longue. **Reste à valider en `LocalSystem`** : les chemins nominaux des huit commandes qui exigent l'élévation, `sfc_scan` en tête — c'est la dernière branche d'encodage du catalogue à n'avoir jamais vu d'octets réels, et la mesure est précisément ce qui a démenti le plan pour les trois autres.

**Instantané — 2026-08-17 (5)** · **Phase 2 — Windows Update** livrée de bout en bout (cf. `plan-phase2-windows-update.md`) : la console dit ce que chaque poste a en attente, et sait le lui faire installer. Quatre nouveaux types de commandes — `wu_scan`, `wu_install` (logicielles seules), `wu_install_full` (pilotes compris), `reboot` — plus un bloc `windows_update` optionnel sur le heartbeat, sur le modèle exact du bloc `defender`. L'agent passe par l'**API COM WUA** (`Microsoft.Update.Session`) pilotée en PowerShell et lue en JSON : PSWindowsUpdate est écarté car il n'est pas livré avec Windows, et un agent déployé par GPO ne peut ni supposer sa présence ni se mettre à l'installer.
> **Le bloc a son propre rythme, et c'est la décision structurante.** Une recherche WU prend des minutes (13 s mesurées sur un poste à jour, bien davantage sur un poste en retard) : elle ne peut donc pas vivre dans le heartbeat de 60 s. Goroutine dédiée, première collecte ~2 min après le démarrage puis toutes les **6 h** (`wu_collect_interval_seconds`), résultat mis en cache, et bloc attaché **seulement si le serveur ne l'a pas déjà accusé** — sinon trente mises à jour avec leurs titres repartiraient toutes les minutes sans rien apprendre à personne. Le suivi se fait par **compteur de génération** et non par un booléen : une collecte qui se termine *pendant* qu'un heartbeat est en vol ne doit pas être enterrée par l'acquittement de ce heartbeat, sinon la lecture fraîche attendrait six heures. Vérifié sur la stack réelle : **18 heartbeats, 2 écritures**.
> **Sémantique de remplacement, à l'inverse des menaces.** Une menace est un fait historique et s'accumule ; une mise à jour en attente est un *état courant* — installée, elle disparaît du rapport de l'agent et doit disparaître de la base, ou la console proposerait d'installer un KB déjà en place. `replace_pending` fait donc un upsert du set reçu puis un `DELETE` de ce qui a disparu. Seul `first_seen` survit à la mise à jour d'une ligne : c'est lui qui répond à « depuis combien de temps ce poste traîne-t-il ce correctif ». La révision WUA fait partie de la clé, Microsoft révisant une mise à jour **sans changer son `UpdateID`**.
> **Jamais d'auto-redémarrage.** Une mise à jour qui en réclame un le signale, point. `reboot` est une commande à part, avec confirmation en console, `shutdown /r /t 60` et un message à l'utilisateur connecté — le délai de 60 s sert deux fois : il laisse enregistrer son travail, et il laisse à l'agent le temps de poster le résultat avant que la machine ne tombe (la file locale le rejoue si le POST échoue quand même). Deux types d'installation plutôt qu'un drapeau : le protocole ne transporte **qu'un nom de type**, jamais d'argument, et le filtre pilotes vit dans le critère de recherche WUA (`Type='Software'`) plutôt que dans une boucle après coup.
> **Deux bugs attrapés par leurs propres tests, tous deux sur le chemin nominal.** (1) Les apostrophes de `Type='Software'` refermaient le littéral PowerShell : le script ne se *parsait pas du tout*, sur la variante sans pilotes — celle de `wu_install`. Trouvé par un test qui fait parser les deux scripts par le parseur de PowerShell lui-même, ajouté précisément parce que la branche d'installation ne peut pas être exercée sans patcher une machine. (2) Une extension de pilote de quelques kilo-octets s'affichait « 0 Mio » à côté d'une icône de téléchargement ; la conversion plancher désormais à 0,1.
> **Statut `running` réutilisé tel quel** : la brique avait été câblée avec les commandes de maintenance (spécifiée au J1 de cette phase, implémentée là-bas), les deux installations s'y branchent sans une ligne de backend. Même récompense côté types : `type` étant stocké en `str` nu, les quatre nouvelles commandes n'ont coûté **aucune migration**.
> `telemetry_interval_seconds` est **supprimé** : la clé n'était lue par aucun code depuis l'origine. Le « cycle lent » qu'elle annonçait existe désormais pour de bon sous le nom `wu_collect_interval_seconds` — avec un défaut de 6 h et non de 15 min, parce qu'une recherche WU interroge le serveur WSUS.
> Vérifications : **178 tests backend** verts sur Postgres 16 (98 % de couverture) + migration `0008_windows_update` rejouée `upgrade`/`downgrade`/`upgrade` sur base vierge (`alembic check` ne signale que la dérive `password_reset_tokens` préexistante) ; Go `gofmt`/`vet`/`test` verts (27 tests Go ajoutés : 21 collector, 5 agent, 1 config), builds croisés `windows/amd64`, `windows/arm64` et `linux` ; **76 vitest** (99,5 % sur `src/services` + `src/utils`), `vue-tsc` et `prettier` verts. **Boucle complète validée sur poste réel contre la stack `docker compose` dev** : agent réel enrôlé → `wu_scan` depuis l'API console → 19 mises à jour remontées en 13 s (accents intacts jusqu'en base), colonnes machine et table `windows_updates` renseignées, dates `LastSearchSuccessDate`/`LastInstallationSuccessDate` lues, pilotes correctement typés, puis cycle de fond à 2 min confirmant l'upsert en place (`first_seen` conservé, `last_seen` avancé). **Reste à valider sur poste réel** : une installation effective (`wu_install*`) et un `reboot` — les deux seules branches qu'on ne peut pas exercer sans patcher ou redémarrer une machine.

| Jalon | État |
|---|---|
| M0 Fondations | 🟢 fini (compose validé de bout en bout) — reste le certificat de signature |
| M1 Tranche verticale | 🟢 agent fonctionnel (service Windows, WMI `MSFT_MpComputerStatus`, token DPAPI) ; reste validation end-to-end sur serveur déployé |
| M2 Agent Defender complet | 🟢 implémenté (état + menaces WMI, scans/MAJ PowerShell, config YAML/registre, file locale/back-off) ; reste DoD end-to-end sur poste réel |
| M3 Backend complet | 🟢 commandes (broadcast par filtre + suivi + expiration), stats `/overview`, recherche/filtrage `/machines`, listing `/threats`, révocation de token, `is_up_to_date` calculé, pool DB configurable ; tests verts sur Postgres |
| M4 Console | 🟢 login JWT + dashboard KPI/alertes + filtres + détail poste + actions de masse + révocation + fusion de postes + catalogue d'actions factorisé (sections + confirmations + dialog Résultat) |
| Commandes de maintenance | 🟢 catalogue fermé de 11 commandes (maintenance + diagnostic) de bout en bout : types backend, exécution agent, console ; statut `running` câblé. Reste la validation en `LocalSystem` des huit commandes exigeant l'élévation (cf. `plan-commandes-distantes.md` §5) |
| Phase 2 Windows Update | 🟢 état WU remonté (MAJ en attente, redémarrage requis, dates) + 4 commandes de bout en bout : cycle lent dédié côté agent, table `windows_updates` à sémantique de remplacement, carte + tableau + KPI côté console. Reste la validation sur poste réel d'une installation effective et d'un redémarrage |
| M5 Durcissement | 🟡 JWT + rôles, provider Mailgun, garde secrets prod, timing-safe enroll, en-têtes sécurité ; reste audit, jobs ARQ branchés, rotation, rate-limit |
| M6 Packaging & GPO | ⬜ à faire |
| Transverse | 🟢 tests backend/frontend + ruff + mypy + CI (tous verts) |

**M0 — Fondations**
- [x] Mono-repo `/agent` `/backend` `/frontend` `/deploy`
- [x] Squelette `docker-compose` (db, redis, backend, worker, frontend, caddy)
- [x] Migrations Alembic (machines, threats, commands + users + empreinte)
- [x] Caddy + TLS (Caddyfile ; `tls internal` possible pour dev)
- [x] `/health` + versionnement `/api/v1`
- [x] `docker compose up` validé de bout en bout (2026-07-08, override dev : HTTP direct + `tls internal` ; cycle enroll → heartbeat → commande → résultat vérifié)
- [ ] Certificat de signature de code préparé (chaîne de build)

**M1 — Tranche verticale**
- [x] Backend `enroll` (valide le secret, émet le token par poste)
- [x] Backend `heartbeat` (upsert machine, `last_seen`, auth token, renvoi des commandes)
- [x] Résolution d'identité (SMBIOS UUID validé / repli UUID agent) + empreinte
- [x] Agent : boucle de polling + client HTTP (squelette buildable)
- [x] Frontend : page liste des postes
- [x] Agent : service Windows + lecture WMI `MSFT_MpComputerStatus`
- [x] Agent : stockage chiffré du token (DPAPI)

**M2 — Agent Defender complet** · 🟢 implémenté (DoD end-to-end à valider sur serveur déployé)
- [x] Lecture complète état (WMI `MSFT_MpComputerStatus`) + remontée menaces (`MSFT_MpThreatDetection`/`MSFT_MpThreat`, `detection_id`)
- [x] Exécution `quick_scan` / `full_scan` / `update_signatures` (PowerShell) + remontée résultat
- [x] Config YAML + surcharge registre (`HKLM\SOFTWARE\Tiai`) ; file locale + back-off
- [x] Identité réelle (SMBIOS UUID via WMI, MachineGuid via registre, EK TPM best-effort) + host info (hostname/domaine/OS)
- [x] **Adresse IP du poste** via `GetAdaptersAddresses` (métrique d'interface + passerelle par défaut, là où `net.Interfaces()` ne donne ni l'un ni l'autre) — relue à chaque heartbeat car elle change sous l'agent (bail DHCP, station d'accueil, VPN) ; une seule adresse élue (IPv4 routée d'abord), loopback / 169.254.0.0/16 / fe80::/10 exclus, commutateurs virtuels sans passerelle écartés sans heuristique de nom. Validé sur poste réel (5 adresses APIPA, 2 commutateurs Hyper-V, Wi-Fi élu)
- [x] **Session utilisateur ouverte** via l'API WTS (`WTSEnumerateSessions` + `WTSQuerySessionInformationW`) — fonctionne depuis la session 0 où tourne l'agent ; élection d'une session (active > déconnectée, console > distante), filtrage session 0 / écran de connexion / écouteur RDP ; interrupteur de confidentialité `report_session_username` (`*bool`, défaut activé) + surcharge registre `ReportSessionUsername` où `0` est signifiant. Validé sur poste réel (deux sessions, dont une déconnectée).
- [x] **Antivirus tiers** via WMI `root\SecurityCenter2` (`AntiVirusProduct`) — nom + décodage conservateur de `productState`, élection d'un produit parmi plusieurs, identification de Defender par `instanceGuid`/URI et non par le nom seul ; `AMRunningMode` ajouté à l'état Defender pour expliquer le mode passif. Lecture seule (le Security Center n'expose ni version de signatures ni action). Échec journalisé une fois puis en DEBUG, l'absence de namespace étant permanente sur SKU Serveur. **À valider sur poste réel avec un antivirus tiers.**

**M3 — Backend complet** · 🟢 implémenté
- [x] File de commandes : création (route `POST /commands`, permission `command:execute`)
- [x] Garde-fou d'empreinte `needs_verification` (enroll + heartbeat)
- [x] Déduplication + stockage des menaces (contrainte + upsert `ON CONFLICT DO NOTHING`, testé)
- [x] Création **groupée** par filtre (tous / domaine / statut) + suivi `GET /commands` + expiration (`mark_expired`, plan §2.8)
- [x] Stats `GET /stats/overview` (total, à jour/non, à vérifier, inactifs, postes avec menaces actives)
- [x] Recherche/filtrage `/machines` (hostname/UUID/IP/antivirus, domaine, antivirus, statut) + valeurs distinctes `GET /machines/antivirus-products` + listing `GET /threats`
- [x] Révocation de token (`POST /machines/{id}/revoke-token`, kill-switch) + ré-enrôlement
- [x] Calcul de `is_up_to_date` au heartbeat (AV+RTP+âge signatures) ; pool DB (psycopg) configurable

**M4 — Console** · 🟢 implémenté
- [x] Authentification console (login JWT, store Pinia, interceptor Bearer + redirection sur 401, guard de route)
- [x] Dashboard : cartes KPI (`/stats/overview`) + listes d'alertes (postes non à jour, menaces actives)
- [x] Liste des postes : recherche (nom/UUID), filtres domaine + statut, lien vers le détail
- [x] Vue détail poste : identité + état Defender complet, historique menaces, dernières commandes, bannière `needs_verification`
- [x] Sélection multiple → actions de masse (scan rapide/complet, MAJ signatures) + révocation de token, avec retour `Notify`
- [x] **Fusion de postes** (`needs_verification`, plan §8) : backend `POST /machines/{id}/merge` (rattache menaces + commandes, dédup `detection_id`, lève le flag, supprime le doublon) + `GET /machines/{id}/duplicates` (même SMBIOS) ; UI = dialog de fusion sur la vue détail
- [x] Détail backend enrichi (`MachineDetailOut`) + services frontend testés (vitest, couverture 100 % sur `src/services`)
- [x] **Adresse IP** : colonne « Adresse IP » dans la liste (non triable — un tri texte placerait `.10` avant `.9`) et ligne sur la fiche détail ; la **recherche** couvre désormais nom / UUID / IP, pour remonter d'une adresse de log de pare-feu au poste
- [x] **Session ouverte** : colonne « Session » dans la liste (badge + infobulle « au dernier contact ») et lignes « Session » / « Type de session » sur la fiche détail ; quatre états distincts (nom, présence sans nom, aucun utilisateur, inconnu) via `sessionLabel`/`sessionColor`/`sessionTypeLabel` — couverture vitest élargie à `src/utils`

**Commandes de maintenance à distance** · 🟢 implémenté (cf. `plan-commandes-distantes.md`)
- [x] Backend : 11 types ajoutés à `CommandType` (stockage `str` nu ⇒ aucune migration) ; endpoint de résultat restreint à `running`/`succeeded`/`failed` et plafonnement du texte remonté à 64 Kio
- [x] Backend : statut intermédiaire **`running`** → `started_at` sans clôture, ignoré s'il arrive après un verdict (brique partagée avec la Phase 2 J1)
- [x] Agent : catalogue `maintenance*.go` (table type → exécutable/arguments/délai/encodage/verdict), exécutables résolus en **chemin absolu sous System32** (jamais le `PATH`)
- [x] Agent : décodage par outil (OEM / ANSI / UTF-8 auto-détecté / UTF-16LE vérifié), rejeu des retours chariot pour effacer la progression `dism`/`sfc`, troncature à 64 Kio, codes HRESULT en hexadécimal
- [x] Agent : `spooler_reset` natif (gestionnaire de services + purge `.spl`/`.shd`, service redémarré même si la purge échoue) ; `running` posté par les 4 commandes longues
- [x] Console : catalogue d'actions **factorisé** (fin de la duplication détail/masse), menu en sections, confirmation avec nombre de postes, **dialog « Résultat »** + copie, libellés des types dans l'historique
- [x] Tests : 17 backend (round-trip des 11 types, cycle `running`, garde de statut, plafonnement), 30 Go collector (encodages, progression, verdicts, exhaustivité du catalogue) + 3 d'intégration réelle sous Windows, 9 vitest de catalogue
- [ ] Validation en `LocalSystem` des huit commandes exigeant l'élévation (`gpo_update`, `time_resync`, `cert_pulse`, `spooler_reset`, `sfc_scan`, `dism_restore_health`, `dism_component_cleanup`, `chkdsk_scan`) — `sfc_scan` en priorité : c'est la dernière branche d'encodage du catalogue jamais vérifiée sur des octets réels

**Phase 2 — Windows Update** · 🟢 implémentée (cf. `plan-phase2-windows-update.md`)
- [x] Backend : bloc `windows_update` optionnel sur le heartbeat (colonnes `wu_pending_count` / `wu_reboot_required` / `wu_last_search` / `wu_last_install` + table `windows_updates`, migration `0008_windows_update`) ; bloc absent = rien n'est écrasé, comme le bloc Defender
- [x] Backend : **sémantique de remplacement** du set de MAJ en attente (`replace_pending` : upsert des présentes + `DELETE` des disparues), à l'inverse des menaces qui s'accumulent — une MAJ installée doit disparaître, `first_seen` seul survit
- [x] Backend : 4 types ajoutés à `CommandType` (`type` stocké en `str` nu ⇒ **aucune migration**) ; `wu_pending_count` dérivé de la liste reçue plutôt que d'un champ à part, pour que le badge et le tableau ne puissent pas se contredire
- [x] Backend : exposition console (`GET /machines` + 2 colonnes, `MachineDetailOut` + 4 champs et `pending_updates` triées critique d'abord, `GET /stats/overview` + `machines_wu_pending` / `machines_reboot_required`)
- [x] Agent : collecteur `wu*.go` sur l'**API COM WUA** (PSWindowsUpdate écarté : non livré avec Windows), wrapper `runPowerShellJSON` séparé (`Out-String` couperait un titre long au milieu du JSON, et les flux doivent rester séparés)
- [x] Agent : **cycle lent dédié** (première collecte à ~2 min, puis 6 h par défaut), cache à compteur de génération — bloc attaché seulement s'il n'a pas déjà été accusé, et une collecte terminée en vol n'est pas enterrée par l'acquittement du heartbeat précédent
- [x] Agent : 4 commandes (`wu_scan`, `wu_install`, `wu_install_full`, `reboot`), filtre pilotes **dans le critère de recherche** WUA et non après coup, `running` posté par les deux installations, opérations WUA sérialisées par mutex (jamais deux sessions WUA), relecture immédiate de l'état après scan/installation
- [x] Agent : `reboot` = `shutdown /r /t 60` avec message à l'utilisateur — jamais automatique ; le délai laisse enregistrer *et* laisse poster le résultat avant la coupure (file locale en repli)
- [x] Agent : codes WU documentés traduits en phrase actionnable (`wuauserv` désactivé, WSUS injoignable, TrustedInstaller occupé…), toujours **à côté** du code brut ; nouvelles clés `wu_collect_interval_seconds` / `wu_install_timeout_seconds` (+ surcharge registre), `telemetry_interval_seconds` supprimée (jamais lue)
- [x] Console : catalogue étendu (section « Windows Update », confirmation sur les deux installations et le redémarrage), carte « Windows Update » + tableau des MAJ en attente sur la fiche détail, colonne « MAJ Windows » dans la liste, 2 cartes KPI au dashboard
- [x] Tests : **18 backend** (bloc heartbeat, remplacement du set, bloc absent, doublon dans un même rapport, entrée malformée, tri, fusion, 4 types, cycle `running`, KPI), **27 Go** (critères, parsing, mappings, résumés d'installation, cache de génération, défauts de config, et les deux scripts parsés par PowerShell lui-même), **13 vitest** (catalogue, champs WU, KPI, libellés)
- [ ] Validation sur poste réel d'une **installation effective** (`wu_install` / `wu_install_full`) et d'un **redémarrage** — les deux seules branches qui ne peuvent pas être exercées sans patcher ou redémarrer une machine ; le reste de la boucle est validé contre la stack dev avec un agent réel (19 MAJ remontées, upsert en place vérifié en base)

**M5 — Durcissement** · 🟡 partiel (anticipé)
- [x] Auth console JWT + rôles `admin` / `readonly` (permissions `(ressource, action)`)
- [x] Provider d'alerte e-mail (Mailgun)
- [x] Garde de démarrage : secrets vides/placeholder `changeme*` refusés hors `local` (`SECRET_KEY`, `ENROLLMENT_SECRET`, `POSTGRES_PASSWORD`, `FIRST_ADMIN_PASSWORD`), testé
- [x] Comparaison timing-safe du secret d'enrôlement (`hmac.compare_digest`)
- [x] En-têtes de sécurité HTTP posés par Caddy (HSTS, CSP, `nosniff`, `frame-ancestors 'none'`, `Referrer-Policy`) — CSP à valider sur la stack déployée
- [x] Logs agent : fichier `agent.log` (rotation simple, `.old` > 5 Mio) + niveau `log_level` INFO/DEBUG enfin branché ; chemin nominal loggé (démarrage, identité, enrôlement, heartbeat, commandes + durée) — indispensable en mode service où stderr est perdu ; validé sur poste réel contre la stack dev (enrôlement + heartbeats visibles dans le fichier et machine visible console)
- [ ] Journal d'audit ; jobs ARQ branchés (nettoyage + envoi d'alertes) ; rotation tokens ; rate-limiting

**M6 — Packaging & GPO** · ⬜ à faire

**Transverse**
- [x] Tests backend (`pytest` : sécurité, permissions, empreinte ; API sur Postgres de test)
- [x] Tests frontend (`vitest` : service machines)
- [x] Qualité backend : `ruff format` + `ruff check` + `mypy --strict` (verts)
- [x] Formatage frontend : `prettier`
- [x] CI GitHub Actions (backend : uv + ruff + mypy + pytest avec Postgres ; frontend : prettier + vue-tsc + vitest ; agent : gofmt + vet + go test + build croisé Windows ; action de couverture épinglée par SHA)
- [x] Contrat d'erreurs API (`AppError` + handlers, enveloppe `{error:{code,message,details}}`, catalogue `ErrorCode` reflété côté frontend `errors.ts`) — migré depuis `HTTPException` (cf. §2.14), testé (8 tests backend de contrat + 6 frontend)

---

## 7. Sécurité — feuille de route

| Étape | Mesure |
|---|---|
| MVP (M0–M1) | **TLS dès le départ** (Caddy + AC interne) ; **auto-enrôlement** : secret d'enrôlement partagé → **token unique par poste** (DPAPI) ; identité = `machine_uuid` ; **auth console JWT** avec rôles `admin` / `readonly`. |
| Durcissement (M5) | Garde-fou de ré-enrôlement + révocation de token ; journal d'audit ; moindre privilège + limitation de débit sur l'API. |
| Plus tard | Rotation automatique des tokens ; mTLS ; attestation d'identité AD à l'enrôlement ; **permissions fines par ressource/table** (lecture/écriture) au-delà des deux rôles. |

Points permanents : binaire agent **signé**, validation stricte des entrées API, limitation de débit côté agent pour éviter l'effet « troupeau ».

---

## 8. Risques & points d'attention

- **Serveur interne uniquement** : pas d'exposition Internet/VPN à ce jour ; un poste hors du réseau d'entreprise ne remonte pas tant qu'il n'y est pas reconnecté (le modèle *polling* le gère sans perte de données). Si une exposition externe devient nécessaire plus tard, prévoir un accès sécurisé (reverse-proxy, IP filtrée, VPN).
- **Postes en workgroup** : hors domaine, la GPO n'est pas disponible → déploiement de l'agent par script/MSI et installation manuelle de la racine AC interne et du secret d'enrôlement.
- **Droits de l'agent** : `LocalSystem` est puissant ; le binaire signé et la chaîne de déploiement deviennent une cible de choix → soigner la sécurité de la build.
- **Cohérence des dates Defender** : certaines propriétés WMI valent `0`/`null` si aucun scan n'a eu lieu — gérer ces cas dans le calcul de `is_up_to_date`.
- **Clones / faux doublons** : l'ancre **SMBIOS UUID** survit à une ré-image (même identité conservée) et distingue les clones non-sysprepés (cf. §2.3). Cas résiduels signalés par `needs_verification` → réconciliation manuelle / **fusion de postes** dans l'UI : swap de carte mère (nouvelle ancre), SMBIOS invalide tombant sur le repli UUID agent, ou clonage préservant le SMBIOS.
- **Effet de masse** : « scan complet sur tout le parc » peut saturer postes et réseau → permettre l'étalement (les commandes sont récupérées au *poll*, ce qui étale naturellement, mais documenter le comportement).
- **Données personnelles (session utilisateur)** : savoir quel salarié nommé est sur quelle machine, et à quelle heure, est une donnée personnelle et un point de vigilance RGPD/CSE. La mitigation est un interrupteur **à la source** (`report_session_username`, valeur registre `ReportSessionUsername`, cf. `plan-session-utilisateur.md`) : coupé, le nom ne transite ni ne se stocke, seule la présence remonte — la garantie est donc vérifiable côté poste et non sur parole. Le nom n'est journalisé à aucun niveau. Le défaut est **activé** ; à arbitrer avec le DPO / le CSE avant la mise en production, sachant que la bascule se fait par GPO sans changement de code. À porter au registre des traitements et à l'information des utilisateurs.

---

## 9. Stack technique — récapitulatif

| Couche | Choix | Note |
|---|---|---|
| Agent | **Go** | Binaire statique unique, idéal GPO, faible empreinte, bon support service Windows (`golang.org/x/sys/windows/svc` ou `kardianos/service`), WMI via `yusufpapurcu/wmi`. Alternative écartée : C#/.NET — intégration Windows plus riche et packaging/signature plus simples, mais runtime à gérer. |
| Backend | **FastAPI** (async) + asyncpg/SQLAlchemy | API REST versionnée (`/api/v1`). |
| Base | **PostgreSQL** | Stockage en UTC (`timestamptz`). |
| File de tâches | **ARQ** + **Redis** | Nettoyage + alertes. |
| Alertes | **e-mail via API Mailgun** | Notifications envoyées par le worker ARQ. |
| Frontend | **Quasar / Vue 3** | Build statique servi par nginx. |
| Infra | docker-compose + **Caddy** (reverse-proxy + TLS) | TLS **dès le départ**, certificat de l'AC interne (déjà approuvée par les postes du domaine). Traefik inutile ici. |

---

## 10. Cadrage retenu

- **Réseau** : serveur joignable **uniquement en interne** (LAN). Pas de VPN ni d'exposition Internet prévus à ce jour.
- **Environnement** : parc **mixte** — postes en domaine AD **et** postes en workgroup. Le déploiement par GPO couvre les postes du domaine ; les postes en workgroup sont provisionnés par script/MSI (agent, racine AC interne, secret d'enrôlement).
- **Canal d'alerte** : **e-mail** via l'**API Mailgun** (premier canal ; d'autres canaux non prévus pour l'instant).
