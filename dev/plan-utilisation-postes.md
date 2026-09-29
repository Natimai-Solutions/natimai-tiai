# Utilisation des postes (heures allumées) : plan de travail

> Objectif : répondre à « **combien de postes, et lesquels, ont été allumés moins de 10 h — ou plus de 30 h — cette semaine** », pour connaître l'utilisation réelle du parc : postes qui ne servent à rien (candidats à la mutualisation ou au retrait), postes qui ne s'éteignent jamais (consommation, mises à jour qui n'atterrissent jamais).
>
> Chantier indépendant des précédents. **Aucune modification de l'agent** dans l'itération de base : tout se déduit du heartbeat existant. Il n'ajoute aucun type de commande ni permission ; il ajoute une table, une colonne dérivée dans la liste des postes, un filtre, une carte au tableau de bord et une carte dans la fiche.

---

## 1. Cadrage retenu

| Sujet | Décision |
|---|---|
| Source de vérité pour « allumé » | **Le heartbeat** (60 s par défaut). Chaque heartbeat reçu prouve que le poste était allumé *depuis le précédent*, à condition que l'écart soit petit — exactement la définition de `is_online` déjà en place ([status.py](backend/app/features/machine/status.py) : `now - last_seen < OFFLINE_AFTER_SECONDS`). Le serveur ne se connecte jamais aux postes : c'est la seule preuve d'allumage qu'il ait, et elle est déjà là. |
| Alternatives écartées | **`last_boot_time` de l'inventaire** : collecté une fois par jour, et un poste mis en veille garde sa date de démarrage — on compterait la veille comme de l'usage, c'est-à-dire l'inverse de la question posée. **Uptime remonté par l'agent** (`GetTickCount64`) : plus précis aux bornes, mais impose une version d'agent déployée par GPO avant que la statistique existe, et `GetTickCount64` inclut la veille sur une partie des SKU. Gardé comme raffinement possible (§7), pas comme fondation. |
| Unité de stockage | **Secondes allumées par poste et par heure UTC** (`machine_uptime_hourly`). Pas par jour : Tahiti est à UTC−10, un jour UTC bascule à 14 h locales, en pleine journée de travail ; l'heure est le grain qui rend n'importe quelle fenêtre glissante exacte et n'impose aucun fuseau. Et il ouvre gratuitement, plus tard, le « profil horaire » d'un poste (§7). |
| Fenêtre | **Glissante, N × 24 h avant maintenant** (défaut 7 jours), pas la semaine calendaire : c'est ce qu'on lit en cliquant un lundi comme un vendredi, et ça évite la question du fuseau. La semaine calendaire est un raffinement (§7). |
| Seuils | Deux réglages serveur : `USAGE_LOW_HOURS = 10` et `USAGE_HIGH_HOURS = 30`, sur `USAGE_WINDOW_DAYS = 7`. **Servis** dans `/stats/overview` comme `low_disk_free_percent` l'est déjà : une carte qui dit « moins de 10 h » pendant que le serveur compte à 12 serait un mensonge invisible. Le filtre de la liste, lui, accepte des bornes libres (`usage_hours_below`, `usage_hours_above`) : la carte est une question fréquente, la liste est l'outil de recherche. |
| Postes sans donnée | Un poste sans ligne dans la fenêtre vaut **0 h**, pas « inconnu » : un poste jamais vu allumé de la semaine est bien un poste inutilisé. Une seule exception, visible : un poste **enrôlé pendant la fenêtre** (`first_seen > cutoff`) est **exclu** du filtre « moins de X h » et sa cellule porte « depuis N j » — un poste arrivé avant-hier n'a pas manqué d'être utilisé. |
| Précision | Sous-estimation de l'ordre d'une minute par cycle d'allumage (le temps entre le démarrage et le premier heartbeat, et entre le dernier heartbeat et l'arrêt). Une panne du serveur ou du réseau plus longue que `OFFLINE_AFTER_SECONDS` est perdue pour tout le parc. Deux limites acceptées et documentées : la question porte sur des dizaines d'heures. |
| Rétention | `USAGE_RETENTION_DAYS = 400` : une année pleine, purgée par la tâche d'entretien du worker. Volume à 300 postes : 7 200 lignes/jour, ~2,6 M/an, 24 octets utiles la ligne. |
| Ce qui **n'est pas** fait | Pas de calendrier hebdomadaire, pas de courbe dans le tableau de bord (les cartes sont des listes cliquables, comme les autres), pas d'e-mail. |

**Pourquoi une table plutôt qu'une colonne `usage_seconds_7d` sur `machines`** : une colonne serait un compteur glissant à recalculer sans cesse (chaque heure qui sort de la fenêtre doit être décomptée), donc soit faux, soit recalculé par un batch qui ferait ce que fait une somme SQL. La table de buckets est écrite une fois par heartbeat et lue par une agrégation ; la fenêtre et les seuils restent des paramètres de lecture.

---

## 2. Comptage : la règle, en une fonction pure

Nouveau module `backend/app/features/usage/` — c'est une entité (une table avec ses lignes), pas un état de machine, d'où un module `features/` et non des colonnes de plus sur `Machine`.

### `usage/accounting.py` — `credit_for_gap(previous_last_seen, now, offline_after_seconds) -> list[tuple[datetime, int]]`

Appelée sur chaque heartbeat, **avant** que `machine.last_seen` soit écrasé (le handler l'écrase à [agent.py:575](backend/app/api/routes/agent.py#L575) ; le crédit doit se calculer depuis l'ancienne valeur).

| Écart `now − previous_last_seen` | Crédit |
|---|---|
| `< OFFLINE_AFTER_SECONDS` (le poste était *en ligne* au sens de la console) | tout l'écart, ventilé sur les buckets horaires UTC qu'il traverse |
| `≥ OFFLINE_AFTER_SECONDS` (le poste était *hors ligne* : éteint, en veille, ou injoignable) | **rien** |
| Écart négatif ou nul (horloge, doublon) | rien |

Une seule définition de « allumé » pour tout le produit : la pastille de la liste, le filtre `online` et ce compteur lisent la même fonction. Deux ou trois heartbeats manqués (réseau, redémarrage du serveur, back-off de l'agent) restent comptés, comme ils restent « allumé » dans la liste ; au-delà, l'écart est un trou, et le premier heartbeat après un démarrage crédite zéro — d'où la sous-estimation d'une minute par cycle, assumée en §1.

Ventilation : l'écart `[previous, now)` est découpé aux frontières d'heure pleine UTC ; chaque morceau donne `(hour_start, secondes)`. Avec `OFFLINE_AFTER_SECONDS` à 180 s c'est au plus deux morceaux, mais la fonction est écrite pour N : le réglage peut monter sur un parc lent (le commentaire de `config.py` le suggère explicitement).

Testée sans base : écart dans une heure, écart à cheval sur une frontière, écart exactement sur une frontière, écart ≥ seuil, écart négatif, `now` naïf refusé.

### `usage/models.py` — `MachineUptime`

```
machine_uptime_hourly
  machine_id   uuid  FK machines.id ON DELETE CASCADE
  hour         timestamptz   -- début d'heure pleine UTC
  seconds_on   integer NOT NULL  -- 0..3600
  PRIMARY KEY (machine_id, hour)
  INDEX ix_uptime_hour (hour)   -- la somme sur le parc balaie par fenêtre, pas par poste
```

`CHECK (seconds_on BETWEEN 0 AND 3600)` : un bucket ne peut pas contenir plus d'une heure ; la contrainte attrape un double comptage plutôt que de le laisser gonfler les chiffres en silence.

### `usage/crud.py`

- `record(session, machine_id, credits)` : un `INSERT … ON CONFLICT (machine_id, hour) DO UPDATE SET seconds_on = LEAST(3600, seconds_on + EXCLUDED.seconds_on)` par morceau — `postgresql.insert` de SQLAlchemy, jamais un SELECT-puis-UPDATE (deux heartbeats concurrents du même poste ne doivent pas se perdre).
- `seconds_by_machine(cutoff)` : la sous-requête `SELECT machine_id, SUM(seconds_on) … WHERE hour >= :cutoff GROUP BY machine_id`, réutilisée par la liste, le tri, l'export et les KPI.
- `usage_clause(hours_below, hours_above, cutoff)` : le prédicat, dans l'esprit de `low_disk_clause` — `LEFT JOIN` sur la sous-requête, `COALESCE(sum, 0)`, et pour la borne basse `Machine.first_seen <= cutoff` (§1).
- `purge_before(cutoff)` pour l'entretien.
- `usage_since(session)` : `MIN(hour)` de la table — la date à partir de laquelle les chiffres veulent dire quelque chose, servie à la console (§4).

**Fusion de postes** ([machine/crud.py `merge_into`](backend/app/features/machine/crud.py)) : les lignes du poste source sont **réattribuées** à la cible avec le même `ON CONFLICT … LEAST(3600, a + b)` — l'historique d'usage est bien de l'historique, contrairement aux mises à jour Windows en attente que la fusion abandonne. À faire dans la même transaction, avant la suppression de la source ; un test le couvre.

---

## 3. Contrat API

### Heartbeat — inchangé côté agent

Rien de nouveau dans `HeartbeatRequest`. Dans le handler, juste avant `machine.last_seen = utcnow()` :

```python
now = utcnow()
for hour, seconds in credit_for_gap(machine.last_seen, now, settings.OFFLINE_AFTER_SECONDS):
    await usage_crud.record(session, machine.id, hour, seconds)
machine.last_seen = now
```

Même `now` pour les deux : un `utcnow()` par ligne créerait un écart d'une microseconde entre ce qui est crédité et ce qui est stocké. Le crédit part dans la même transaction que le reste du heartbeat, avant le commit — la réponse est déjà construite avant le commit (piège `MissingGreenlet` noté dans le handler).

`POST /agent/enroll` ne crédite rien : `first_seen = last_seen = now`, écart nul.

### Liste des postes — `GET /machines`

| Paramètre | Type | Sens |
|---|---|---|
| `usage_days` | `int`, `ge=1, le=90`, défaut `USAGE_WINDOW_DAYS` | largeur de la fenêtre glissante |
| `usage_hours_below` | `float | None`, `ge=0` | strictement moins de X h allumé dans la fenêtre — **exclut** les postes enrôlés dans la fenêtre |
| `usage_hours_above` | `float | None`, `ge=0` | strictement plus de X h |

Les deux bornes se combinent (« entre 10 et 30 h »). Ajoutées à `MachineFilters` / `machine_filters()` / `_filtered_machines()` ([machines.py](backend/app/api/routes/machines.py)), à côté de `disk_free_below` dont elles suivent la forme. Le filtre est une **quatrième axe**, combinable avec `status`, `online`, `wu_status` : « quels postes très utilisés ont des MAJ en attente » est la question suivante.

Nouveau champ de `MachineOut` (liste **et** détail) : `usage_hours: float | None` — heures allumées sur `usage_days`, arrondies au dixième, `None` seulement quand le poste a été enrôlé dans la fenêtre (la console y écrit « depuis N j »). Toujours joint, jamais calculé par poste : la sous-requête `seconds_by_machine` entre dans le `SELECT` de la liste par `LEFT JOIN`, une agrégation pour toute la page. La réponse porte aussi `usage_days` (echo du paramètre effectif) pour que l'en-tête de colonne dise « Allumé (7 j) » sans hardcoder 7.

Tri : `MachineSortField.USAGE_HOURS` (`usage_hours`) dans `_sort_key`, `COALESCE(sum, 0)` pour que les zéros trient avec les zéros. Export ([machine_export.py](backend/app/api/machine_export.py)) : colonne `usage_hours`, groupe « Identité », non par défaut — nombre réel dans le classeur, texte dans le CSV.

### Tableau de bord — `GET /stats/overview`

```
machines_usage_low: int        # < USAGE_LOW_HOURS sur USAGE_WINDOW_DAYS, enrôlés avant la fenêtre
machines_usage_high: int       # > USAGE_HIGH_HOURS
usage_low_hours: int           # les seuils, servis (cf. low_disk_free_percent)
usage_high_hours: int
usage_window_days: int
usage_since: datetime | None   # première heure comptée ; None tant que la table est vide
```

`usage_since` est ce qui rend les cartes honnêtes la première semaine : tant que `now − usage_since < USAGE_WINDOW_DAYS`, la console affiche « comptage depuis le 12/10 » sous la carte au lieu de laisser croire que tout le parc est sous-utilisé.

### Fiche d'un poste — `GET /machines/{id}/usage?days=28`

`{ "days": 28, "total_hours": 61.4, "daily": [ { "date": "2026-09-01", "hours": 8.9 }, … ] }` — heures par **jour local** de la console : le paramètre `tz` (nom IANA, défaut `UTC`) est passé par le navigateur et résolu par le `resolve_timezone` que l'export utilise déjà pour ses horodatages. C'est le seul endroit où un jour est découpé, et il l'est à la lecture, dans le fuseau du lecteur, ce qui est la raison d'être des buckets horaires. Protégé par `MACHINE.READ` comme le reste de la fiche.

### Aucune permission nouvelle

Tout est derrière `require_permission(Resource.MACHINE, Action.READ)` — les routes `/machines` et `/stats` le portent déjà.

---

## 4. Console

### Liste des postes ([MachinesPage.vue](frontend/src/pages/MachinesPage.vue))

- Dans le panneau « Filtres », un `q-select` **« Utilisation (7 j) »** à trois valeurs : `< 10 h`, `10 – 30 h`, `> 30 h`, les nombres venant des seuils servis par `/stats/overview` (déjà chargé pour les captions de cartes) — plus un choix « Personnalisé » qui déplie deux champs numériques. Le `q-select` ne fait qu'écrire `usage_hours_below` / `usage_hours_above` dans l'URL ; c'est l'URL qui est le contrat, et le tableau de bord la fabrique directement.
- [machineQuery.ts](frontend/src/utils/machineQuery.ts) : les trois clés dans le round-trip URL ↔ `ListMachinesParams`, avec `queryInt`/`queryFloat` bornés ; `'usage_hours'` dans `MACHINE_SORT_FIELDS`.
- [machineColumns.ts](frontend/src/utils/machineColumns.ts) : colonne `usage` (« Allumé (N j) »), entre `session` et `model`, **hors** layout par défaut — c'est une colonne de campagne, pas une colonne de tous les jours ; elle s'ajoute par « Colonnes » et suit le compte. Cellule : `12,4 h`, en gris `0 h`, « depuis 2 j » pour un poste enrôlé dans la fenêtre. Pas de couleur : un poste peu allumé n'est pas une alerte, c'est une information.
- [services/machines.ts](frontend/src/services/machines.ts) : `usage_hours`, `usage_days` sur `MachineRow`, les trois paramètres sur `ListMachinesParams`.
- Export ([MachineExportDialog.vue](frontend/src/components/machine/MachineExportDialog.vue)) : rien à faire, le dialogue lit le catalogue servi par `GET /machines/export-columns` ; la colonne apparaît d'elle-même dans le groupe « Identité ».

### Tableau de bord ([DashboardPage.vue](frontend/src/pages/DashboardPage.vue))

Deux cartes dans `inventoryKpis` (« chaque carte est une liste qu'un administrateur ouvre ») :

| Carte | Valeur | Clic |
|---|---|---|
| **Peu utilisés** — « < 10 h sur 7 j » | `machines_usage_low` | `{ name: 'machines', query: { usage_hours_below: 10 } }` |
| **Toujours allumés** — « > 30 h sur 7 j » | `machines_usage_high` | `{ name: 'machines', query: { usage_hours_above: 30 } }` |

Caption orange « comptage depuis le JJ/MM » tant que la fenêtre n'est pas pleine (§3). [services/stats.ts](frontend/src/services/stats.ts) += les six champs.

### Fiche d'un poste

Nouvelle `MachineUsageCard.vue` dans l'onglet où vit `MachineStatusCard` : le total sur 28 jours et **un histogramme de barres, un jour par barre**, construit sur `GET /machines/{id}/usage` avec le fuseau du navigateur. Inline SVG ou `q-linear-progress` empilés : pas de bibliothèque de graphiques pour vingt-huit barres, le projet n'en embarque aucune. La carte se rafraîchit avec `useAutoRefresh` comme les autres.

### Réglages

Les trois seuils sont des variables d'environnement, documentées dans `deploy/.env.example`, **pas** des `app_settings` : ils n'ont pas de raison de changer sans redémarrage et ne nomment aucun compte (le critère qui a fait entrer le cycle de maintenance dans la table). Ils apparaissent dans la page Réglages via le groupe `EnvGroupOut` existant, en lecture.

---

## 5. Jalons

### J1 — Backend : comptage *(~1 j)*

- Migration `0023_machine_uptime` (`down_revision = "0022_user_preferences"`, nommage manuel, `downgrade()` implémenté) : la table, sa PK, son index sur `hour`, le CHECK.
- `features/usage/{__init__,models,accounting,crud}.py` ; `MachineUptime` importé dans [features/models.py](backend/app/features/models.py) (sinon `create_all` des tests ne la crée pas).
- Trois réglages + `USAGE_RETENTION_DAYS` dans [config.py](backend/app/core/config.py), avec le commentaire de politique qui accompagne chaque seuil de ce fichier.
- Crédit dans le heartbeat ; réattribution dans `merge_into` ; `purge_usage` accroché à `housekeeping` dans [worker.py `build_jobs`](backend/app/core/worker.py).
- Tests : `test_usage_accounting.py` (fonction pure, sans base) ; dans `test_api_agent.py`, deux heartbeats rapprochés créditent l'écart, un heartbeat après un trou ≥ `OFFLINE_AFTER_SECONDS` ne crédite rien, un écart à cheval sur une heure écrit deux lignes ; `test_api_machines_list.py`, fusion conserve la somme ; `test_worker.py`, la purge respecte la rétention. Les tests manipulent l'horloge en écrivant `machine.last_seen` directement en base (helper `_heartbeat` + `db_session` de [test_api_console.py](backend/tests/test_api_console.py)), jamais avec un `sleep`.

### J2 — Backend : lecture *(~1 j)*

- Sous-requête, filtre, `usage_hours` dans `MachineOut`, tri, export, `/stats/overview`, `/machines/{id}/usage`.
- Tests : filtre bas exclut le poste enrôlé dans la fenêtre et inclut le poste sans ligne ; bornes combinées ; tri place les `0` ensemble ; export produit un nombre ; `usage_since` vaut `None` sur table vide ; `/usage` découpe par jour dans le fuseau demandé, sur un cas qui change de jour : un bucket à 09 h UTC compte pour la *veille* à `Pacific/Tahiti` (23 h locales).
- Vérifier que le `LEFT JOIN` ne fausse pas le `COUNT` de pagination : la sous-requête est agrégée par `machine_id`, donc une ligne au plus par poste — le même raisonnement que pour l'`EXISTS` du logiciel, écrit en commentaire.

### J3 — Console *(~1,5 j)*

- Services, `machineQuery.ts` (+ spec : round-trip des trois clés, valeur hors borne ignorée), colonne (+ spec `machineColumns`), filtre, cartes, `MachineUsageCard.vue`.
- `npm run typecheck`, `format:check`, `test:coverage` verts.

### J4 — Documentation *(~0,25 j)*

- README « Fonctionnalités » : un paragraphe **Utilisation** après « Vue du parc », avec la limite (une minute par allumage, panne serveur non comptée).
- `deploy/.env.example` : les quatre variables. `backend/README.md` : le module `usage`.
- Ce plan : bannière « livré le … » et écarts constatés en §8, comme les autres plans.

Total ≈ 4 jours. J1 seul est déjà utile à déployer tôt : **le comptage commence à la mise en production du backend**, et chaque jour d'avance est un jour de données quand la lecture arrive.

---

## 6. Séquencement et conflits

- J1 puis J2 puis J3 : la console lit les champs que J2 sert. J1 peut partir en production seul.
- Fichiers touchés en commun avec d'autres chantiers : [machines.py](backend/app/api/routes/machines.py) (filtres, `MachineOut`, tri), [MachinesPage.vue](frontend/src/pages/MachinesPage.vue), [DashboardPage.vue](frontend/src/pages/DashboardPage.vue), [stats.py](backend/app/api/routes/stats.py). Ce sont les points de passage de tout chantier « un filtre, une carte » ; aucune structure n'y change, seulement des ajouts en fin de liste.
- La migration `0023` prend le numéro : tout autre chantier en cours qui en réserve un doit s'aligner.

---

## 7. Raffinements possibles (hors périmètre)

| Raffinement | Ce qu'il apporte | Ce qu'il coûte |
|---|---|---|
| **Uptime dans le heartbeat** (`uptime_seconds`, `QueryUnbiasedInterruptTime` pour exclure la veille) | Le premier heartbeat après un démarrage créditerait le temps réel depuis le boot ; une panne serveur pourrait être reconstruite (l'uptime dit si le poste est resté allumé pendant le trou). | Une version d'agent à déployer ; une règle de réconciliation entre les deux sources. Le contrat du bloc serait le même *patch conditionnel* que `defender` et `session`. |
| **Semaine calendaire** (`usage_week=2026-W39`) | Un rapport « la semaine dernière » stable d'un jour à l'autre. | Un fuseau de référence du parc (`CONSOLE_TIMEZONE`, absent aujourd'hui) — c'est la vraie question, pas le code. |
| **Profil horaire** (heatmap heure × jour de la semaine, par poste ou par salle) | Dit *quand* une salle sert, pas seulement combien — la question suivante d'un gestionnaire de salles. | Une lecture de plus sur la même table ; aucune écriture nouvelle. |
| **Extinction des postes inutilisés** | Une action groupée « éteindre les postes allumés depuis plus de X h sans session » — le filtre `usage_hours_above` + `session_user_present=false` existe déjà, l'action `shutdown` aussi. | Rien côté données ; une décision produit. |
| **Résumé quotidien** | Une ligne « N postes n'ont pas servi cette semaine » dans le digest. | La fenêtre glissante calculée à l'heure du digest. |

---

## 8. Écarts constatés à l'implémentation

*(à remplir à la livraison)*
