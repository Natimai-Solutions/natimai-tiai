# Tia'i — Backend

API FastAPI (async) + worker (une boucle asyncio : outbox e-mail et tâches
périodiques). Architecture « features » (inspirée de `fastapi-ecommerce`),
SQLModel sur PostgreSQL (psycopg 3), migrations Alembic. Tout l'état passe par
Postgres — commandes en attente, e-mails à envoyer — il n'y a ni Redis ni file
de tâches externe.

## Layout

```
app/
  core/        config, db, security (tokens), worker (outbox + tâches périodiques)
  api/         deps + routes (agent, machines, health)
  features/    machine/ threat/ command/ notification/ (modèles + logique)
  alembic/     migrations
  scripts/     entrypoint.sh (api | worker | migrate)
```

## Dév local

Dépendances gérées par [**uv**](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`).

```bash
uv sync                                         # crée .venv et installe deps + groupe dev
cp ../deploy/.env.example .env                  # ajuster POSTGRES_SERVER=localhost, etc.
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

`/health` répond à la racine ; l'API versionnée est sous `/api/v1`.

## Tests

```bash
uv run pytest                # unitaires (sécurité, permissions, empreinte)
# Tests d'API (enroll/heartbeat) : nécessite une base Postgres de test
TIAI_TEST_DATABASE_URL=postgresql+psycopg://tiai:tiai@localhost:5432/tiai_test uv run pytest
```

Ajouter une dépendance : `uv add <pkg>` (ou `uv add --dev <pkg>` pour le groupe dev).

## Endpoints

**Agent** (auth : secret d'enrôlement puis token par poste)
- `POST /api/v1/agent/enroll` — en-tête `X-Enrollment-Secret`, renvoie le token du poste.
- `POST /api/v1/agent/heartbeat` — `Authorization: Bearer <token>`, renvoie les commandes en attente.
- `POST /api/v1/agent/commands/{id}/result` — résultat d'exécution.

**Console** (auth : JWT utilisateur)
- `POST /api/v1/auth/login` — email + mot de passe (OAuth2 password), renvoie un JWT.
- `GET  /api/v1/auth/me` — utilisateur courant.
- `GET  /api/v1/machines` / `GET /api/v1/machines/{id}` — lecture (permission `machine:read`).
- `POST /api/v1/commands` — file une commande par poste (permission `command:execute`, admin).
- `POST /api/v1/machines/wake` — réveil Wake-on-LAN (permission `command:execute`, admin).
  La seule action que le **serveur** exécute lui-même : le poste visé est éteint,
  il n'a pas d'agent à qui la confier. Le paquet magique est diffusé sur le
  sous-réseau du poste ([features/wol/](app/features/wol/)) et la tentative est
  inscrite dans l'historique des commandes, close d'emblée — elle n'est jamais
  proposée à un agent. Réponse poste par poste : un poste sans MAC connue est un
  échec parmi les autres, pas une erreur HTTP.

## Utilisateurs & permissions

Les opérateurs se connectent en **JWT** (email + mot de passe, hash bcrypt). Deux
rôles ([models.py](app/features/user/models.py)) :

| Rôle | Capacités |
|---|---|
| `admin` | lecture + écriture + exécution de commandes à distance |
| `readonly` | lecture seule |

L'autorisation passe par des permissions `(ressource, action)`
([permissions.py](app/features/user/permissions.py)) : les routes demandent une
capacité via `require_permission(Resource.X, Action.Y)`, jamais un test de rôle
en dur. Le mapping rôle→permissions est statique aujourd'hui ; il pourra être
remplacé par des **grants en base par utilisateur/table** (lecture/écriture fine)
en ne modifiant que `has_permission`, sans toucher aux routes.

Le premier admin est créé au démarrage depuis `FIRST_ADMIN_EMAIL` /
`FIRST_ADMIN_PASSWORD` (script [seed_admin.py](app/scripts/seed_admin.py)).
