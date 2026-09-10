# Salles, vérifications, maintenance et interventions — plan de travail

> **Statut : cadrage validé le 2026-09-10** (§2), §2.2 compris. **J1 à J6
> livrés** (groupes de droits, commandes à risque, bâtiments et salles,
> classement depuis l'annuaire, journal des interventions, vérifications
> demandées, maintenance) — voir §11. Restent J7 (notifications) et J8
> (documentation, captures).
>
> Branche de travail : `claude/postes-maintenance-features-85buig`, fondée sur
> `claude/agent-location-wol-ughnse` (emplacement des postes + réveil relayé),
> **elle-même non encore fusionnée dans `main`** — voir §10.
>
> Objectif : la console cesse d'être seulement un tableau de bord de l'état
> *technique* des postes pour porter aussi leur **vie d'exploitation** :
> 1. regrouper les postes par **bâtiment et salle** en plus de l'emplacement,
>    à la main ou automatiquement depuis l'annuaire ;
> 2. **demander une vérification** d'un poste, l'affecter à quelqu'un, la clore
>    avec une note datée qui reste en base ;
> 3. un **cycle de maintenance** (global, par salle, par poste) avec un
>    responsable, une liste « à faire » par utilisateur, la transmission à un
>    autre, et la trace de chaque maintenance (note globale + note par poste) ;
> 4. un **historique des interventions** par poste (panne, installation,
>    mise à niveau…).

---

## 1. Point de départ — ce que le dépôt sait déjà faire

| Existant | Où | Conséquence pour ce chantier |
|---|---|---|
| `machines.location` — l'**emplacement** (site), texte libre **déclaré par l'agent** (YAML ou registre → GPO), vidé quand l'agent ne le déclare plus. Filtre, tri et regroupement dans la liste ; base du relais Wake-on-LAN. | `agent/internal/config`, `backend/app/api/routes/agent.py` (`clean_location`), `MachinesPage.vue` | L'emplacement **reste piloté par l'agent** : le rendre éditable en console créerait un conflit à chaque heartbeat. Bâtiments et salles sont des objets **côté serveur**, distincts. |
| `machines.needs_verification` + statut `needs_verification`, libellé **« À vérifier »** dans la liste et le tableau de bord. | `features/machine/fingerprint.py`, `MachinesPage.vue:573`, `DashboardPage.vue:217` | C'est la **vérification d'identité** (empreinte matérielle suspecte), pas une demande d'intervention humaine. L'existant est renommé « Identité à confirmer » (§2). |
| Deux rôles seulement : `admin` (tout) et `readonly` (lecture). Permissions statiques `(ressource, action)`, point d'extension prévu. `COMMAND/EXECUTE` garde les commandes ; `MACHINE/WRITE` garde la révocation de token et la fusion. | `features/user/permissions.py`, `routes/machines.py:994,1364-1427` | Un utilisateur « lecture seule » ne peut rien écrire. Un troisième rôle, **technicien**, est ajouté (§5). |
| Journal d'audit append-only ; `commands.created_by` porte l'e-mail de l'opérateur. | `features/audit` | Même convention pour « qui a fait quoi » : e-mail conservé en texte, pour survivre à la suppression du compte. |
| File d'e-mails (outbox) + préférence par compte ; worker avec jobs périodiques (`every`, `daily_at`). | `features/notification`, `core/worker.py` | Les rappels de maintenance et les affectations passent par la même file (J7). |
| L'agent connaît le **domaine** (`NetGetJoinInformation`) mais **rien de l'annuaire** : ni l'OU, ni l'attribut `location` de l'objet ordinateur. `go-ole` est déjà dans l'arbre de dépendances (via `wmi`). | `agent/internal/sysinfo` | La classification automatique demande un bloc de données de plus dans le heartbeat, et pour l'attribut AD un accès ADSI (§3). |
| Fusion de postes (`merge_machine`) et cascade `ON DELETE` sur les tables filles. | `routes/machines.py:1429`, `features/machine/crud.py` | Tout historique rattaché à un poste **suit la fusion** ; à la suppression, il disparaît avec lui (§2). |

---

## 2. Cadrage retenu

### 2.1 Décisions

| Sujet | Décision |
|---|---|
| **Hiérarchie** | **Emplacement › Bâtiment › Salle › Poste.** L'emplacement reste la valeur déclarée par l'agent (pas une table). Le **bâtiment est une table** (liste déroulante, jamais du texte libre), facultatif sur une salle, **sans cycle ni responsable propres** : c'est une clé de regroupement et de tri, pas un niveau d'héritage. La salle est l'entité qui porte les réglages de maintenance. |
| **Vocabulaire** | « Emplacement » (inchangé), « Bâtiment », « Salle ». |
| **Appartenance** | Un poste appartient à **une** salle ou à aucune. Une salle appartient à un bâtiment ou à aucun. |
| **Emplacement d'une salle** | Proposition §2.2, à confirmer : dérivé du bâtiment, ou porté par la salle quand elle n'a pas de bâtiment ; **divergence signalée, jamais refusée**. |
| **Classement automatique** | `ROOM_SOURCE` = `manual` (défaut) · `ad_ou` · `ad_location`. En mode `ad_*`, le rattachement manuel des postes est **interdit** (l'annuaire fait foi, aucun conflit possible) ; l'épinglage d'un poste se rajoutera si le besoin apparaît. Le site AD n'alimente **pas** l'emplacement (hors périmètre). |
| **Nom d'une salle auto-créée** | Le nom de l'OU (ou la valeur `location` AD) à la création, **renommable** ensuite en console — la clé est le DN, pas le nom. Une OU renommée = une nouvelle salle ; l'ancienne reste vide. Le bâtiment d'une salle auto-créée se choisit en console. |
| **Vérifications** | Le statut d'identité existant est **renommé « Identité à confirmer »** ; « Vérification » désigne la demande humaine. **Une seule** demande ouverte par poste. |
| **Droits** | **Groupes flexibles** plutôt que des rôles fixes : un groupe est un ensemble de permissions `ressource:action` composé dans la console, un compte cumule les droits de ses groupes. Trois groupes intégrés : Administrateurs (tous les droits, implicites), Lecture seule, Techniciens (lecture + commandes courantes et à risque). Les nouvelles ressources du chantier (salles, vérifications, maintenance, interventions, paramètres) entrent dans le catalogue au jalon qui les crée, et les Techniciens reçoivent par défaut l'écriture sur vérifications, interventions et maintenances. |
| **Commandes à risque** | Deux permissions : `command:execute` (scans, signatures, recherche de mises à jour, cache DNS, stratégies, diagnostics, réveil) et `risky_command:execute` en plus pour redémarrage, arrêt, installation de mises à jour, réinitialisation de Windows Update, réparations DISM, réinitialisation du spouleur. Liste côté serveur (`RISKY_COMMAND_TYPES`), miroir dans le catalogue de la console. |
| **Portée par emplacement** | **Plus tard.** Restreindre un groupe à certains emplacements ou salles (« les techniciens de Taravao ne voient que Taravao ») est du filtrage ligne par ligne dans chaque requête de liste, de fiche et de commande : un chantier à part, noté §12. Le modèle de groupes le permet sans refonte (une table `group_scopes` et un filtre commun aux requêtes). |
| **Transmettre la maintenance** | Changement **durable** du responsable de la salle ou du poste, par un admin. La délégation d'une seule occurrence n'est pas en v1. |
| **Réglages globaux** | Table `settings` + page **Paramètres** (admin) : cycle par défaut (initialisé depuis `MAINTENANCE_DEFAULT_CYCLE_DAYS`, 90 j), responsable par défaut, fenêtre « à échéance » (14 j). |
| **Cycle** | `NULL` = hérite ; `0` = **pas de maintenance** (salle de serveurs, VM). Poste jamais maintenu : dû à `first_seen + cycle`, pas immédiatement. Une intervention `maintenance` **antidatée** amorce le cycle pour un poste maintenu avant Tia'i. |
| **Notifications** | E-mail à l'affectation d'une vérification ; ligne « vos maintenances en retard » dans le résumé quotidien ; rappel hebdomadaire au responsable. Toutes derrière la préférence e-mail du compte. Jalon J7. |
| **Interventions** | Types fermés : maintenance, vérification, panne, installation logicielle, mise à niveau, autre. Modifiable par l'auteur et l'admin ; suppression admin, tracée dans l'audit. |
| **Suppression / fusion d'un poste** | Fusion : l'historique, la salle, la dernière maintenance suivent le poste conservé. Suppression : cascade ; l'export préalable est la sauvegarde. |
| **Livraison** | **Deux PR** : Salles + Journal (J1–J4), puis Vérifications + Maintenance (J5–J7). |

### 2.2 L'emplacement dans la hiérarchie (validé)

L'emplacement a deux natures qu'il faut tenir ensemble : **une valeur que
l'agent déclare** sur chaque poste (GPO), et **un lieu physique** dont un
bâtiment fait forcément partie. Proposition :

```
Emplacement « Lycée de Taravao »          ← valeur, portée par les bâtiments (et par les postes, via l'agent)
   └── Bâtiment « Bâtiment B »            ← table, location = « Lycée de Taravao »
          └── Salle « B12 »               ← table, building_id ; location propre seulement si pas de bâtiment
                 └── Poste                ← machines.location vient de l'agent
```

- **Un bâtiment porte l'emplacement** (`buildings.location`). Une salle
  rattachée à un bâtiment **en hérite** ; une salle sans bâtiment peut porter
  le sien (`rooms.location`). L'emplacement effectif d'une salle est donc
  `bâtiment.location ?? salle.location`, jamais saisi deux fois.
- **Le champ se choisit dans une liste** alimentée par les emplacements que le
  parc remonte déjà (`GET /machines/locations`), avec saisie libre autorisée —
  un bâtiment peut être créé avant que son premier poste ne parle. Cela évite
  la coquille qui rendrait chaque poste « divergent ».
- **Divergence** : quand `machines.location` et l'emplacement effectif de la
  salle sont tous deux renseignés et diffèrent, le poste est **signalé** :
  avertissement dans le dialogue de rattachement (mode manuel), badge dans la
  fiche et la liste, filtre « emplacement divergent ». **Jamais refusé** : en
  mode AD, c'est précisément l'information qui révèle une GPO mal ciblée ou
  un poste déménagé sans que l'OU suive.
- Ce que cela **ne fait pas** : modifier `machines.location`. L'agent reste
  seul à l'écrire ; corriger une divergence, c'est corriger la GPO ou déplacer
  le poste de salle.

Alternative écartée : faire de l'emplacement une table à part entière, avec
les bâtiments dessous. Elle obligerait à réconcilier chaque valeur remontée
par un agent avec une ligne (créer à la volée ? refuser ?), pour un objet qui
n'a aujourd'hui ni réglage ni responsable. La valeur suffit ; si un jour
l'emplacement doit porter quelque chose, la table se crée alors et les deux
colonnes `location` deviennent des clés étrangères.

---

## 3. Classification automatique depuis l'annuaire (1b)

Trois sources possibles, de coût très différent :

| Source | Où la lire | Coût | Verdict |
|---|---|---|---|
| **OU parente** de l'objet ordinateur | **Localement, sans LDAP** : le traitement des GPO écrit le DN de l'ordinateur dans `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine\Distinguished-Name`. L'OU parente est le second RDN (`CN=PC-B12-03,OU=Salle B12,OU=Postes,DC=lycee,DC=local` → `Salle B12`). Présent sur tout poste joint qui applique des GPO — c'est précisément le cas de déploiement de l'agent. | Une lecture de registre, aucune dépendance. | **v1** |
| **Attribut `location`** de l'objet ordinateur (onglet « Emplacement » d'ADUC) | Pas mis en cache localement → **requête LDAP**. Deux endroits possibles : (a) le **serveur**, avec un compte de service et une route réseau vers un DC — exclu pour un serveur hébergé hors site, le cas même pour lequel le relais WoL existe ; (b) l'**agent**, via **ADSI** (COM, `GetObject("LDAP://<DN>")`), qui s'authentifie avec le compte machine sans rien configurer et sans nouvelle dépendance (`go-ole` déjà présent). | Un appel COM, à lire **au rythme de l'inventaire (24 h)**, jamais dans le heartbeat de 60 s. | **v1, côté agent** |
| Nom de **site AD** (`DsGetSiteName`, netapi32) | Localement, un appel système. | Nul. | **Hors périmètre** : il alimenterait l'*emplacement*, pas la salle. Noté pour plus tard. |

Contrat :

- **Agent** : nouveau bloc facultatif `directory` dans le heartbeat, envoyé
  quand la valeur change (même mécanisme de hachage que l'inventaire) :
  ```json
  { "directory": { "distinguished_name": "CN=PC-B12-03,OU=Salle B12,OU=Postes,DC=lycee,DC=local",
                   "ou": "Salle B12", "ad_location": "Bât. B — salle 12" } }
  ```
  L'agent envoie **les deux** valeurs quand il les a ; c'est le serveur qui
  choisit. Poste hors domaine : bloc absent.
- **Serveur** : hors `manual`, à réception du bloc, le serveur **trouve ou
  crée** la salle par sa clé (`rooms.ad_key` : DN de l'OU, ou la chaîne
  `location`) et y rattache le poste. Une salle créée automatiquement garde
  ses réglages éditables en console (nom, bâtiment, cycle, responsable) ;
  seul **le rattachement des postes** est verrouillé.
- Les valeurs brutes sont aussi stockées sur le poste (`ad_distinguished_name`,
  `ad_ou`, `ad_location`) et affichées dans la fiche, quel que soit le mode :
  c'est une information utile même en classement manuel.

---

## 4. Modèle de données

Une migration par jalon (`0017_rooms` pour J2 ; les colonnes de maintenance, d'annuaire et les tables de vérifications et d'interventions arrivent avec leur jalon), pour que chaque PR reste lisible seule.

### 4.1 Bâtiments et salles

```
buildings
  id          uuid PK
  name        text NOT NULL            -- « Bâtiment B »
  location    text NULL                -- emplacement (site), même vocabulaire que machines.location
  notes       text NULL
  created_at, updated_at
  UNIQUE NULLS NOT DISTINCT (location, name)   -- PostgreSQL ≥ 15 (le compose est en 16)

rooms
  id                      uuid PK
  name                    text NOT NULL            -- « B12 »
  building_id             uuid NULL FK buildings ON DELETE SET NULL (index)
  location                text NULL                -- seulement quand building_id est NULL ; ignoré sinon
  ad_key                  text NULL UNIQUE         -- DN de l'OU ou valeur AD `location` ; NULL = salle manuelle
  maintenance_cycle_days  int  NULL                -- NULL = hérite du global ; 0 = pas de maintenance
  maintenance_owner_id    uuid NULL FK users ON DELETE SET NULL
  notes                   text NULL
  created_at, updated_at
  UNIQUE NULLS NOT DISTINCT (building_id, name)    -- deux « B12 » dans deux bâtiments, oui ; dans le même, non
```

Supprimer un bâtiment ne supprime pas ses salles : elles deviennent « sans
bâtiment » (`SET NULL`), et l'emplacement qu'elles en héritaient est recopié
dans `rooms.location` au moment de la suppression pour ne rien perdre.

### 4.2 Colonnes ajoutées à `machines`

```
room_id                 uuid NULL FK rooms ON DELETE SET NULL   (index)
maintenance_cycle_days  int  NULL      -- surcharge poste
maintenance_owner_id    uuid NULL FK users ON DELETE SET NULL
last_maintenance_at     timestamptz NULL   -- dénormalisé depuis interventions : trie, filtre et compte sans sous-requête (même raison que wu_pending_count)
ad_distinguished_name   text NULL
ad_ou                   text NULL
ad_location             text NULL
```

La divergence d'emplacement (§2.2) n'est **pas** stockée : elle se calcule
dans la requête de liste (`machines.location <> COALESCE(buildings.location,
rooms.location)`) et dans la fiche. Une colonne dénormalisée se démentirait à
chaque heartbeat qui change `location`.

### 4.3 Vérifications demandées

```
machine_checks
  id              uuid PK
  machine_id      uuid FK machines ON DELETE CASCADE (index)
  requested_by    text NOT NULL       -- e-mail, convention du journal d'audit
  assigned_to_id  uuid NULL FK users ON DELETE SET NULL (index)
  instructions    text NULL
  created_at      timestamptz
  closed_at       timestamptz NULL    -- NULL = ouverte
  closed_by       text NULL
  closing_note    text NULL
  UNIQUE (machine_id) WHERE closed_at IS NULL   -- une seule demande ouverte par poste
```

La clôture **crée aussi une intervention** (`kind = verification`, note =
`closing_note`) : l'historique du poste raconte tout au même endroit.

### 4.4 Maintenances et interventions

```
maintenances                        -- une « séance » : une salle (ou un poste seul) à une date
  id            uuid PK
  room_id       uuid NULL FK rooms ON DELETE SET NULL
  performed_by  text NOT NULL        -- e-mail
  performed_at  timestamptz NOT NULL
  note          text NULL            -- observation globale de la séance
  created_at

interventions                       -- LE journal par poste, toutes causes confondues
  id              uuid PK
  machine_id      uuid FK machines ON DELETE CASCADE (index)
  kind            text NOT NULL      -- maintenance | verification | incident | software_install | upgrade | other
  title           text NULL          -- une ligne, facultative (« Remplacement SSD »)
  note            text NULL
  performed_by    text NOT NULL
  performed_at    timestamptz NOT NULL (index avec machine_id)
  maintenance_id  uuid NULL FK maintenances ON DELETE SET NULL
  check_id        uuid NULL FK machine_checks ON DELETE SET NULL
  created_at, updated_at
```

Pourquoi une table unique d'interventions plutôt qu'une table par cause : la
fiche du poste veut **une** chronologie ; une maintenance de salle y apparaît
comme une intervention `maintenance` par poste, avec sa note propre, et le
lien `maintenance_id` ramène à la note globale de la séance. Trois tables
séparées obligeraient à une union à chaque affichage et à trois formulaires
presque identiques.

### 4.5 Réglages globaux

```
settings
  key    text PK       -- « maintenance.default_cycle_days », « maintenance.default_owner_id », « maintenance.due_soon_days »
  value  jsonb NOT NULL
  updated_at, updated_by
```

Le cycle par défaut est initialisé au premier démarrage depuis
la variable d'environnement `MAINTENANCE_DEFAULT_CYCLE_DAYS`
(défaut 90) ; ensuite la base fait foi et la page Paramètres l'édite sans
redémarrage. Le responsable global est un compte : il ne peut venir que de la
console.

### 4.6 Règles de résolution

```
cycle(poste)       = poste.cycle ?? salle.cycle ?? global.cycle
responsable(poste) = poste.owner ?? salle.owner ?? global.owner
référence          = poste.last_maintenance_at ?? poste.first_seen
échéance           = référence + cycle
état               = exclu (cycle 0) | à jour | à échéance (échéance − due_soon_days ≤ aujourd'hui) | en retard
```

Un poste virtuel (`hw_is_virtual`) suit les mêmes règles : c'est le cycle 0
sur sa salle ou sur lui-même qui l'exclut, pas une exception codée. Le
bâtiment n'entre pas dans la résolution.

---

## 5. Groupes et permissions (livré en J1)

Le vocabulaire est `ressource:action`, tenu dans `PERMISSION_CATALOGUE`
(`permissions.py`) et son miroir `utils/permissions.ts` ; un groupe ne peut
recevoir qu'une permission du catalogue. Les jalons suivants l'étendent :

| Jalon | Ressources ajoutées | Défaut Techniciens |
|---|---|---|
| J2 | `room:read`, `room:write` (bâtiments compris) | lecture |
| J4 | `intervention:read`, `intervention:write` | lecture + écriture |
| J5 | `check:read`, `check:write` | lecture + écriture |
| J6 | `maintenance:read`, `maintenance:write`, `settings:read`, `settings:write` | maintenance : lecture + écriture ; paramètres : rien |

« Transmettre » une maintenance, gérer salles et bâtiments, fixer cycles et
responsables = `room:write` / `maintenance:write` — un groupe qui les a, pas
un rôle. Les Administrateurs ont tout implicitement, donc rien à leur
accorder quand une ressource apparaît.

Une route `GET /users/assignable` (id + nom, sans e-mail ni rôle) servira les
listes d'affectation à quiconque détient `check:write` ou `maintenance:write`,
sans ouvrir la gestion des comptes (J5).

Côté console, `auth.can(resource, action)` remplace l'ancien `isAdmin` ; le
catalogue de commandes se filtre sur les permissions du profil, si bien qu'un
menu n'offre jamais un 403.

## 6. API (esquisse)

```
Bâtiments
  GET    /buildings                     liste (+ nombre de salles et de postes)
  POST   /buildings                     admin
  PATCH  /buildings/{id}                admin — nom, emplacement, notes
  DELETE /buildings/{id}                admin — les salles deviennent « sans bâtiment »

Salles
  GET    /rooms                         liste (+ compteurs : postes, en retard, à vérifier, divergents) ; filtres building, location
  POST   /rooms                         admin
  GET    /rooms/{id}                    détail + postes + état de maintenance
  PATCH  /rooms/{id}                    admin — nom, bâtiment, emplacement, cycle, responsable, notes
  DELETE /rooms/{id}                    admin — les postes redeviennent « sans salle »
  POST   /rooms/{id}/machines           admin, mode manuel — rattacher des postes (liste d'ids) ; réponse = divergences éventuelles
  DELETE /rooms/{id}/machines/{mid}     admin, mode manuel

Postes
  PATCH  /machines/{id}/maintenance     admin — cycle, responsable (NULL = hériter)
  GET    /machines/{id}/interventions   journal
  POST   /machines/{id}/interventions   technician+
  PATCH  /interventions/{id}            auteur ou admin
  DELETE /interventions/{id}            admin, tracé dans l'audit

Vérifications
  POST   /machines/{id}/check           technician+ — instructions, assigned_to
  PATCH  /checks/{id}                   réaffecter / modifier les instructions
  POST   /checks/{id}/close             affecté, demandeur ou admin — note de clôture
  GET    /checks?open=1&assigned_to=me  la page « Mes tâches »

Maintenance
  GET    /maintenance/due?owner=me      salles et postes à faire (groupés par bâtiment puis salle)
  POST   /maintenance                   { room_id?, performed_at, note, items: [{machine_id, note}] }
  GET    /maintenance/{id}              une séance et ses postes
  POST   /rooms/{id}/maintenance/transfer    admin — nouveau responsable
  POST   /machines/{id}/maintenance/transfer admin

Paramètres
  GET/PATCH /settings                   admin

Listes : GET /machines gagne les filtres room, building, location_mismatch, check_open,
maintenance_state, et les colonnes building / room / maintenance_due_at / has_open_check
dans l'export. Le statut « needs_verification » garde sa valeur d'API, seul le libellé change.
```

---

## 7. Console

- **Salles** (`/rooms`, entrée de menu) : tableau bâtiment · salle ·
  emplacement effectif · postes · responsable effectif · cycle effectif ·
  état (« 3 en retard », « 1 divergent »). Les bâtiments se gèrent depuis
  cette page (onglet ou dialogue), pas depuis une entrée de menu à part.
  Fiche salle : réglages, liste des postes, bouton **« Effectuer la
  maintenance »**, historique des séances. En mode manuel, un sélecteur avec
  recherche (hostname, IP, utilisateur connecté) rattache des postes, avec
  avertissement si l'emplacement diverge ; en mode AD, la liste est en
  lecture seule avec la mention de la source.
- **Liste des postes** : colonnes **Bâtiment** et **Salle** (triables,
  regroupables comme l'emplacement), filtres bâtiment / salle / « emplacement
  divergent » / « vérification ouverte » / « maintenance en retard ou à
  échéance » ; actions groupées **« Affecter à une salle »** (mode manuel) et
  **« Demander une vérification »**. Colonnes ajoutées à l'export. Le filtre
  d'identité est relibellé **« Identité à confirmer »**.
- **Fiche poste** : bandeau d'alerte « Vérification demandée par X, affectée à
  Y — instructions » avec bouton « Clore » ; badge « Emplacement divergent »
  quand il y a lieu ; dans l'onglet Identité : bâtiment, salle, cycle et
  responsable effectifs avec leur origine (« hérité de la salle B12 »), et les
  valeurs AD brutes ; nouvel onglet **« Historique »** : chronologie des
  interventions (maintenances, vérifications closes, incidents…), bouton
  « Ajouter une intervention », lien vers la séance de maintenance pour lire
  la note globale.
- **Mes tâches** (`/tasks`, entrée de menu, pastille avec le compte) : deux
  sections — *vérifications qui me sont affectées* et *maintenances à faire*
  (bâtiment › salle avec le nombre de postes en retard, puis postes sans
  salle). Un admin peut basculer sur « tout le monde » et transmettre depuis
  là.
- **Formulaire de maintenance** (depuis une salle ou un poste) : date (défaut
  maintenant), note globale, tableau des postes de la salle avec case « fait »
  (cochée par défaut ; un poste absent ou éteint se décoche) et note par
  poste. Enregistre une séance + une intervention par poste coché. Une date
  antérieure est acceptée (amorçage du cycle).
- **Tableau de bord** : deux cartes (« vérifications ouvertes », « maintenances
  en retard ») qui renvoient sur la liste filtrée.
- **Paramètres** (admin) : cycle par défaut, responsable par défaut, fenêtre
  « à échéance », mode de classement (lecture seule, vient de l'environnement).
- **Comptes** : le rôle Technicien dans le sélecteur de rôle.

---

## 8. Jalons

L'ordre place le **journal** avant la **maintenance**, parce que la seconde
écrit dans le premier.

| Jalon | Contenu | Estimation |
|---|---|---|
| **J0 — Cadrage** | Confirmation du §2.2, fusion préalable de la branche emplacement/WoL (§10). | 0,5 j |
| **J1 — Groupes de droits** ✅ | Tables `groups`, `group_permissions`, `user_groups` (migration `0016`, `users.role` supprimée), trois groupes intégrés, union des droits par requête, garde anti-verrouillage, commandes à risque (`risky_command:execute`), routes `/groups`, page Groupes avec grille, multi-sélecteur de groupes sur les comptes, `can()` côté console, relibellé « Identité à confirmer ». | 3 j |
| **J2 — Bâtiments et salles** ✅ | Migration `0017` (bâtiments, salles, `machines.room_id`), ressource `room`, modèles `Building` et `Room`, CRUD, rattachement manuel, divergence d'emplacement, filtres et colonnes dans la liste et l'export, page Salles. | 2,5 j |
| **J3 — Agent : bloc `directory`** ✅ | Lecture du DN (registre) et de l'attribut `location` (ADSI), hachage et envoi ; réception serveur, `ROOM_SOURCE`, création automatique des salles. Tests Go (parse du DN) et Python (get-or-create, verrouillage en mode auto). | 1,5 j |
| **J4 — Journal des interventions** ✅ | Modèle, routes, ressource `intervention`, onglet Historique, formulaire d'ajout, prise en compte dans la fusion de postes. **→ PR 1** | 1 j |
| **J5 — Vérifications** ✅ | Modèle, routes, ressource `check`, `GET /checks/assignable-users`, contrainte « une ouverte par poste », bandeau sur la fiche, action groupée, section dans Mes tâches, clôture → intervention. | 1,5 j |
| **J6 — Maintenance** ✅ | Ressources `maintenance` et `settings`, table `app_settings` + page Paramètres, résolution cycle/responsable, `last_maintenance_at`, `/maintenance/due`, formulaire de séance (salle ou poste), transmission, section dans Mes tâches, cartes du tableau de bord, filtre « en retard ». | 2,5 j |
| **J7 — Notifications** | E-mail à l'affectation d'une vérification ; ligne « vos maintenances en retard » dans le résumé quotidien ; rappel hebdomadaire par responsable. | 1 j |
| **J8 — Validation et documentation** | Couverture, `alembic check`, README (Fonctionnalités), DEPLOYMENT.md (variables, clés de registre), captures. **→ PR 2** | 1 j |

Total indicatif : **14 à 15 jours**, J1 compris.

---

## 9. Questions tranchées

Les quinze questions du premier brouillon sont reportées dans le §2.1 avec
leur réponse. Écarts par rapport aux défauts proposés : des **groupes
flexibles** plutôt qu'un rôle technicien codé en dur, avec les **commandes à
risque** comme droit distinct ; le bâtiment est **une table**, pas un champ
texte. Reste ouvert : le §2.2.

---

## 10. Points d'attention

- **Branche de base non fusionnée.** `claude/agent-location-wol-ughnse`
  (migration `0015`, colonne `location`) n'est pas dans `main`. Ce chantier
  la suppose fusionnée : la migration `0016` la suit, et la page Salles
  s'appuie sur le filtre d'emplacement. Fusionner d'abord, ou accepter une PR
  empilée.
- **`UNIQUE NULLS NOT DISTINCT`** demande PostgreSQL 15 ; le compose est en
  `postgres:16-alpine`, donc disponible. La suite de tests tourne sur le même
  moteur (`TIAI_TEST_DATABASE_URL`).
- **Suppression d'un compte** : `ON DELETE SET NULL` sur les responsables et
  affectations — une salle sans responsable retombe sur le global, une
  vérification sans affecté redevient « à prendre ». Les auteurs
  (`performed_by`, `closed_by`) restent en texte, comme dans l'audit.
- **Fusion de postes** : `merge_into` doit déplacer `interventions`,
  `machine_checks` et reporter `last_maintenance_at` / `room_id` sur le poste
  conservé (J4).
- **Mode AD et postes hors domaine** : un parc mixte garde les postes sans
  bloc `directory` « sans salle » ; en mode `ad_*`, ils ne sont pas
  rattachables à la main — à documenter, ou à prévoir l'épinglage plus tard.
- **ADSI côté agent** : premier usage de COM hors WMI dans l'agent. Même
  garde-fou que WMI (délai, échec silencieux → bloc absent, log une fois).
  Tester sur un poste dont le DC est injoignable : l'appel doit échouer vite
  et l'agent continuer.
- **Nouvelle ressource = trois endroits** : `PERMISSION_CATALOGUE` côté
  serveur, `utils/permissions.ts` côté console (libellés de la grille), et
  les défauts des Techniciens dans `BUILTIN_GROUP_DEFAULTS` **plus** une
  insertion dans la migration du jalon pour les installations déjà migrées
  (le seed ne crée que les groupes manquants, il ne complète pas leurs
  droits). Les Administrateurs n'ont rien à recevoir.
- **Charge** : `/maintenance/due` et les compteurs par salle sont des
  agrégats sur `machines` (une colonne dénormalisée, un index sur `room_id`) ;
  rien qui ne tienne pas sur un parc de mille postes.
- **RGPD** : les notes sont du texte libre ; rien n'empêche d'y écrire un nom
  d'utilisateur. Pas de règle technique, mais une phrase dans la doc.

---

## 11. J1 — écarts constatés à l'implémentation

- `users.role` est **supprimée** (pas conservée en doublon) : la migration
  range les `admin` dans Administrateurs et le reste dans Lecture seule, et
  le `downgrade` refait le chemin inverse depuis l'appartenance au groupe
  intégré. Les tests créent leurs comptes avec `groups=[BuiltinGroup.X]`, le
  groupe intégré étant créé à la volée s'il manque.
- Les Administrateurs n'ont **aucune permission stockée** : `is_admin` est
  implicite sur la clé `admin`, la grille les affiche cochés et verrouillés.
  Ainsi une ressource nouvelle ne leur est jamais à accorder.
- La garde anti-verrouillage compte les **comptes actifs détenant
  `user:write`** après la modification (flush puis comptage, rollback si
  zéro), sur les comptes comme sur les groupes. Un compte désactivé ne
  compte pas. À cela s'ajoute la règle existante : personne ne se désactive,
  ne se supprime ni ne change ses propres groupes.
- `risky_command:execute` seul n'ouvre rien : la route reste gardée par
  `command:execute`, le risque est un supplément. La console le dit dans le
  formulaire de groupe quand la case est cochée sans l'autre.
- Les permissions sont **lues à chaque requête** (une jointure), pas mises
  dans le JWT : modifier un groupe prend effet immédiatement, sans
  reconnexion. Le profil `/auth/me` les renvoie pour la console, qui les
  cache dans `localStorage` pour la garde de route.
- Le statut d'identité s'appelle désormais « Identité à confirmer » dans la
  liste, le tableau de bord et le résumé quotidien ; sa valeur d'API
  (`needs_verification`) ne change pas.

### J2 — écarts constatés à l'implémentation

- **Une migration par jalon** plutôt qu'une seule pour tout le chantier :
  `0017_rooms` ne crée que `buildings`, `rooms` et `machines.room_id`. Les
  colonnes de maintenance sur `rooms` et `machines`, les colonnes `ad_*` et
  `rooms.ad_key`, les tables de vérifications et d'interventions viennent
  avec leur jalon.
- **`room:read` est aussi donné à Lecture seule** (pas seulement aux
  Techniciens) : consulter les salles est de la supervision. La migration
  l'insère pour les deux groupes intégrés existants.
- **La liste des postes joint `rooms` et `buildings`** (une seule requête,
  `select(Machine, Room, Building)`), ce qui donne le filtre et le tri sur la
  salle et le bâtiment, et le filtre « emplacement divergent » calculé en
  SQL. L'export lit la même jointure (`ExportRow`) : colonnes Bâtiment,
  Salle, Emplacement divergent, proposées et non par défaut.
- **Une salle dans un bâtiment ne stocke pas d'emplacement propre** : la
  route l'efface au rattachement, pour qu'il n'y ait jamais deux réponses.
  À la suppression du bâtiment, l'emplacement est recopié sur ses salles.
- **Rattachement manuel toujours possible** en J2 : le verrouillage en mode
  `ad_*` arrive avec `ROOM_SOURCE` en J3.
- **Fusion de doublons** : le poste conservé prend la salle du doublon
  s'il n'en avait pas.
- Route de retrait groupée `POST /rooms/unassign` en plus du rattachement
  `POST /rooms/{id}/machines` ; les deux renvoient les postes dont
  l'emplacement diverge, que la console signale dans la notification.

### J3 — écarts constatés à l'implémentation

- **Le bloc `directory` voyage dans l'inventaire** (`inventory.directory`)
  plutôt que comme bloc séparé du heartbeat : même cycle quotidien, même
  hachage, même acquittement par génération, et `inventory_scan` le
  rafraîchit à la demande. Aucune plomberie nouvelle côté agent.
- **Deux lectures, deux coûts.** Le DN vient du cache des stratégies de
  groupe dans le registre (zéro dépendance, hors ligne compris) ; l'attribut
  Emplacement passe par ADSI (`go-ole`, désormais dépendance directe), sur
  un thread verrouillé avec son propre appartement COM, borné à 30 s comme
  les requêtes WMI. Le bind utilise un BSTR nul construit à la main pour
  que ADSI prenne le compte machine — un `nil` go-ole serait un VT_NULL
  refusé par la couche dispatch. **Non testé sur un domaine réel dans cette
  session** : à valider sur un poste joint avant de déployer.
- **La clé d'une salle OU est le DN de l'OU** (`rooms.ad_key`, unique), son
  nom celui de l'OU à la création. Une OU renommée = nouvelle salle,
  l'ancienne reste vide ; une salle renommée en console garde sa clé.
- **Adoption d'une salle manuelle** : une OU nommée comme une salle créée à
  la main sans bâtiment ni clé la reprend au lieu de créer « Salle B12
  (2) » — le cas du parc qui a classé à la main avant d'activer l'annuaire.
  Deux OU homonymes sous deux branches donnent bien deux salles, la
  seconde suffixée.
- **Un poste sans OU (ou sans attribut) est retiré de sa salle** en mode
  annuaire : l'annuaire a parlé et a dit « nulle part ».
- **Le bloc est appliqué même à hachage inchangé** (il est bon marché), et
  `POST /rooms/sync-directory` reclasse tout le parc depuis les lectures
  mémorisées : un `ROOM_SOURCE` changé côté serveur ne dépend pas du jour
  où chaque agent bougera. Les lectures `ad_*` sont stockées et affichées
  quel que soit le mode.
- Pas de clé de configuration agent ni de registre : la lecture est
  automatique sur tout poste joint, et n'échoue jamais bruyamment.

### J4 — écarts constatés à l'implémentation

- **Modification ouverte à tout détenteur de `intervention:write`**, pas
  seulement à l'auteur : un collègue qui corrige une note est le cas
  courant. Une modification par un autre que l'auteur, et toute
  suppression, sont tracées dans le journal d'audit ; une modification par
  l'auteur ne l'est pas (le journal affiche l'auteur, pas l'éditeur).
- **Les colonnes `maintenance_id` et `check_id`** arrivent avec J5 et J6,
  pas avec cette migration (`0019_interventions`), fidèle à « une migration
  par jalon ».
- **Lecture seule reçoit `intervention:read`**, Techniciens
  `intervention:read` + `intervention:write`, insérés par la migration pour
  les installations déjà migrées.
- Pagination par « Afficher plus » (25 par page) plutôt qu'un tableau : un
  journal se lit de haut en bas.

### J5 — écarts constatés à l'implémentation

- **`GET /checks/assignable-users`** plutôt que `/users/assignable` : le
  routeur des comptes exige `user:read` à sa racine, et la liste des
  affectables doit être lisible par qui détient `check:write` seulement.
  Elle ne renvoie que l'identifiant et un nom d'affichage.
- **Affectation à un compte désactivé refusée** (404) ; un compte supprimé
  laisse ses demandes ouvertes « à prendre » (`SET NULL`).
- **Clôture antidatable** comme une intervention ; elle crée l'entrée
  `verification` du journal avec `check_id`, colonne ajoutée à
  `interventions` par la migration `0020`.
- **Fusion de doublons** : les demandes suivent le poste conservé ; si les
  deux en ont une ouverte, celle du doublon est close par « system » avec
  une note, pour respecter « une seule ouverte par poste ».
- **Demande groupée** (`POST /checks/bulk`) depuis la liste : les postes
  qui en ont déjà une ouverte sont sautés et comptés.
- **Page « Mes tâches »** avec trois portées (les miennes, à prendre,
  toutes), « Me l'affecter », réaffectation et clôture ; pastille du menu
  = mes demandes ouvertes. Carte « Vérifications demandées » sur le
  tableau de bord, filtre et icône dans la liste, bandeau et boutons sur la
  fiche, colonnes d'export.
- **Pas d'e-mail** à l'affectation : prévu en J7 avec le reste des
  notifications.

### J6 — écarts constatés à l'implémentation

- **Table `app_settings`** (clé, valeur JSONB, qui, quand) ; les variables
  d'environnement `MAINTENANCE_DEFAULT_CYCLE_DAYS` et
  `MAINTENANCE_DUE_SOON_DAYS` ne sont que des valeurs initiales, la ligne
  écrite par la console prend le dessus. Le responsable par défaut n'a pas
  de variable d'environnement : c'est un compte.
- **La règle est écrite deux fois, volontairement** : en Python
  (`policy.resolve`) pour les réponses et l'origine de chaque valeur, en
  SQL (`due_expr`, `state_clause`) pour le filtre, le tri et les compteurs.
  Même entrées, même sortie ; un poste exclu a une date due NULL en SQL
  pour se trier en dernier.
- **« Transmettre » n'est pas une route** : c'est `PATCH …/maintenance`
  avec un nouveau responsable, audité comme le reste des réglages. Les
  réglages de salle et de poste demandent `maintenance:write` (pas
  `room:write`), les Techniciens l'ont par défaut.
- **La liste « à faire » est calculée en Python** sur le parc entier joint
  aux salles (`fleet_resolved`) : un poste qui surcharge son responsable
  sort de la liste de celui de sa salle. Les postes exclus sont comptés
  dans leur salle, pas listés.
- **Une séance antidatée ne recule jamais le cycle** : `last_maintenance_at`
  n'avance que.
- **Titre de l'entrée du journal** : « Maintenance — B12 » pour une salle,
  « Maintenance » seul depuis la fiche d'un poste ; `maintenance_id`
  ajouté à `interventions` par `0021`.
- Console : carte Maintenance dans l'onglet Historique de la fiche (état,
  cycle et responsable avec leur origine, réglages, séance pour ce poste),
  carte et bouton « Effectuer la maintenance » sur la fiche salle avec les
  trois dernières séances, section « Maintenances à faire » dans Mes tâches
  (salles dépliables, séance depuis la liste), filtre et colonne dans la
  liste des postes, carte du tableau de bord, colonne dans la page Salles,
  page Paramètres.

## 12. Plus tard — portée par emplacement

Restreindre un groupe à des emplacements, bâtiments ou salles : une table
`group_scopes (group_id, kind, value)` et, dans chaque requête de liste, de
fiche, de commande et d'export, un filtre commun dérivé des scopes du
profil (`machines.location IN (...)` ou `room_id IN (...)`), plus la même
règle sur les cibles d'une commande groupée et sur les agrégats du tableau
de bord. Un groupe sans scope voit tout — c'est la compatibilité. À chiffrer
quand le besoin se présente ; rien dans le modèle de J1 ne s'y oppose.
