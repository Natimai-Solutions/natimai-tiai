# Tiai

[![CI](https://github.com/Natimai-Solutions/natimai-tiai/actions/workflows/ci.yml/badge.svg)](https://github.com/Natimai-Solutions/natimai-tiai/actions/workflows/ci.yml)
[![Couverture backend](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/jburckel/80b72bc52448a36bc1a08370a68c88a1/raw/tiai-coverage-backend.json)](https://github.com/Natimai-Solutions/natimai-tiai/actions/workflows/ci.yml)
[![Couverture frontend](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/jburckel/80b72bc52448a36bc1a08370a68c88a1/raw/tiai-coverage-frontend.json)](https://github.com/Natimai-Solutions/natimai-tiai/actions/workflows/ci.yml)

> **Console de gestion de parc informatique** — pilotage centralisé d'un parc de postes Windows.
>
> *« Tīa'i »* — en reo tahiti : *gardien, vigile, garder, protéger.*

Tiai est une plateforme qui collecte l'état des postes Windows d'un parc, orchestre des actions à distance et offre une console web de supervision. La **Phase 1** se concentre sur **Microsoft Defender** (état antivirus, scans à distance, mise à jour des signatures). Les phases suivantes étendront la plateforme à Windows Update, au déploiement logiciel et à l'inventaire — en réutilisant le **même agent, le même canal de communication et le même modèle de commandes**.

---

## Sommaire

- [Pourquoi Tiai](#pourquoi-tiai)
- [Architecture](#architecture)
- [Principes de conception](#principes-de-conception)
- [Stack technique](#stack-technique)
- [Modules & feuille de route](#modules--feuille-de-route)
- [Structure du dépôt](#structure-du-dépôt)
- [Démarrage rapide](#démarrage-rapide)
- [Sécurité](#sécurité)
- [Documentation](#documentation)
- [Licence](#licence)

---

## Pourquoi Tiai

Administrer Microsoft Defender sur des centaines de postes Windows sans console centralisée est laborieux : pas de vue d'ensemble de l'état des signatures, pas de moyen simple de déclencher un scan sur tout le parc, pas d'historique consolidé des menaces. Tiai répond à ce besoin avec :

- une **vue temps quasi-réel** de l'état Defender de chaque poste (signatures, protection temps réel, dates de scans) ;
- le **déclenchement d'actions à distance** (scan rapide / complet, mise à jour des signatures) sur un poste ou sur tout le parc ;
- un **historique des menaces** dédupliqué et consultable ;
- un **déploiement sans friction** via GPO, avec auto-enrôlement des postes.

## Architecture

Tiai repose sur un **modèle de polling** : l'agent installé sur chaque poste interroge le serveur à intervalle régulier. Le serveur ne se connecte jamais aux postes — il met des commandes en file que les agents récupèrent à leur prochain appel. Ce choix traverse naturellement NAT et pare-feu, gère les postes hors-ligne et reste trivial à dimensionner pour un millier de postes.

```
   POSTES WINDOWS (hors Docker)                 SERVEUR (docker compose)
 ┌───────────────────────────┐         ┌─────────────────────────────────────┐
 │  Agent Tiai (Go)          │  HTTPS  │  Caddy : reverse-proxy + TLS         │
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

**Cycle de vie d'une commande**

1. L'agent appelle `POST /heartbeat` → remonte l'état Defender et les menaces détectées.
2. La **même réponse** renvoie les commandes en attente pour ce poste.
3. L'agent exécute la commande, puis poste le résultat via `POST /commands/{id}/result`.

Deux intervalles de polling sont prévus : un **long** pour la remontée d'état (~15 min) et un **court** pour la récupération de commandes (~1 min).

## Principes de conception

| Principe | Choix |
|---|---|
| **Communication** | Polling (l'agent interroge le serveur), jamais de push. Traverse NAT/pare-feu, gère les postes hors-ligne. |
| **Identité des postes** | Identifiant stable (`MachineGuid` Windows ou UUID persisté), pas le `hostname` — qui devient un simple attribut. |
| **Enrôlement** | *Trust on first use* : un secret d'enrôlement partagé (déployé par GPO) ne sert **qu'à** s'enregistrer ; chaque poste reçoit ensuite un **token unique** (seul le hash est stocké côté serveur). |
| **TLS** | Activé dès le MVP via **Caddy** + certificat de l'AC interne (déjà approuvée par les postes du domaine). |
| **Accès Defender** | Lecture directe via **WMI** (`ROOT\Microsoft\Windows\Defender`) plutôt que des appels `powershell.exe` coûteux. |
| **Déduplication** | Contrainte d'unicité `(machine_id, detection_id)` + upsert `ON CONFLICT DO NOTHING`. |
| **Expiration des commandes** | Chaque commande porte un `expires_at` — un poste éteint 3 semaines ne déclenche pas un scan obsolète à son retour. |
| **Robustesse de l'agent** | File locale + back-off si le serveur est injoignable, commandes idempotentes, compte de service `LocalSystem`. |

## Stack technique

| Couche | Choix | Note |
|---|---|---|
| **Agent** | Go | Binaire statique unique, idéal GPO, faible empreinte. WMI via `yusufpapurcu/wmi`, service Windows via `kardianos/service`. |
| **Backend** | FastAPI (async) + asyncpg / SQLAlchemy | API REST versionnée (`/api/v1`). |
| **Base de données** | PostgreSQL | Stockage en UTC (`timestamptz`). |
| **File de tâches** | ARQ + Redis | Nettoyage des postes inactifs, envoi d'alertes par e-mail (API Mailgun). |
| **Frontend** | Quasar / Vue 3 | Build statique servi par nginx. |
| **Infra** | docker-compose + Caddy | Reverse-proxy + terminaison TLS dès le départ. |

## Modules & feuille de route

| Module | Priorité | Horizon |
|---|---|---|
| **Defender** — état, scans à distance, mise à jour des signatures | 🔴 Urgent | Phase 1 |
| Windows Update | 🟠 Moyen | Fin d'année |
| Déploiement logiciel | 🟡 Bas | Fin d'année |
| Inventaire matériel / logiciel | 🟡 Bas | Fin d'année |

**Jalons de la Phase 1 (Defender)**

- **M0 — Fondations** : mono-repo, squelette docker-compose en HTTPS, migrations Alembic, chaîne de signature de code.
- **M1 — Tranche verticale 🎯** : agent minimal (heartbeat WMI), enrôlement + émission de token, page de liste des postes.
- **M2 — Agent Defender complet** : lecture complète de l'état, remontée des menaces, exécution des commandes (`quick_scan`, `full_scan`, `update_signatures`).
- **M3 — Backend complet** : déduplication, file de commandes (unitaire et groupée), stats, recherche/filtrage, révocation de token.
- **M4 — Console** : dashboard KPI, recherche/filtres, vue détail poste, actions de masse.
- **M5 — Durcissement** : auth console (JWT), journal d'audit, jobs ARQ (nettoyage + alertes), rotation des tokens, rate-limiting.
- **M6 — Packaging & GPO** : build MSI signé, distribution du certificat en *Éditeurs approuvés*, déploiement sur un OU pilote.

Le détail complet figure dans [plan-projet-tiai.md](plan-projet-tiai.md).

## Structure du dépôt

```
.
├── agent/        # Agent Windows (Go) — service, WMI Defender, polling
├── backend/      # API FastAPI + worker ARQ + migrations Alembic
├── frontend/     # Console web (Quasar / Vue 3)
├── deploy/       # docker-compose, Caddyfile, .env.example
└── plan-projet-tiai.md
```

Chaque composant a son propre README : [agent/](agent/README.md), [backend/](backend/README.md), [frontend/](frontend/README.md).

## Démarrage rapide

```bash
# 1. Serveur — lève la stack en HTTPS
cd deploy
cp .env.example .env        # renseigner les secrets, placer le certificat dans deploy/certs/
docker compose up -d        # db + redis + backend + worker + frontend + caddy

# Variante dev/tests — sans certificat : Caddy en TLS auto-signé (`tls internal`)
# + backend exposé en HTTP direct sur http://localhost:8800 (agents/curl).
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# 2. Vérifier la santé du backend
curl -k https://tiai.natimai.local/health

# 3. Agent — déployé par GPO sur les postes (MSI signé en M6)
#    Configuration : C:\ProgramData\Tiai\config.json (+ surcharge registre)
```

Pour le développement backend/frontend hors Docker, voir leurs README respectifs.

**Prérequis serveur** : Docker + docker-compose, un certificat serveur émis par l'AC interne (ex. AD CS) pour le nom du serveur.

**Prérequis agent** : Windows avec Defender actif, droits `LocalSystem`, accès HTTPS au serveur.

## Sécurité

| Étape | Mesure |
|---|---|
| MVP (M0–M1) | TLS dès le départ ; auto-enrôlement par secret partagé → token unique par poste (chiffré via DPAPI) ; identité = `machine_uuid`. |
| Durcissement (M5) | Auth console (JWT) ; garde-fou de ré-enrôlement + révocation de token ; journal d'audit ; rate-limiting. |
| Plus tard | Rotation automatique des tokens ; mTLS ; attestation d'identité AD ; RBAC console. |

Points permanents : binaire agent **signé** (certificat de l'AC interne), validation stricte des entrées API, limitation de débit côté agent pour éviter l'effet « troupeau ».

Pour signaler une vulnérabilité, contactez l'équipe sécurité de Natimai plutôt que d'ouvrir une issue publique.

## Tests & couverture

La CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) tourne à chaque push sur `main` et sur chaque PR :

- **Backend** : `ruff format` + `ruff check` + `mypy --strict` + `pytest` **sous couverture** (service PostgreSQL pour les tests d'API). Seuil `fail_under` dans [backend/pyproject.toml](backend/pyproject.toml) — le build échoue en dessous.
- **Agent** : `gofmt` + `go vet` + `go test` (stubs linux) + build croisé `windows/amd64` (code réel).
- **Frontend** : `prettier --check` + `vue-tsc` (typecheck) + `vitest run --coverage` (cadré sur `src/services`, à élargir au fil des tests).
- **PR** : un commentaire de couverture est posté automatiquement (backend + frontend).

```bash
# Backend (Postgres de test optionnel pour les tests d'API)
cd backend && uv run pytest --cov=app --cov-report=term-missing
# Frontend
cd frontend && npm run test:coverage
```

### Badges de couverture (gist)

Les badges en tête de README s'appuient sur un **gist** lu par shields.io, mis à jour par la CI à chaque push sur `main` (action `schneegans/dynamic-badges-action`). Configuration : gist `80b72bc52448a36bc1a08370a68c88a1` (compte `jburckel`), fichiers `tiai-coverage-backend.json` / `tiai-coverage-frontend.json`, secret **`GIST_SECRET`** (PAT scope `gist`). Sans `GIST_SECRET`, les étapes de badge sont simplement ignorées (CI verte).

## Documentation

- [plan-projet-tiai.md](plan-projet-tiai.md) — plan projet détaillé : vision, architecture, modèle de données, contrat d'API, jalons, risques.

## Licence

Distribué sous licence **Apache 2.0**. Voir [LICENSE](LICENSE) pour le texte complet.

```
Copyright 2026 Natimai

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```
