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
               user/ (comptes, groupes, permissions) auth_session/ (sessions console)
               room/ (bâtiments, salles, annuaire)
               intervention/ check/ maintenance/ setting/ (exploitation du parc)
               usage/ (heures allumées par poste, comptées depuis les battements)
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

**Console** (auth : JWT utilisateur adossé à une session serveur, cf. *Sessions de la console*)
- `POST /api/v1/auth/login` — email + mot de passe (OAuth2 password) : ouvre une session, renvoie le jeton d'accès et pose le jeton de session en cookie.
- `POST /api/v1/auth/refresh` — échange le cookie contre un nouveau jeton d'accès (et un nouveau cookie) ; `POST /api/v1/auth/logout` ferme la session courante.
- `GET /api/v1/auth/sessions`, `DELETE /api/v1/auth/sessions/{id}` — les sessions ouvertes du compte, et la fermeture de l'une d'elles (audit `auth.session_revoked`).
- `GET  /api/v1/auth/me` — utilisateur courant, ses groupes et ses permissions.
- `GET/POST/PATCH/DELETE /api/v1/groups` — groupes et leurs droits (permission `user:read` / `user:write`) ; `GET /api/v1/groups/permissions` liste le catalogue.
- `GET /api/v1/maintenance/due?owner=me|none|<id>`, `POST /api/v1/maintenance`, `GET /api/v1/maintenance[/{id}]`, `GET/PATCH /api/v1/rooms/{id}/maintenance`, `GET/PATCH /api/v1/machines/{id}/maintenance` — maintenance : ce qui est dû par salle et par responsable, enregistrement d'une séance (note globale + note par poste, une ligne « maintenance » dans le journal de chacun, cycle relancé), cycle et responsable par salle et par poste (permission `maintenance:read` / `maintenance:write`). La résolution est à trois niveaux, poste › salle › parc (`features/maintenance/policy.py`), en Python pour les réponses et en SQL pour le filtre `maintenance_state`, le tri `maintenance_due_at` et les compteurs du tableau de bord.
- `GET/PATCH /api/v1/settings` — les défauts du parc (cycle, responsable, fenêtre « à échéance » ; fenêtre et seuils d'utilisation), table `app_settings`, permission `settings:read` / `settings:write` (administrateurs seuls par défaut).
- `POST /api/v1/machines/{id}/check`, `GET /api/v1/checks?open&assigned_to=me|none|<id>`, `PATCH /api/v1/checks/{id}`, `POST /api/v1/checks/{id}/close`, `POST /api/v1/checks/bulk`, `GET /api/v1/checks/assignable-users` — vérifications demandées sur un poste, affectables à un compte, une seule ouverte par poste, closes avec une note qui s'inscrit dans le journal (permission `check:read` / `check:write`). La liste des postes se filtre par `check_open`.
- `GET/POST /api/v1/machines/{id}/interventions`, `PATCH/DELETE /api/v1/interventions/{id}` — le journal d'un poste : panne, installation logicielle, mise à niveau, maintenance, vérification, autre (permission `intervention:read` / `intervention:write`). Antidatable ; les suppressions et les modifications par un autre que l'auteur sont tracées dans l'audit ; une fusion de doublons déplace le journal sur le poste conservé.
- `GET/POST/PATCH/DELETE /api/v1/buildings` et `/api/v1/rooms` — bâtiments et salles (permission `room:read` / `room:write`) ; `POST /api/v1/rooms/{id}/machines` et `POST /api/v1/rooms/unassign` déplacent des postes. La liste des postes se filtre par `room_id`, `building_id`, `without_room`, `location_mismatch` et se trie par `building` / `room`. Avec `ROOM_SOURCE=ad_ou` ou `ad_location`, le bloc `directory` de l'inventaire range les postes tout seul (`features/room/crud.py`, `place_from_directory`), le rattachement manuel répond `room.placement.locked`, et `POST /api/v1/rooms/sync-directory` reclasse le parc depuis les lectures mémorisées ; `GET /api/v1/rooms/config` dit le mode.
- `GET  /api/v1/machines` / `GET /api/v1/machines/{id}` — lecture (permission `machine:read`). La liste porte les heures allumées de chaque poste (`usage_hours`), se filtre par `usage_hours_below` / `usage_hours_above` sur `usage_days` jours et se trie par `usage_hours`.
- `GET /api/v1/machines/{id}/usage?days=28&tz=<IANA>` — heures allumées d'un poste, jour par jour dans le fuseau demandé (permission `machine:read`).
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

## Exploitation du parc : salles, vérifications, maintenance, journal

Quatre chantiers livrés ensemble (cf. `dev/plan-salles-maintenance-interventions.md`),
migrations `0016` à `0021`, chacun sa ressource de permission :

| Objet | Tables | Ce qu'il porte |
|---|---|---|
| Bâtiments et salles (`room`) | `buildings`, `rooms`, `machines.room_id` | Un bâtiment porte l'emplacement (le site que l'agent déclare), une salle en hérite. Un poste dont l'agent nomme un autre site que sa salle est **signalé** (`location_mismatch`), jamais refusé. `ROOM_SOURCE` fait ranger les postes par l'annuaire (OU ou attribut Emplacement, lus par l'agent avec l'inventaire) au lieu de la console. |
| Journal (`intervention`) | `interventions` | Toute intervention humaine sur un poste, une chronologie ; les vérifications closes et les séances de maintenance y écrivent leur ligne (`check_id`, `maintenance_id`). |
| Vérifications (`check`) | `machine_checks` | « Va voir ce poste » : consignes, affectataire, une seule ouverte par poste (index partiel), close avec une note datée. |
| Maintenance (`maintenance`, `settings`) | `maintenances`, `app_settings`, `*.maintenance_cycle_days`, `*.maintenance_owner_id`, `machines.last_maintenance_at` | Cycle et responsable résolus poste › salle › parc (`features/maintenance/policy.py`, en Python pour les réponses et en SQL pour les filtres et compteurs) ; une séance = une visite, une ligne de journal par poste fait, le cycle relancé. |

Les trois groupes intégrés reçoivent les droits de ces ressources par les
migrations qui les créent ; les administrateurs ont tout implicitement.

## Utilisation des postes

Livrée selon `dev/plan-utilisation-postes.md`, migration `0023`. Aucune
modification de l'agent : chaque battement crédite l'écart depuis le
précédent quand il est plus court que `OFFLINE_AFTER_SECONDS`, la même règle
que la pastille « allumé » (`features/usage/accounting.py`).

| Pièce | Où | Ce qu'elle fait |
|---|---|---|
| Compteurs | `machine_uptime_hourly` | Secondes allumées par poste et par heure UTC, plafonnées à 3 600 ; ajoutées par un upsert à chaque battement, fusionnées avec les doublons, purgées au-delà de `USAGE_RETENTION_DAYS`. |
| Lecture | `features/usage/crud.py` | Une fenêtre de N jours couvre les N × 24 heures pleines avant l'heure courante, plus celle-ci. La même borne sert la liste, son filtre et son tri, l'export et le tableau de bord ; un poste enrôlé pendant la fenêtre n'est jamais « peu utilisé ». |
| Réglages | `app_settings` (`usage.*`) | Fenêtre et seuils, avec les variables `USAGE_*` pour valeurs initiales (`setting/crud.py`, `usage_policy`). |

## Sessions de la console

Migration `0024`, [features/auth_session/](app/features/auth_session/). Une
connexion crée une ligne `auth_sessions` ; le jeton d'accès (JWT, `type=access`,
`sid` = la session, `ACCESS_TOKEN_EXPIRE_MINUTES`) n'est accepté que tant que
cette ligne est ouverte — une lecture par clé primaire, jointe au compte, à
chaque requête ([deps.py](app/api/deps.py)). Le jeton de session
(`<id>.<secret>`, seul son SHA-256 est stocké) voyage dans le cookie
`tiai_refresh` (`HttpOnly`, `SameSite=Strict`, `Path=/api/v1/auth`, `Secure`
hors `local`) :

| Évènement | Effet |
|---|---|
| `POST /auth/refresh` avec le jeton courant | nouveau jeton d'accès, nouveau jeton de session ; échéance repoussée de `REFRESH_TOKEN_EXPIRE_DAYS`, plafonnée à `created_at + SESSION_MAX_DAYS` |
| … avec le jeton précédent, dans les 30 s | deux onglets ont rafraîchi ensemble : jeton d'accès, cookie laissé tel quel |
| … avec un jeton déjà échangé, au-delà | vol présumé : la session est révoquée pour ses deux détenteurs, ligne `presumed theft` dans le journal `app.security` |
| changement / réinitialisation du mot de passe, désactivation | toutes les sessions du compte révoquées, dans la même transaction |
| suppression du compte | sessions supprimées (`ON DELETE CASCADE`) |

`crud.purge_expired_sessions` supprime les sessions expirées ou révoquées
(elles n'autorisent plus rien) ; elle est faite pour le ménage quotidien du
worker. `password_changed_at` reste en seconde ligne : un jeton émis avant un
changement de mot de passe est refusé quelle que soit sa session.

La connexion coûte une vérification bcrypt dans tous les cas — contre un hash
factice pour une adresse inconnue ou un compte désactivé —, et les adresses
sont comparées et stockées en minuscules (index unique sur `lower(email)`).

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
| Lecture seule | `readonly` | `machine:read`, `threat:read`, `command:read`, `room:read`, `intervention:read`, `check:read`, `maintenance:read` |
| Techniciens | `technician` | lecture seule + `command:execute` + `risky_command:execute` + `intervention:write` + `check:write` + `maintenance:write` |

Les groupes intégrés se renomment et, sauf les administrateurs, se modifient
comme les autres ; ils ne se suppriment pas. Aucune modification ne peut laisser
la console sans compte actif détenant `user:write` (erreur `user.lockout`), et
personne ne modifie ses propres groupes.

**Pas d'escalade** (`permissions.escalation`, erreur `auth.permission.escalation`,
403) : un compte qui n'est pas administrateur n'accorde que ce qu'il détient.
Il ne compose un groupe qu'avec ses propres permissions, ne modifie ni ne
supprime un groupe qui accorde davantage — le groupe Administrateurs en
premier —, ne place un compte (création ou modification) que dans des groupes
qui n'excèdent pas ses droits, et ne touche pas — modification, désactivation,
suppression, réinitialisation du mot de passe — à un compte plus puissant que
lui. Le groupe Administrateurs est hors de portée même d'un compte qui
détiendrait tout le catalogue : il accorde aussi les permissions à venir.
Chaque refus est journalisé (`app.security`, « privilege escalation refused »).

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
