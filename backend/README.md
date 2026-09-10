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
- `GET  /api/v1/auth/me` — utilisateur courant, ses groupes et ses permissions.
- `GET/POST/PATCH/DELETE /api/v1/groups` — groupes et leurs droits (permission `user:read` / `user:write`) ; `GET /api/v1/groups/permissions` liste le catalogue.
- `GET/POST /api/v1/machines/{id}/interventions`, `PATCH/DELETE /api/v1/interventions/{id}` — le journal d'un poste : panne, installation logicielle, mise à niveau, maintenance, vérification, autre (permission `intervention:read` / `intervention:write`). Antidatable ; les suppressions et les modifications par un autre que l'auteur sont tracées dans l'audit ; une fusion de doublons déplace le journal sur le poste conservé.
- `GET/POST/PATCH/DELETE /api/v1/buildings` et `/api/v1/rooms` — bâtiments et salles (permission `room:read` / `room:write`) ; `POST /api/v1/rooms/{id}/machines` et `POST /api/v1/rooms/unassign` déplacent des postes. La liste des postes se filtre par `room_id`, `building_id`, `without_room`, `location_mismatch` et se trie par `building` / `room`. Avec `ROOM_SOURCE=ad_ou` ou `ad_location`, le bloc `directory` de l'inventaire range les postes tout seul (`features/room/crud.py`, `place_from_directory`), le rattachement manuel répond `room.placement.locked`, et `POST /api/v1/rooms/sync-directory` reclasse le parc depuis les lectures mémorisées ; `GET /api/v1/rooms/config` dit le mode.
- `GET  /api/v1/machines` / `GET /api/v1/machines/{id}` — lecture (permission `machine:read`).
- `POST /api/v1/commands` — file une commande par poste (permission `command:execute`, plus `risky_command:execute` pour les types à risque).
  Champ optionnel `ttl_minutes` (borné à 1 min → 30 j) ; omis, le déploiement
  décide via `COMMAND_DEFAULT_TTL_MINUTES` (**60** par défaut). Au-delà, une
  commande jamais distribuée est périmée — voir *Cycle de vie d'une commande*.
- `POST /api/v1/machines/wake` — réveil Wake-on-LAN (permission `command:execute`).
  La seule action que le **serveur** exécute lui-même : le poste visé est éteint,
  il n'a pas d'agent à qui la confier. Le paquet magique est diffusé sur le
  sous-réseau du poste ([features/wol/](app/features/wol/)) et la tentative est
  inscrite dans l'historique des commandes, close d'emblée — elle n'est jamais
  proposée à un agent. Réponse poste par poste : un poste sans MAC connue est un
  échec parmi les autres, pas une erreur HTTP.

## Cycle de vie d'une commande

Une commande naît `pending` et suit un chemin à sens unique
([models.py](app/features/command/models.py)) :

| Statut | Écrit par | Signification |
|---|---|---|
| `pending` | serveur | en file, pas encore remise à un agent |
| `delivered` | serveur | remise sur un heartbeat ; l'agent en est désormais propriétaire |
| `running` | agent | commande longue (`sfc`, `dism`, `chkdsk`) qui signale son démarrage |
| `succeeded` / `failed` | agent | verdict final |
| `expired` | serveur | jamais distribuée dans son délai |

Un agent ne peut poster que `running`, `succeeded` ou `failed` : celui qui
pourrait écrire `pending` ou `expired` réécrirait la file qu'il est seulement
censé vider. `succeeded`, `failed` et `expired` sont **terminaux** — un `running`
qui arrive en retard ne rouvre pas une commande close.

### Péremption

`expires_at` est figé à la création : `utcnow() + ttl_minutes`, ce dernier
retombant sur `COMMAND_DEFAULT_TTL_MINUTES` (**60 min**) quand la requête ne le
porte pas. Il joue à trois endroits :

- **Distribution** — un heartbeat ne se voit remettre que les commandes encore
  dans leur délai ([agent.py](app/api/routes/agent.py)). Un poste rallumé après
  trois semaines n'exécute pas le scan demandé entre-temps.
- **Balayage** — le worker repasse les `pending` échues en `expired` toutes les
  5 min ([worker.py](app/core/worker.py)) ; la création et le suivi de commandes
  déclenchent le même balayage au passage, pour que la console n'affiche jamais
  un `pending` mort.
- **Déduplication** — une commande échue ne bloque plus la mise en file du même
  type sur ce poste (`machines_with_open_command`).

**Seules les `pending` sont périmées.** Une fois délivrée, la commande appartient
à l'agent et son verdict fait foi : une commande confiée à un agent qui n'est
jamais revenu reste `delivered` indéfiniment dans l'historique — c'est le
comportement attendu, pas une ligne oubliée. Passé son délai, elle cesse
simplement de verrouiller son type sur ce poste, et si l'agent finit par
répondre, son résultat s'inscrit malgré tout sur la ligne d'origine.

## Utilisateurs, groupes & permissions

Les opérateurs se connectent en **JWT** (email + mot de passe, hash bcrypt). Ce
qu'un compte peut faire est l'**union des droits de ses groupes**
([models.py](app/features/user/models.py) : `groups`, `group_permissions`,
`user_groups`). Un groupe est un ensemble nommé de permissions
`ressource:action`, composé depuis la console (`/groups`). Trois groupes sont
intégrés et créés par la migration `0016` puis par
[seed_admin.py](app/scripts/seed_admin.py) à chaque démarrage s'ils manquent :

| Groupe intégré | Clé | Droits par défaut |
|---|---|---|
| Administrateurs | `admin` | **tous**, implicitement — y compris ceux des ressources à venir ; non modifiables |
| Lecture seule | `readonly` | `machine:read`, `threat:read`, `command:read`, `room:read`, `intervention:read` |
| Techniciens | `technician` | lecture seule + `command:execute` + `risky_command:execute` + `intervention:write` |

Les groupes intégrés se renomment et, sauf les administrateurs, se modifient
comme les autres ; ils ne se suppriment pas. Aucune modification ne peut laisser
la console sans compte actif détenant `user:write` (erreur `user.lockout`), et
personne ne modifie ses propres groupes.

L'autorisation passe par des permissions `(ressource, action)`
([permissions.py](app/features/user/permissions.py)) : les routes demandent une
capacité via `require_permission(Resource.X, Action.Y)`, jamais un test de
groupe en dur. Le catalogue (`PERMISSION_CATALOGUE`) est ce que la grille de la
console propose ; une permission hors catalogue est refusée à l'écriture.

Les commandes sont coupées en deux : `command:execute` ouvre `POST /commands`
et le réveil Wake-on-LAN ; les types de `RISKY_COMMAND_TYPES`
([command/models.py](app/features/command/models.py) — redémarrage, arrêt,
installation de mises à jour, réinitialisation de Windows Update, réparations
DISM, réinitialisation du spouleur) demandent en plus `risky_command:execute`,
vérifié dans la route puisque le type est dans le corps.

Le premier admin est créé au démarrage depuis `FIRST_ADMIN_EMAIL` /
`FIRST_ADMIN_PASSWORD` (script [seed_admin.py](app/scripts/seed_admin.py)).
