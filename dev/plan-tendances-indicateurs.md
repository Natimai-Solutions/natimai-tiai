# C9 — Tendances, indicateurs et pannes récurrentes : plan détaillé

> **📝 Document de travail — 2026-11-25.** Chantier C9 de `plan-evolutions-itil.md` (§4.5). Trois parties qui ne se mêlent pas : les **tendances** (une photo quotidienne des compteurs du tableau de bord, gardée par lieu ; T1 à T3), les **indicateurs** (délais et taux calculés à la lecture sur l'historique déjà en base ; I1), les **pannes récurrentes** (les interventions `incident` regroupées par modèle et par salle ; P1), plus le **rapport Excel** (R1). Agent non modifié. Migration `0060_trends`. Écarts constatés à l'implémentation en §8.

---

## 1. Ce que le chantier doit tenir

- **La portée vaut pour l'historique comme pour le présent.** Un compte limité à certains lieux voit la somme de ses lieux, jamais celle du parc ; un compte sans limite voit tout. C'est la décision du responsable du 2026-11-25, et la raison pour laquelle la photo est gardée **par lieu** et non pour le parc entier (question ouverte du §4.5 tranchée).
- **Même chiffre que le tableau de bord.** La photo d'un jour, sommée sur la portée d'un compte, est ce que `GET /stats/overview` lui aurait répondu à cet instant : mêmes clauses, postes réformés exclus de la même façon. Pas une seconde définition de « à jour » ou de « disque presque plein ».
- **Rien d'inventé.** Pas de reconstitution du passé : l'historique commence au déploiement de C9, et la console le dit (« Suivi depuis le … »). Un jour sans photo (worker arrêté) est un trou dans la courbe, pas un zéro.
- **Ce qui grandit se purge.** Photos gardées 25 mois (`TREND_RETENTION_DAYS`), ce qui permet de comparer douze mois à ceux d'avant.
- **Lecture seule.** Le chantier n'écrit rien de configurable : pas de route d'écriture, pas d'action d'audit nouvelle, pas de droit nouveau (cf. §2.4).

## 2. Tendances : la photo quotidienne

### 2.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Grain | Une ligne par **jour** et par **cellule** ; une cellule est le couple (site rapporté par l'agent `machines.location`, salle `machines.room_id`), avec le bâtiment et le site effectif de la salle **tels qu'ils étaient ce jour-là** | La portée lit exactement ces quatre valeurs (`user/scope.py`, `machine_clause` et `_room_ids_in` : `machines.location`, `rooms.id`, `rooms.building_id`, `COALESCE(buildings.location, rooms.location)`). Un poste est dans une seule cellule : pas de double compte quand le site de l'agent et celui de la salle diffèrent, et un compte limité à un bâtiment ou à une salle (pas seulement à un site) voit aussi sa juste part. « Par lieu » seul aurait perdu ces deux cas. |
| Lieu figé | Bâtiment et site de la salle recopiés dans la ligne, pas relus dans `rooms` à la lecture | Une salle déplacée ou supprimée ne réécrit pas l'histoire : un site voit ce qui était à lui ce jour-là. Une salle supprimée reste lisible par son site. |
| Compteurs | Ceux de `/stats/overview` qui sont des **nombres de postes** (ou de lignes d'un poste) : sommables cellule par cellule. Liste en §2.3. **Pas** `software_count` (programmes distincts : la somme de deux salles n'est pas le nombre de programmes des deux), ni les seuils | La somme sur la portée doit égaler le compteur du tableau de bord. |
| Seuils | Gardés une fois par jour (`trend_days.policies`) : `low_disk_free_percent`, `hardware_aging_years`, `inactive_after_days`, `signature_max_age_days`, `usage_low_hours`, `usage_high_hours`, `usage_window_days`, `agent_latest_version` | Un saut de la courbe « disque presque plein » le jour où le seuil passe de 10 à 15 % doit pouvoir s'expliquer : la console marque le changement. |
| Stockage des valeurs | Un `JSONB` `counters` par ligne, **sans les zéros** (clé absente = 0) | Une quarantaine de clés dont la plupart valent zéro dans une salle donnée ; ajouter une règle d'alerte ou un contrôle de conformité n'impose pas de migration. |
| Jour | Date locale dans le fuseau de la console (`schedule.windows.schedule_policy(...).zone`, réglage `schedules.timezone`, initialement `CONSOLE_TIMEZONE`) | Le « jour » de l'établissement, comme les planifications. |
| Fréquence | Tâche `snapshot_trends` **toutes les heures** ; elle **remplace** la photo du jour (suppression des lignes du jour puis insertion, une transaction, verrou consultatif) | Le chiffre d'un jour est le dernier pris ce jour-là (~23 h locales) ; un worker arrêté le soir laisse la photo de l'après-midi plutôt qu'un trou. Le point du jour en cours est dessiné « provisoire ». |
| Postes réformés | Exclus de tous les compteurs (`asset_crud.in_parc_clause`, `in_parc_ids_clause`), sauf `machines_retired` | Décision 5 de la feuille de route, appliquée par `/stats/overview`. |
| Reprise de l'historique | **Aucune.** La courbe commence au premier passage de la tâche | Les compteurs du tableau de bord sont un état, pas des évènements : il n'existe rien à relire pour savoir combien de postes avaient un disque plein en mars. |
| Fusion de postes | Rien à faire : les photos ne référencent aucun poste | `merge_into` n'est pas modifié ; un test le constate. |
| Conservation | `TREND_RETENTION_DAYS` = 760 (25 mois), purge quotidienne | Douze mois affichés, douze mois de comparaison. |

### 2.2 Modèle (migration `0060_trends`, `down_revision = "0059_webhooks_api_tokens"`)

Nouveau module `backend/app/features/trend/` (`models.py`, `snapshot.py`, `crud.py`, `indicators.py`, `failures.py`, `report.py`).

- **`trend_days`** : `day` (`DATE`, clé primaire), `taken_at` (horodatage UTC de la dernière prise), `zone` (`VARCHAR(64)`, le fuseau qui a fixé le jour), `policies` (`JSONB NOT NULL`, `server_default '{}'::jsonb`).
- **`trend_snapshots`** : `id` (UUID), `day` (`DATE NOT NULL`, FK `trend_days.day` `ON DELETE CASCADE`), `location` (`VARCHAR(255) NULL`, `machines.location`), `room_id` (`UUID NULL`, **sans clé étrangère** : la salle peut disparaître, la ligne reste), `building_id` (`UUID NULL`, idem), `site` (`VARCHAR(255) NULL`, site effectif de la salle ce jour-là), `counters` (`JSONB NOT NULL`, `server_default '{}'::jsonb`).
  - Index unique `uq_trend_snapshots_cell` sur (`day`, `location`, `room_id`) avec `postgresql_nulls_not_distinct=True` (la forme déjà employée par `room/models.py` ; PostgreSQL 16 en production).
  - Index `ix_trend_snapshots_day` sur `day` (lecture d'une période, purge).
- **Index ajoutés aux tables existantes**, pour les indicateurs (§3) : `ix_interventions_kind_performed` (`kind`, `performed_at`), `ix_machine_checks_closed_at` (`closed_at`), `ix_commands_finished_at` (`finished_at`). Pas de colonne nouvelle sur ces tables.
- Taille attendue : quelques centaines de cellules × 760 jours, chaque ligne ne portant que ses compteurs non nuls.

### 2.3 Compteurs photographiés

Une seule définition, partagée avec le tableau de bord : nouveau module `backend/app/features/stats/counters.py`, qui expose `machine_counters(now, policies, fleet) -> dict[str, ColumnElement[bool]]` — un prédicat par compteur sur la jointure `machines ⟕ rooms ⟕ usage_seconds`, repris tel quel de `api/routes/stats.py` (`status_clause`, `reenroll_pending_clause`, `low_disk_clause`, `asset_crud.aging_clause`, l'`EXISTS` sur `Volume` avec `FULLY_ENCRYPTED`, `agent_outdated_clause(fleet.outdated, True)`, `maintenance_policy.state_clause`, `usage_crud.usage_clause`, `win11.blocked_clause`, `compliance_crud.filter_clause`, `asset_crud.retired_clause`).

- `overview` est réécrit pour compter ces prédicats en **une** requête (`count(*) FILTER (WHERE …)`) ; sa réponse ne change pas (les tests existants de `/stats/overview` restent tels quels).
- `trend.snapshot.take(session, now)` fait la même requête **groupée par cellule** (`GROUP BY machines.location, machines.room_id`, plus `rooms.building_id` et le site effectif), puis une seconde pour les deux répartitions (`alerts.<règle>` sur `machine_alerts` ouvertes, `compliance.<contrôle>` sur `machines.compliance_failed`).

Clés : `total`, `up_to_date`, `needs_verification`, `inactive`, `with_active_threats`, `machines_wu_pending`, `machines_reboot_required`, `machines_low_disk`, `machines_unencrypted`, `machines_aging`, `machines_agent_outdated`, `open_checks`, `machines_maintenance_overdue`, `machines_maintenance_due_soon`, `machines_usage_low`, `machines_usage_high`, `machines_reenroll_pending`, `machines_token_revoked`, `machines_with_alerts`, `machines_win11_blocked`, `machines_compliant`, `machines_noncompliant`, `machines_retired`, `alerts.<règle>` (chaque valeur de `ALL_RULES`), `compliance.<contrôle>` (chaque contrôle de `compliance/checks.py`). `outdated` n'est pas gardé : c'est `total − up_to_date`, recalculé. Les deux répartitions donnent enfin l'historique de la conformité que C5 renvoyait à C9 (§8 de la feuille de route).

`open_checks` et `with_active_threats` comptent, comme aujourd'hui, une vérification ouverte par poste au plus (`uq_machine_checks_open`) et des postes distincts : tous deux sont des nombres de lignes d'un poste, donc sommables.

### 2.4 Portée à la lecture

`trend.crud.cell_clause(scope)` : `None` sans limite ; sinon `location IN L OR site IN L OR building_id IN B OR room_id IN R` — la traduction littérale de `machine_clause` + `_room_ids_in` sur les colonnes figées. Une portée vide ne voit rien (`false()`), comme `machine_clause`.

### 2.5 API

Sous le routeur existant `api/routes/stats.py` (préfixe `/stats`, droit `machine:read` déjà posé sur le routeur).

- **`GET /stats/trends?months=12&step=week&keys=…`** — `months` 1 à 24 (défaut 12), `step` `day` ou `week` (défaut `week` au-delà de 3 mois : le dernier jour photographié de chaque semaine ISO), `keys` facultatif (liste séparée par des virgules, prise dans le catalogue des clés ; une clé inconnue → 422 de validation, comme `exact=` de la liste des postes). Réponse : `days` (dates), `series` (`{clé: [entier | null]}`, `null` = pas de photo ce jour-là), `provisional_day` (le jour en cours s'il figure), `since` (premier jour photographié, `null` s'il n'y en a aucun), `policy_changes` (jours où un seuil de `trend_days.policies` a changé, avec l'ancienne et la nouvelle valeur). Somme en SQL : `jsonb_each_text(counters)` groupé par jour et clé, sous `cell_clause(scope)`.
- **Droits** : `machine:read`, comme le tableau de bord. Pas de ressource nouvelle (cf. décisions par défaut).
- **Audit** : aucune action (lecture). **Codes d'erreur** : aucun nouveau ; les bornes sont des 422 de validation, déjà mis en mots par la console (`validationTexts`).

## 3. Indicateurs (calculés à la lecture)

### 3.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Source | Les tables d'historique elles-mêmes, agrégées **par mois** (fuseau de la console) sur la période demandée | Ce sont des évènements datés, déjà en base : pas besoin de photo, et l'indicateur a un passé dès le premier jour (dans la limite des conservations ci-dessous). |
| Portée | `machine_ids_clause(scope, <table>.machine_id)` sur chaque agrégat | Règle commune §2. |
| Postes réformés | Exclus (`asset_crud.in_parc_ids_clause`) | Comme le tableau de bord ; un indicateur et une carte ne doivent pas parler de deux parcs. |
| Délai de clôture des vérifications | `machine_checks` closes dans le mois (`closed_at`) : nombre, **médiane** et **9e décile** de `GREATEST(closed_at − created_at, 0)` en heures (`percentile_cont`), et, pour celles qui avaient une échéance (`due_date`, C4), part closes au plus tard ce jour-là. Exclues : les clôtures par fusion (`closing_note_code = check_crud.CLOSED_BY_MERGE`) | Une moyenne est tirée par la vérification oubliée six mois ; la médiane et le 9e décile disent « d'habitude » et « au pire ». `closed_at` peut être antidaté (`PastDatetime`) : borné à zéro. |
| Maintenances faites à l'heure | Lignes `interventions` de type `maintenance` du mois ; à l'heure si `performed_at` ≤ référence + cycle, où la référence est la maintenance précédente du poste (`LAG(performed_at)` sur **tout** son journal, calculé avant le filtre de période), à défaut `machines.first_seen`, et le cycle celui que résout `maintenance_policy.cycle_expr(policy)` (poste, salle, parc). Cycle ≤ 0 : poste exclu. Les lignes « Maintenance non faite » (type `other`, `title_code = maintenance.skipped`) ne comptent pas | C'est la règle même de `maintenance/policy.py` (`reference = last_maintenance_at ?? first_seen`), rejouée ligne par ligne. Le cycle est celui d'aujourd'hui (pas d'historique des cycles) : dit sous l'indicateur. |
| Réussite des commandes | Commandes terminées dans le mois (`COALESCE(finished_at, expires_at)`), hors types serveur (`SERVER_ONLY_COMMAND_TYPES`) et hors clôtures dues à un geste d'opérateur (`result_code` dans `command.merged`, `package.deleted`, `package.retired`, `package.retired_after_queue`, `package.changed_after_queue`, `package.superseded`, `directory.not_reader`, constante `trend.indicators.OPERATOR_CLOSURES`). Taux = `succeeded / (succeeded + failed)` ; les `expired` (jamais délivrées, poste éteint) comptés à part | Une commande jamais délivrée ne dit rien de ce que fait la commande ; la mêler au taux ferait d'un parc éteint pendant les vacances un parc en échec. Les clôtures d'opérateur reprennent la liste que `command.failed` (C8) écarte déjà. |
| Réussite des déploiements | Même calcul sur `PACKAGE_COMMAND_TYPES`, séparé en « directs » et « en anneaux » (`commands.schedule_stage IS NOT NULL`) ; plus, pour un compte sans limite qui lit les planifications, le nombre d'exécutions en anneaux arrêtées (`schedule_runs.status = 'halted'`) | Le taux par commande respecte la portée ; une exécution de planification couvre plusieurs lieux, d'où sa réserve aux comptes sans limite. |
| Profondeur | 12 mois par défaut, 24 au plus ; la console signale quand `COMMAND_RETENTION_DAYS` (365) ou `SCHEDULE_RUN_RETENTION_DAYS` (180) est plus court que la période (« historique conservé : 180 jours ») | Ces tables sont purgées ; l'indicateur ne doit pas faire croire à un mois sans commande. |

### 3.2 API

**`GET /stats/indicators?months=12`** (routeur `/stats`, `machine:read`). Réponse : `months` (liste `AAAA-MM`), puis une section par indicateur, chacune **`null` si le compte n'a pas le droit de sa source** :

| Section | Droit en plus de `machine:read` | Champs par mois |
|---|---|---|
| `checks` | `check:read` | `closed`, `median_hours`, `p90_hours`, `with_due`, `on_time_due` |
| `maintenance` | `maintenance:read` | `done`, `on_time` |
| `commands` | `command:read` | `succeeded`, `failed`, `expired` |
| `deployments` | `command:read` et `package:read` | `direct` et `rings` : `succeeded`, `failed`, `expired` ; `halted_runs` (`null` pour un compte limité ou sans `schedule:read`) |

Plus `retention` : `{commands_days, schedule_runs_days}` pour l'avertissement de la console. Aucune action d'audit, aucun code d'erreur nouveau.

## 4. Pannes récurrentes

### 4.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Source | `interventions` de type `incident` (`InterventionKind.INCIDENT`) sur la période (`performed_at`) | Ce que demande la feuille de route. Les vérifications de catégorie « matériel » ne sont pas des pannes constatées. |
| Regroupements | Par **modèle** (`machines.hw_model`, NULL → « Modèle inconnu ») et par **salle** (salle **actuelle** du poste, `machines.room_id`, avec son bâtiment ; sans salle → « Sans salle ») | L'intervention ne garde pas la salle du jour ; la salle actuelle répond à la question posée (« où ça casse »). Dit sous le tableau. |
| Mesures | `incidents`, `machines` (postes distincts touchés), `parc` (postes de ce modèle ou de cette salle aujourd'hui, dans la portée, hors réformés), `per_100` (incidents pour 100 postes), `last_at` | « Douze pannes sur le même modèle » ne dit rien sans le nombre de postes de ce modèle. |
| Postes réformés | **Comptés** dans les incidents, avec `retired_machines` à part | Un modèle qui casse au point d'être réformé est précisément l'information d'achat cherchée. Seule exception à la règle des réformés, dite dans la console. |
| Seuil | `min_incidents` (défaut 2) : un modèle à une seule panne n'est pas « récurrent » | Sinon la liste est l'inventaire des modèles. |
| Portée | `machine_ids_clause(scope, Intervention.machine_id)` ; pour le regroupement par salle, seules les salles de la portée sont nommées (`room_clause`) | Règle commune. |

### 4.2 API

**`GET /stats/recurring-failures?months=12&by=hw_model|room&min_incidents=2&limit=50`** (routeur `/stats`, `machine:read` **et** `intervention:read`, sinon 403 habituel). Lignes triées par `incidents` décroissant puis `per_100`. Pour `by=room` : `room_id`, `room_name`, `building_name`. Liens de la console : `/machines?hw_model=<modèle>&exact=hw_model` (filtre existant de la liste) ou `/machines?room_id=<id>`.

## 5. Rapport Excel

| Sujet | Choix | Pourquoi |
|---|---|---|
| Forme | **`GET /stats/report.xlsx?months=12&lang=fr|en&tz=…`**, téléchargé depuis la page Tendances | « Excel d'abord ». Pas d'envoi par e-mail : l'outbox ne porte pas de pièce jointe (hors périmètre). |
| Générateur | `api/xlsx_export.py` étendu : `xlsx_workbook_bytes(sheets: Sequence[Sheet])` (plusieurs feuilles, mêmes règles : cellules texte forcées, caractères illégaux retirés, dates natives, largeurs bornées) ; `xlsx_bytes` devient un appel à une feuille ; `xlsx_response` reste construit dans un fil (`asyncio.to_thread`) | Le même rempart contre les formules (`=HYPERLINK` dans un nom de modèle) et contre le gel de la boucle. |
| Feuilles | « Parc » (une ligne par mois : valeur du dernier jour photographié de chaque compteur principal), « Indicateurs », « Pannes par modèle », « Pannes par salle » ; une feuille n'apparaît que si le compte lit sa source (mêmes droits qu'en §3.2 et §4.2) | Le classeur voyage plus loin que la console : il ne contient que ce que son auteur voit. |
| Langue, fuseau | `lang` et `tz` comme l'export des postes (`ExportLanguage`, `machine_export.resolve_timezone`) ; textes dans `trend/report.py` (`REPORT_TEXTS[lang]`) | Plan console bilingue. |
| Audit | Aucun, comme les exports de postes et de logiciels | Lecture. |

## 6. Worker, configuration et console

### 6.1 Worker et configuration

- **`snapshot_trends`** : `Job("snapshot_trends", snapshot_trends, now, every(3600))` dans `core/worker.py` `build_jobs` ; ouvre sa session, prend `pg_advisory_xact_lock` sur une clé propre (deux workers ne photographient pas en même temps), appelle `trend.snapshot.take`, valide. Renvoie le nombre de cellules.
- **`purge_trends`** : sur `housekeeping` (8 h UTC, comme les autres purges) ; supprime de `trend_days` les jours antérieurs à `aujourd'hui − TREND_RETENTION_DAYS` (cascade sur `trend_snapshots`).
- **Variable** : `TREND_RETENTION_DAYS: int = Field(default=760, ge=400, le=3650)` dans `core/config.py`, avec son commentaire ; `deploy/.env.example` (commentée), `DEPLOYMENT.md` (section des conservations, à côté de `USAGE_RETENTION_DAYS` et `ALERT_RETENTION_DAYS`), et l'aperçu de l'environnement de Paramètres (`setting/environment.py`, `settingsEnv.ts` FR/EN). Le minimum de 400 jours garantit les douze mois affichés. Pas de réglage dans `app_settings` : rien à arbitrer depuis la console.

### 6.2 Console

- **Page « Tendances »** (`frontend/src/pages/TrendsPage.vue`, route `trends` à `/trends`, `requiresPermission: 'machine:read'`, titre `layout.pages.trends`) ; entrée de menu dans `MainLayout.vue` juste sous « Tableau de bord », visible avec `machine:read` ; ajoutée à `router/access.ts`. Pas sur le tableau de bord lui-même, qui reste un instantané qui se charge vite : il gagne seulement un lien « Évolution » dans sa barre de titre.
- **Bloc « Évolution du parc »** : sélecteur de période (3, 12, 24 mois), puces des séries (par défaut : postes, à jour, avec menace active, avec alerte, non conformes, maintenance en retard, vérifications ouvertes), courbe ; sous la courbe « Suivi depuis le … » et les changements de seuil. Bouton « Voir les chiffres » : la même donnée en tableau (accessibilité, et ce que lisent les tests).
- **Graphique** : aucune bibliothèque de graphiques dans `frontend/package.json` ; un composant SVG simple, `components/trends/TrendChart.vue` (polylignes, axe des dates, trous pour les `null`, point provisoire en pointillé, info-bulle au survol), couleurs prises dans les variables du thème Quasar pour le mode sombre. Pas de dépendance nouvelle.
- **Bloc « Indicateurs »** (`components/trends/IndicatorsCard.vue`) : une carte par section non nulle ; chiffre du dernier mois complet, petit histogramme des mois en SVG, et l'avertissement de conservation quand il s'applique.
- **Bloc « Pannes récurrentes »** (`components/trends/RecurringFailuresCard.vue`, affiché avec `intervention:read`) : bascule « Par modèle / Par salle », tableau triable, lien vers la liste des postes filtrée.
- **Bouton « Rapport Excel »** : télécharge `report.xlsx` dans la langue et le fuseau de la console, comme l'export des postes.
- **Service** `services/trends.ts` (`getTrends`, `getIndicators`, `getRecurringFailures`, `downloadReport`) ; **catalogue** `i18n/messages/trends.ts` FR/EN enregistré dans `index.ts` (libellés des séries, des sections, des règles et contrôles repris de `alerts.ts` et `compliance.ts` plutôt que recopiés) ; `layout.ts` gagne `pages.trends`.
- Comptes limités : rien de différent à afficher, la somme est déjà la leur ; une phrase sous la courbe le rappelle (« Postes de votre périmètre »).

## 7. Jalons, tests et décisions

### 7.1 Jalons

| Jalon | Contenu |
|---|---|
| T1 | `features/stats/counters.py`, `overview` réécrit en une requête, réponse identique. |
| T2 | Migration `0060_trends`, modèle, `snapshot.take`, tâches `snapshot_trends` et `purge_trends`, `TREND_RETENTION_DAYS`. |
| T3 | `GET /stats/trends`, `cell_clause`, page Tendances (courbe, tableau, lien du tableau de bord). |
| I1 | `GET /stats/indicators`, index, carte des indicateurs. |
| P1 | `GET /stats/recurring-failures`, carte des pannes. |
| R1 | `xlsx_workbook_bytes`, `GET /stats/report.xlsx`, bouton. Docs (`DEPLOYMENT.md`, `.env.example`, `README.md` : ligne « Tendances, indicateurs… » de la feuille de route), notes de version. |

### 7.2 Tests

**Serveur** (`tests/test_trends.py`, `tests/test_indicators.py`, `tests/test_recurring_failures.py`, `tests/test_trend_report.py`, compléments de `test_worker.py`) :

- **Parité** : pour un parc construit avec des postes dont le site d'agent et celui de la salle diffèrent, des salles dans un bâtiment et hors bâtiment, un poste sans lieu, un réformé, des alertes, des menaces et des vérifications ouvertes : après `snapshot.take`, la somme des cellules sous `cell_clause` égale `GET /stats/overview` (hors `software_count`, `outdated` recalculé) pour un compte sans limite, limité à un site, à un bâtiment, à une salle, et à un site et une salle qui se recouvrent (pas de double compte).
- `overview` inchangé : les tests existants passent sans modification ; un test compte les requêtes (une pour les compteurs de postes).
- Zéros absents de `counters` ; deuxième passage du même jour : remplace, ne duplique pas ; poste changé de salle dans la journée : dans la seule nouvelle cellule ; jour pris dans le fuseau de la console (passage de minuit à Tahiti contre UTC).
- Lieu figé : salle déplacée dans un autre bâtiment puis supprimée après la photo : l'ancien bâtiment voit toujours l'historique, le nouveau non.
- `trend_days.policies` gardé ; `policy_changes` signale un seuil modifié entre deux jours.
- `GET /stats/trends` : droit `machine:read` (403 sans) ; jour manquant → `null` ; `step=week` prend le dernier jour présent de chaque semaine ; `months` hors de 1 à 24 et clé inconnue → 422 ; `since` nul sans photo ; portée vide → séries vides.
- Purge : jours plus vieux que `TREND_RETENTION_DAYS` supprimés avec leurs cellules, les autres gardés ; `build_jobs` contient `snapshot_trends` (horaire) et `purge_trends` (quotidienne) ; deux prises simultanées sérialisées par le verrou.
- Fusion : `merge_into` ne touche pas aux photos.
- **Indicateurs** : médiane et 9e décile sur des délais connus ; clôture par fusion exclue ; clôture antidatée avant la création bornée à zéro ; échéance respectée ou non ; vérification d'un poste hors portée ou réformé non comptée ; section `null` sans `check:read`. Maintenance : première ligne comparée à `first_seen`, suivantes à la précédente (y compris une précédente hors période), cycle de la salle et du poste, cycle 0 exclu, lignes « non faite » ignorées. Commandes : `expired` à part et hors taux, types serveur et clôtures d'opérateur exclus, mois pris sur `expires_at` pour une expirée ; déploiements séparés directs / anneaux ; `halted_runs` nul pour un compte limité.
- **Pannes** : regroupement par modèle (modèle inconnu), par salle (sans salle), seuil `min_incidents`, `per_100` sur le parc de la portée, réformés comptés et signalés, salle hors portée jamais nommée, 403 sans `intervention:read`, liens `hw_model` exacts.
- **Rapport** : feuilles selon les droits (un compte sans `check:read` n'a pas la ligne des vérifications) ; en-têtes anglais avec `lang=en` ; un modèle nommé `=HYPERLINK(…)` écrit en texte ; `xlsx_bytes` d'une feuille inchangé (tests existants d'`test_export_injection.py`).
- **Migration** : `tests/test_migration_0060.py` : montée et descente, index uniques avec NULL non distincts.

**Console** (Vitest) :

- `TrendsPage.spec.ts` / `.en.spec.ts` : chargement des trois blocs ; changement de période relance la requête ; carte des indicateurs absente quand la section est `null` ; carte des pannes absente sans `intervention:read` ; tableau « Voir les chiffres » ; avertissement de conservation ; bouton du rapport (langue et fuseau passés).
- `TrendChart.spec.ts` : trous pour `null`, point provisoire, une série vide n'affiche pas d'axe faux, rendu avec une seule journée.
- `RecurringFailuresCard.spec.ts` : bascule modèle / salle, lien vers `/machines?hw_model=…&exact=hw_model`, « Modèle inconnu ».
- `services/trends.spec.ts` ; `routes.spec.ts` et `access.ts` (page ouverte avec `machine:read`) ; `MainLayout.spec.ts` (entrée du menu) ; `DashboardPage.spec.ts` (lien « Évolution ») ; catalogue FR/EN complet (test de parité des clés existant).

### 7.3 Décisions prises par défaut (à confirmer)

1. **Cellule = (site de l'agent, salle)** avec bâtiment et site de la salle figés, plutôt que le seul site : c'est ce qu'il faut pour que les portées par bâtiment et par salle, et les postes dont les deux sites diffèrent, reçoivent leur juste somme. C'est une précision de la décision « par lieu », pas un retour dessus.
2. **Pas de droit nouveau** : tendances sous `machine:read` comme le tableau de bord ; chaque indicateur sous le droit de lecture de sa source ; pannes sous `intervention:read`.
3. **Photo horaire, dernière du jour retenue** ; jour au fuseau de la console.
4. **Conservation 760 jours** (`TREND_RETENTION_DAYS`, minimum 400) ; affichage 12 mois par défaut, 24 au plus ; points hebdomadaires au-delà de 3 mois.
5. **Indicateurs calculés à la lecture** sur les tables existantes, limités par leurs conservations (commandes 365 j, exécutions 180 j), sans table d'agrégats.
6. **Taux de réussite = réussies / (réussies + échouées)** ; expirées à part ; clôtures d'opérateur et commandes serveur exclues.
7. **Maintenance « à l'heure »** jugée avec le cycle d'aujourd'hui.
8. **Postes réformés** : exclus des tendances et des indicateurs, **comptés** dans les pannes récurrentes.
9. **Pannes par salle actuelle** du poste ; seuil de 2 incidents.
10. **Rapport à la demande** (téléchargement), pas d'envoi périodique par e-mail.
11. **Page dédiée « Tendances »** plutôt qu'un agrandissement du tableau de bord ; graphique en SVG maison, sans dépendance.

### 7.4 Hors périmètre

- Reprise de l'historique antérieur au déploiement (impossible pour des états) ; photo du parc entier « hors portée ».
- PDF et envoi du rapport par e-mail ou par webhook (l'outbox ne porte pas de pièce jointe) ; une section « tendances » du résumé quotidien.
- Indicateurs par personne (délai de clôture d'un technicien) : ce n'est pas l'objet, et un classement des agents serait une donnée personnelle de plus.
- Historique des cycles de maintenance et des salles des interventions (colonnes nouvelles sur `interventions`).
- Nombre de logiciels distincts dans le temps (non sommable par lieu).
- Seuils d'alerte sur une tendance (« le nombre de disques pleins a doublé ») : à rouvrir avec C1 si le parc le demande.

## 8. Écarts constatés à l'implémentation

*(à remplir)*
