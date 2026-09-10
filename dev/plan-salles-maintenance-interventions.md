# Salles, vérifications, maintenance et interventions — plan de travail

> **Statut : brouillon (2026-09-10), en attente des réponses aux questions du §9.**
> Rien n'est encore implémenté ; ce document fixe le cadrage proposé et les
> choix à trancher avant de coder. Une fois les réponses connues, le §9 est
> reporté dans le §2 (« Cadrage retenu ») et les jalons du §8 démarrent.
>
> Branche de travail : `claude/postes-maintenance-features-85buig`, fondée sur
> `claude/agent-location-wol-ughnse` (emplacement des postes + réveil relayé),
> **elle-même non encore fusionnée dans `main`** — voir §10.
>
> Objectif : la console cesse d'être seulement un tableau de bord de l'état
> *technique* des postes pour porter aussi leur **vie d'exploitation** :
> 1. regrouper les postes par **salle** en plus de l'emplacement, à la main ou
>    automatiquement depuis l'annuaire ;
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
| `machines.location` — l'**emplacement** (site), texte libre **déclaré par l'agent** (YAML ou registre → GPO), vidé quand l'agent ne le déclare plus. Filtre, tri et regroupement dans la liste ; base du relais Wake-on-LAN. | `agent/internal/config`, `backend/app/api/routes/agent.py` (`clean_location`), `MachinesPage.vue` | L'emplacement **reste piloté par l'agent** : le rendre éditable en console créerait un conflit à chaque heartbeat. La salle est donc un objet **côté serveur**, distinct. |
| `machines.needs_verification` + statut `needs_verification`, libellé **« À vérifier »** dans la liste et le tableau de bord. | `features/machine/fingerprint.py`, `MachinesPage.vue:573`, `DashboardPage.vue:217` | C'est la **vérification d'identité** (empreinte matérielle suspecte), pas une demande d'intervention humaine. Le nouveau concept doit porter un autre nom, en base comme à l'écran (question Q7). |
| Deux rôles seulement : `admin` (tout) et `readonly` (lecture). Permissions statiques `(ressource, action)`, point d'extension prévu vers des droits en base. | `features/user/permissions.py` | Un utilisateur « lecture seule » ne peut rien écrire, donc **ne peut pas clore une vérification ni saisir une maintenance**. Il faut un rôle intermédiaire ou des droits par ressource (Q8). |
| Journal d'audit append-only ; `commands.created_by` porte l'e-mail de l'opérateur. | `features/audit` | Même convention pour « qui a fait quoi » : e-mail conservé en texte, pour survivre à la suppression du compte. |
| File d'e-mails (outbox) + préférence par compte ; worker avec jobs périodiques (`every`, `daily_at`). | `features/notification`, `core/worker.py` | Les rappels de maintenance et les affectations peuvent passer par la même file (Q11). |
| L'agent connaît le **domaine** (`NetGetJoinInformation`) mais **rien de l'annuaire** : ni l'OU, ni l'attribut `location` de l'objet ordinateur. `go-ole` est déjà dans l'arbre de dépendances (via `wmi`). | `agent/internal/sysinfo` | La classification automatique demande un bloc de données de plus dans le heartbeat, et pour l'attribut AD un accès ADSI (§3). |
| Fusion de postes (`merge_machine`) et cascade `ON DELETE` sur les tables filles. | `routes/machines.py:1429`, `features/machine/crud.py` | Tout historique rattaché à un poste doit **suivre la fusion** et se prononcer sur la suppression (§10). |

---

## 2. Hiérarchie des lieux — avis et proposition

**Question posée : faut-il une hiérarchie Emplacement / Bâtiment / Salle ?**
Avis : **non, pas comme trois entités.** Deux niveaux suffisent, le bâtiment
étant un *attribut* de la salle.

```
Emplacement (site)  ──  déclaré par l'agent, GPO, texte libre     « Lycée de Taravao »
   └── Salle         ──  entité serveur, manuelle ou dérivée AD    « B12 »  (bâtiment : « Bâtiment B »)
          └── Poste
```

Pourquoi :

- **La maintenance se résout sur trois niveaux** (global → salle → poste) pour
  le cycle comme pour le responsable. Un quatrième niveau double les cas
  « hérité de… » dans chaque formulaire et chaque fiche, pour un bénéfice
  rare : un bâtiment a très rarement *son* responsable ou *son* cycle.
- **Le bâtiment est une clé de tri**, pas un objet à administrer. Une colonne
  `building` sur la salle donne le regroupement et le tri (liste des postes,
  page des salles) sans rien de plus. Si un jour il lui faut une existence
  propre, transformer une colonne en table est une migration bornée.
- **Les deux sources restent séparées.** L'emplacement vient de l'agent et
  conditionne le relais Wake-on-LAN ; la salle vient de la console ou de
  l'annuaire. Une salle *appartient* facultativement à un emplacement
  (`rooms.location`) ; un poste dont `location` ≠ celle de sa salle est
  **signalé** (incohérence de déploiement), jamais bloqué.
- Une **arborescence générique** (table `places` auto-référencée) couvrirait
  tous les cas, mais chaque écran devrait alors gérer une profondeur
  arbitraire. Écartée : trop de généralité pour un parc d'établissements.

Vocabulaire proposé (Q1) : **« Emplacement »** (inchangé) et **« Salle »** avec
un champ **« Bâtiment »** facultatif. « Lieu » est évité, trop proche
d'« emplacement ».

---

## 3. Classification automatique depuis l'annuaire (1b)

Trois sources possibles, de coût très différent :

| Source | Où la lire | Coût | Verdict |
|---|---|---|---|
| **OU parente** de l'objet ordinateur | **Localement, sans LDAP** : le traitement des GPO écrit le DN de l'ordinateur dans `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine\Distinguished-Name`. L'OU parente est le second RDN (`CN=PC-B12-03,OU=Salle B12,OU=Postes,DC=lycee,DC=local` → `Salle B12`). Présent sur tout poste joint qui applique des GPO — c'est précisément le cas de déploiement de l'agent. | Une lecture de registre, aucune dépendance. | **v1** |
| **Attribut `location`** de l'objet ordinateur (onglet « Emplacement » d'ADUC) | Pas mis en cache localement → **requête LDAP**. Deux endroits possibles : (a) le **serveur**, avec un compte de service et une route réseau vers un DC — exclu pour un serveur hébergé hors site, le cas même pour lequel le relais WoL existe ; (b) l'**agent**, via **ADSI** (COM, `GetObject("LDAP://<DN>")`), qui s'authentifie avec le compte machine sans rien configurer et sans nouvelle dépendance (`go-ole` déjà présent). | Un appel COM, à lire **au rythme de l'inventaire (24 h)**, jamais dans le heartbeat de 60 s. | **v1, côté agent** |
| Nom de **site AD** (`DsGetSiteName`, netapi32) | Localement, un appel système. | Nul. | **Hors périmètre** sauf avis contraire : il alimenterait l'*emplacement* (un site AD est justement un site physique), pas la salle. Noté pour plus tard (Q4). |

Contrat proposé :

- **Agent** : nouveau bloc facultatif `directory` dans le heartbeat, envoyé
  quand la valeur change (même mécanisme de hachage que l'inventaire) :
  ```json
  { "directory": { "distinguished_name": "CN=PC-B12-03,OU=Salle B12,OU=Postes,DC=lycee,DC=local",
                   "ou": "Salle B12", "ad_location": "Bât. B — salle 12" } }
  ```
  L'agent envoie **les deux** valeurs quand il les a ; c'est le serveur qui
  choisit. Poste hors domaine : bloc absent.
- **Serveur** : variable `ROOM_SOURCE` = `manual` (défaut) · `ad_ou` ·
  `ad_location`. Hors `manual`, à réception du bloc, le serveur **trouve ou
  crée** la salle par sa clé (`rooms.ad_key` : DN de l'OU, ou la chaîne
  `location`) et y rattache le poste. Une salle créée automatiquement garde
  ses réglages de maintenance éditables en console (cycle, responsable,
  bâtiment) ; seul **le rattachement des postes** est verrouillé (Q3).
- Les deux valeurs brutes sont aussi stockées sur le poste (`ad_ou`,
  `ad_distinguished_name`, `ad_location`) et affichées dans la fiche, quel
  que soit le mode : c'est une information utile même en classement manuel.

---

## 4. Modèle de données

Une seule migration, `0016_rooms_checks_maintenance`.

### 4.1 Salles

```
rooms
  id                      uuid PK
  name                    text NOT NULL            -- « B12 »
  building                text NULL                -- « Bâtiment B », attribut de tri
  location                text NULL                -- emplacement (site) de rattachement, texte libre comme machines.location
  ad_key                  text NULL UNIQUE         -- DN de l'OU ou valeur AD `location` ; NULL = salle manuelle
  maintenance_cycle_days  int  NULL                -- NULL = hérite du global ; 0 = pas de maintenance (Q10)
  maintenance_owner_id    uuid NULL FK users ON DELETE SET NULL
  notes                   text NULL
  created_at, updated_at
  UNIQUE (location, name)   -- deux « B12 » sur deux sites, oui ; deux sur le même, non
```

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
  UNIQUE (machine_id) WHERE closed_at IS NULL   -- une seule demande ouverte par poste (Q7)
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
  kind            text NOT NULL      -- maintenance | verification | incident | software_install | upgrade | other  (Q12)
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

Le responsable global est un utilisateur : une variable d'environnement ne
peut pas le désigner proprement (un e-mail dans `.env` qui doit correspondre
à un compte…). Proposition : une petite table `settings (key text PK, value
jsonb)` — réutilisable ensuite pour d'autres réglages qu'on veut changer
sans redémarrer —, éditée depuis une page « Paramètres » réservée à l'admin,
avec :

- `maintenance.default_cycle_days` (initialisé depuis
  `MAINTENANCE_DEFAULT_CYCLE_DAYS`, défaut **90**) ;
- `maintenance.default_owner_id` ;
- `maintenance.due_soon_days` (défaut **14**) : fenêtre « à échéance ».

Alternative plus légère si la page Paramètres est jugée prématurée : cycle en
variable d'environnement seulement, responsable global = un drapeau sur le
compte (`users.is_default_maintenance_owner`). (Q9)

### 4.6 Règles de résolution

```
cycle(poste)       = poste.cycle ?? salle.cycle ?? global.cycle
responsable(poste) = poste.owner ?? salle.owner ?? global.owner
référence          = poste.last_maintenance_at ?? poste.first_seen     (Q10)
échéance           = référence + cycle
état               = à jour | à échéance (échéance − due_soon_days ≤ aujourd'hui) | en retard
```

Un poste virtuel (`hw_is_virtual`) suit les mêmes règles : c'est le cycle 0
sur sa salle ou sur lui-même qui l'exclut, pas une exception codée.

---

## 5. Rôles et permissions

Nouvelles ressources dans `permissions.py` : `ROOM`, `CHECK`, `MAINTENANCE`,
`INTERVENTION`, `SETTINGS`.

Proposition d'un troisième rôle, **`technician`** (libellé « Technicien »),
entre lecture seule et admin :

| | readonly | technician | admin |
|---|---|---|---|
| Lire postes, salles, historiques, tâches | ✔ | ✔ | ✔ |
| Clore une vérification **qui lui est affectée**, saisir une maintenance / intervention sur un poste ou une salle **dont il est responsable** | — | ✔ | ✔ |
| Créer une demande de vérification, saisir une intervention sur n'importe quel poste | — | ✔ (Q8) | ✔ |
| Créer / modifier une salle, rattacher des postes, fixer cycles et responsables, **transmettre** une maintenance | — | — | ✔ |
| Commandes à distance | — | — (Q8) | ✔ |
| Comptes, audit, paramètres | — | — | ✔ |

« Utilisateur avec droit avancé » (transmission de maintenance) = **admin**
dans cette proposition, pour ne pas inventer un quatrième rôle. Une route
`GET /users/assignable` (id + nom, sans e-mail ni rôle) sert les listes
d'affectation à quiconque peut affecter, sans ouvrir la gestion des comptes.

Côté console, `auth.isAdmin` est complété d'un `can(resource, action)` miroir
de la table serveur, pour masquer les boutons plutôt que d'attendre un 403.

---

## 6. API (esquisse)

```
Salles
  GET    /rooms                         liste (+ compteurs : postes, en retard, à vérifier)
  POST   /rooms                         admin
  GET    /rooms/{id}                    détail + postes + état de maintenance
  PATCH  /rooms/{id}                    admin — nom, bâtiment, emplacement, cycle, responsable, notes
  DELETE /rooms/{id}                    admin — les postes redeviennent « sans salle »
  POST   /rooms/{id}/machines           admin, mode manuel — rattacher des postes (liste d'ids)
  DELETE /rooms/{id}/machines/{mid}     admin, mode manuel

Postes
  PATCH  /machines/{id}/maintenance     admin — cycle, responsable (NULL = hériter)
  GET    /machines/{id}/interventions   journal
  POST   /machines/{id}/interventions   technician+
  PATCH  /interventions/{id}            auteur ou admin (Q12)
  DELETE /interventions/{id}            admin, tracé dans l'audit

Vérifications
  POST   /machines/{id}/check           technician+ — instructions, assigned_to
  PATCH  /checks/{id}                   réaffecter / modifier les instructions
  POST   /checks/{id}/close             affecté, demandeur ou admin — note de clôture
  GET    /checks?open=1&assigned_to=me  la page « Mes tâches »

Maintenance
  GET    /maintenance/due?owner=me      salles et postes à faire (groupés par salle)
  POST   /maintenance                   { room_id?, machine_ids[], performed_at, note, items: [{machine_id, note}] }
  GET    /maintenance/{id}              une séance et ses postes
  POST   /rooms/{id}/maintenance/transfer    admin — nouveau responsable (persistant, Q6)
  POST   /machines/{id}/maintenance/transfer admin

Paramètres
  GET/PATCH /settings                   admin

Listes : GET /machines gagne les filtres room, building, check_open, maintenance_state,
et les colonnes room / maintenance_due_at / has_open_check dans l'export.
```

---

## 7. Console

- **Salles** (`/rooms`, entrée de menu) : tableau bâtiment · salle ·
  emplacement · postes · responsable effectif · cycle effectif · état
  (« 3 en retard »). Fiche salle : réglages, liste des postes, bouton
  **« Effectuer la maintenance »**, historique des séances. En mode manuel,
  un sélecteur avec recherche (hostname, IP, utilisateur connecté) pour
  rattacher des postes ; en mode AD, la liste est en lecture seule avec la
  mention de la source.
- **Liste des postes** : colonne **Salle** (triable, regroupable comme
  l'emplacement), filtres salle / bâtiment / « demande de vérification
  ouverte » / « maintenance en retard ou à échéance » ; actions groupées
  **« Affecter à une salle »** (mode manuel) et **« Demander une
  vérification »**. Colonnes ajoutées à l'export.
- **Fiche poste** : bandeau d'alerte « Vérification demandée par X, affectée à
  Y — instructions » avec bouton « Clore » ; dans l'onglet Identité : salle,
  cycle et responsable effectifs avec leur origine (« hérité de la salle
  B12 ») ; nouvel onglet **« Historique »** : chronologie des interventions
  (maintenances, vérifications closes, incidents…), bouton « Ajouter une
  intervention », lien vers la séance de maintenance pour lire la note
  globale.
- **Mes tâches** (`/tasks`, entrée de menu, pastille avec le compte) : deux
  sections — *vérifications qui me sont affectées* et *maintenances à faire*
  (salles avec le nombre de postes en retard, puis postes sans salle). Un
  admin peut basculer sur « tout le monde » et transmettre depuis là.
- **Formulaire de maintenance** (depuis une salle ou un poste) : date (défaut
  maintenant), note globale, tableau des postes de la salle avec case « fait »
  (cochée par défaut ; un poste absent ou éteint se décoche) et note par
  poste. Enregistre une séance + une intervention par poste coché.
- **Tableau de bord** : deux cartes (« vérifications ouvertes », « maintenances
  en retard ») qui renvoient sur la liste filtrée.
- **Paramètres** (admin) : cycle par défaut, responsable par défaut, fenêtre
  « à échéance », mode de classement (lecture seule, vient de l'environnement).

---

## 8. Jalons

L'ordre place le **journal** avant la **maintenance**, parce que la seconde
écrit dans le premier.

| Jalon | Contenu | Estimation |
|---|---|---|
| **J0 — Cadrage** | Réponses au §9, mise à jour de ce document, fusion préalable de la branche emplacement/WoL (§10). | 0,5 j |
| **J1 — Rôles et socle** | Rôle `technician`, ressources et table de permissions, `GET /users/assignable`, `can()` côté console, table `settings` + page Paramètres. Tests de permissions. | 1 j |
| **J2 — Salles** | Migration `0016` (toutes les tables, en une fois), modèle `Room`, CRUD, rattachement manuel, filtres et colonne dans la liste et l'export, page Salles. | 2 j |
| **J3 — Agent : bloc `directory`** | Lecture du DN (registre) et de l'attribut `location` (ADSI), hachage et envoi ; réception serveur, `ROOM_SOURCE`, création automatique des salles. Tests Go (parse du DN) et Python (get-or-create, verrouillage en mode auto). | 1,5 j |
| **J4 — Journal des interventions** | Modèle, routes, onglet Historique, formulaire d'ajout, prise en compte dans la fusion de postes. | 1 j |
| **J5 — Vérifications** | Modèle, routes, contrainte « une ouverte par poste », bandeau sur la fiche, action groupée, section dans Mes tâches, clôture → intervention. | 1,5 j |
| **J6 — Maintenance** | Résolution cycle/responsable, `last_maintenance_at`, `/maintenance/due`, formulaire de séance (salle ou poste), transmission, section dans Mes tâches, cartes du tableau de bord, filtre « en retard ». | 2,5 j |
| **J7 — Notifications** *(si Q11 = oui)* | E-mail à l'affectation d'une vérification ; ligne « vos maintenances en retard » dans le résumé quotidien ; rappel hebdomadaire par responsable. | 1 j |
| **J8 — Validation et documentation** | Couverture, `alembic check`, README (Fonctionnalités), DEPLOYMENT.md (variables, clés de registre), captures. | 1 j |

Total indicatif : **11 à 12 jours**, en une PR par jalon à partir de J2 (J1
peut être fusionné seul : il ne change rien de visible pour un admin).

---

## 9. Questions ouvertes — à trancher avant J1

Chaque question porte la réponse **par défaut** retenue si elle reste sans
réponse.

| # | Question | Défaut proposé |
|---|---|---|
| **Q1** | Vocabulaire : « Salle » + champ « Bâtiment », et « Emplacement » inchangé ? Ou « Lieu » ? | Salle / Bâtiment / Emplacement |
| **Q2** | Une salle est-elle rattachée à un emplacement (site) ? Si oui, un poste dont l'emplacement diffère de celui de sa salle est-il seulement signalé, ou le rattachement est-il refusé ? | Rattachement facultatif, incohérence signalée, jamais refusée |
| **Q3** | En mode `ad_ou` / `ad_location`, le rattachement manuel est-il **interdit** (l'annuaire fait foi, aucun conflit possible) ou permet-on d'**épingler** un poste sur une salle (drapeau `room_pinned`, l'annuaire ne le déplace plus) ? | Interdit en v1 ; l'épinglage se rajoute sans migration lourde si le besoin apparaît |
| **Q4** | Faut-il aussi alimenter automatiquement **l'emplacement** depuis le site AD (`DsGetSiteName`) quand l'agent n'en déclare aucun ? | Non, hors périmètre |
| **Q5** | En mode `ad_ou` : la salle prend-elle le **nom de l'OU** (« Salle B12 ») ou faut-il une table de correspondance OU → salle éditable ? Une OU renommée renomme-t-elle la salle ? | Nom de l'OU à la création, renommable ensuite en console (la clé est le DN, pas le nom) ; une OU renommée = nouvelle salle, l'ancienne reste vide |
| **Q6** | « Transmettre la maintenance » : (a) changer **durablement** le responsable de la salle / du poste, (b) déléguer **la prochaine occurrence** seulement (le responsable reprend après), ou les deux ? | (a) seul en v1 |
| **Q7** | Nom du concept « à vérifier » pour ne pas heurter le statut d'identité déjà libellé « À vérifier » : renommer l'existant en « Identité à confirmer » et prendre « À vérifier » pour la demande humaine ? Ou « Contrôle demandé » ? Et : **une seule** demande ouverte par poste, ou plusieurs ? | Renommer l'existant en « Identité à confirmer » ; nouveau concept « Vérification » ; une seule ouverte par poste |
| **Q8** | Rôles : un rôle `technician` convient-il ? Peut-il créer des demandes de vérification et des interventions sur **tout** poste, ou seulement sur ceux dont il est responsable ? Peut-il lancer des **commandes à distance** (scan, redémarrage) — utile pendant une maintenance, mais c'est aujourd'hui réservé à l'admin ? | Oui ; tout poste ; **pas** de commandes en v1 |
| **Q9** | Réglages globaux : table `settings` + page Paramètres (admin), ou variables d'environnement seules + responsable global par drapeau sur le compte ? | Table `settings` + page Paramètres |
| **Q10** | Cycle : `0` = « pas de maintenance » pour une salle ou un poste (serveurs, VM) ? Un poste **jamais maintenu** est-il dû à `first_seen + cycle` (défaut) ou **immédiatement** (tout le parc bascule en retard à l'activation) ? Faut-il pouvoir saisir une date de dernière maintenance **antérieure** à Tia'i pour amorcer le cycle ? | `0` = exclu ; `first_seen + cycle` ; oui, une intervention `maintenance` antidatée sert d'amorce |
| **Q11** | Notifications : e-mail à la personne à qui l'on affecte une vérification ? Ligne « maintenances en retard » dans le résumé quotidien ? Rappel hebdomadaire au responsable ? (respecte la préférence e-mail existante) | Oui aux trois, en J7, derrière la préférence e-mail du compte |
| **Q12** | Interventions : liste fermée de types (maintenance, vérification, panne, installation logicielle, mise à niveau, autre) — d'autres à prévoir ? Une intervention est-elle **modifiable** après coup (par son auteur), **supprimable** (admin, tracé) ? | Liste ci-dessus ; modifiable par l'auteur et l'admin ; suppression admin, tracée dans l'audit |
| **Q13** | Que devient l'historique quand un poste est **supprimé** (nettoyage des postes disparus, fusion) ? Cascade (perdu), ou conservé orphelin ? | Fusion : l'historique suit le poste conservé. Suppression : cascade — l'historique d'un poste qui n'existe plus n'a pas de fiche où s'afficher ; l'export préalable est la sauvegarde |
| **Q14** | Un poste peut-il appartenir à **plusieurs** salles (chariot mobile, portable) ? | Non : une salle ou aucune |
| **Q15** | Ordre de livraison : tout en une fois, ou d'abord Salles + Journal (J1–J4), puis Vérifications et Maintenance (J5–J6) dans une seconde PR ? | Deux PR, dans cet ordre |

---

## 10. Points d'attention

- **Branche de base non fusionnée.** `claude/agent-location-wol-ughnse`
  (migration `0015`, colonne `location`) n'est pas dans `main`. Ce chantier
  la suppose fusionnée : la migration `0016` la suit, et la page Salles
  s'appuie sur le filtre d'emplacement. Fusionner d'abord, ou accepter une PR
  empilée.
- **Collision de libellé « À vérifier »** (Q7) : à trancher avant de toucher
  la liste, sinon deux filtres homonymes.
- **Suppression d'un compte** : `ON DELETE SET NULL` sur les responsables et
  affectations — une salle sans responsable retombe sur le global, une
  vérification sans affecté redevient « à prendre ». Les auteurs
  (`performed_by`, `closed_by`) restent en texte, comme dans l'audit.
- **Fusion de postes** : `merge_into` doit déplacer `interventions`,
  `machine_checks` et reporter `last_maintenance_at` / `room_id` sur le poste
  conservé (J4).
- **Mode AD et postes hors domaine** : un parc mixte garde les postes sans
  bloc `directory` « sans salle » ; en mode `ad_*`, ils ne sont pas
  rattachables à la main (Q3) — à documenter, ou à prévoir l'épinglage.
- **ADSI côté agent** : premier usage de COM hors WMI dans l'agent. Même
  garde-fou que WMI (délai, échec silencieux → bloc absent, log une fois).
  Tester sur un poste dont le DC est injoignable : l'appel doit échouer vite
  et l'agent continuer.
- **Charge** : `/maintenance/due` et les compteurs par salle sont des
  agrégats sur `machines` (une colonne dénormalisée, un index sur `room_id`) ;
  rien qui ne tienne pas sur un parc de mille postes.
- **RGPD** : les notes sont du texte libre ; rien n'empêche d'y écrire un nom
  d'utilisateur. Pas de règle technique, mais une phrase dans la doc.
