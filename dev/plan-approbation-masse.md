# C10 — Approbation à deux des actions de masse : plan détaillé

> **📝 Document de travail — 2026-11-25.** Chantier C10 de `plan-evolutions-itil.md` (§4.6). Au-delà de N postes, une commande à risque n'est pas mise en file : elle devient une **demande** qu'un second compte, détenant les mêmes droits et voyant les mêmes postes, approuve ou refuse. Désactivée par défaut. Elle porte sur les commandes envoyées à la main (`POST /commands`, déploiements de paquets compris) et sur les planifications de C3 (anneaux compris) : on approuve **la planification**, pas chacune de ses exécutions. Migration `0061_mass_approval`. Jalons, tests et limites en §7 ; les écarts constatés à l'implémentation vont en §8.

---

## 1. Ce que le chantier doit tenir

- **Ce qui est approuvé est ce qui part.** La demande garde la requête exacte (type, paquet et son empreinte, liste figée des postes, durée de vie) ; l'approbation exécute cette liste-là, rien de plus. Un poste ajouté au domaine entre-temps n'est pas visé ; un paquet modifié entre-temps fait échouer la demande.
- **Tout est revérifié au moment d'approuver**, comme C3 le fait à chaque exécution (`schedule/runner.py`, `check_author`) : le compte de l'auteur est actif et a encore ses droits, la cible est dans sa portée du moment, le paquet est toujours déployable (`command/dispatch.py`, `deployable_package`), les plages interdites (`schedule/windows.py`) s'appliquent à l'heure de l'approbation.
- **Deux personnes, pas deux sessions.** L'approbateur est un autre compte (identifiant différent), qui détient les mêmes droits que ceux que l'action demande et dont la portée couvre tous les postes visés. Une approbation ne se fait pas par jeton d'API.
- **Jamais bloquant par surprise.** Désactivée par défaut ; impossible à activer s'il n'existe pas au moins deux comptes capables d'approuver ; une demande que personne d'autre ne peut approuver est refusée à la création avec un message qui le dit, plutôt que de rester en attente jusqu'à expiration.
- **Rien n'est perdu ni rejoué.** Une demande se décide une seule fois (verrou de ligne) ; elle expire ; son auteur peut l'annuler ; chaque transition est journalisée dans la transaction qui la fait.
- **Invariants du produit** (§2 de la feuille de route) : catalogue de commandes inchangé, serveur qui ne contacte jamais un poste, portée respectée par toute lecture (liste, compteur du badge, e-mail), `audit.record` dans la transaction de l'appelant, réglages dans `app_settings` servis à la console, textes codés en deux langues, purge de ce qui grossit.

---

## 2. Décisions

### 2.1 Ce qui est soumis à approbation

| Sujet | Choix | Pourquoi |
|---|---|---|
| Types concernés | Exactement `RISKY_COMMAND_TYPES` (`command/models.py`) : `reboot`, `shutdown`, `wu_install`, `wu_install_full`, `wu_reset`, `spooler_reset`, `dism_restore_health`, `dism_component_cleanup`, `package_install`, `package_uninstall` ; plus toute planification avec « éteindre ensuite » (`shutdown_after`), que C3 traite déjà comme à risque (`runner.required_permissions`). | La feuille de route dit « commande à risque », et le produit en a une définition unique, celle qui demande `risky_command:execute`. Pas de seconde liste à tenir. |
| Déploiements de paquets | Concernés : ils passent par `POST /commands` (il n'y a pas de route de déploiement dans `api/routes/packages.py`, `PackageDeployDialog.vue` appelle `createCommands`) et leurs deux types sont à risque. Les routes de composition du catalogue (`/packages`, fichiers, signature, retrait) ne le sont pas : elles ne touchent aucun poste. | Installer sur tout le parc est l'action de masse type. Le retrait d'un paquet *annule* des installations, il n'en crée pas. |
| Non concernés | Le réveil (`POST /machines/wake`, `machine.wake_bulk`, droit `command:execute` seul), les commandes courantes (analyses, diagnostics, `gpo_update`…), les types du serveur (`directory_read`), l'arrêt que le runner met en file pour « éteindre ensuite » d'une planification déjà approuvée. | Rien de cela n'est « à risque » au sens du produit ; « éteindre ensuite » est couvert par l'approbation de la planification qui le porte. |
| Seuil | Strictement plus de N postes, N = réglage `approvals.threshold` (défaut **40**, de 2 à 10 000). Compté **après** résolution de la cible dans la portée de l'auteur et retrait des postes au jeton révoqué : la liste `machine_ids` que `create_commands` passerait à `dispatch.queue`. Les postes qui ont déjà la commande en cours (les futurs `skipped`) comptent. | 40 laisse passer une salle (15 à 35 postes), soit le dépannage courant, et arrête un bâtiment ou le parc. Compter ce qui serait réellement visé, pas ce qui est demandé : « tout le parc » vu d'un compte limité à un site, c'est ce site. |
| Un seul poste | Jamais soumis, quel que soit N (N ≥ 2). | Le dépannage reste libre, comme pour les plages interdites (C3). |
| Planifications | Approuvées **à l'écriture** (création, modification, réactivation), une fois pour toutes les exécutions et toutes les étapes d'anneaux. Le nombre de postes est la réunion des cibles de toutes les étapes, résolue à l'écriture dans la portée de l'auteur. | « Approuver la planification, pas chaque déclenchement » : un déploiement hebdomadaire approuvé ne doit pas réclamer quelqu'un chaque mercredi à 18 h. |
| Planification qui grossit | Garde à l'exécution : une planification à risque **jamais approuvée** dont une étape résout plus de N postes, approbation activée, est suspendue (`suspended_code = approval_required`) par le chemin existant (`runner._suspend` : journal `schedule.suspend`, e-mail à l'auteur). Une planification approuvée n'est pas re-comptée. | Couvre deux cas sans mécanisme de plus : les planifications écrites avant l'activation du réglage, et une cible « salle » ou « domaine » qui a grandi au-delà du seuil. La réactiver passe par l'approbation. |
| Réglage désactivé après coup | Les demandes en attente restent décidables (approuver, refuser, annuler) jusqu'à leur expiration ; aucune nouvelle demande n'est créée. Les planifications approuvées gardent leur approbation. | Couper le réglage ne doit ni exécuter d'un coup ce que personne n'a approuvé, ni jeter le travail d'un collègue. |

### 2.2 Qui approuve, et comment

| Sujet | Choix | Pourquoi |
|---|---|---|
| Droit | Aucun droit nouveau dans `PERMISSION_CATALOGUE`. Approuver une commande demande `command:execute` **et** `risky_command:execute` ; approuver une planification demande en plus `schedule:write` — exactement `runner.required_permissions(schedule)`. | « Un second compte qui détient le même droit. » Un droit « approuver » séparé permettrait d'approuver ce qu'on ne pourrait pas faire soi-même. |
| Portée | L'approbateur doit voir **chaque** poste de la liste figée (`user/scope.py`, `machine_in_scope` sur les lieux de `room_places`). Pour une planification : la règle de lecture des planifications (`api/routes/schedules.py`, `_visible`), qui demande un compte sans limite pour une cible « tout le parc / domaine / emplacement / état ». `_visible` est déplacée dans `schedule/crud.py` (`visible_to`) pour servir aux deux. | On n'approuve pas un redémarrage de postes qu'on ne voit pas ; et la règle de visibilité des planifications existe déjà, il ne faut pas en écrire une seconde. |
| Pas soi-même | `approver.id != request.requested_by_id`. Pour une planification, l'approbateur ne peut pas non plus être celui qui la réactive ensuite sans nouvelle approbation (§2.4). | Deux personnes. |
| Pas par jeton d'API | Approuver et refuser dépendent de `CurrentAuthSession` (`api/deps.py`) : un jeton reçoit `api_token.forbidden_here`. Créer une demande ou annuler la sienne reste possible par jeton en écriture. | L'approbation est un geste humain ; un script qui approuve ce qu'un autre script demande annule la règle. |
| Mot de passe ou second facteur à l'approbation | Non demandés. | Le contrôle porte sur « une seconde personne », que la session authentifiée établit déjà ; rejouer le mot de passe à chaque approbation pèserait sur l'usage quotidien. Cf. Hors périmètre. |
| Activation du réglage | Refusée (`approval.not_enough_approvers`, 422, `details.eligible`) tant que moins de **deux** comptes actifs détiennent `command:execute` et `risky_command:execute` (administrateurs compris). La carte de Paramètres affiche ce nombre. | « Dans un établissement à un seul administrateur, elle bloquerait tout » : on ne la laisse pas s'activer là. |
| Demande sans approbateur possible | Refusée à la création (`approval.no_approver`, 409) s'il n'existe aucun autre compte actif détenant les droits et couvrant tous les postes (ou voyant la planification). | Un compte de l'annexe limité à son site, seul à pouvoir voir ses postes, sinon attendrait une approbation impossible. Le message dit les deux issues : viser moins de postes, ou qu'un administrateur ajuste les groupes ou le réglage. |
| Expiration | `approvals.ttl_hours`, défaut **24 h** (1 à 168). Pour une planification ponctuelle : au plus tard à son `run_at`. Expirée par le worker et à la lecture. | Une demande de la veille au soir doit pouvoir être approuvée le matin ; une demande d'une semaine n'a plus de sens (le parc a changé). |
| Annulation | Par son auteur seul, tant qu'elle est en attente. | Il a changé d'avis ou s'est trompé de cible. |
| Refus | Par tout compte qui pourrait l'approuver, avec un motif facultatif (500 caractères), transmis à l'auteur. | Le refus est aussi une décision à deux. |
| Concurrence | Approuver, refuser, annuler, expirer verrouillent la ligne de la demande (`SELECT … FOR UPDATE`) et exigent `status = pending`, sinon `approval.not_pending` (409). L'approbation d'un déploiement prend en plus le verrou du paquet (`package_crud.locked`, via `deployable_package`) ; celle d'une planification, la ligne de la planification. | Une demande ne se décide qu'une fois ; deux approbateurs simultanés ne mettent pas deux fois en file. |
| Doublon | Une demande en attente du même auteur, de même type, même paquet et même ensemble de postes est renvoyée telle quelle (même identifiant) au lieu d'en créer une seconde. Au plus **20** demandes en attente par auteur (`approval.too_many_pending`). | Le bouton pressé deux fois, comme `skipped` pour les commandes. |

### 2.3 Ce qui est revérifié à l'approbation d'une commande

Dans cet ordre, dans la transaction de l'approbation :

1. Demande en attente, non expirée (sinon `approval.not_pending`).
2. L'approbateur n'est pas l'auteur (`approval.own_request`, 403), détient les deux droits (`auth.permission.denied` habituel), voit tous les postes encore existants de la liste (sinon `approval.not_found` : il ne devait pas la voir).
3. L'auteur : existe, est actif, détient encore `command:execute` et `risky_command:execute` — sinon la demande est **close en échec** (`status = failed`, `result_code` = `author_gone` | `author_inactive` | `permission_lost`, les codes de C3) et la route répond `approval.author_not_allowed` (409, `details.cause`).
4. Le paquet (déploiements) : `dispatch.deployable_package` (retiré, incomplet, supprimé → l'erreur de paquet habituelle, demande close en échec) puis l'empreinte `package_crud.fingerprint(package, files)` comparée à `package_digest` de la demande : différente → `approval.package_changed` (409), demande close en échec.
5. La cible : `target.resolve(Target("machines", liste figée), scope_de_l_auteur_maintenant)`, sans les jetons révoqués. Ce qui sort de la liste est compté `left_out`. Plus rien → `approval.nothing_left` (409), demande close en échec.
6. Plage interdite **à l'instant de l'approbation** : `windows.require_outside_forbidden(session, now, confirmed=body.confirm_forbidden_window)` — l'approbateur voit le même avertissement que l'auteur (`command.forbidden_window`, la demande reste en attente). Ce que l'auteur avait confirmé à la demande ne vaut pas pour l'heure de l'approbation.
7. `dispatch.queue(…, created_by=<e-mail de l'auteur>, package=…, ttl_minutes=request.ttl_minutes)` ; puis `command.bulk` comme aujourd'hui, au nom de l'auteur, avec en plus `approval_id` et `approved_by` ; puis `approval.approve`. Une seule transaction.

Les commandes portent l'auteur en `created_by` : c'est lui qui a demandé l'action ; l'approbateur est dans la demande et au journal. Pas de colonne nouvelle sur `commands` (table la plus grosse, et une clé étrangère sans index y rendrait la purge des demandes coûteuse).

### 2.4 Planifications (C3)

| Sujet | Choix |
|---|---|
| État | Une valeur de plus dans `ScheduleState` : `TO_APPROVE = "to_approve"` (10 caractères ; la colonne est `String(12)`, `0050_schedules`). Le runner ne prend que `active` : une planification à approuver ne s'exécute pas, sans changement de `run_due`. `next_run_at` y est `NULL`. |
| Écriture (`_apply`, création et `PUT`) | Après les contrôles existants (droits, cible, plage interdite, date passée) : si l'approbation est active, la planification à risque et `estimate()` > N, alors `state = to_approve`, `next_run_at = NULL`, et une demande `kind = schedule` est créée. Sinon `active` comme aujourd'hui. Toute écriture du contenu efface l'approbation (`approved_*` à `NULL`) et clôt la demande en attente précédente (`cancelled`, `result_code = schedule_changed`). Réponse 201/200 inchangée, `ScheduleOut` portant `state` et `approval`. |
| Réactivation (`POST /schedules/{id}/state`, `enabled: true`) | Si la planification est approuvée et que celui qui la réactive (et en devient l'auteur, règle de C3) n'est pas l'approbateur : elle redevient active sans nouvelle demande. S'il **est** l'approbateur, ou si elle n'a jamais été approuvée et compte plus de N postes : `to_approve` et nouvelle demande. |
| Désactivation et suppression | Désactiver une planification à approuver clôt sa demande (`cancelled`, `schedule_disabled`). La supprimer supprime la demande (clé étrangère `CASCADE`) ; le journal garde `schedule.delete`. |
| Approbation | Verrou sur la demande puis sur la planification ; `state` doit être `to_approve`. Revérifie : `runner.check_author` (refus → demande en échec, planification `suspended` avec le même code) ; l'approbateur détient `runner.required_permissions` et voit la planification (`visible_to`) ; ponctuelle : `run_at` encore futur (sinon échec `in_past`) ; plage interdite de nouveau évaluée comme à l'écriture (`policy.forbidden_at(run_at)` / `weekly_in_forbidden`, échec `forbidden_window`) ; paquet existant. Puis `state = active`, `next_run_at` calculé comme `set_state` le fait, `approved_by_id`, `approved_by`, `approved_at` renseignés. Les anneaux s'exécutent ensuite normalement (`follow_runs`), étape par étape, sans autre approbation. |
| Refus, expiration | La planification passe `suspended` avec `suspended_code` = `approval_rejected` ou `approval_expired` : la page Planifications le dit déjà pour les autres causes, et « Réactiver » relance une demande. |
| Garde à l'exécution | Dans `runner.run_stage`, après la résolution et avant le réveil : approbation active, planification à risque, `approved_at IS NULL`, `len(ids) > N` → `Refusal("approval_required", {"count": n, "threshold": N})`. |
| Estimation | `schedule/crud.py`, `estimate(session, schedule, scope) -> int` : réunion des `target.resolve` de la cible et de chaque anneau, sans les jetons révoqués. |

### 2.5 Notifications

| Sujet | Choix | Pourquoi |
|---|---|---|
| E-mail aux approbateurs | À la création, un e-mail à chaque compte qui peut approuver (actif, droits, portée, pas l'auteur) et dont `email_preference` n'est pas `none` ; dans sa langue (`notification/language.mail_language`), mis en file dans la transaction (`outbox.queue_email`). Au-delà de 20 approbateurs possibles, seuls les 20 premiers par adresse. | Sans cela la demande attend que quelqu'un ouvre la console. La préférence « rien » est respectée, comme pour le résumé. |
| E-mail à l'auteur | À chaque issue : approuvée (postes envoyés, laissés de côté), refusée (motif), expirée, en échec (cause). Quelle que soit sa cadence, comme `schedule_mail` (« c'est à propos de quelque chose qu'il a lancé »). | Il attend une réponse. |
| Webhook | Un évènement de plus dans `WebhookEvent` (`webhook/models.py`) : `approval.requested`, abonnable, émis dans la transaction de la demande (`webhook/emit.py`). Pas d'évènement pour les issues. | Le canal Teams de l'équipe est l'endroit naturel pour « il faut quelqu'un pour approuver ». Les issues regardent l'auteur, que l'e-mail prévient. Les lecteurs de webhooks sont des comptes sans limite (C8, §8) : le corps peut nommer la cible. |

### 2.6 Réglages

Trois clés dans `app_settings`, lues par une fonction `setting/crud.py: approval_policy(session, values=None) -> ApprovalPolicy(enabled, threshold, ttl_hours)` sur le modèle de `license_expiry_days`, valeur initiale dans l'environnement :

| Clé | Champ API (`GET/PATCH /settings`) | Variable | Défaut | Bornes |
|---|---|---|---|---|
| `approvals.enabled` | `approval_enabled` | `APPROVAL_ENABLED` | `false` | — |
| `approvals.threshold` | `approval_threshold` | `APPROVAL_THRESHOLD` | 40 | 2–10 000 |
| `approvals.ttl_hours` | `approval_ttl_hours` | `APPROVAL_TTL_HOURS` | 24 | 1–168 |
| — | `approval_eligible` (lecture seule) | — | — | nombre de comptes actifs détenant les deux droits |
| — | — | `APPROVAL_RETENTION_DAYS` | 180 | ≥ 1 |

`SettingsOut` gagne aussi `env_approval_enabled`, `env_approval_threshold`, `env_approval_ttl_hours`, comme les autres. `approval_threshold` et `approval_ttl_hours` vont dans `_SIMPLE_KEYS` (`settings_routes.py`) ; `approval_enabled` est écrit à part, après la vérification des deux approbateurs (sous `user_crud.lock_account_management`, pour ne pas croiser une désactivation de compte). Journal : `settings.update` comme le reste. Les variables vont dans le groupe d'environnement « Planifications » de `EnvGroupOut` et dans `deploy/.env.example`.

---

## 3. Modèle de données (migration `0061_mass_approval`, `down_revision = "0060_trends"`)

Nouvelle fonctionnalité `backend/app/features/approval/` : `models.py`, `crud.py` (création, liste visible, expiration, purge, déplacement à la fusion), `reach.py` (qui peut approuver : sur le modèle de `maintenance/reach.py`, `owner_reach` — groupes, droits et portées de tous les comptes actifs lus en un nombre fixe de requêtes, portée comparée en Python par `machine_in_scope`), `execute.py` (approbation d'une commande, §2.3), `schedule.py` (approbation d'une planification, §2.4).

### 3.1 Table `approval_requests`

| Colonne | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `kind` | varchar(10), NOT NULL | `command` \| `schedule` |
| `status` | varchar(10), NOT NULL, défaut serveur `'pending'` | `pending`, `approved`, `rejected`, `cancelled`, `expired`, `failed` |
| `command_type` | varchar(40), NOT NULL | Celui de la commande, ou de la planification |
| `package_id` | uuid NULL, FK `packages.id` `ON DELETE SET NULL` | |
| `package_name` | varchar(255) NULL | « 7-Zip 23.01 » tel qu'à la demande, pour l'affichage si le paquet disparaît |
| `package_digest` | varchar(64) NULL | `package_crud.fingerprint` à la demande |
| `target` | JSONB NOT NULL | `Target.as_json()` tel que demandé (ce que la console décrit : « tout le domaine LYCEE ») |
| `machine_ids` | JSONB NULL (`none_as_null`) | Liste figée des postes (chaînes) ; `NULL` pour une planification |
| `machine_count` | integer NOT NULL | Nombre compté au seuil |
| `threshold` | integer NOT NULL | Seuil en vigueur à la demande (pour le journal et l'e-mail) |
| `ttl_minutes` | integer NULL | La durée de vie demandée, appliquée aux commandes à l'approbation (`NULL` : celle du parc) |
| `schedule_id` | uuid NULL, FK `schedules.id` `ON DELETE CASCADE` | |
| `schedule_name` | varchar(200) NULL | |
| `requested_by_id` | uuid NULL, FK `users.id` `ON DELETE SET NULL` | Ce qui est revérifié |
| `requested_by` | varchar(255) NOT NULL | Ce que l'historique montre |
| `requested_at` | timestamptz NOT NULL | |
| `expires_at` | timestamptz NOT NULL | |
| `decided_by_id` | uuid NULL, FK `users.id` `ON DELETE SET NULL` | Approbateur ou refuseur ; `NULL` pour annulation, expiration |
| `decided_by` | varchar(255) NULL | |
| `decided_at` | timestamptz NULL | Toute clôture, y compris expiration |
| `note` | varchar(500) NULL | Motif du refus |
| `result_code` | varchar(64) NULL | Cause d'un échec ou d'une clôture (`author_inactive`, `package_changed`, `nothing_left`, `schedule_changed`, …) |
| `result_params` | JSONB NULL (`none_as_null`) | |
| `created` | integer NULL | Commandes créées à l'approbation |
| `skipped` | integer NULL | Postes qui avaient déjà la commande |
| `left_out` | integer NULL | Postes de la liste sortis de la portée de l'auteur, disparus ou révoqués |

Index : `ix_approval_requests_status_expires (status, expires_at)` (expiration, badge) ; `ix_approval_requests_requested_by_status (requested_by_id, status)` (« mes demandes », limite de 20) ; `ix_approval_requests_decided_at (decided_at)` (purge) ; index unique partiel `uq_approval_requests_pending_schedule (schedule_id) WHERE status = 'pending'` (une seule demande en attente par planification).

### 3.2 Colonnes ajoutées à `schedules`

`approved_by_id` (uuid NULL, FK `users.id` `ON DELETE SET NULL`), `approved_by` (varchar(255) NULL), `approved_at` (timestamptz NULL). Aucune donnée existante n'est touchée : les planifications actuelles restent `active`, non approuvées ; la garde d'exécution (§2.4) ne les arrête que si le réglage est activé et qu'elles dépassent le seuil.

### 3.3 Fusion de postes

`machine/crud.py: merge_into` appelle `approval_crud.move_to(session, source_id, target_id)` : dans les demandes **en attente**, l'identifiant du doublon est remplacé par celui du poste gardé (sans doublon dans la liste, `machine_count` inchangé). Les demandes closes sont laissées telles quelles, comme l'historique des exécutions de C3. Un poste supprimé n'est pas retiré de la liste : il disparaît à la résolution (§2.3, étape 5) et compte dans `left_out`.

### 3.4 Conservation

Demandes closes purgées `APPROVAL_RETENTION_DAYS` (180) jours après `decided_at`. Le journal d'audit garde la trace au-delà (`AUDIT_RETENTION_DAYS`).

---

## 4. API

### 4.1 `POST /commands` (modifié, `api/routes/commands.py`)

Après le contrôle des plages interdites et avant `dispatch.queue` : si `approval_policy.enabled`, `payload.type in RISKY_COMMAND_TYPES` et `len(machine_ids) > threshold`, alors pas de mise en file :

- vérifie `approval.no_approver` et `approval.too_many_pending`, renvoie une demande identique en attente si elle existe ;
- crée la demande (`kind = command`, `machine_ids` = la liste résolue, `package_digest` si déploiement), `audit.record(action="approval.request", resource_type="approval", resource_id=<id>, details={command_type, package_id?, package?, **target.audit(), count, threshold, expires_at})`, `webhook.emit(APPROVAL_REQUESTED, …)`, e-mails aux approbateurs ; **pas** de `command.bulk` à ce stade (rien n'est parti) ;
- répond **202** avec le corps `CreateCommandsResponse` : `created = []`, `count = 0`, `revoked` comme aujourd'hui, et trois champs nouveaux, facultatifs : `approval_id`, `approval_expires_at`, `pending_approval` (le nombre de postes en attente).

Le verrou du paquet pris par `deployable_package` est relâché au commit ; il sera repris à l'approbation.

### 4.2 Routes nouvelles (`api/routes/approvals.py`, préfixe `/approvals`)

Toutes demandent `risky_command:execute` (dépendance de route) ; la liste et le détail filtrent par portée.

| Route | Rôle |
|---|---|
| `GET /approvals?view=to_decide\|mine&status=&page=&page_size=` | `to_decide` : demandes en attente d'autres comptes que le lecteur pourrait approuver (droits, portée, `visible_to` pour une planification) ; `mine` : les siennes, tout statut, les plus récentes d'abord. Expire d'abord ce qui doit l'être (`approval_crud.mark_expired`, commit), comme `list_commands` le fait avec `mark_expired`. |
| `GET /approvals/summary` | `{enabled, to_decide, mine_pending}` : le badge du menu. Un lecteur sans `risky_command:execute` reçoit 403, et la console ne l'appelle pas. |
| `GET /approvals/{id}` | Détail, avec la liste des postes (`id`, `hostname`, salle) pour une commande, la planification résumée pour une planification. Visible de son auteur et de qui pourrait l'approuver ; sinon `approval.not_found` (404). |
| `POST /approvals/{id}/approve` | Corps `{confirm_forbidden_window: bool = false}`. Session obligatoire (`CurrentAuthSession`). Réponse : la demande, avec `created`, `skipped`, `left_out`. |
| `POST /approvals/{id}/reject` | Corps `{note?: str ≤ 500}`. Session obligatoire. |
| `POST /approvals/{id}/cancel` | Son auteur seul (sinon `approval.not_found`). |

Planifications (`api/routes/schedules.py`) : `ScheduleOut` gagne `approval: {id, status, expires_at, approved_by, approved_at} | null` et accepte l'état `to_approve` dans `list_schedules?state=`.

### 4.3 Journal d'audit (`resource_type = "approval"`)

| Action | Acteur | Détails |
|---|---|---|
| `approval.request` | l'auteur | `kind`, `command_type`, `package`, cible décrite (`target.audit()`), `count`, `threshold`, `expires_at`, `schedule` (nom) |
| `approval.approve` | l'approbateur | `requested_by`, `created`, `skipped`, `left_out` (commande) ou `schedule` |
| `approval.reject` | le refuseur | `requested_by`, `note` |
| `approval.cancel` | l'auteur | `cause` si la clôture vient d'une modification ou désactivation de la planification |
| `approval.expire` | `settings.PROJECT_NAME` | `requested_by` |
| `approval.fail` | l'approbateur | `cause` (`author_inactive`, `permission_lost`, `package_changed`, `nothing_left`, `in_past`, `forbidden_window`, code d'erreur de paquet) |

Plus `command.bulk` à l'approbation (acteur : l'auteur ; détails : `approval_id`, `approved_by`), `schedule.create`/`update`/`enable` inchangés (`details.approval: "required"` quand une demande est créée), `schedule.suspend` avec la cause `approval_required`. Console : section `approval` de `i18n/messages/audit.ts` (FR et EN), libellé de ressource `approval`, libellés des clés de détails nouvelles.

### 4.4 Codes d'erreur (`core/errors.py`, `ErrorCode`, et `i18n/messages/errorCodes.ts` FR et EN)

| Code | Statut | Quand |
|---|---|---|
| `approval.not_found` | 404 | Inconnue, ou hors de ce que le lecteur peut voir |
| `approval.not_pending` | 409 | Déjà décidée, annulée, expirée |
| `approval.own_request` | 403 | L'auteur tente d'approuver ou de refuser la sienne |
| `approval.no_approver` | 409 | Aucun autre compte ne pourrait l'approuver |
| `approval.too_many_pending` | 409 | 20 demandes en attente pour cet auteur |
| `approval.not_enough_approvers` | 422 | Activation du réglage avec moins de deux comptes capables d'approuver (`details.eligible`) |
| `approval.author_not_allowed` | 409 | L'auteur n'a plus son compte, ses droits (`details.cause`) |
| `approval.package_changed` | 409 | Le paquet a changé depuis la demande |
| `approval.nothing_left` | 409 | Aucun poste de la liste n'est encore dans la portée de l'auteur |

Les refus réutilisés : `auth.permission.denied`, `command.forbidden_window`, `schedule.in_past`, `schedule.forbidden_window`, `package.*`, `api_token.forbidden_here`.

---

## 5. Worker (`core/worker.py`)

| Job | Rythme | Rôle |
|---|---|---|
| `expire_approvals` | `every(300)` | `approval_crud.mark_expired(session, now)` : demandes `pending` dont `expires_at <= now` → `expired`, `decided_at = now`, `approval.expire` au journal, e-mail à l'auteur ; pour une planification, `state = suspended`, `suspended_code = approval_expired`. Ligne verrouillée `FOR UPDATE SKIP LOCKED`, par lots de 100, commit par lot. |
| `purge_approvals` | `housekeeping` (quotidien, 8 h) | Supprime les demandes closes depuis plus de `APPROVAL_RETENTION_DAYS`. |

Pas de job d'exécution : l'approbation met en file dans la requête de l'approbateur, comme `POST /commands`.

---

## 6. Console

| Élément | Où | Qui le voit |
|---|---|---|
| **Page « Approbations »** (`pages/ApprovalsPage.vue`, route `approvals`, `/approvals`, `router/routes.ts` et règle d'accès dans `router/access.ts`) | Menu, après « Planifications », avec un badge orange (nombre `to_decide`) sur le modèle de « Signalements » (`useReportsBadge.ts` → `composables/useApprovalsBadge.ts`, `notifyApprovalsChanged()`). | `risky_command:execute`, et seulement si l'approbation est activée **ou** qu'il reste des demandes (`summary`). |
| Onglet « À approuver » | Tableau : auteur, action (libellé du catalogue `services/commands.ts`, paquet), cible décrite, nombre de postes, demandée le, expire dans ; boutons « Approuver » et « Refuser ». | Idem |
| Onglet « Mes demandes » | Tableau de ses demandes, statut en puce (en attente, approuvée par X, refusée — motif, annulée, expirée, en échec — cause), bouton « Annuler » si en attente. | Idem |
| Dialogue de décision (`components/approval/ApprovalDecisionDialog.vue`) | Rappel de la demande, liste des postes (pliée au-delà de 20), plage interdite en cours avec la même confirmation que l'envoi (`schedules.forbiddenConfirm`), champ motif pour le refus. Après décision : notification avec le résultat (`created`, `skipped`, `left_out`). | L'approbateur |
| Envoi en masse | `bulkSendNotification` (`services/commands.ts`) : une réponse portant `approval_id` affiche « Demande d'approbation envoyée pour N postes : un second compte doit l'approuver avant {heure} », avec une action « Voir » vers la page. Couvre `useMachineBulkActions.ts` et `PackageDeployDialog.vue`, qui l'utilisent déjà. `MachineDetailPage` (un seul poste) n'est pas concernée. | L'auteur |
| Planifications | `services/schedules.ts` : état `to_approve` (« À approuver ») ; causes de suspension `approval_required`, `approval_rejected`, `approval_expired` dans `i18n/messages/schedules.ts` ; `ScheduleDialog.vue` notifie « Enregistrée : en attente d'approbation » quand l'état revenu est `to_approve` ; colonne « État » de `SchedulesPage.vue` avec l'approbateur en infobulle d'une planification approuvée. | Lecteurs des planifications |
| Carte « Approbation à deux » (`components/settings/SettingsApprovalCard.vue`, dans `SettingsPage.vue` après la carte « Planifications ») | Interrupteur, seuil, durée de validité, phrase « N comptes peuvent approuver » ; l'interrupteur est grisé avec l'explication quand N < 2 ; erreur `approval.not_enough_approvers` affichée dans la carte. | `settings:read` ; modifiable avec `settings:write` |
| Webhooks | Clé `approval_requested` dans les évènements de `i18n/messages/integrations.ts` (avec un soulignement, cf. C8 §8). | |

Catalogue de textes : `i18n/messages/approvals.ts` (FR et EN, typé par `types.ts`), enregistré dans `i18n/messages/index.ts`. Service : `services/approvals.ts`.

---

## 7. Jalons, tests et limites

### 7.1 Jalons

| Jalon | Contenu | Durée |
|---|---|---|
| A1 | Migration `0061_mass_approval`, modèle, `approval_policy`, réglages (`settings_routes.py`, refus sous deux approbateurs), `approval/reach.py`. | 0,5 j |
| A2 | `POST /commands` en demande (202), routes `/approvals`, exécution revérifiée (§2.3), journal, codes d'erreur, e-mails, évènement de webhook, fusion, jobs `expire_approvals` et `purge_approvals`. | 1 j |
| A3 | Planifications : état `to_approve`, `_apply`, `set_state`, approbation, refus, expiration, garde d'exécution dans `run_stage`, `visible_to` déplacée, causes de `schedule_mail`. | 0,5 j |
| A4 | Console : page, badge, dialogue, notification d'envoi, planifications, carte de Paramètres, audit, erreurs, webhooks. | 0,75 j |
| A5 | Docs (`DEPLOYMENT.md` : ce que fait le réglage, pourquoi il ne s'active pas avec un seul administrateur, ce qu'il ne protège pas ; `deploy/.env.example` ; `README.md`, feuille de route), notes de version, §8. | 0,25 j |

---

### 7.2 Tests du serveur (`tests/test_approvals.py`, `tests/test_approvals_schedules.py`)

- **Seuil** : réglage désactivé → comportement actuel (200, commandes créées) ; activé, N postes exactement → 200 ; N + 1 → 202, aucune ligne `commands`, une demande, `approval.request` au journal, pas de `command.bulk`.
- Comptage : postes au jeton révoqué non comptés ; « tout le parc » d'un compte limité compte son site ; postes ayant déjà la commande ouverte comptés.
- Types : commande courante (`quick_scan`) sur 500 postes → jamais de demande ; `package_install` et `package_uninstall` au-delà du seuil → demande avec `package_digest` ; un seul poste → jamais.
- Plage interdite à la demande : refus sans confirmation, demande créée avec confirmation.
- Doublon : la même requête deux fois → même `approval_id` ; vingt-et-unième demande en attente → `approval.too_many_pending`.
- `approval.no_approver` : administrateur seul détenteur des droits ; compte limité à un site dont aucun autre compte ne couvre les postes.
- **Approbation** : par un autre compte → commandes créées au nom de l'auteur (`created_by`), `command.bulk` avec `approval_id` et `approved_by`, `approval.approve`, e-mail à l'auteur ; par l'auteur → `approval.own_request` ; par un compte sans `risky_command:execute` → 403 ; par un compte ne voyant qu'une partie des postes → 404 ; par jeton d'API (même en écriture) → `api_token.forbidden_here`.
- Revérification : auteur désactivé, auteur privé de `risky_command:execute`, auteur supprimé → échec codé, demande `failed`, aucune commande ; paquet retiré, paquet modifié (empreinte) → échec ; tous les postes sortis de la portée de l'auteur → `approval.nothing_left` ; une partie → `left_out` compté ; poste révoqué entre-temps → laissé de côté.
- Plage interdite à l'approbation : refus sans confirmation de l'approbateur, la demande reste en attente ; avec confirmation, approuvée.
- Concurrence : deux approbations simultanées → une seule mise en file (l'autre `approval.not_pending`) ; approbation et annulation simultanées → une seule issue.
- **Refus** avec motif → e-mail à l'auteur avec le motif ; **annulation** par l'auteur, par un autre (404) ; décision sur une demande close → 409.
- **Expiration** : job `expire_approvals` et expiration à la lecture ; e-mail ; une demande expirée ne s'approuve plus.
- Liste et badge : `to_decide` exclut ses propres demandes et celles hors de sa portée ; `summary` cohérent avec la liste ; un compte limité ne voit pas une demande « tout le parc » d'un autre.
- E-mails : envoyés aux approbateurs possibles, pas à l'auteur, pas aux comptes `email_preference = none`, pas à un compte désactivé, dans la langue de chacun.
- Webhook `approval.requested` mis en file pour un webhook abonné, dans la transaction (rollback → rien) ; corps Teams et Mattermost composés en FR et EN.
- **Réglages** : activation avec un seul compte capable → `approval.not_enough_approvers` ; avec deux → accepté, `settings.update` au journal ; bornes du seuil et de la durée ; `approval_eligible` exact (administrateurs, groupe Techniciens, compte désactivé exclu) ; désactivation avec demandes en attente → elles restent décidables, plus aucune nouvelle.
- Fusion : identifiant du doublon remplacé dans une demande en attente, laissé dans une demande close.
- Purge : demande close au-delà de la rétention supprimée, demande en attente gardée.
- Migration : montée et descente de `0061_mass_approval` sur une base avec planifications existantes.
- **Planifications** : création à risque au-delà du seuil (réunion des anneaux comprise) → `to_approve`, `next_run_at` nul, non exécutée par `run_due` ; approbation → `active`, `next_run_at` calculé, `approved_by` ; un anneau s'enchaîne sans nouvelle demande ; modification d'une planification approuvée → nouvelle demande, ancienne close `schedule_changed` ; réactivation par l'approbateur → nouvelle demande, par un tiers → active sans demande ; désactivation d'une planification à approuver → demande close ; suppression → demande supprimée ; refus et expiration → `suspended` avec leur code ; ponctuelle dont l'heure est passée à l'approbation → échec `in_past` ; plage interdite ajoutée entre la demande et l'approbation → échec ; garde d'exécution : planification non approuvée qui dépasse le seuil à l'exécution → suspendue `approval_required`, e-mail ; approuvée qui dépasse → exécutée ; un compte limité ne voit pas une planification « tout le parc » à approuver.
- Textes : causes nouvelles dans `schedule_mail` (FR, EN) ; chaque `ErrorCode` nouveau a son texte (test existant du catalogue).

### 7.3 Tests de la console

- `services/approvals.spec.ts` : appels, paramètres de liste.
- `ApprovalsPage.spec.ts` et `ApprovalsPage.en.spec.ts` : les deux onglets, puces de statut, annulation, actualisation du badge après décision, pluriels anglais.
- `ApprovalDecisionDialog.spec.ts` : approbation, refus avec motif, confirmation de plage interdite sur `command.forbidden_window`, affichage des erreurs (`approval.package_changed`, `approval.not_pending`), liste des postes pliée.
- `services/commands` : `bulkSendNotification` sur une réponse 202 (`approval_id`) ; `useMachineBulkActions.spec.ts` et `PackageDeployDialog.spec.ts` : la notification d'attente.
- `MainLayout.spec.ts` : entrée et badge visibles avec `risky_command:execute` et réglage actif, absents sinon.
- `SchedulesPage.spec.ts`, `ScheduleDialog.spec.ts` : état « À approuver », causes de suspension, notification d'enregistrement en attente.
- `SettingsApprovalCard.spec.ts` : interrupteur grisé sous deux approbateurs, enregistrement, erreur `approval.not_enough_approvers`.
- `AuditPage` : libellés des six actions `approval.*` en FR et EN ; `SettingsWebhooksCard.spec.ts` : libellé de `approval_requested`.

---

### 7.4 Hors périmètre

- Approbation à plus de deux personnes, ou par un rôle d'approbateur distinct des droits d'exécution.
- Approbation des commandes courantes, du réveil, d'une commande sur un seul poste.
- Approbation des changements de réglages, de groupes ou de comptes : un compte qui détient `settings:write` peut désactiver l'approbation puis agir seul ; le journal (`settings.update`) en garde la trace. DEPLOYMENT.md le dit.
- Ressaisie du mot de passe ou du second facteur au moment d'approuver.
- Re-approbation d'une planification approuvée quand son paquet change de version (la mise en file compare déjà l'empreinte à la livraison, `commands.package_digest`), ou quand sa cible grandit après approbation.
- Notifications poussées autres que l'e-mail et le webhook ; évènements de webhook pour les issues d'une demande.
- Agent : non modifié.

---

### 7.5 Décisions prises par défaut (à confirmer)

1. **Seuil par défaut : 40 postes**, approbation déclenchée strictement au-delà ; compté sur les postes réellement visés (portée de l'auteur, jetons révoqués exclus).
2. **Types concernés : `RISKY_COMMAND_TYPES` tels quels** (déploiements de paquets compris) et les planifications à « éteindre ensuite » ; pas de liste réglable.
3. **Planifications approuvées une fois, à l'écriture** ; modification ou réactivation par l'approbateur lui-même redemande ; garde d'exécution qui suspend une planification non approuvée devenue trop large.
4. **Liste de postes figée à la demande**, exécutée telle quelle (moins ce qui est sorti de la portée de l'auteur) ; empreinte du paquet comparée.
5. **Pas de droit nouveau** : approuver demande les mêmes droits que l'action, et une portée couvrant tous les postes.
6. **Activation refusée avec moins de deux comptes capables d'approuver** ; demande refusée à la création si aucun autre compte ne peut l'approuver.
7. **Validité de 24 h** (réglable de 1 à 168 h) ; 20 demandes en attente au plus par auteur ; conservation 180 jours.
8. **Réponse 202** de `POST /commands` pour une demande, avec `approval_id` ; pas de `command.bulk` avant l'approbation.
9. **Approbation et refus impossibles par jeton d'API** ; pas de ressaisie du mot de passe.
10. **Un évènement de webhook nouveau, `approval.requested`**, et des e-mails aux approbateurs (sauf préférence « rien », 20 au plus) et à l'auteur à chaque issue.
11. **Désactiver le réglage laisse les demandes en attente décidables** et n'exécute rien de lui-même.

---

## 8. Écarts constatés à l'implémentation

*(à remplir)*
