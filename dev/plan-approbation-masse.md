# C10 — Approbation à deux des actions de masse : plan détaillé

> **📝 Document de travail — 2026-11-25.** Chantier C10 de `plan-evolutions-itil.md` (§4.6). Au-delà de N postes, une commande à risque n'est pas mise en file : elle devient une **demande** qu'un second compte, détenant les mêmes droits et voyant les mêmes postes, approuve ou refuse. Désactivée par défaut. Elle porte sur les commandes envoyées à la main (`POST /commands`, déploiements de paquets compris) et sur les planifications de C3 (anneaux compris) : on approuve **la planification**, pas chacune de ses exécutions. Migration `0061_mass_approval`. Jalons en §6, tests en §7, puis Hors périmètre et Décisions prises par défaut ; les écarts constatés à l'implémentation vont en §8.

---

## 1. Ce que le chantier doit tenir

- **Ce qui est approuvé est ce qui part.** La demande garde la requête exacte (type, paquet et son empreinte, liste figée des postes, durée de vie) ; l'approbation exécute cette liste-là, rien de plus. Un poste ajouté au domaine entre-temps n'est pas visé ; un paquet modifié entre-temps fait échouer la demande. Pour une planification, l'approbation vaut pour un auteur et un nombre de postes : un autre auteur, ou une cible qui dépasse ce nombre, redemande.
- **Tout est revérifié au moment d'approuver**, comme C3 le fait à chaque exécution (`schedule/runner.py`, `check_author`) : le compte de l'auteur est actif et a encore ses droits, la cible est dans sa portée du moment, le paquet existe et est toujours déployable (`command/dispatch.py`, `deployable_package`), les plages interdites (`schedule/windows.py`) s'appliquent à l'heure de l'approbation.
- **Deux personnes, pas deux sessions.** L'approbateur est un autre compte (identifiant différent), qui détient les mêmes droits que ceux que l'action demande et dont la portée couvre tous les postes visés. Approuver ou refuser par jeton d'API est refusé.
- **Jamais bloquant par surprise.** Désactivée par défaut ; impossible à activer s'il n'existe pas au moins deux comptes capables d'approuver ; une demande que personne d'autre ne peut approuver est refusée à la création avec un message qui le dit, plutôt que de rester en attente jusqu'à expiration.
- **Rien n'est perdu ni rejoué.** Une demande se décide une seule fois (verrou de ligne) ; deux envois identiques simultanés n'en créent qu'une (index unique) ; elle expire ; son auteur peut l'annuler ; chaque transition est journalisée dans la transaction qui la fait, **et cette transaction est validée même quand la route répond ensuite par une erreur** (§2.3).
- **Invariants du produit** (§2 de la feuille de route) : catalogue de commandes inchangé, serveur qui ne contacte jamais un poste, portée respectée par toute lecture (liste, compteur du badge, détail, e-mail) et appliquée en SQL (`machine_clause` / `machine_ids_clause`), `audit.record` dans la transaction de l'appelant, réglages dans `app_settings` servis à la console, textes codés en deux langues, purge de ce qui grossit.

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
| Découpage en lots | **Limite assumée** : le seuil s'applique **par envoi**. 1 000 postes envoyés en 25 lots de 40 (console ou script par jeton en écriture), ou 25 planifications de 40 postes, ne déclenchent pas l'approbation ; une même personne qui dispose de deux comptes (compte local de secours et compte de l'annuaire, C7) peut aussi s'approuver elle-même. Aucun cumul par auteur n'est compté. Dit dans Hors périmètre et dans `DEPLOYMENT.md` : chaque lot laisse sa ligne `command.bulk` au journal, ce qui permet de repérer un découpage. | Le contrôle vise l'erreur et le geste trop large fait d'un clic, pas un compte décidé à le contourner : celui-là détient déjà `risky_command:execute`, et un cumul glissant ferait refuser du travail légitime (la salle B après la salle A). |
| Planifications | Approuvées **à l'écriture** (création, modification, réactivation), une fois pour toutes les exécutions et toutes les étapes d'anneaux. Le nombre de postes est `schedule_crud.estimate()` (§2.4) : la réunion des cibles de toutes les étapes, résolue dans la portée de l'auteur, jetons révoqués exclus. L'approbation retient l'auteur approuvé (`approved_for_id`) et le nombre approuvé (`approved_count`). | « Approuver la planification, pas chaque déclenchement » : un déploiement hebdomadaire approuvé ne doit pas réclamer quelqu'un chaque mercredi à 18 h. |
| Planification qui grossit ou change de mains | Garde à l'exécution, dans `runner.run_one` (§2.4) : approbation activée, planification à risque, et `estimate()` dans la portée de l'auteur du moment dépasse `max(N, approved_count)` — ou l'auteur n'est plus `approved_for_id` — alors la planification est suspendue (`suspended_code = approval_required`) par le chemin existant (`runner._suspend` : journal `schedule.suspend`, e-mail à l'auteur). La même fonction `estimate()` compte à l'écriture et à l'exécution : le seuil vaut la même chose partout. | Couvre sans autre mécanisme les planifications écrites avant l'activation du réglage, une cible « salle » ou « domaine » qui a grandi au-delà de ce qui a été approuvé, et une portée d'auteur élargie depuis. La réactiver passe par l'approbation. |
| Réglage désactivé après coup | Les demandes en attente restent décidables (approuver, refuser, annuler) jusqu'à leur expiration ; aucune nouvelle demande n'est créée ; la garde d'exécution ne s'applique plus. Les planifications approuvées gardent leur approbation ; une planification `to_approve` le reste jusqu'à la décision ou l'expiration de sa demande. | Couper le réglage ne doit ni exécuter d'un coup ce que personne n'a approuvé, ni jeter le travail d'un collègue. |

### 2.2 Qui approuve, et comment

| Sujet | Choix | Pourquoi |
|---|---|---|
| Droit | Aucun droit nouveau dans `PERMISSION_CATALOGUE`. Approuver une commande demande `command:execute` **et** `risky_command:execute` ; approuver une planification demande en plus `schedule:write` — exactement `runner.required_permissions(schedule)`. | « Un second compte qui détient le même droit. » Un droit « approuver » séparé permettrait d'approuver ce qu'on ne pourrait pas faire soi-même. |
| Portée | L'approbateur doit voir **chaque** poste encore existant de la liste figée. Appliqué en SQL sur la table enfant `approval_request_machines` (§3.1) : `NOT EXISTS (SELECT 1 FROM approval_request_machines m WHERE m.request_id = approval_requests.id AND m.machine_id NOT IN (SELECT id FROM machines WHERE machine_clause(scope)))`, rien quand `machine_clause` renvoie `None` (compte sans limite). Pour une planification : la règle de lecture des planifications (`api/routes/schedules.py`, `_visible`), qui demande un compte sans limite pour une cible « tout le parc / domaine / emplacement / état ». `_visible` est déplacée dans `schedule/crud.py` (`visible_to`) pour servir aux deux. | On n'approuve pas un redémarrage de postes qu'on ne voit pas ; et la règle de visibilité des planifications existe déjà, il ne faut pas en écrire une seconde. |
| Une seule règle « peut décider » | `approval_crud.decidable(session, scope, user_id, permissions) -> clause` : demandes `pending`, `requested_by_id != user_id`, droits du lecteur ; pour `kind = command` le `NOT EXISTS` ci-dessus ; pour `kind = schedule`, rien de plus pour un compte sans limite, et pour un compte limité `id IN (…)` des demandes de planification en attente que `visible_to` accepte (au plus une par planification, index unique §3.1, donc une liste courte évaluée en Python). La liste `to_decide`, `summary`, le détail et les routes de décision utilisent toutes cette clause. | Liste, badge et décision ne peuvent pas diverger ; la pagination et le décompte se font en SQL, en une requête. |
| Pas soi-même | `approver.id != request.requested_by_id`. Pour une planification, celui qui la réactive en devient l'auteur (règle de C3) : s'il n'est pas `approved_for_id`, une nouvelle demande est créée (§2.4), qu'il ne peut pas approuver lui-même. | Deux personnes. |
| Pas par jeton d'API | Approuver et refuser dépendent de `CurrentAuthSession` (`api/deps.py`, `get_current_auth_session`) : un jeton reçoit `api_token.forbidden_here` (403). Créer une demande (par `POST /commands`) ou annuler la sienne reste possible par jeton en écriture. | L'approbation est un geste humain ; un script qui approuve ce qu'un autre script demande annule la règle. |
| Mot de passe ou second facteur à l'approbation | Non demandés. | Le contrôle porte sur « une seconde personne », que la session authentifiée établit déjà ; rejouer le mot de passe à chaque approbation pèserait sur l'usage quotidien. Cf. Hors périmètre. |
| Activation du réglage | Refusée (`approval.not_enough_approvers`, 422, `details.eligible`) tant que `approval/reach.py: eligible_count(session)` vaut moins de **2**. `eligible_count` compte les comptes actifs dont les groupes donnent, par `user_crud.permissions_of_groups` (administrateurs compris, catalogue complet), à la fois `command:execute` et `risky_command:execute` ; il ne regarde pas les lieux. Aucun verrou de gestion des comptes n'est pris : retirer un droit ou désactiver un compte ensuite reste libre, et ce cas est couvert à la création de chaque demande par `approval.no_approver`. La carte de Paramètres affiche ce nombre. `DEPLOYMENT.md` dit que ce nombre ne tient pas compte des lieux : un approbateur limité doit couvrir **tous** les postes d'une demande, et deux comptes limités à deux sites différents ne s'approuvent pas l'un l'autre. | « Dans un établissement à un seul administrateur, elle bloquerait tout » : on ne la laisse pas s'activer là. `user_crud.users_holding` ne compte qu'un droit à la fois, d'où une fonction à part. |
| Demande sans approbateur possible | Refusée à la création (`approval.no_approver`, 409) s'il n'existe aucun autre compte actif détenant les droits et couvrant tous les postes (ou voyant la planification) : `approval/reach.py: approvers(session, request, *, limit=None)`, sur le modèle de `maintenance/reach.py` (`owner_reach` : groupes, droits et portées de tous les comptes actifs lus en un nombre fixe de requêtes, portée comparée par `machine_in_scope` sur les lieux de `room_places`). | Un compte de l'annexe limité à son site, seul à pouvoir voir ses postes, sinon attendrait une approbation impossible. Le message dit les deux issues : viser moins de postes, ou qu'un administrateur ajuste les groupes ou le réglage. |
| Expiration | `approvals.ttl_hours`, défaut **24 h** (1 à 168). Pour une planification ponctuelle : au plus tard à son `run_at`. Une seule transition, `approval_crud.expire(session, request, now)` (statut `expired`, `decided_at`, `approval.expire` au journal, e-mail à l'auteur, planification `suspended` / `approval_expired`), appelée par `approval_crud.mark_expired(session, now)` — lignes `pending` échues prises en `FOR UPDATE SKIP LOCKED`, par lots de 100 — depuis le job du worker **et** depuis la lecture de la liste ; et par `approve`, `reject`, `cancel` sur la ligne qu'elles ont verrouillée : si `expires_at <= now`, elles appliquent la transition, valident (`commit`), puis répondent `approval.not_pending` (§2.3). | Une demande de la veille au soir doit pouvoir être approuvée le matin ; une demande d'une semaine n'a plus de sens (le parc a changé). `SKIP LOCKED` : une demande qu'un approbateur tient verrouillée n'est pas expirée sous lui ; c'est lui qui constate l'échéance. |
| Annulation | Par son auteur seul, tant qu'elle est en attente. | Il a changé d'avis ou s'est trompé de cible. |
| Refus | Par tout compte qui pourrait l'approuver (`decidable`), avec un motif facultatif (500 caractères), transmis à l'auteur. | Le refus est aussi une décision à deux. |
| Concurrence | Approuver, refuser, annuler verrouillent la ligne de la demande (`SELECT … FOR UPDATE`) et exigent `status = pending`, sinon `approval.not_pending` (409). L'approbation d'un déploiement prend en plus le verrou du paquet (`package_crud.locked`, via `deployable_package`) ; celle d'une planification, la ligne de la planification (après celle de la demande, toujours dans cet ordre). | Une demande ne se décide qu'une fois ; deux approbateurs simultanés ne mettent pas deux fois en file. |
| Doublon | Colonne `request_key` = sha256 hexadécimal de (`requested_by_id`, `command_type`, `package_id`, liste triée des postes, `ttl_minutes`), et index unique partiel `uq_approval_requests_pending_key (request_key) WHERE status = 'pending'` (§3.1). La création s'insère dans un point de sauvegarde (`session.begin_nested()`, comme `api/routes/rooms.py`) ; sur `IntegrityError`, la demande existante est relue et renvoyée telle quelle (même identifiant, ni e-mail ni webhook de plus). | Le bouton pressé deux fois, ou un script relancé, comme `skipped` pour les commandes ; deux POST simultanés n'en créent qu'une, sans comparer des listes de milliers de postes. |
| Limite par auteur | Au plus **20** demandes en attente par auteur (`approval.too_many_pending`, 409), comptées sous `approval_crud.lock_author(session, user_id)` : `pg_advisory_xact_lock` à deux clés (un espace propre aux approbations, puis les 32 premiers bits de l'identifiant), sur le modèle de `package_crud._file_lock`. | Sans verrou, vingt envois simultanés passent tous le compte. |

### 2.3 Ce qui est revérifié à l'approbation d'une commande

**Chemin d'échec : valider, puis répondre l'erreur.** `core/db.get_db` ferme la session sans valider : lever une `AppError` annulerait la clôture de la demande, son audit et l'e-mail en file, et chaque nouvelle tentative referait la même chose. Toute issue qui clôt la demande en échec suit donc le schéma déjà employé par `api/routes/auth.py` (validé avant de répondre) : `approval_crud.fail(session, request, code, params, actor=approver)` pose `status = failed`, `result_code`, `result_params`, `decided_by_id`, `decided_by`, `decided_at`, `audit.record(action="approval.fail")`, l'e-mail à l'auteur et, pour une planification, `state = suspended` avec le même code ; la route fait `await session.commit()`, **puis** lève l'erreur. Même schéma pour l'expiration constatée par `approve`, `reject` ou `cancel` (§2.2). La console relit la liste sur chacun de ces codes.

Dans cet ordre, dans la transaction de l'approbation :

1. Demande verrouillée et décidable par le lecteur (`decidable`, sinon `approval.not_found`, 404) ; `status = pending` (sinon `approval.not_pending`) ; si `expires_at <= now` : `expire`, commit, `approval.not_pending`.
2. L'approbateur n'est pas l'auteur (`approval.own_request`, 403 — vérifié avant `decidable`, qui exclut ses propres demandes), détient les deux droits (`auth.permission.denied` habituel).
3. L'auteur : existe, est actif, détient encore `command:execute` et `risky_command:execute` — sinon `fail` (`author_gone` | `author_inactive` | `permission_lost`, les codes de C3), commit, `approval.author_not_allowed` (409, `details.cause`).
4. Le paquet (déploiements) : pour un type de `PACKAGE_COMMAND_TYPES` dont `package_id` est passé à `NULL` (paquet supprimé, `ON DELETE SET NULL`), `fail` (`package_gone`, comme `runner.run_stage` renvoie `Refusal("package_gone")`), commit, `approval.package_gone` (409) — sans appeler `deployable_package`, qui répondrait à tort `package.required`. Sinon `dispatch.deployable_package` dans un `try` : une `AppError` de paquet (retiré, incomplet) donne `fail` (`result_code` = son code), commit, puis la même erreur relevée. Puis l'empreinte `package_crud.fingerprint(package, files)` comparée à `package_digest` : différente → `fail` (`package_changed`), commit, `approval.package_changed` (409).
5. La cible : `target_crud.resolve(session, Target("machines", machine_ids=<postes de approval_request_machines>), scope_de_l_auteur_maintenant)`, sans les jetons révoqués. `left_out = machine_count - len(ids)` (postes supprimés depuis — leurs lignes enfant sont parties avec eux —, sortis de la portée de l'auteur, révoqués). Plus rien → `fail` (`nothing_left`), commit, `approval.nothing_left` (409).
6. Plage interdite **à l'instant de l'approbation** : `windows.require_outside_forbidden(session, now, confirmed=body.confirm_forbidden_window)` — l'approbateur voit le même avertissement que l'auteur (`command.forbidden_window`) ; la demande reste en attente, rien n'est validé. Ce que l'auteur avait confirmé à la demande ne vaut pas pour l'heure de l'approbation.
7. `dispatch.queue(…, created_by=<e-mail de l'auteur>, package=…, ttl_minutes=request.ttl_minutes)` ; puis `command.bulk` comme aujourd'hui, au nom de l'auteur, avec en plus `approval_id` et `approved_by` ; puis `approval.approve`, l'e-mail à l'auteur. Une seule transaction, un seul commit.

Les commandes portent l'auteur en `created_by` : c'est lui qui a demandé l'action ; l'approbateur est dans la demande et au journal. Pas de colonne nouvelle sur `commands` (table la plus grosse, et une clé étrangère sans index y rendrait la purge des demandes coûteuse).

### 2.4 Planifications (C3)

| Sujet | Choix |
|---|---|
| État | Une valeur de plus dans `ScheduleState` (`schedule/models.py`) : `TO_APPROVE = "to_approve"` (10 caractères ; la colonne est `String(12)`, `0050_schedules`). `run_due` ne prend que `active` : une planification à approuver ne s'exécute pas. `next_run_at` y est `NULL`. |
| Colonnes d'approbation | `approved_by_id`, `approved_by`, `approved_at` (qui a approuvé, quand), `approved_for_id` (l'auteur, `created_by_id`, au moment de l'approbation) et `approved_count` (`estimate()` à l'approbation, dans la portée de cet auteur). Une approbation ne vaut que tant que `created_by_id = approved_for_id` et que `estimate()` ne dépasse pas `max(N, approved_count)`. |
| Estimation | `schedule/crud.py`, `estimate(session, schedule, scope) -> int` : réunion des `target_crud.resolve` de la cible et de chaque anneau, sans les jetons révoqués. Seule fonction de comptage : écriture, réactivation, approbation, garde d'exécution. |
| Écriture (`_apply`, création et `PUT`) | Après les contrôles existants (droits, cible, plage interdite, date passée) : toute écriture du contenu efface l'approbation (`approved_*` à `NULL`) et clôt la demande en attente précédente (`cancelled`, `result_code = schedule_changed`, `approval.cancel` au journal). Puis, si l'approbation est active, la planification à risque et `estimate(session, schedule, scope_du_rédacteur)` > N : `state = to_approve`, `next_run_at = NULL`, et une demande `kind = schedule` est créée. Sinon `active` comme aujourd'hui. Sur un `PUT`, les exécutions `running` de la planification à qui il reste un anneau sont marquées `result_code = schedule_changed` : leur étape suivante ne démarre plus (ci-dessous), l'extinction des postes déjà réveillés se fait quand même. Réponse 201/200 inchangée, `ScheduleOut` portant `state` et `approval`. |
| Réactivation (`POST /schedules/{id}/state`, `enabled: true`) | Celui qui réactive en devient l'auteur (règle de C3). Approbation active, planification à risque, `n = estimate(…, portée de celui qui réactive)` > N : elle redevient `active` sans nouvelle demande **seulement si** `approved_at` est renseigné, que celui qui réactive est `approved_for_id` et que `n <= approved_count`. Sinon (autre compte, cible plus large que ce qui a été approuvé, jamais approuvée) : `to_approve`, approbation effacée, nouvelle demande. Exemple couvert : un compte limité au site A écrit une planification « tout le parc » (45 postes), approuvée ; un administrateur sans limite la réactive ensuite, elle compterait 1 000 postes : nouvelle demande. |
| Désactivation et suppression | Désactiver une planification à approuver clôt sa demande (`cancelled`, `schedule_disabled`). La supprimer supprime la demande (clé étrangère `CASCADE`) ; le journal garde `schedule.delete`. |
| Exécutions en cours (`runner.follow_one`) | L'étape suivante d'un anneau ne démarre pas quand `schedule.state` est `disabled`, `to_approve` ou `suspended`, ou que l'exécution porte `result_code = schedule_changed` (posé par `_apply`) : même branche qu'aujourd'hui pour `DISABLED` (`result_code` = `schedule_disabled`, `schedule_changed` ou `approval_required`, exécution `halted` une fois l'extinction faite). L'état `done` n'arrête rien : une ponctuelle passe `done` dès sa première étape (`run_one`) et ses anneaux doivent continuer. Sans cela, une planification approuvée modifiée en plein déploiement passerait à l'étape suivante avec les **nouveaux** `rings` (`stage_target` relit `schedule.rings`), au nom du nouvel auteur, sans approbation. |
| Approbation | Verrou sur la demande puis sur la planification ; `state` doit être `to_approve`. Revérifie : `runner.check_author` (refus → `fail`, planification `suspended` avec le même code, commit puis `approval.author_not_allowed`) ; l'approbateur détient `runner.required_permissions` et voit la planification (`visible_to`) ; ponctuelle : `run_at` encore futur (sinon `fail` `in_past`, commit, `schedule.in_past`) ; plage interdite de nouveau évaluée comme à l'écriture (`policy.forbidden_at(run_at)` / `windows.weekly_in_forbidden`, sinon `fail` `forbidden_window`, commit, `schedule.forbidden_window`) ; paquet : `package_id` nul pour un déploiement → `fail` `package_gone`, commit, `approval.package_gone`. Puis `state = active`, `next_run_at` calculé comme `set_state` le fait, `approved_by_id`, `approved_by`, `approved_at`, `approved_for_id = created_by_id`, `approved_count = estimate(…, portée de l'auteur)`. Les anneaux s'exécutent ensuite normalement (`follow_runs`), étape par étape, sans autre approbation. |
| Refus, expiration | La planification passe `suspended` avec `suspended_code` = `approval_rejected` ou `approval_expired` : la page Planifications le dit déjà pour les autres causes, et « Réactiver » relance une demande. |
| Garde à l'exécution | Dans `runner.run_one`, après `check_author` et avant `run_stage(session, schedule, run, 0, checked, now)` : approbation active, planification à risque (`risky_command:execute` dans `required_permissions`), et `n = estimate(session, schedule, checked.scope)` > `max(N, approved_count or 0)`, ou `approved_for_id != created_by_id` alors que `n > N` → `_suspend` avec `Refusal("approval_required", {"count": n, "threshold": N})`. Pas de garde dans `run_stage` : les étapes 2 et suivantes, lancées par `_advance_rings`, ne sont pas recomptées au milieu d'un déploiement (l'exécution entière a été comptée à son départ, toutes étapes réunies). Une planification à anneaux de 5 étapes de 39 postes, avec N = 40, est donc arrêtée comme à l'écriture. |
| Changement de fuseau (`runner.rezone`) | La requête prend `state IN (active, to_approve)` : une ponctuelle à approuver voit son `run_at` recalé comme les autres (son `next_run_at` reste `NULL`) ; une hebdomadaire à approuver n'est pas touchée (son `next_run_at` reste `NULL`, calculé à l'approbation). |

### 2.5 Notifications

| Sujet | Choix | Pourquoi |
|---|---|---|
| E-mail aux approbateurs | À la création, un e-mail à chaque compte que `reach.approvers(…, limit=20)` retient (actif, droits, portée, pas l'auteur) et dont `email_preference` n'est pas `none` ; dans sa langue (`notification/language.mail_language`), mis en file dans la transaction (`outbox.queue_email`). Au-delà de 20 approbateurs possibles, seuls les 20 premiers par adresse. | Sans cela la demande attend que quelqu'un ouvre la console. La préférence « rien » est respectée, comme pour le résumé. |
| E-mail à l'auteur | À chaque issue : approuvée (postes envoyés, laissés de côté), refusée (motif), expirée, en échec (cause). Quelle que soit sa cadence, comme `schedule_mail` (« c'est à propos de quelque chose qu'il a lancé »). Il donne des nombres, jamais de noms de postes. | Il attend une réponse ; un poste sorti de sa portée depuis ne doit pas y être nommé. |
| Module | `notification/approval_mail.py` : `render(…)`, `queue_request_mails(session, request, approvers)` et `queue_outcome_mail(session, request, author)`, avec un lien `_link()` vers `{console_base_url}/#/approvals` comme `schedule_mail._link()`. Textes FR et EN dans `notification/approval_mail_texts.py` (dataclass `ApprovalMailTexts`, `FR`, `EN`, `TEXTS`, sur le modèle de `threat_alert_texts.py`) : sujets « Approbation demandée : {action} sur {count} postes », « Votre demande a été approuvée / refusée / a expiré / a échoué », et les causes `author_gone`, `author_inactive`, `permission_lost`, `package_gone`, `package_changed`, `nothing_left`, `in_past`, `forbidden_window`. Exemples figés dans `tests/data/mail_texts.json` (`test_mail_languages.py`). | Comme les autres e-mails : un module, des textes typés, un test mot pour mot. |
| Webhook | Un évènement de plus dans `WebhookEvent` (`webhook/models.py`) : `APPROVAL_REQUESTED = "approval.requested"`, abonnable (il entre de lui-même dans `SUBSCRIBABLE`). Émis dans la transaction de la demande par un helper `emit.approval_requested(session, request)` de `webhook/emit.py`, qui appelle `emit.emit(session, WebhookEvent.APPROVAL_REQUESTED, data)`. `data` : `{id, kind, command_type, package (nom ou null), schedule (nom ou null), target (description : `target.audit()` pour une commande, `{"target": kind, …}` pour une planification), count, threshold, requested_by, expires_at}` — jamais la liste des postes. Corps Teams et Mattermost : une entrée `"approval.requested"` dans `_FR` et `_EN` de `webhook/texts.py` (« Approbation demandée par {requested_by} : « {command_type} » sur {count} postes, avant {expires_at} »). Pas d'évènement pour les issues. Console : `'approval.requested'` ajouté à `WEBHOOK_EVENTS` (`services/webhooks.ts`) et clé `approval_requested` dans les évènements de `i18n/messages/integrations.ts` (FR et EN, avec un soulignement, cf. C8 §8). | Le canal Teams de l'équipe est l'endroit naturel pour « il faut quelqu'un pour approuver ». Les issues regardent l'auteur, que l'e-mail prévient. Les lecteurs de webhooks sont des comptes sans limite (C8, §8) : le corps peut décrire la cible. |

### 2.6 Réglages

Trois clés dans `app_settings`, lues par une fonction `setting/crud.py: approval_policy(session, values=None) -> ApprovalPolicy(enabled, threshold, ttl_hours)` sur le modèle de `license_expiry_days`, valeur initiale dans l'environnement :

| Clé | Champ API (`GET/PATCH /settings`) | Variable (`core/config.py`) | Défaut | Bornes |
|---|---|---|---|---|
| `approvals.enabled` | `approval_enabled` | `APPROVAL_ENABLED: bool` | `false` | — |
| `approvals.threshold` | `approval_threshold` | `APPROVAL_THRESHOLD: int = Field(default=40, ge=2, le=10000)` | 40 | 2–10 000 |
| `approvals.ttl_hours` | `approval_ttl_hours` | `APPROVAL_TTL_HOURS: int = Field(default=24, ge=1, le=168)` | 24 | 1–168 |
| — | `approval_eligible` (lecture seule) | — | — | `reach.eligible_count(session)` |
| — | — | `APPROVAL_RETENTION_DAYS: int = Field(default=180, ge=1)` | 180 | ≥ 1 |

`SettingsOut` (`api/routes/settings_routes.py`) gagne aussi `env_approval_enabled`, `env_approval_threshold`, `env_approval_ttl_hours`, comme `env_license_expiry_days`. `approval_threshold` et `approval_ttl_hours` vont dans `_SIMPLE_KEYS` ; `approval_enabled` est écrit à part, après la vérification `eligible_count >= 2` quand il passe à vrai. Journal : `settings.update` comme le reste.

Variables d'environnement, chacune à sa place :

- `features/setting/environment.py` : quatre `_item(env, "APPROVAL_…", …)` dans le groupe existant `console` (« Console et sécurité »), après les variables de connexion — pas de groupe nouveau, donc pas de libellé de groupe à ajouter. Les variables `SCHEDULE_*` n'y figurent pas aujourd'hui et ne sont pas concernées ici.
- `frontend/src/i18n/messages/settingsEnv.ts` : le texte de chacune en FR (mot pour mot celui du serveur) et en EN ;
- `backend/tests/data/settings_texts_fr.json` : les quatre entrées du groupe `console` (`test_settings_texts.py`) ;
- `deploy/.env.example` (lignes commentées, comme `#SCHEDULE_RUN_RETENTION_DAYS=180`) et `DEPLOYMENT.md` (tableau « Variables d'environnement (serveur) »).

---

## 3. Modèle de données (migration `0061_mass_approval`, `down_revision = "0060_trends"`)

Nouvelle fonctionnalité `backend/app/features/approval/` : `models.py`, `crud.py` (création avec `request_key` et `lock_author`, `decidable`, liste, `expire` et `mark_expired`, `fail`, purge, `move_to` pour la fusion), `reach.py` (`eligible_count`, `approvers`), `execute.py` (approbation d'une commande, §2.3), `schedule.py` (approbation d'une planification, §2.4).

### 3.1 Tables `approval_requests` et `approval_request_machines`

| Colonne | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `kind` | varchar(10), NOT NULL | `command` \| `schedule` |
| `status` | varchar(10), NOT NULL, défaut serveur `'pending'` | `pending`, `approved`, `rejected`, `cancelled`, `expired`, `failed` |
| `request_key` | varchar(64) NULL | sha256 de la requête (§2.2, Doublon) ; `NULL` pour une planification (dédoublonnée par `schedule_id`) |
| `command_type` | varchar(40), NOT NULL | Celui de la commande, ou de la planification |
| `package_id` | uuid NULL, FK `packages.id` `ON DELETE SET NULL` | |
| `package_name` | varchar(255) NULL | « 7-Zip 23.01 » tel qu'à la demande, pour l'affichage si le paquet disparaît |
| `package_digest` | varchar(64) NULL | `package_crud.fingerprint` à la demande |
| `target` | JSONB NOT NULL | La cible décrite, telle que demandée (ce que la console affiche : « tout le domaine LYCEE ») : `Target.as_json()`, sauf pour le kind `machines`, réduit à `{"kind": "machines"}` — la liste est dans la table enfant |
| `machine_count` | integer NOT NULL | Nombre compté au seuil |
| `threshold` | integer NOT NULL | Seuil en vigueur à la demande (pour le journal et l'e-mail) |
| `ttl_minutes` | integer NULL | La durée de vie demandée, appliquée aux commandes à l'approbation (`NULL` : celle du parc) |
| `schedule_id` | uuid NULL, FK `schedules.id` `ON DELETE CASCADE` | |
| `schedule_name` | varchar(200) NULL | |
| `requested_by_id` | uuid NULL, FK `users.id` `ON DELETE SET NULL` | Ce qui est revérifié |
| `requested_by` | varchar(255) NOT NULL | Ce que l'historique montre |
| `requested_at` | timestamptz NOT NULL | |
| `expires_at` | timestamptz NOT NULL | |
| `decided_by_id` | uuid NULL, FK `users.id` `ON DELETE SET NULL` | Approbateur, refuseur, ou approbateur dont la tentative a échoué ; `NULL` pour annulation, expiration |
| `decided_by` | varchar(255) NULL | |
| `decided_at` | timestamptz NULL | Toute clôture, y compris expiration |
| `note` | varchar(500) NULL | Motif du refus |
| `result_code` | varchar(64) NULL | Cause d'un échec ou d'une clôture (`author_inactive`, `package_gone`, `package_changed`, `nothing_left`, `schedule_changed`, …) |
| `result_params` | JSONB NULL (`none_as_null`) | |
| `created` | integer NULL | Commandes créées à l'approbation |
| `skipped` | integer NULL | Postes qui avaient déjà la commande |
| `left_out` | integer NULL | Postes de la liste supprimés, sortis de la portée de l'auteur ou révoqués |

`approval_request_machines` : `request_id` (uuid, FK `approval_requests.id` `ON DELETE CASCADE`), `machine_id` (uuid, FK `machines.id` `ON DELETE CASCADE`), clé primaire `(request_id, machine_id)`, index `ix_approval_request_machines_machine_id (machine_id)` (portée, fusion, suppression d'un poste). Une ligne par poste de la liste figée d'une demande `kind = command` ; aucune pour une planification.

Index de `approval_requests` : `ix_approval_requests_status_expires (status, expires_at)` (expiration, badge) ; `ix_approval_requests_requested_by_status (requested_by_id, status)` (« mes demandes », limite de 20, suppression d'un compte) ; `ix_approval_requests_decided_at (decided_at)` (purge) ; `ix_approval_requests_decided_by_id (decided_by_id)`, `ix_approval_requests_schedule_id (schedule_id)`, `ix_approval_requests_package_id (package_id)` (clés étrangères : supprimer un compte, une planification ou un paquet ne parcourt pas la table) ; index uniques partiels `uq_approval_requests_pending_schedule (schedule_id) WHERE status = 'pending'` (une seule demande en attente par planification) et `uq_approval_requests_pending_key (request_key) WHERE status = 'pending'` (doublons).

### 3.2 Colonnes ajoutées à `schedules`

`approved_by_id` (uuid NULL, FK `users.id` `ON DELETE SET NULL`, index `ix_schedules_approved_by_id`), `approved_by` (varchar(255) NULL), `approved_at` (timestamptz NULL), `approved_for_id` (uuid NULL, FK `users.id` `ON DELETE SET NULL`, index `ix_schedules_approved_for_id`), `approved_count` (integer NULL). Aucune donnée existante n'est touchée : les planifications actuelles restent `active`, non approuvées ; la garde d'exécution (§2.4) ne les arrête que si le réglage est activé et qu'elles dépassent le seuil.

### 3.3 Descente

`downgrade()` : `UPDATE schedules SET state = 'disabled', next_run_at = NULL WHERE state = 'to_approve'` (le code antérieur, `ScheduleState` et le type `state` de `services/schedules.ts`, ne connaissent que `active`, `disabled`, `suspended`, `done`) ; les planifications `suspended` avec un `suspended_code` `approval_*` restent suspendues, la console antérieure affiche le code brut — elles se réactivent comme les autres. Puis suppression des colonnes et index de `schedules`, de `approval_request_machines`, des index et de `approval_requests`. `tests/test_migration_0061.py` : montée et descente sur une base avec une planification `to_approve` (elle revient `disabled`, `next_run_at` nul) et une demande en attente.

### 3.4 Fusion de postes

`machine/crud.py: merge_into` appelle `approval_crud.move_to(session, source_id=…, target_id=…)` (à côté de `schedule_crud.move_to`) : dans les demandes **en attente**, un `DELETE` des lignes enfant du doublon dont la demande vise déjà le poste gardé, puis un `UPDATE approval_request_machines SET machine_id = <gardé> WHERE machine_id = <doublon>` sur les autres ; `machine_count` inchangé. Les lignes des demandes closes sont supprimées avec le poste fusionné (cascade) : les compteurs de la demande close restent ce qu'ils étaient, comme l'historique des exécutions de C3. Un poste supprimé disparaît de la liste par la cascade et compte dans `left_out` à l'approbation (§2.3, étape 5).

### 3.5 Conservation

Demandes closes purgées `APPROVAL_RETENTION_DAYS` (180) jours après `decided_at` (leurs lignes enfant partent par la cascade). Le journal d'audit garde la trace au-delà (`AUDIT_RETENTION_DAYS`).

---

## 4. API

### 4.1 `POST /commands` (modifié, `api/routes/commands.py`)

Après le contrôle des plages interdites et avant `dispatch.queue` : si `approval_policy.enabled`, `payload.type in RISKY_COMMAND_TYPES` et `len(machine_ids) > threshold`, alors pas de mise en file :

- `lock_author`, puis `approval.no_approver` et `approval.too_many_pending` ; création dans un point de sauvegarde, et sur doublon la demande existante est renvoyée (§2.2) ;
- crée la demande (`kind = command`, une ligne `approval_request_machines` par poste de la liste résolue, `package_digest` si déploiement), `audit.record(action="approval.request", resource_type="approval", resource_id=<id>, details={command_type, package_id?, package?, **target.audit(), count, threshold, expires_at})`, `emit.approval_requested(session, request)`, `approval_mail.queue_request_mails(…)` ; **pas** de `command.bulk` à ce stade (rien n'est parti) ;
- répond **202** avec le corps `CreateCommandsResponse` : `created = []`, `count = 0`, `revoked` comme aujourd'hui, et trois champs nouveaux, facultatifs : `approval_id`, `approval_expires_at`, `pending_approval` (le nombre de postes en attente). La route reçoit un paramètre `response: Response` et pose `response.status_code = 202` dans ce seul cas ; le décorateur gagne `responses={202: {"model": CreateCommandsResponse, "description": "En attente d'approbation"}}` pour l'OpenAPI.

Sémantique pour les scripts sur jeton (C8) : un **202** veut dire « rien n'est parti, une demande attend un second compte » ; `count = 0` n'y veut pas dire « rien à faire ». Un script lit `approval_id` (ou le statut), pas `count`. Écrit dans `DEPLOYMENT.md`, paragraphe « Webhooks et jetons d'API ».

Le verrou du paquet pris par `deployable_package` est relâché au commit ; il sera repris à l'approbation.

### 4.2 Routes nouvelles (`api/routes/approvals.py`, préfixe `/approvals`)

Toutes demandent `risky_command:execute` (dépendance de route) ; la liste, le décompte et le détail passent par `decidable` ou par « est l'auteur ».

| Route | Rôle |
|---|---|
| `GET /approvals?view=to_decide\|mine&status=&page=&page_size=` | `to_decide` : demandes `decidable` par le lecteur, paginées en SQL ; `mine` : les siennes, tout statut, les plus récentes d'abord. Expire d'abord ce qui doit l'être (`approval_crud.mark_expired`, `SKIP LOCKED`, commit), comme `list_commands` le fait avec `command_crud.mark_expired`. |
| `GET /approvals/summary` | `{enabled, to_decide, mine_pending}` : le badge du menu ; `to_decide` est le `count()` de la même clause que la liste. Un lecteur sans `risky_command:execute` reçoit 403, et la console ne l'appelle pas. |
| `GET /approvals/{id}` | Détail, visible de son auteur et de qui peut la décider ; sinon `approval.not_found` (404). Pour une commande : les postes de la liste **dans la portée actuelle du lecteur** (`machine_ids_clause(scope, ApprovalRequestMachine.machine_id)` : `id`, `hostname`, salle), et `hidden` = le nombre des autres — l'auteur dont la portée a été restreinte depuis ne voit plus leurs noms. Pour une planification : la planification résumée. |
| `POST /approvals/{id}/approve` | Corps `{confirm_forbidden_window: bool = false}`. Session obligatoire (`CurrentAuthSession`) : un jeton d'API reçoit `api_token.forbidden_here`. Réponse : la demande, avec `created`, `skipped`, `left_out`. Échecs : validés puis répondus (§2.3). |
| `POST /approvals/{id}/reject` | Corps `{note?: str ≤ 500}`. Session obligatoire, même refus du jeton. |
| `POST /approvals/{id}/cancel` | Son auteur seul (sinon `approval.not_found`) ; possible par jeton en écriture. |

Planifications (`api/routes/schedules.py`) : `ScheduleOut` gagne `approval: {id, status, expires_at, approved_by, approved_at, approved_count} | null` et accepte l'état `to_approve` dans `list_schedules?state=`.

### 4.3 Journal d'audit (`resource_type = "approval"`)

| Action | Acteur | Détails |
|---|---|---|
| `approval.request` | l'auteur | `kind`, `command_type`, `package`, cible décrite (`target.audit()`), `count`, `threshold`, `expires_at`, `schedule` (nom) |
| `approval.approve` | l'approbateur | `requested_by`, `created`, `skipped`, `left_out` (commande) ou `schedule`, `approved_count` |
| `approval.reject` | le refuseur | `requested_by`, `note` |
| `approval.cancel` | l'auteur, ou qui modifie ou désactive la planification | `cause` si la clôture vient d'une modification ou désactivation de la planification |
| `approval.expire` | `settings.PROJECT_NAME`, ou l'approbateur qui constate l'échéance | `requested_by` |
| `approval.fail` | l'approbateur | `cause` (`author_gone`, `author_inactive`, `permission_lost`, `package_gone`, `package_changed`, `nothing_left`, `in_past`, `forbidden_window`, code d'erreur de paquet) |

Plus `command.bulk` à l'approbation (acteur : l'auteur ; détails : `approval_id`, `approved_by`), `schedule.create`/`update`/`enable` inchangés (`details.approval: "required"` quand une demande est créée), `schedule.suspend` avec la cause `approval_required`. Console : section `approval` de `i18n/messages/audit.ts` (FR et EN), libellé de ressource `approval`, libellés des clés de détails nouvelles.

### 4.4 Codes d'erreur (`core/errors.py`, `ErrorCode`, et `i18n/messages/errorCodes.ts` FR et EN)

| Code | Statut | Quand |
|---|---|---|
| `approval.not_found` | 404 | Inconnue, ou hors de ce que le lecteur peut voir |
| `approval.not_pending` | 409 | Déjà décidée, annulée, expirée (y compris expirée à l'instant, validée avant de répondre) |
| `approval.own_request` | 403 | L'auteur tente d'approuver ou de refuser la sienne |
| `approval.no_approver` | 409 | Aucun autre compte ne pourrait l'approuver |
| `approval.too_many_pending` | 409 | 20 demandes en attente pour cet auteur |
| `approval.not_enough_approvers` | 422 | Activation du réglage avec moins de deux comptes capables d'approuver (`details.eligible`) |
| `approval.author_not_allowed` | 409 | L'auteur n'a plus son compte, ses droits (`details.cause`) ; demande close en échec |
| `approval.package_gone` | 409 | Le paquet a été supprimé depuis la demande ; demande close en échec |
| `approval.package_changed` | 409 | Le paquet a changé depuis la demande ; demande close en échec |
| `approval.nothing_left` | 409 | Aucun poste de la liste n'est encore dans la portée de l'auteur ; demande close en échec |

Les refus réutilisés : `auth.permission.denied`, `command.forbidden_window`, `schedule.in_past`, `schedule.forbidden_window`, `package.*`, `api_token.forbidden_here`.

### 4.5 Worker (`core/worker.py`)

| Job | Rythme | Rôle |
|---|---|---|
| `expire_approvals` | `every(300)` | `approval_crud.mark_expired(session, now)` : demandes `pending` dont `expires_at <= now`, verrouillées `FOR UPDATE SKIP LOCKED`, par lots de 100, commit par lot ; chacune passe par `expire` (§2.2). |
| `purge_approvals` | `housekeeping` (quotidien, 8 h) | Supprime les demandes closes depuis plus de `APPROVAL_RETENTION_DAYS`. |

Pas de job d'exécution : l'approbation met en file dans la requête de l'approbateur, comme `POST /commands`.

---

## 5. Console

| Élément | Où | Qui le voit |
|---|---|---|
| **Page « Approbations »** (`pages/ApprovalsPage.vue`, route `approvals`, `/approvals`) | Route déclarée dans `router/routes.ts` avec `meta: { title: 'layout.pages.approvals', requiresPermission: 'risky_command:execute' }` ; `router/access.ts` n'est pas touché (la page n'entre pas dans `LANDING_PAGES`). Menu de `layouts/MainLayout.vue`, après « Planifications », avec un badge orange (nombre `to_decide`) sur le modèle de « Signalements » (`useReportsBadge.ts` → `composables/useApprovalsBadge.ts`, `notifyApprovalsChanged()`). | `risky_command:execute`, et seulement si l'approbation est activée **ou** qu'il reste des demandes (`summary`). |
| Onglet « À approuver » | Tableau : auteur, action (libellé du catalogue `services/commands.ts`, paquet), cible décrite, nombre de postes, demandée le, expire dans ; boutons « Approuver » et « Refuser ». | Idem |
| Onglet « Mes demandes » | Tableau de ses demandes, statut en puce (en attente, approuvée par X, refusée — motif, annulée, expirée, en échec — cause), bouton « Annuler » si en attente. | Idem |
| Dialogue de décision (`components/approval/ApprovalDecisionDialog.vue`) | Rappel de la demande, liste des postes (pliée au-delà de 20, « + N hors de votre portée » pour `hidden`), plage interdite en cours avec la même confirmation que l'envoi (`schedules.forbiddenConfirm`), champ motif pour le refus. Après décision : notification avec le résultat (`created`, `skipped`, `left_out`). Sur `approval.not_pending`, `approval.author_not_allowed`, `approval.package_gone`, `approval.package_changed`, `approval.nothing_left` : message, puis liste et badge relus (la demande est close). | L'approbateur |
| Envoi en masse | `bulkSendNotification` (`services/commands.ts`) : une réponse portant `approval_id` affiche « Demande d'approbation envoyée pour N postes : un second compte doit l'approuver avant {heure} », avec une action « Voir » vers la page ; elle s'appuie sur `approval_id`, jamais sur `count`. Couvre `composables/useMachineBulkActions.ts` et `components/package/PackageDeployDialog.vue`, qui l'importent déjà de `services/commands`. `CreateCommandsResponse` (type) gagne les trois champs facultatifs. `MachineDetailPage` (un seul poste) n'est pas concernée. | L'auteur |
| Planifications | `services/schedules.ts` : type `state` (`'active' \| 'disabled' \| 'suspended' \| 'done'`) += `'to_approve'`, champ `approval` ; libellé « À approuver » et causes de suspension `approval_required`, `approval_rejected`, `approval_expired`, et `result_code` d'exécution `schedule_changed`, `approval_required`, dans `i18n/messages/schedules.ts` ; `ScheduleDialog.vue` notifie « Enregistrée : en attente d'approbation » quand l'état revenu est `to_approve` ; colonne « État » de `SchedulesPage.vue` avec l'approbateur en infobulle d'une planification approuvée. | Lecteurs des planifications |
| Carte « Approbation à deux » (`components/settings/SettingsApprovalCard.vue`) | Placée dans `pages/SettingsPage.vue` juste après le bloc en ligne des Planifications (commentaire « Schedules (C3) »), qui n'est pas un composant. Interrupteur, seuil, durée de validité, phrase « N comptes peuvent approuver (sans tenir compte des lieux) » ; l'interrupteur est grisé avec l'explication quand N < 2 ; erreur `approval.not_enough_approvers` affichée dans la carte. Libellés dans `i18n/messages/settings.ts` (FR et EN). `services/settings` : champs `approval_*` et `env_approval_*`. | `settings:read` ; modifiable avec `settings:write` |
| Webhooks | `'approval.requested'` dans `WEBHOOK_EVENTS` (`services/webhooks.ts`) ; clé `approval_requested` dans les évènements de `i18n/messages/integrations.ts` (FR et EN). | |

Catalogue de textes : `i18n/messages/approvals.ts` (FR et EN, typé par `types.ts`), enregistré dans `i18n/messages/index.ts` ; `layout.pages.approvals` et l'entrée de menu dans `i18n/messages/layout.ts`. Service : `services/approvals.ts`.

---

## 6. Jalons

| Jalon | Contenu | Durée |
|---|---|---|
| A1 | Migration `0061_mass_approval` (tables, colonnes, index, descente), modèle, `approval_policy`, réglages (`core/config.py`, `settings_routes.py`, refus sous deux approbateurs, `environment.py`, `settingsEnv.ts`, `settings_texts_fr.json`, `.env.example`), `approval/reach.py`. | 0,5 j |
| A2 | `POST /commands` en demande (202, `request_key`, `lock_author`), routes `/approvals` avec `decidable`, exécution revérifiée (§2.3) et chemin d'échec validé, journal, codes d'erreur, `approval_mail.py` et ses textes, évènement de webhook (modèle, `emit`, `texts`), fusion, jobs `expire_approvals` et `purge_approvals`. | 1 j |
| A3 | Planifications : état `to_approve`, colonnes `approved_*`, `estimate`, `_apply`, `set_state`, approbation, refus, expiration, garde dans `run_one`, `follow_one` (états et `schedule_changed`), `rezone`, `visible_to` déplacée, causes de `schedule_mail`. | 0,5 j |
| A4 | Console : page, route, badge, dialogue, notification d'envoi, planifications, carte de Paramètres, audit, erreurs, webhooks. | 0,75 j |
| A5 | Docs (`DEPLOYMENT.md` : ce que fait le réglage, pourquoi il ne s'active pas avec un seul administrateur, le nombre d'approbateurs qui ignore les lieux, le seuil par envoi et le découpage, le 202 pour les scripts sur jeton, ce qu'il ne protège pas ; variables ; `README.md`, feuille de route), notes de version, §8. | 0,25 j |

---

## 7. Tests

### 7.1 Serveur (`tests/test_approvals.py`, `tests/test_approvals_schedules.py`, `tests/test_migration_0061.py`)

- **Seuil** : réglage désactivé → comportement actuel (200, commandes créées) ; activé, N postes exactement → 200 ; N + 1 → 202, aucune ligne `commands`, une demande et ses N + 1 lignes `approval_request_machines`, `approval.request` au journal, pas de `command.bulk` ; l'OpenAPI déclare la réponse 202.
- Comptage : postes au jeton révoqué non comptés ; « tout le parc » d'un compte limité compte son site ; postes ayant déjà la commande ouverte comptés.
- Types : commande courante (`quick_scan`) sur 500 postes → jamais de demande ; `package_install` et `package_uninstall` au-delà du seuil → demande avec `package_digest` ; un seul poste → jamais.
- Plage interdite à la demande : refus sans confirmation, demande créée avec confirmation.
- **Doublon** : la même requête deux fois → même `approval_id`, un seul e-mail par approbateur, un seul webhook ; deux créations **concurrentes** (deux sessions) → une seule demande en attente, les deux réponses portent le même `approval_id` ; vingt-et-unième demande en attente → `approval.too_many_pending`, y compris quand les créations sont simultanées.
- `approval.no_approver` : administrateur seul détenteur des droits ; compte limité à un site dont aucun autre compte ne couvre les postes.
- **Approbation** : par un autre compte → commandes créées au nom de l'auteur (`created_by`), `command.bulk` avec `approval_id` et `approved_by`, `approval.approve`, e-mail à l'auteur ; par l'auteur → `approval.own_request` ; par un compte sans `risky_command:execute` → 403 ; par un compte ne voyant qu'une partie des postes → 404 ; approuver ou refuser par jeton d'API (même en écriture) → `api_token.forbidden_here` ; annuler la sienne par jeton → accepté.
- **Chemin d'échec validé** : après un 409 `approval.package_changed`, la demande relue est `failed` (`result_code = package_changed`), `approval.fail` figure au journal et l'e-mail à l'auteur est en file ; une seconde tentative répond `approval.not_pending`. Même vérification pour `approval.author_not_allowed` (auteur désactivé, privé de `risky_command:execute`, supprimé) et `approval.nothing_left`.
- Revérification : paquet retiré → erreur de paquet, demande `failed` ; paquet supprimé (`package_id` nul) → `approval.package_gone`, pas `package.required` ; une partie des postes sortie de la portée de l'auteur, supprimée ou révoquée → `left_out` compté.
- Plage interdite à l'approbation : refus sans confirmation de l'approbateur, la demande reste en attente ; avec confirmation, approuvée.
- Concurrence : deux approbations simultanées → une seule mise en file (l'autre `approval.not_pending`) ; approbation et annulation simultanées → une seule issue ; `mark_expired` pendant qu'une approbation tient la ligne → la ligne est sautée.
- **Refus** avec motif → e-mail à l'auteur avec le motif ; **annulation** par l'auteur, par un autre (404) ; décision sur une demande close → 409.
- **Expiration** : job `expire_approvals` et expiration à la lecture ; approbation d'une demande échue mais pas encore marquée → 409 `approval.not_pending`, et la demande relue est `expired` avec `approval.expire` au journal ; e-mail.
- Liste, badge et détail : `to_decide` exclut ses propres demandes et celles hors de sa portée ; `summary.to_decide` égal au total de la liste ; un compte limité ne voit pas une demande « tout le parc » d'un autre ; l'auteur dont la portée a été restreinte voit au détail les seuls postes encore dans sa portée et `hidden` pour le reste.
- E-mails : envoyés aux approbateurs possibles, pas à l'auteur, pas aux comptes `email_preference = none`, pas à un compte désactivé, dans la langue de chacun ; textes figés dans `mail_texts.json`.
- Webhook `approval.requested` mis en file pour un webhook abonné, dans la transaction (rollback → rien) ; `data` au schéma §2.5, sans liste de postes ; corps Teams et Mattermost composés en FR et EN par `webhook/texts.py`.
- **Réglages** : activation avec un seul compte capable → `approval.not_enough_approvers` ; avec deux → accepté, `settings.update` au journal ; bornes du seuil et de la durée ; `approval_eligible` exact (administrateurs, groupe Techniciens, compte désactivé exclu, deux comptes limités à deux sites comptent pour 2) ; désactivation avec demandes en attente → elles restent décidables, plus aucune nouvelle ; textes des variables (`test_settings_texts.py`).
- Fusion : le poste du doublon remplacé dans une demande en attente, sans ligne en double quand la demande visait les deux.
- Purge : demande close au-delà de la rétention supprimée avec ses lignes enfant, demande en attente gardée.
- Migration : montée et descente de `0061_mass_approval` sur une base avec planifications existantes ; descente avec une planification `to_approve` → `disabled`, `next_run_at` nul.
- **Planifications** : création à risque au-delà du seuil (réunion des anneaux comprise) → `to_approve`, `next_run_at` nul, non exécutée par `run_due` ; approbation → `active`, `next_run_at` calculé, `approved_by`, `approved_for_id`, `approved_count` ; un anneau s'enchaîne sans nouvelle demande ; modification d'une planification approuvée → nouvelle demande, ancienne close `schedule_changed` ; **modifier une planification à anneaux pendant l'étape 1 ne lance pas l'étape 2** (ni avec les anciens ni avec les nouveaux `rings`), qu'elle redevienne `active` ou passe `to_approve`, et les postes réveillés sont quand même éteints ; une ponctuelle `done` à anneaux continue ses étapes ; réactivation par l'auteur approuvé, cible inchangée → active sans demande ; **réactivation par un tiers sans limite** → nouvelle demande, comptée dans sa portée ; réactivation par l'approbateur → nouvelle demande ; désactivation d'une planification à approuver → demande close ; suppression → demande supprimée ; refus et expiration → `suspended` avec leur code ; échec d'approbation (auteur désactivé) → planification `suspended`, validée avant le 409 ; ponctuelle dont l'heure est passée à l'approbation → échec `in_past` ; plage interdite ajoutée entre la demande et l'approbation → échec ; paquet supprimé → `approval.package_gone`.
- Garde d'exécution : planification non approuvée qui dépasse le seuil → suspendue `approval_required`, e-mail ; **planification à anneaux de 5 étapes de 39 postes avec N = 40**, écrite avant l'activation → suspendue au départ ; approuvée dont la cible **dépasse `approved_count`** → suspendue ; approuvée qui reste sous `approved_count` → exécutée ; la garde ne se déclenche pas aux étapes 2 et suivantes.
- `rezone` : une ponctuelle `to_approve` voit son `run_at` recalé, une hebdomadaire `to_approve` garde `next_run_at` nul.
- Textes : causes nouvelles dans `schedule_mail` (FR, EN) ; chaque `ErrorCode` nouveau a son texte (test existant du catalogue).

### 7.2 Console

- `services/approvals.spec.ts` : appels, paramètres de liste.
- `ApprovalsPage.spec.ts` et `ApprovalsPage.en.spec.ts` : les deux onglets, puces de statut, annulation, actualisation du badge après décision, pluriels anglais.
- `ApprovalDecisionDialog.spec.ts` : approbation, refus avec motif, confirmation de plage interdite sur `command.forbidden_window`, affichage des erreurs (`approval.package_changed`, `approval.package_gone`, `approval.not_pending`) suivi d'une relecture de la liste, liste des postes pliée, `hidden`.
- `services/commands` : `bulkSendNotification` sur une réponse 202 portant `approval_id` (et `count = 0`) → notification d'attente, pas « rien envoyé » ; `useMachineBulkActions.spec.ts` et `PackageDeployDialog.spec.ts` : la notification d'attente.
- `MainLayout.spec.ts` : entrée et badge visibles avec `risky_command:execute` et réglage actif, absents sinon ; la route `approvals` refusée sans le droit (`meta.requiresPermission`).
- `SchedulesPage.spec.ts`, `ScheduleDialog.spec.ts` : état « À approuver », causes de suspension, notification d'enregistrement en attente.
- `SettingsApprovalCard.spec.ts` : interrupteur grisé sous deux approbateurs, enregistrement, erreur `approval.not_enough_approvers`.
- `AuditPage` : libellés des six actions `approval.*` en FR et EN ; `SettingsWebhooksCard.spec.ts` : `approval.requested` proposé, libellé de `approval_requested`.
- Catalogues : `settingsEnv.ts` FR et EN complets pour les quatre variables.

---

## Hors périmètre

- Approbation à plus de deux personnes, ou par un rôle d'approbateur distinct des droits d'exécution.
- Approbation des commandes courantes, du réveil, d'une commande sur un seul poste.
- **Cumul des envois** : le seuil s'applique par envoi ; une action découpée en lots de N postes ou moins (console, script sur jeton, plusieurs planifications), ou approuvée par la même personne depuis un second compte (local de secours et annuaire, C7), n'est pas arrêtée. Le journal (`command.bulk`, `schedule.create`) permet de repérer un découpage. `DEPLOYMENT.md` le dit.
- Approbation des changements de réglages, de groupes ou de comptes : un compte qui détient `settings:write` peut désactiver l'approbation puis agir seul ; le journal (`settings.update`) en garde la trace. Retirer un droit ou désactiver un compte n'est pas bloqué quand cela laisse moins de deux approbateurs : la demande suivante répond `approval.no_approver`. `DEPLOYMENT.md` le dit.
- Ressaisie du mot de passe ou du second facteur au moment d'approuver.
- Re-approbation d'une planification approuvée quand son paquet change de version (la mise en file compare déjà l'empreinte à la livraison, `commands.package_digest`). Une cible qui grandit au-delà de `approved_count`, elle, suspend la planification (§2.4).
- Re-comptage aux étapes 2 et suivantes d'une exécution à anneaux déjà partie.
- Notifications poussées autres que l'e-mail et le webhook ; évènements de webhook pour les issues d'une demande.
- Agent : non modifié.

---

## Décisions prises par défaut (à confirmer)

1. **Seuil par défaut : 40 postes**, approbation déclenchée strictement au-delà ; compté sur les postes réellement visés (portée de l'auteur, jetons révoqués exclus), **par envoi**, sans cumul.
2. **Types concernés : `RISKY_COMMAND_TYPES` tels quels** (déploiements de paquets compris) et les planifications à « éteindre ensuite » ; pas de liste réglable.
3. **Planifications approuvées une fois, à l'écriture, pour un auteur et un nombre de postes** ; modification, réactivation par un autre compte que l'auteur approuvé, ou cible plus large que le nombre approuvé redemandent ; garde à l'exécution (`run_one`, même `estimate()`) qui suspend ce qui dépasse.
4. **Liste de postes figée à la demande** (table enfant), exécutée telle quelle (moins ce qui est sorti de la portée de l'auteur) ; empreinte du paquet comparée ; paquet supprimé → échec `package_gone`.
5. **Pas de droit nouveau** : approuver demande les mêmes droits que l'action, et une portée couvrant tous les postes ; le décompte des approbateurs possibles ignore les lieux.
6. **Activation refusée avec moins de deux comptes capables d'approuver**, sans verrou sur la gestion des comptes ensuite ; demande refusée à la création si aucun autre compte ne peut l'approuver.
7. **Validité de 24 h** (réglable de 1 à 168 h) ; 20 demandes en attente au plus par auteur ; conservation 180 jours.
8. **Réponse 202** de `POST /commands` pour une demande, avec `approval_id` ; pas de `command.bulk` avant l'approbation.
9. **Un échec à l'approbation clôt la demande** (validé, puis erreur 409), plutôt qu'une réponse 200 portant `status = failed`.
10. **Approbation et refus impossibles par jeton d'API** ; pas de ressaisie du mot de passe.
11. **Un évènement de webhook nouveau, `approval.requested`**, et des e-mails aux approbateurs (sauf préférence « rien », 20 au plus) et à l'auteur à chaque issue.
12. **Désactiver le réglage laisse les demandes en attente décidables** et n'exécute rien de lui-même.
13. **Variables `APPROVAL_*` rangées dans le groupe d'environnement `console`** (« Console et sécurité »), sans groupe nouveau.

---

## 8. Écarts constatés à l'implémentation

Côté serveur (jalons A1 à A3, et la partie de A5 qui touche aux variables et au 202) :

1. **Textes de la console ajoutés dès le serveur.** Les tests du serveur exigent un texte FR et EN pour chaque code d'erreur, chaque action et chaque type de ressource du journal (`test_errors_unit.py`) : `i18n/messages/errorCodes.ts` (les dix codes `approval.*`), `i18n/messages/audit.ts` (section `approval`, ressource `approval`, clés de détails `count`, `threshold`, `approval_id`, `approved_by`, `requested_by`, `cause`, `left_out`, `approved_count`, `schedule`, `approval`) et `i18n/messages/settingsEnv.ts` (les quatre variables) sont donc remplis avec le serveur, et la liste figée de `utils/auditLabels.spec.ts` gagne les six actions `approval.*`. Le reste de la console (§5) reste à faire.
2. **`decidable(…, pending=False, only_id=…)`.** Le détail et les routes de décision lisent la règle sans la condition `status = pending` : une décision sur une demande close répond `approval.not_pending` (409) et non `approval.not_found`, comme §7.1 le demande. Le badge (`summary`) ne lance pas `mark_expired` : il ne compte que les demandes dont `expires_at` est à venir, ce qui donne le même total que la liste, qui, elle, expire d'abord.
3. **Ordre des contrôles d'une décision** (`approval_crud.lock_for_decision`) : ligne verrouillée → `approval.own_request` → droits de l'action (`auth.permission.denied`, `schedule:write` en plus pour une planification) → `decidable` (404) → `pending` (409) → échéance (expiration validée puis 409).
4. **Annuler la demande d'une planification la désactive.** §4.2 ne dit pas ce que devient une planification `to_approve` dont l'auteur annule la demande : elle passe `disabled` (comme « Désactiver »), plutôt que de rester à attendre une décision qui ne viendra plus.
5. **Une approbation de planification qui trouve la planification hors de l'état `to_approve`** (réécrite, désactivée, supprimée sous la demande) clôt la demande `cancelled` / `schedule_changed`, valide, puis répond `approval.not_pending`.
6. **Réactiver une planification `to_approve`** clôt sa demande en attente (`schedule_changed`) et en crée une nouvelle si la règle l'exige (nouvel e-mail aux approbateurs) ; la réactiver alors que le réglage est coupé ou sous le seuil la rend `active` et clôt la demande : c'est un geste explicite d'une personne, pas une bascule automatique (§2.1, « Réglage désactivé après coup », reste vrai pour ce que le serveur fait seul).
7. **`follow_one` et l'état `suspended`** : l'étape suivante ne démarre pas, avec `result_code = approval_required` si `suspended_code` commence par `approval_`, `schedule_disabled` sinon. Une exécution marquée `schedule_changed` s'arrête quelles que soient les nouvelles `rings` (même si la planification réécrite n'en a plus).
8. **La limite de vingt demandes et `lock_author` valent aussi pour les planifications.** Le verrou est pris avant la recherche d'approbateurs ; pour une commande, la demande identique déjà en attente est relue avant tout autre contrôle (un renvoi ne répond jamais `too_many_pending`).
9. **Échéance d'une ponctuelle** : `expires_at = min(maintenant + ttl, run_at)` ; `rezone` recale `run_at` mais pas `expires_at` de la demande déjà créée.
10. **Libellés des actions dans les e-mails** : le serveur n'avait pas de catalogue des types de commande ; `approval_mail_texts.py` en porte un pour les dix types à risque (FR, EN). Le paquet y est nommé sans guillemets (« Installer le paquet 7-Zip 23.01 »), pour éviter des guillemets imbriqués. Les causes d'échec comprennent aussi les codes d'erreur de paquet (`package.retired`, `package.not_ready`, `package.not_found`), que `fail` garde tels quels en `result_code`.
11. **E-mails aux approbateurs** : `reach.*_approvers(limit=20)` retient les vingt premiers par adresse, puis ceux en préférence « rien » sont écartés : moins de vingt e-mails partent quand certains l'ont choisie.
12. **Webhook** : pour une planification, `data.target` vaut `{"target": kind, kind: value}` ; pour une commande, ce que `target.audit()` donnerait (`{"target": "machines", "requested": n}` pour une liste).
13. **Réglage `approval_enabled`** : la vérification `eligible_count >= 2` n'a lieu que quand le réglage passe de faux à vrai ; renvoyer `true` alors qu'il l'est déjà (la carte envoie tous ses champs) ne la refait pas. `null` rend la main à l'environnement sans vérification.
14. **`to_decide`** est trié par échéance (la plus proche d'abord), `mine` par date de demande décroissante.
15. **Docs serveur** : `DEPLOYMENT.md` a reçu avec le serveur les quatre variables, le paragraphe « Approbation à deux » et la sémantique du 202 pour les scripts sur jeton ; `deploy/.env.example` les quatre variables.

Côté console et docs (jalons A4 et A5) :

16. **Cible d'une demande** : l'API ne sert que la cible telle que stockée (`{kind, value}`), sans le nom d'une salle ou d'un bâtiment (`value` y est un identifiant). La console dit « une salle », « un bâtiment », « une liste de postes » ; le domaine, le site et l'état sont nommés (« le domaine LYCEE »). Le détail d'une commande nomme les postes visés et leur salle.
17. **Sous-titre de la page** : `summary` ne sert pas le seuil ; la page dit « au-delà du nombre de postes fixé dans Paramètres » plutôt que le nombre, et dit quand l'approbation est désactivée que les demandes restantes se décident encore.
18. **Entrée du menu** : visible avec `risky_command:execute` quand l'approbation est activée, ou qu'il reste une demande à décider (`to_decide`) ou une demande à soi en attente (`mine_pending`) — lecture de « qu'il reste des demandes ». Le compteur du badge (orange) est `to_decide` ; il est relu sur `notifyApprovalsChanged()` (décision, annulation, envoi mis en attente, planification enregistrée ou réactivée « à approuver », désactivée ou supprimée en attente, réglage enregistré), à chaque navigation et quand le droit change. La page suit le même signal pour relire sa liste.
19. **`bulkSendNotification(res, onView?)`** : le service ne connaît pas le routeur ; l'action « Voir » n'est offerte que quand l'appelant passe de quoi naviguer (`useMachineBulkActions`, `PackageDeployDialog`). La notification d'attente est de type `info`, affichée dix secondes, et s'appuie sur `approval_id`, jamais sur `count`.
20. **Dialogue de décision** : les codes qui closent la demande (`approval.not_pending`, `approval.not_found`, `approval.author_not_allowed`, `approval.package_gone`, `approval.package_changed`, `approval.nothing_left`, `approval.target_grew`, et pour une planification `schedule.in_past`, `schedule.forbidden_window`) affichent leur message, ferment le dialogue et font relire liste et badge ; les autres erreurs laissent le dialogue ouvert. La plage interdite demande une confirmation propre à l'approbation (« Approuver quand même… »), avec le titre et le bouton d'annulation de `schedules.forbiddenConfirm`. Au-delà de vingt postes, la liste est pliée derrière « Afficher les N postes ».
21. **Colonne « Expire »** : la date et l'heure d'échéance plutôt qu'une durée relative (« expire dans »), qui aurait demandé une horloge rafraîchie sur la page.
22. **Carte de Paramètres** : composant à part (`SettingsApprovalCard.vue`) qui reçoit les réglages de la page et lui rend la réponse de l'enregistrement ; il expose `dirty`, et la garde « modifications non enregistrées » de la page le compte (`settings.unsaved.cards.approval`). L'interrupteur n'est grisé sous deux approbateurs que si l'approbation est éteinte : allumée (elle l'a été quand il y en avait deux), elle peut toujours être coupée. La carte se remplit de nouveau quand ses propres valeurs changent, pas quand une autre carte enregistre. L'erreur `approval.not_enough_approvers` s'affiche dans la carte, pas en notification.
23. **Planifications** : « Désactiver » est offert pour une planification `to_approve` (le serveur clôt sa demande) ; sous l'état, « En attente d'approbation, avant le … » et, pour qui détient `risky_command:execute`, un lien vers « Approbations ». Les codes de suspension laissés par une approbation en échec comprennent aussi `in_past` et `forbidden_window` (textes ajoutés). Le `result_code` d'exécution `approval_required` a deux formes : au départ (`count`, `threshold`, posé par `run_one`) et avant une étape suivante (`stage`, posé par `follow_one`) ; la console a un texte pour chacune (`approval_required`, `approval_required_stage`).
24. **Pas d'écran de détail pour « Mes demandes »** : l'onglet montre statut, approbateur, motif du refus ou cause de l'échec et compteurs de l'approbation ; le détail (`GET /approvals/{id}`) ne sert qu'au dialogue de décision.
25. **Notes de version** : le dépôt n'en tient pas en dehors de `README.md` (tableau de la feuille de route, ligne « Approbation à deux des actions de masse » passée « Livré ») et de `DEPLOYMENT.md` (paragraphe sur la console ajouté au paragraphe « Approbation à deux »).

Relecture (C10, serveur) :

26. **Cible grandie entre la demande et l'approbation.** §2.4 disait « `approved_count = estimate(...)` à l'approbation » : c'était approuver des postes que l'approbateur n'avait pas vus (le courriel, le webhook et la liste montrent `machine_count`). `approve_schedule` compare désormais le compte du moment à `machine_count` de la demande : plus grand, la demande échoue (`failed`, cause `target_grew`, paramètres `count` et `approved`), la planification est suspendue avec le même code, et la réponse est `approval.target_grew` (409), validée avant la réponse comme les autres échecs. Plus petit ou égal, `approved_count` est le compte du moment. Textes ajoutés : code d'erreur, cause de l'e-mail de résultat, cause de « Mes demandes », code de suspension de la page Planifications (sans nombre : la suspension vient de l'approbation, sans passage, et la page ne lit ses paramètres que dans le dernier passage ; les comptes restent dans « Mes demandes », l'e-mail et la réponse 409) ; le code compte parmi ceux qui closent la demande dans le dialogue de décision.
27. **Écrire, activer, désactiver ou supprimer une planification verrouille dans l'ordre de l'approbation** (`routes/schedules._lock`) : la demande en attente de la planification d'abord, puis la planification, relue sous le verrou (`populate_existing`). Une approbation validée entre la lecture et l'écriture est ainsi vue puis effacée par l'écriture, et l'ordre inverse, qui faisait un interblocage avec `approve_schedule` ou l'expiration, n'existe plus. `clear_approval` marque en outre ses cinq colonnes modifiées (`flag_modified`) : elles sont écrites même quand la copie chargée les lisait déjà vides.
28. **Renvoi d'une commande dont la demande identique a passé son échéance** sans que le worker l'ait encore expirée : `submit_command` l'expire (`approval.expire`, e-mail à l'auteur) et crée une nouvelle demande, au lieu de rendre la demande morte avec une échéance passée. Précise le point 8 : la demande identique relue avant tout autre contrôle est celle qui est encore dans son délai. Avant d'expirer, la demande est relue sous le verrou de sa ligne (`SELECT … FOR UPDATE`, `populate_existing`) et doit être encore `pending` : le worker a pu l'expirer entre-temps (sinon deux `approval.expire` et deux e-mails), ou un approbateur la décider juste avant son échéance (sinon `expired` écrasait `approved`). Close entre-temps, quel que soit son état, elle est laissée telle quelle et le renvoi crée une nouvelle demande, comme tout renvoi après une décision : l'unicité ne vaut qu'entre demandes en attente (§2.2, « Doublon »), et répondre 202 avec l'identifiant d'une demande approuvée annoncerait une attente qui n'existe pas. Tests : `test_a_resend_past_its_time_leaves_an_approval_made_meanwhile`, `test_a_resend_past_its_time_expires_it_once_beside_the_job`.
29. **`APPROVAL_ENABLED=true` dans l'environnement** est appliqué tel quel, sans la vérification « deux approbateurs » du point 13 (qui ne vaut que pour Paramètres) : avec un seul compte capable d'approuver, une action à risque au-delà du seuil répond `approval.no_approver` jusqu'à ce que Paramètres coupe l'approbation. `DEPLOYMENT.md` et `README.md` le disent ; un test le couvre.

Relecture (C10, console) :

30. **Refus du paquet à l'approbation.** Un déploiement dont le paquet a été retiré, rendu non déployable ou supprimé depuis la demande échoue à l'approbation (`execute.failed`, demande close `failed` avec le code du paquet, commit) : `package.retired`, `package.not_ready`, `package.not_found` et `package.required` comptent désormais parmi les codes qui closent la demande dans le dialogue de décision (point 20), qui se ferme et fait relire liste et badge. Test : `on package.retired (the approval failed the request), closes and has the list read again` (`ApprovalDecisionDialog.spec.ts`).
31. **Réponses en retard.** La page des approbations numérote ses lectures : la réponse d'un onglet quitté depuis (ou d'une page précédente) est ignorée, au lieu d'afficher sous « Mes demandes » les demandes d'autres comptes avec un bouton « Annuler ». Test : `drops a late answer to a tab left since` (`ApprovalsPage.spec.ts`).
32. **Réécrire une planification `to_approve`** en une planification qui n'exige plus d'approbation clôt sa demande côté serveur (`schedule_changed`) : le dialogue de planification fait relire badge et liste quand la planification était `to_approve` avant l'écriture, pas seulement quand elle l'est après (comme `SchedulesPage` pour activer, désactiver ou supprimer). Test : `has the approvals read again when a waiting schedule is rewritten to need none` (`ScheduleDialog.spec.ts`).
