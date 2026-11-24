# Évolutions inspirées d'ITIL et des autres plateformes : document de travail

> **📝 Document de travail — 2026-11-19, révisé le 2026-11-20. ✅ C1 (alertes), C2 (actifs), C3 (planifications) et C4 (signalements) livrés le 2026-11-20, C5 (conformité) et C6 (licences) le 2026-11-24 ; écarts en §8.** Il porte sur les fonctionnalités propres à la console. Le fonctionnement avec GLPI, décidé le 2026-11-20, est mis de côté dans son propre document, `plan-connecteur-glpi.md`. Il ordonne onze chantiers, donne pour chacun le cadrage, l'esquisse technique et les jalons, et liste en §6 les décisions à prendre avant de coder. Conformément à l'usage du dépôt, chaque chantier retenu aura son propre `plan-*.md` détaillé au moment de l'ouvrir ; celui-ci sert à choisir et à ordonner.

> Origine : comparaison avec GLPI, Snipe-IT, Lansweeper, Intune, PDQ Deploy, Action1, NinjaOne et Tactical RMM, relue au travers des pratiques ITIL 4. Les estimations sont des ordres de grandeur en jours de développement, tests et documentation compris, validation sur poste réel non comprise.

---

## 1. Ordre de priorité

Trois critères, dans cet ordre : la valeur immédiate pour un technicien de terrain, le coût (un chantier sans modification de l'agent passe avant un chantier qui impose un redéploiement par GPO), et les dépendances entre chantiers.

| Rang | Chantier | Pratique ITIL | Agent modifié | Estimation | Dépend de |
|---|---|---|---|---|---|
| 1 | **C1 — Règles d'alerte** sur les données déjà collectées | Surveillance et gestion des événements | Non | 5 j | — |
| 2 | **C2 — Cycle de vie des actifs** (achat, garantie, statut, étiquette QR) | Gestion des actifs informatiques | Non | 8 j | — |
| 3 | **C3 — Planification, fenêtres et anneaux** | Gestion des déploiements, habilitation des changements | Non (à confirmer, §3.3) | 11 j | — |
| 4 | **C4 — Signalement par l'utilisateur** | Gestion des incidents, centre de services | Non | 6 j | C2 (QR) |
| 5 | **C5 — Conformité des postes et mises à jour tierces** | Sécurité de l'information, gestion des déploiements | **Oui** | 9 j | C1 |
| 6 | **C6 — Licences logicielles** | Gestion des actifs logiciels | Non | 4 j | C1 (logiciels interdits) |
| 7 | **C7 — Second facteur et connexion par l'annuaire** | Sécurité de l'information | Non | 6 j | — |
| 8 | **C8 — Webhooks et jetons d'API** | Intégration | Non | 5 j | C1 |
| 9 | **C9 — Tendances, indicateurs et pannes récurrentes** | Mesure et rapports, gestion des problèmes | Non | 6 j | C1, C4 |
| 10 | **C10 — Approbation à deux des actions de masse** | Habilitation des changements | Non | 3 j | C3 |
| 11 | **C11 — Procédures et pièces jointes** | Gestion des connaissances | Non | 4 j | — |

Total : environ 67 jours. Les quatre premiers (30 j) forment le lot prioritaire ; le reste se prend à l'unité.

**Pourquoi C1 d'abord, alors que le cycle de vie des actifs est le manque le plus visible** : C1 n'ajoute aucune donnée à saisir et aucune collecte — tout est déjà en base — et il crée la table d'alertes que C2 (fin de garantie), C5 (contrôle non conforme), C6 (logiciel interdit) et C8 (événements à émettre) réutilisent.

---

## 2. Règles communes à tous les chantiers

Rien de nouveau ici : ce sont les invariants du produit, rappelés parce que chaque chantier doit les tenir.

| Sujet | Règle |
|---|---|
| Catalogue de commandes fermé | Aucun chantier n'ajoute d'exécuteur de scripts ni d'argument libre (`command/models.py`, `CommandType`). Une action nouvelle est une valeur de plus dans l'énumération et une entrée dans le binaire de l'agent. |
| Le serveur ne se connecte jamais aux postes | Toute donnée nouvelle remonte par le battement ou l'inventaire ; toute action part dans la réponse au battement. |
| Portée des groupes | Chaque liste, compteur, e-mail et export nouveau passe par `machine_clause(scope)` ; un poste hors de portée répond « introuvable ». |
| Droits | Une ressource nouvelle entre dans `PERMISSION_CATALOGUE` (`user/permissions.py`) et dans la grille de la console ; pas de droit implicite. |
| Journal d'audit | Toute écriture de configuration (règle, planification, licence, jeton) écrit `audit.record` dans la transaction de l'appelant. |
| Réglages | Les seuils vivent dans `app_settings` avec leur valeur initiale dans l'environnement, sur le modèle de `usage_policy()` et `fleet_policy()`, et sont **servis** à la console plutôt que recopiés. |
| Deux langues | Tout texte composé par le serveur part codé (`*_code` + paramètres), cf. `plan-console-bilingue.md`. |
| Fusion de postes | Toute table qui référence `machines.id` dit ce que `merge_into` en fait (réattribuer ou abandonner), avec un test. |
| Agent | Un champ nouveau est facultatif des deux côtés : un vieil agent doit continuer à fonctionner avec un serveur récent, et inversement. |
| Migrations | La dernière est `0047_room_texts` ; les numéros ci-dessous sont indicatifs. |
| GLPI plus tard | Le connecteur GLPI est mis de côté (`plan-connecteur-glpi.md`). En attendant, C2 et C4 ne ferment pas la porte : la saisie des actifs et la création d'une vérification depuis un signalement passent chacune par une seule fonction, que le connecteur pourra rediriger. |

---

## 3. Lot prioritaire

### 3.1 C1 — Règles d'alerte

**Constat.** Le tableau de bord compte déjà les postes au disque presque plein, non chiffrés, vieillissants ou en attente de redémarrage (`stats.py` : `machines_low_disk`, `machines_unencrypted`, `machines_aging`, `machines_reboot_required`). Mais ce sont des compteurs à aller lire : rien n'est daté, rien n'est notifié, et le résumé quotidien ne parle que des menaces, des correctifs et de l'antivirus (`notification/digest.py`). La santé des disques (`Disk.health_status`) est collectée et n'alimente aucun compteur.

**Cadrage proposé.**

| Sujet | Proposition |
|---|---|
| Règles | Un **catalogue fermé dans le code**, comme les commandes : pas de moteur de règles à écrire dans la console. Chaque règle a un interrupteur et, au besoin, un seuil dans `app_settings`. |
| Règles de la première itération | `disk_low` (seuil existant `low_disk_free_percent`), `disk_unhealthy` (`health_status` ≠ `Healthy`), `volume_unencrypted` (portables seulement par défaut, d'après `hw_chassis_type`), `reboot_pending_long` (N jours, défaut 7), `os_unsupported`, `forbidden_software`, `inactive` (seuil existant). |
| Alerte | Une ligne datée par poste et par règle, ouverte quand la condition devient vraie, **résolue toute seule** quand elle cesse. Une seule ouverte à la fois par couple (poste, règle). |
| Évaluation | Une tâche du worker toutes les cinq minutes, en SQL ensembliste, qui réutilise les clauses existantes (`low_disk_clause`, etc.). Pas dans le gestionnaire du battement : il doit rester court. |
| Notification | Une section de plus dans le résumé quotidien. E-mail immédiat pour `disk_unhealthy` seulement, sur le modèle de `threat_alert.py`, parce que c'est la seule règle où un jour de délai peut coûter des données. |
| Vérification automatique | Option par règle : ouvrir une vérification demandée. `uq_machine_checks_open` n'en autorise qu'une ouverte par poste : s'il y en a déjà une, l'alerte reste visible sur la fiche et n'en crée pas. La consigne part codée (`instructions_code`, à ajouter). |

**Modèle** (migration `0048_machine_alerts`).

```
machine_alerts
  id           uuid PK
  machine_id   uuid FK machines.id ON DELETE CASCADE
  rule         varchar(40)
  opened_at    timestamptz
  resolved_at  timestamptz NULL
  detail       jsonb         -- ce qui a déclenché : volume, pourcentage, logiciel…
  check_id     uuid NULL FK machine_checks.id ON DELETE SET NULL
  UNIQUE (machine_id, rule) WHERE resolved_at IS NULL
```

Plus une colonne `machines.wu_reboot_required_since` : `wu_reboot_required` est un booléen sans date, et « depuis sept jours » ne se calcule pas sans elle.

**Deux règles demandent une donnée de référence.**
- `os_unsupported` : une table des dates de fin de support par version de Windows, tenue dans le code et mise à jour à chaque version de Tia'i. À vérifier d'abord : ce que contient exactement `machines.os_version`, et si l'édition (Éducation, Entreprise, LTSC), qui change la date, est remontée.
- `forbidden_software` : une liste de motifs (nom, éditeur) dans les réglages, rapprochée du catalogue `Software`. Partagée avec C6.

**API et console.** `GET /alerts` (filtrable par règle et par état, dans la portée), `GET /machines/{id}/alerts`, un filtre `alert=` sur la liste des postes, une carte « Alertes » sur la fiche, une section « Alertes » dans les Paramètres. Aucun droit nouveau : `machine:read` pour lire, `settings:write` pour régler.

**Jalons.**

| Jalon | Contenu | Durée |
|---|---|---|
| A1 | Table, catalogue des règles, tâche d'évaluation, ouverture et résolution, purge. Les cinq règles sans donnée de référence. | 2 j |
| A2 | Résumé quotidien, e-mail immédiat, vérification automatique. | 1 j |
| A3 | Console : fiche, filtre, Paramètres. | 1,5 j |
| A4 | `os_unsupported` et `forbidden_software`. | 0,5 j |

### 3.2 C2 — Cycle de vie des actifs

**Constat.** L'inventaire dit ce qu'est un poste, pas où il en est dans sa vie. Le code le reconnaît : `aging_hardware_clause` se rabat sur la date du BIOS parce que la date d'achat « vit dans un système comptable auquel ce produit ne parle pas ». Et un vidéoprojecteur ou une imprimante n'existent nulle part.

**Cadrage proposé.**

| Sujet | Proposition |
|---|---|
| Où ranger les données | Une table `assets` distincte, liée à `machines` par un `machine_id` facultatif et unique. Pas des colonnes de plus sur `machines` : la table en compte déjà plus de cent, et un matériel sans agent doit pouvoir exister sans fiche de poste. |
| Champs | Numéro d'inventaire (unique), statut, date d'achat, fournisseur, référence de commande, fin de garantie, prix (facultatif), notes ; pour un prêt : emprunteur et date de retour prévue. |
| Statuts | `in_stock`, `in_service`, `in_repair`, `on_loan`, `retired`. Un poste réformé sort des compteurs du tableau de bord, comme un poste inactif. |
| Saisie | Sur la fiche, et **par import** Excel ou CSV rapproché sur le numéro de série (`hw_serial`) — saisir trois cents dates d'achat à la main n'arrivera pas. L'import montre ce qu'il va écrire avant de l'écrire. |
| Âge du matériel | `aging_hardware_clause` lit la date d'achat quand elle existe, la date du BIOS sinon. |
| Étiquette QR | Planche d'étiquettes imprimable depuis une salle ou une sélection. Le QR porte un **jeton opaque** (`public_token`), pas l'identifiant du poste : C4 en a besoin, et l'étiquette ne doit rien révéler à qui la photographie. |
| Windows 11 | Un indicateur « prêt matériellement » calculé depuis l'inventaire : TPM 2.0, mémoire, taille du disque, architecture. Deux limites à afficher : `secure_boot` dit s'il est *activé*, pas si le poste en est capable, et la liste des processeurs pris en charge n'est pas dans le produit — le processeur sort en « à vérifier ». |
| Matériels sans agent | Dernier jalon : type (imprimante, vidéoprojecteur, écran, autre), salle, et les mêmes champs de cycle de vie. Ni commandes, ni inventaire, ni battement. |

**Console.** Onglet « Actif » sur la fiche d'un poste, filtres par statut et par fin de garantie sur la liste, colonnes ajoutées à l'export (`api/fields.py`), page « Matériels » au dernier jalon. La fin de garantie à N jours devient une règle de C1.

**Jalons.**

| Jalon | Contenu | Durée |
|---|---|---|
| B1 | Table, API, onglet de la fiche, filtres, export, fusion de postes. | 2,5 j |
| B2 | Import Excel/CSV avec aperçu. | 1,5 j |
| B3 | Jeton public, planche d'étiquettes QR. | 1 j |
| B4 | Indicateur Windows 11, âge par date d'achat, vue « à renouveler ». | 1 j |
| B5 | Matériels sans agent. | 2 j |

### 3.3 C3 — Planification, fenêtres et anneaux

**Constat.** Une commande est en file dès sa création et expire au bout d'une heure (`Command.expires_at`). On ne peut ni dire « mercredi à 18 h », ni interdire les heures de cours, ni déployer une salle pilote avant le parc. C'est le chantier le plus délicat du lot : il touche au cycle de vie des commandes.

**Cadrage proposé.**

| Sujet | Proposition |
|---|---|
| Mécanisme | Une table `schedules`, et une tâche du worker qui, à l'échéance, **crée les commandes** par le chemin existant. Pas une colonne `not_before` sur `commands` : la cible doit se résoudre au moment de l'exécution (une salle a pu changer entre-temps), une planification peut se répéter, et le Wake-on-LAN est exécuté par le serveur, pas remis à un agent. |
| Cible | Les cibles de `POST /commands` (liste, tout le parc, domaine, emplacement, état), plus la salle et le bâtiment. |
| Récurrence | Une fois, ou hebdomadaire (jours et heure). Le fuseau est un réglage de la console : Tahiti est à UTC−10, une heure UTC n'a pas de sens pour qui planifie. |
| **Au nom de qui** | Une planification garde son auteur, et à chaque exécution le serveur **revérifie** que ce compte est actif, détient encore le droit d'exécuter ce type de commande et que la cible est dans sa portée. Sinon elle est suspendue et le dit. Sans cela, planifier serait un moyen de conserver un droit qu'on a perdu. |
| Durée de vie | Une commande planifiée porte sa propre expiration (défaut 3 h) : un poste réveillé met plusieurs minutes à contacter le serveur. |
| Enchaînement | Première itération : une action par planification, plus deux options — « réveiller d'abord » et « éteindre ensuite ». L'arrêt final ne vise **que les postes que la planification a elle-même réveillés**, et jamais un poste où une session est ouverte (`session_user_present`). |
| Plages interdites | Des plages hebdomadaires dans les réglages. Une planification qui y tombe est refusée à la création ; une commande à risque lancée à la main sur plusieurs postes demande une confirmation de plus. Une commande sur un seul poste reste libre : c'est le dépannage. |
| Anneaux | Pour l'installation de mises à jour et le déploiement d'un paquet : des étapes ordonnées (salle pilote, bâtiment, parc), un délai d'observation et un seuil d'échec. Le worker fait avancer ; au-delà du seuil, tout s'arrête et l'auteur est prévenu. S'appuie sur le suivi poste par poste des paquets. |
| Extinction du soir | Pas un mécanisme de plus : une planification d'arrêt, quotidienne, sur les postes « toujours allumés ». |

**À vérifier avant de s'engager sur « agent non modifié ».** L'agent rationne lui-même l'arrêt et le redémarrage (`agent/internal/agent/power.go`). Il faut confirmer qu'un arrêt quotidien passe ce rationnement ; sinon l'extinction du soir demande une version d'agent.

**Droits.** Ressource `schedule` (lecture, écriture). Écrire une planification exige en plus le droit d'exécuter la commande qu'elle porte (`command:execute` ou `risky_command:execute`).

**Jalons.**

| Jalon | Contenu | Durée |
|---|---|---|
| P1 | Table, tâche d'échéance avec réservation (deux workers ne doivent pas exécuter deux fois), revérification des droits, audit, expiration propre. | 3 j |
| P2 | Console : page Planifications, création depuis une salle et depuis la liste, historique des exécutions. | 2,5 j |
| P3 | « Réveiller d'abord », « éteindre ensuite », garde sur la session ouverte. | 1,5 j |
| P4 | Plages interdites. | 1 j |
| P5 | Anneaux de déploiement. | 3 j |

### 3.4 C4 — Signalement par l'utilisateur

**Constat.** Seul un compte de la console peut ouvrir une vérification. Un enseignant devant un poste en panne n'a aucun canal.

**Cadrage proposé.**

| Sujet | Proposition |
|---|---|
| Canal | Le QR de l'étiquette (C2) ouvre un formulaire **sans compte** : une catégorie, un texte, un contact facultatif. |
| File de tri | Un signalement n'est **pas** une vérification. Il arrive dans une file ; un technicien le transforme en vérification, le rattache à celle déjà ouverte ou le rejette. Sans cette étape, n'importe qui occuperait l'unique vérification ouverte d'un poste. |
| Surface d'attaque | C'est le premier point d'entrée non authentifié qui ne soit pas l'agent. Limitation de débit par adresse et par jeton (`core/ratelimit.py`), tailles bornées, aucune information sur le poste renvoyée par le formulaire, jeton révocable, et la fonction **désactivée par défaut**. |
| Portée réseau | Le serveur est interne (`plan-projet-tiai.md` §8) : le formulaire ne marche que depuis le réseau de l'établissement. C'est une limite acceptable, et une protection. |
| Données personnelles | Le contact est facultatif, purgé avec le signalement, et mentionné sur le formulaire. À porter au registre des traitements. |
| Vérifications enrichies | Priorité (basse, normale, haute), catégorie, échéance facultative. Le délai entre ouverture et clôture devient mesurable (C9). |

**Jalons.**

| Jalon | Contenu | Durée |
|---|---|---|
| S1 | Priorité, catégorie et échéance sur les vérifications ; « Mes tâches » triées en conséquence. | 1,5 j |
| S2 | Table des signalements, point d'entrée public, limitation de débit, réglage. | 2 j |
| S3 | Formulaire public (deux langues), file de tri, droit `report`. | 2,5 j |

---

## 4. Chantiers suivants

Cadrage plus court : chacun sera détaillé au moment de l'ouvrir.

### 4.1 C5 — Conformité des postes et mises à jour tierces *(9 j, agent modifié)*

- **Conformité** : une liste fermée de contrôles, affichée « 7 sur 9 » plutôt qu'en score pondéré, parce qu'une note ne dit pas quoi corriger. Sans toucher l'agent : volume système chiffré, Secure Boot, TPM, antivirus actif et à jour, correctifs en attente, redémarrage en attente, système pris en charge, agent à jour. Avec une nouvelle collecte : état des trois profils du pare-feu, et membres du groupe Administrateurs local — ce dernier contient des noms de comptes, donc un interrupteur à la source comme `ReportSessionUsername`.
- **Mises à jour tierces** : l'agent sait installer par winget (`agent/internal/deploy/deploy.go`) et reconnaît déjà le code « aucune mise à jour applicable ». Il manque la remontée des mises à jour *disponibles* et un taux de conformité par logiciel. À valider sur poste réel avant tout : le comportement de `winget upgrade` sous `LocalSystem`, et son coût.
- **Hors périmètre** : le croisement de l'inventaire avec les CVE. Il demande une base de correspondance entre noms de logiciels et identifiants de vulnérabilités, une source externe à interroger depuis un serveur aujourd'hui sans sortie Internet obligatoire, et produit beaucoup de faux positifs. À reprendre seul, plus tard.

### 4.2 C6 — Licences logicielles *(4 j)*

Une table `licenses` : logiciel (lié à une ou plusieurs entrées du catalogue `Software`), nombre de postes couverts, échéance, fournisseur, référence. **Jamais la clé elle-même.** La page Logiciels affiche « 32 installations pour 30 licences » ; le dépassement et l'échéance proche deviennent des règles de C1. La liste des logiciels interdits est celle de C1.

### 4.3 C7 — Second facteur et connexion par l'annuaire *(6 j)*

- **Second facteur TOTP** (3 j) : enrôlement depuis « Mon compte », codes de secours, obligation réglable par groupe. Il s'insère avant la création de la session (`auth_session`) ; la réponse de connexion ne doit pas dire si le compte a un second facteur avant que le mot de passe soit bon, pour garder la connexion sans fuite d'information.
- **OpenID Connect** (3 j), Entra ID en premier : correspondance entre groupes de l'annuaire et groupes de Tia'i, et au moins un compte local conservé pour le cas où le fournisseur d'identité est injoignable.
- Une authentification LDAP directe est possible avec la configuration de `plan-lecture-annuaire.md`, mais OIDC apporte le second facteur de l'établissement sans le réécrire.

### 4.4 C8 — Webhooks et jetons d'API *(5 j)*

- **Webhooks sortants** : menace détectée, alerte ouverte ou résolue, vérification créée ou close, commande échouée. Même garantie que les e-mails — une file en base et des réessais, sur le modèle de `notification/outbox.py`. Corps signé (HMAC), et contrôle de la destination : un webhook est un moyen de faire émettre des requêtes au serveur vers son propre réseau.
- **Jetons d'API personnels** : liés à un compte, limités à ses droits et à sa portée, en lecture seule par défaut, révocables, à durée de vie bornée, journalisés.
- Teams et Mattermost ne sont que deux formats de webhook.

### 4.5 C9 — Tendances, indicateurs et pannes récurrentes *(6 j)*

- **Tendances** : le tableau de bord est un instantané. Une tâche quotidienne enregistre les compteurs de `/stats/overview` ; une courbe montre le parc sur douze mois. Question ouverte : un instantané global ne respecte pas la portée d'un groupe limité — il faut le tenir par bâtiment, ou réserver la vue aux comptes sans limite.
- **Indicateurs** : délai de clôture des vérifications, part des maintenances faites à l'heure, taux de réussite des commandes et des déploiements.
- **Pannes récurrentes** : les interventions de type `incident` regroupées par modèle (`hw_model`) et par salle. « Douze pannes en un an sur le même modèle » est une information d'achat.
- Rapport périodique en Excel d'abord (le générateur existe, `api/xlsx_export.py`), PDF seulement si demandé.

### 4.6 C10 — Approbation à deux des actions de masse *(3 j)*

Au-delà de N postes, une commande à risque attend l'accord d'un second compte qui détient le même droit. Désactivée par défaut : dans un établissement à un seul administrateur, elle bloquerait tout. Se pose sur les planifications et les anneaux de C3.

### 4.7 C11 — Procédures et pièces jointes *(4 j)*

- Pièces jointes sur une intervention (photo d'une panne, bon de réparation), stockées par empreinte comme les fichiers de paquets (`package/storage.py`), avec taille et types bornés.
- Notes de procédure par modèle de poste, affichées sur la fiche de tous les postes de ce modèle (« sur ce modèle, le BIOS s'ouvre par F10 »).

---

## 5. Ce qui n'est pas proposé

| Fonctionnalité | Raison |
|---|---|
| Exécuteur de scripts | Tous les outils de gestion à distance en ont un. C'est précisément ce que le catalogue fermé interdit : un serveur compromis ne doit pouvoir déclencher que les actions prévues. |
| Prise en main à distance intégrée | Même raison, et le serveur ne se connecte jamais aux postes. Un lien qui lance l'outil déjà en place (Assistance rapide, bureau à distance) suffit. |
| Centre de services complet (contrats de service, catalogue de demandes) | GLPI le fait. C4 s'arrête au signalement et au tri. |
| Agents macOS, Linux, ChromeOS | Hors du périmètre « parc de postes Windows » ; à rouvrir seulement sur demande. |

---

## 6. Décisions à prendre

1. ~~Outil de tickets existant ?~~ **Tranché le 2026-11-20** : Tia'i fonctionnera seul ou avec GLPI ; le connecteur est reporté (`plan-connecteur-glpi.md`).
2. **Exposition de la console.** « Interne » veut dire que l'adresse de la console n'est joignable que depuis le réseau de l'établissement — son réseau local, ou un réseau qui y est relié par VPN —, même si le serveur est hébergé ailleurs. « Exposée » veut dire joignable depuis n'importe quelle connexion Internet. La documentation actuelle suppose la première (`plan-projet-tiai.md` §8). Si la console doit devenir joignable de l'extérieur, C7 passe avant C4.
3. ~~Actifs : table distincte ou colonnes ?~~ **Tranché le 2026-11-20** : table distincte `assets`.
4. ~~Droits sur les actifs.~~ **Tranché le 2026-11-20** : ressource `asset` à part, accordée par défaut aux seuls administrateurs.
5. ~~Poste réformé.~~ **Tranché le 2026-11-20** : sorti des compteurs et des alertes ; son jeton n'est pas révoqué (la réforme reste réversible).
6. ~~Chiffrement.~~ **Tranché le 2026-11-20** : portables et tablettes par défaut, tous les postes sur réglage.
7. ~~Fuseau de la console.~~ **Tranché le 2026-11-20** : un seul fuseau pour toute la console, réglage de Paramètres (`CONSOLE_TIMEZONE`, Tahiti par défaut).
8. ~~Enchaînements de C3.~~ **Tranché le 2026-11-20** : les deux options, « réveiller d'abord » et « éteindre ensuite », pas de séquences libres.
9. **Administrateurs locaux (C5).** Collecte à arbitrer avec le DPO, comme le nom de session.
10. ~~Périmètre de la prochaine version.~~ **Tranché le 2026-11-20** : C1 et C2 d'abord.

---

## 7. Séquencement

- **C1 et C2 sont indépendants** et peuvent avancer en parallèle ; ils ne touchent pas les mêmes fichiers, sauf `machine/crud.py` (`merge_into`) et la fiche d'un poste.
- **C3 se mène seul** : il modifie le chemin de création des commandes, que le déploiement de paquets emprunte aussi.
- **C4 attend B3** (jeton public et étiquettes).
- **C5 impose une version d'agent** : le grouper avec toute autre évolution de l'agent en attente (lecture de l'annuaire en mode relais, `plan-lecture-annuaire.md`) pour ne redéployer qu'une fois.
- À chaque chantier livré : feuille de route du `README.md`, notes de version, et une section « Écarts constatés à l'implémentation » dans son plan.

---

## 8. Écarts constatés à l'implémentation

### C1 — Alertes

- **Huit règles et non sept** : `warranty_ending` (garantie bientôt terminée, `ALERT_WARRANTY_DAYS`, 30 jours) a été ajoutée avec C2, comme prévu en §3.2.
- **La table des fins de support de Windows** (`alert/os_support.py`) lit le numéro de build et l'édition dans la chaîne que l'agent compose déjà (« Windows 11 Education 23H2 (Build 22631) ») : rien à changer côté agent. Canaux distingués : Famille/Pro (Pro Éducation et Pro pour stations de travail compris, que Microsoft maintient avec Famille/Pro malgré « Éducation »), Entreprise/Éducation, LTSC et IoT Entreprise LTSC (dix ans depuis 2021 : LTSC 2021 jusqu'au 13/01/2032, LTSC 2024 jusqu'au 10/10/2034). Ce qui n'est pas reconnu (serveur, build plus récent que la table) n'est jamais signalé. Les dates sont à revérifier contre les pages de cycle de vie de Microsoft à chaque extension de la table ; les mises à jour de sécurité étendues payantes (ESU) ne sont pas connues de la console.
- **Logiciels interdits** : un motif est une sous-chaîne du nom du programme, insensible à la casse, jamais une expression `LIKE` (« 100 % » ne correspond pas à tout).
- **Vérification automatique** : les instructions sont codées (`machine_checks.instructions_code`, `instructions_params`) et mises en mots par la console dans la langue du lecteur, par le serveur dans celle du destinataire pour les e-mails (affectation, rappel des tâches) et dans celle du fichier pour l'export, ses dates au jour du fuseau de l'export (en UTC dans un e-mail). Seul un texte réellement modifié efface le code : la console renvoie le texte à chaque modification, une simple réaffectation le garde codé.
- **Garantie et droit `asset`** : la date de fin de garantie est une donnée d'achat. `GET /alerts` la retire du détail d'une alerte `warranty_ending` pour qui n'a pas `asset:read` (il lit « garantie terminée dans moins de N jours »), et la vérification ouverte pour cette alerte ne porte que le seuil.
- **Badge « Vérification demandée »** : affiché tant que la vérification ouverte pour l'alerte l'est encore (`check_open`), plus seulement parce qu'une l'a été.
- **Évaluation par lots** : les alertes et les vérifications nouvelles sont insérées par lots de 1 000, sous la limite de 65 535 paramètres de PostgreSQL (premier passage sur un grand parc).
- **Forme** : la règle s'appelle `reboot_pending` et non `reboot_pending_long` (valeur enregistrée dans les réglages, gardée) ; pas de route `GET /machines/{id}/alerts`, la fiche lit `GET /alerts?machine_id=…&state=all` ; le filtre `alert=` de la liste s'ouvre depuis la page Alertes (« Voir ces postes », pour l'onglet affiché), la carte du tableau de bord menant à cette page.
- **Résumé quotidien** : la section « Alertes ouvertes » ne s'affiche que s'il y en a, pour ne pas changer les résumés existants ; elle ne déclenche pas à elle seule le résumé « seulement s'il y a du nouveau ».
- **`wu_reboot_required_since`** : les postes déjà en attente à la migration comptent depuis la migration.
- Un test existant dépendait de la date du jour (`test_mail_languages`, détection datée du 18/11) : corrigé au passage.

### C2 — Actifs

- **Droit `asset`** : lecture et écriture ; le scan d'une étiquette (`/assets/by-token`) ne demande que `machine:read`, puisque celui qui scanne veut la fiche du poste.
- **Portée** : l'actif d'un poste suit son poste ; le matériel sans agent suit sa salle, et celui qui n'est dans aucune salle n'est vu que des comptes sans restriction (un compte restreint ne peut pas en créer hors salle).
- **Import** : séparateur choisi par la ligne d'en-têtes qu'il fait apparaître parmi les dix premières (sous un titre aussi), pas par `csv.Sniffer`, qui prenait l'apostrophe de « N° d'inventaire » pour un guillemet. 5 000 lignes et 8 Mo au plus (refus `asset.import.too_large`, qui dit quelle limite), lu hors de la boucle d'évènements ; une feuille mise en forme très bas (plus de 100 000 lignes, vides pour la plupart) est refusée pour ses lignes vides, à supprimer. Un CSV que le lecteur ne peut suivre (guillemet jamais refermé) est « illisible », pas une erreur du serveur ; à égalité entre séparateurs, celui qui découpe la ligne d'en-têtes en plus de cellules l'emporte, puis « ; ». Une ligne n'est écrite que si son n° de série désigne exactement un poste de la portée ; un n° de série présent deux fois est refusé sur sa seconde ligne, à l'aperçu comme à l'import ; une case blanche (espaces) ne change rien ; un prix ambigu (« 1,299 », « 125.000 » : trois chiffres après un seul séparateur) ou de plus de deux décimales significatives est refusé plutôt qu'arrondi, les zéros d'un export comptable (« 1299.9900 ») acceptés. Les en-têtes de l'export (FR et EN) se relisent.
- **Statut** : absent, il ne change pas ; `null` est refusé (422, `tiai_null_refused`, mis en mots par la console).
- **Étiquettes** : QR dessiné côté console (`qrcode-generator`), qui porte `<origine de la console>/a/<jeton>` ; le jeton se renouvelle depuis la fiche d'actif. Planche imprimable depuis une sélection de « Matériels » ou depuis une salle (bouton « Étiquettes » de la salle, filtre par salle de « Matériels ») ; un poste sans fiche matériel n'a pas d'étiquette, et la planche d'une salle propose de créer d'un coup les fiches qui manquent (`POST /assets/rooms/{id}/complete`). Le QR d'un matériel sans agent ouvre « Matériels » sur ce seul matériel.
- **Adresses** : la page « Matériels » est à `/equipment` et sa planche à `/equipment/labels` — pas sous `/assets`, où nginx sert les fichiers hachés du build sans repli sur la console (404 au rechargement).
- **Fiche matériel** : une carte dans l'onglet Identité de la fiche, plutôt qu'un onglet « Actif » de plus.
- **Garantie « bientôt terminée »** : sur la fiche, dans le filtre de « Matériels » et pour l'alerte, un seul seuil : celui de l'alerte (Paramètres, 30 jours par défaut). Le serveur calcule l'état (`warranty_state`), la console ne le recompte pas.
- **Windows 11** : verdict « prêt » au mieux « processeur à vérifier » ; « incompatible » seulement sur le TPM, la mémoire ou le disque. La mémoire est la somme des barrettes quand l'inventaire les lit toutes (comme le contrôle de Microsoft) ; à défaut, ce que Windows adresse, un peu sous 4 Go étant « à vérifier » (mémoire réservée par une puce graphique intégrée). Un Windows Server n'a pas de verdict. Carte « Bloqués pour Windows 11 » au tableau de bord et filtre `win11_blocked`, dont `false` est le complément exact.
- **Poste réformé** : sorti de tous les chiffres du tableau de bord (menaces, vérifications, maintenance, utilisation, alertes comprises), du résumé quotidien et des alertes. Les listes le montrent toujours ; tant que le parc en compte, les cartes du tableau de bord ouvrent la liste avec `in_parc=true` (puce « Hors postes réformés »), pour que la carte et la liste disent le même nombre ; les listes d'à côté (postes en retard, menaces actives) et le bloc « Vos tâches » du résumé et du rappel hebdomadaire les laissent de côté aussi. Filtrable aussi par `asset_status` (« Voir ces postes » depuis « Matériels »).
- **Fusion** : quand les deux fiches ont chacune leur actif, celui de la fiche gardée l'emporte ; celui du doublon complète ce qu'il laisse vide (n° d'inventaire compris ; l'emprunteur seulement si l'actif gardé est prêté) puis est supprimé, ce qu'il portait inscrit au journal (`asset.delete`, prix masqué). Une étiquette imprimée depuis le jeton du doublon ne mène plus nulle part : celle de la fiche gardée est à imprimer.
- **Âge du matériel** : compté depuis la date d'achat de la fiche matériel, à défaut la date du BIOS (textes de Paramètres et `DEPLOYMENT.md` corrigés).
- **Page d'arrivée** : un compte qui ne lit que les achats (`asset:read` sans `machine:read`) arrive sur « Matériels ».
- **Export** : cinq colonnes d'actif (n° d'inventaire, statut, date d'achat, fin de garantie, fournisseur) offertes aux seuls comptes qui détiennent `asset:read` ; pas le prix, un classeur voyageant plus loin que la console.

### C3 — Planifications

- **Agent non modifié, confirmé** : l'agent ne refuse un arrêt ou un redémarrage que dans les dix minutes qui suivent un démarrage ou une autre action d'alimentation (`power.go`). L'extinction du soir passe ; « éteindre ensuite » attend quinze minutes après le réveil.
- **Mécanisme** : tables `schedules` et `schedule_runs`, `commands.schedule_run_id` et `schedule_stage` (migration `0050_schedules`). La tâche `run_schedules` du worker passe chaque minute ; chaque échéance est réservée sous verrou de ligne (`FOR UPDATE SKIP LOCKED`) et avancée à la suivante dans la même transaction. Les commandes passent par le même chemin que la console (`command.dispatch`, `wol.dispatch`), extrait de la route à cette occasion.
- **Au nom de qui** : à chaque exécution, le compte de l'auteur doit exister, être actif et détenir `schedule:write`, `command:execute` et, pour une commande à risque ou « éteindre ensuite », `risky_command:execute` ; la cible est résolue dans sa portée du moment. Sinon la planification est **suspendue**, l'exécution le dit, le journal l'inscrit (`schedule.suspend`) et l'auteur reçoit un e-mail. Modifier ou réactiver une planification la reprend au nom de celui qui le fait.
- **Ressource `schedule`** (lecture, écriture), accordée par défaut aux seuls administrateurs. Un compte restreint voit ses propres planifications et celles qui visent une salle, un bâtiment ou des postes tous dans sa portée ; une planification sur tout le parc, un domaine ou un emplacement, écrite par un autre, ne le regarde pas.
- **Cibles** : celles de `POST /commands`, plus la salle et le bâtiment (ajoutés aussi à `POST /commands`). Une salle ou un bâtiment disparu suspend la planification.
- **Retard** : une échéance manquée de plus d'une heure (worker arrêté) n'est pas rattrapée ; l'exécution est notée « non exécutée » et la suivante calculée. Une plage interdite ajoutée après coup fait sauter l'exécution de la même façon.
- **Arrêt et redémarrage planifiés** : un poste où une session est ouverte est laissé de côté, comme pour « éteindre ensuite ». Une planification peut aussi être un simple réveil (« allumer la salle à 7 h 30 »).
- **Éteindre ensuite** : seulement les postes que l'exécution a réveillés, une fois leur commande terminée (ou expirée), au moins quinze minutes après le réveil, et jamais un poste où une session est ouverte ; un poste déjà éteint compte comme éteint.
- **Plages interdites** : plages hebdomadaires dans Paramètres, dans le fuseau de la console. Refus à l'écriture d'une planification à risque (`schedule.forbidden_window`) ; une commande à risque envoyée à la main à plusieurs postes demande une confirmation de plus (`command.forbidden_window`, `confirm_forbidden_window`). Un seul poste reste libre.
- **Anneaux** : pour `wu_install`, `wu_install_full` et `package_install` ; deux à cinq étapes, chacune une cible ; délai d'observation (1 à 336 h) et seuil d'échec (%, sur les postes qui ont répondu). Une étape dont aucun poste n'a répondu arrête aussi le déploiement (`ring_no_result`) plutôt que de passer au parc à l'aveugle. Arrêt inscrit au journal (`schedule.halt`) et e-mail à l'auteur.
- **Fusion** : une planification qui vise le poste doublon vise désormais le poste gardé ; l'historique des exécutions est laissé tel quel.
- **Conservation** : historique des exécutions purgé après `SCHEDULE_RUN_RETENTION_DAYS` (180 jours).
- **Console** : page Planifications (liste, exécutions, réactivation, suppression), boutons « Planifier » sur la page d'une salle et dans la barre de sélection de la liste des postes, carte « Planifications » des Paramètres (fuseau, plages interdites). Les heures sont envoyées et affichées dans le fuseau de la console, quel que soit celui du navigateur.

### C4 — Signalements

- **Vérifications enrichies** (`0051_reports`) : priorité (basse, normale, haute ; les existantes « normale »), catégorie (matériel, logiciel, réseau, impression, compte, autre — liste fermée partagée avec les signalements) et échéance facultative. « Mes tâches » trie les ouvertes par priorité, puis échéance, puis ancienneté ; une échéance passée est signalée.
- **Canal** : le QR des étiquettes déjà imprimées (`/a/<jeton>`) devient une page publique. Un membre du personnel connecté va à la fiche, comme avant (la page connectée est désormais `/a/<jeton>/open`) ; un visiteur voit le formulaire si la console l'a ouvert, la connexion sinon. Formulaire en français et en anglais, sur téléphone.
- **Surface d'attaque** : désactivé par défaut (`REPORTS_ENABLED`, puis Paramètres) ; 10 envois par heure et par adresse, 20 par jour et par étiquette, 60 lectures du formulaire par heure ; texte de 3 à 2 000 caractères, contact de 200 au plus ; la réponse ne dit rien du poste (« reçu », ou étiquette invalide) et, formulaire fermé, la même chose quel que soit le jeton. Renouveler le QR d'un actif (C2) retire l'étiquette imprimée. Chaque envoi est inscrit au journal (`report.create`, acteur `report:<adresse>`).
- **File de tri** : page Signalements (droit `report`, lecture et tri, accordé par défaut aux seuls administrateurs), badge du nombre à trier dans le menu. Ouvrir en vérification (le texte devient les consignes, la catégorie suit ; priorité, échéance, affectation choisies au tri) ou rattacher à la vérification ouverte demande aussi `check:write` ; clore ou rejeter, avec une note, `report:write` seul. Un signalement sur du matériel sans agent ne peut que se clore. Portée : un compte restreint voit les signalements de ses postes et du matériel de ses salles.
- **GLPI plus tard** : un signalement devient une vérification par une seule fonction (`report.crud.open_check_from`), que le connecteur pourra rediriger.
- **Données personnelles** : le contact est facultatif, le formulaire le dit ; il est purgé avec le signalement, `REPORT_RETENTION_DAYS` (90 jours) après son traitement. Un signalement à trier n'est jamais purgé.
- **Fusion** : les signalements du doublon passent au poste gardé.
- **Non fait** : pas d'e-mail ni de section du résumé quotidien pour un nouveau signalement ; le badge du menu en tient lieu.


### C5 — Conformité et mises à jour tierces

- **Dix contrôles, pas neuf** : chiffrement du volume système, Secure Boot, TPM 2.0, antivirus actif et à jour, correctifs critiques, redémarrage en retard, Windows pris en charge, agent à jour, pare-feu (trois profils), administrateurs locaux. Chacun vaut conforme, non conforme, non relevé ou non requis ; « 7 sur 9 » ne compte que les contrôles relevés, un contrôle non relevé ne compte ni pour ni contre (`features/compliance/checks.py`).
- **Seuils repris** : le chiffrement suit la portée de l'alerte (portables et tablettes par défaut, sinon « non requis »), le redémarrage son délai, l'antivirus le seuil de signatures du parc, l'agent la version de référence. Un seul seuil nouveau : un correctif **critique ou important** en attente depuis plus de `COMPLIANCE_PATCH_GRACE_DAYS` (14 jours, puis Paramètres) — sans ce délai, chaque mardi de correctifs ferait passer tout le parc au rouge.
- **Administrateurs locaux** : sont tolérés sans réglage l'Administrateur intégré (RID 500), les Admins du domaine (512) et les Administrateurs de l'entreprise (519), reconnus par leur SID et non par leur nom, qui est traduit. Les autres comptes ou groupes acceptés se listent dans Paramètres (« DOMAINE\nom » ou « nom »).
- **Résumé stocké, détail calculé** : la tâche `refresh_compliance` du worker (toutes les 10 minutes) range sur chaque poste les contrôles réussis, relevés et échoués (`0052_compliance`), pour le filtre de la liste (`compliance`, `compliance_check`), la colonne « Conformité » (triable, les moins conformes d'abord) et la carte du tableau de bord. La fiche calcule les siens à l'ouverture, avec le détail : un réglage changé s'y voit tout de suite, dans la liste au plus 10 minutes après. Un poste réformé n'a pas de résumé.
- **Pas de règle d'alerte « non conforme »** : la section 2 prévoyait que C5 réutilise la table des alertes. Les contrôles qui méritent une alerte en ont déjà une (chiffrement, redémarrage, système non pris en charge) ; une alerte de plus par contrôle doublerait les mêmes postes dans la même liste. À rouvrir si le parc le demande.
- **Agent** (`agent/internal/collector/compliance*.go`) : trois nouvelles données dans l'inventaire quotidien, toutes facultatives, et un serveur plus ancien les ignore.
  - **Pare-feu** : `EnableFirewall` de chaque profil, le réglage de stratégie de groupe l'emportant sur le réglage local. Toujours relevé.
  - **Administrateurs locaux** : `NetLocalGroupGetMembers` sur le groupe trouvé par son SID (S-1-5-32-544), noms et SID. Interrupteur `ReportLocalAdmins`, **désactivé par défaut** en attendant la décision du DPO (décision 9) ; coupé, la liste stockée est effacée au cycle suivant.
  - **winget** : `winget list --source winget` lancé sous `LocalSystem` depuis le même `winget.exe` que les déploiements, sa table lue par position de colonnes (les en-têtes sont traduits). Interrupteur `ReportWingetPackages`, **désactivé par défaut** : la commande n'a pas de sortie lisible par une machine, elle tronque les noms trop longs (une ligne dont l'identifiant est coupé est ignorée), et son comportement sous `LocalSystem` reste **à valider sur un poste réel**, comme le plan le demandait.
  - Les deux interrupteurs se posent par le registre (GPO), par le YAML ou par les propriétés du MSI `REPORTLOCALADMINS` et `REPORTWINGETPACKAGES`.
- **Taux par logiciel** : `GET /software/updates` et l'onglet « Mises à jour tierces » de la page Logiciels. Pour chaque identifiant winget : postes qui l'ont, postes à mettre à jour (lien vers la liste, filtre `winget_outdated`), dernière version proposée, part des postes à jour. Le taux ne porte que sur les postes qui remontent leurs paquets winget, et la page dit combien ils sont.
- **Fusion** : les paquets winget du doublon disparaissent avec lui, comme le reste de l'inventaire ; le poste gardé les remonte à son cycle suivant.
- **Non fait** : déployer une mise à jour depuis l'onglet (il faut toujours créer un paquet winget) ; historique de la conformité dans le temps (C9).
- **Livré avec C5** (§7) : la lecture de l'annuaire en mode relais, seule autre évolution d'agent en attente — voir `plan-lecture-annuaire.md` §10.

### Relecture du 2026-11-24 (C3, C4, C5, annuaire)

Quatre relectures indépendantes, une par chantier. Corrections livrées dans la même PR, chacune avec son test.

- **C3** : « éteindre ensuite » n'éteint plus un poste dont la commande tourne encore après son délai, ni ceux d'une étape ultérieure ; désactiver une planification arrête les étapes suivantes ; le paquet est vérifié avant le réveil ; une étape qui n'a atteint aucun poste n'ouvre pas la suivante, et une étape attend la fin d'une plage interdite ; une planification qui lève une exception est close en échec sans bloquer les autres ; changer le fuseau garde l'heure planifiée ; l'historique se lit dans le fuseau de la console ; le déploiement d'un paquet propose la confirmation en plage interdite.
- **C4** : le tri d'un signalement se fait sous verrou (trois comptes au même instant obtenaient trois succès) ; la page publique ne dit « étiquette invalide » que si le serveur le dit ; l'entrée d'audit de réception porte l'identifiant du signalement. Les bornes par adresse supposent le proxy déclaré dans `TRUSTED_PROXIES` (DEPLOYMENT.md).
- **C5** : le tri par conformité ne fait plus échouer le passage à la fiche suivante ; un poste inventorié sans TPM est non conforme ; le délai des correctifs se compte depuis que le poste est en retard sans interruption (`wu_critical_pending_since`, migration `0054`) ; un administrateur local sans nom lisible est gardé sous son SID ; winget : largeur d'affichage, échec ponctuel sans perte, attente bornée ; pare-feu : stratégie de l'ancien modèle lue.
- **Annuaire** : voir `plan-lecture-annuaire.md` §11.
- **Non repris** : budgets de signalement réglables ; cumul des déplacements d'annuaire sur plusieurs lectures ; versions tronquées par winget laissées telles quelles, avec leur ellipse.

### C6 — Licences logicielles

- **Ce qui est couvert : des motifs, pas des entrées du catalogue.** Le plan liait une licence à « une ou plusieurs entrées du catalogue `Software` » ; or le catalogue a une ligne par (nom, version, éditeur), et une licence « Office 2021 » liée par identifiant serait à relier à chaque mise à jour mensuelle. Une licence porte donc des motifs (1 à 20) : un morceau du nom du programme, insensible à la casse et pris littéralement, comme la liste des logiciels interdits de C1, plus un éditeur facultatif qui restreint quand un nom est partagé (« Reader »). Le dialogue montre, pendant la saisie, les noms du catalogue que les motifs attrapent et le nombre de postes (`POST /licenses/preview`).
- **Décompte** : un poste compte une fois par licence, même avec plusieurs versions ou plusieurs logiciels couverts (Office et Visio) ; un poste réformé ne compte pas. « 32 pour 30 » sur la page, le nombre menant à la liste des postes (filtre `license_id`). Une licence de site se saisit sans nombre de postes (« sans limite ») ; une licence perpétuelle, sans échéance.
- **Jamais la clé** : aucun champ ne la reçoit, un champ inconnu envoyé est ignoré, et le dialogue le rappelle.
- **Pas de règle d'alerte de C1** : le plan voyait le dépassement et l'échéance devenir des règles de C1, mais une alerte de C1 est une ligne par poste, et une licence dépassée n'est la faute d'aucun poste en particulier. Ce sont deux verdicts de la licence elle-même, calculés à la lecture : `over` (plus d'installations que de postes couverts) et `expiry` (`none`, `active`, `soon`, `expired` ; « bientôt » sous `LICENSE_EXPIRY_DAYS`, 60 jours, puis Paramètres). Ils sont montrés sur la page Logiciels (vue « Licences »), dans une carte « Licences à revoir » du tableau de bord (absente quand il n'y a rien à revoir) et dans une section « Licences à revoir » du résumé quotidien. Pas d'e-mail immédiat.
- **Droit `license`** (lecture, écriture), accordé par défaut aux seuls administrateurs : un contrat et sa référence de commande sont des données d'achat, comme un actif.
- **Portée** : une licence est celle du parc. L'écrire demande un compte sans limite de lieux (`auth.scope.restricted` sinon) ; un compte limité la lit avec les installations comptées sur ses postes seulement et sans verdict de dépassement (`over` vaut `null`, la page le dit), puisque son nombre n'est pas celui du contrat. Le résumé quotidien ne porte la section qu'aux comptes sans limite qui lisent les licences (et les postes : le résumé d'un compte qui ne lit pas les postes reste celui de ses tâches).
- **Journal** : `license.create`, `license.update`, `license.delete`, avec le nom, les motifs, le nombre de postes, l'échéance, le fournisseur et la référence.
- **Fusion de postes** : rien à faire, aucune table de C6 ne référence `machines.id` ; le décompte suit le catalogue du poste gardé.
- **Logiciels interdits** : la liste reste celle de C1 (Paramètres, Alertes), inchangée.
- **Non fait** : export des licences ; historique du décompte dans le temps (C9) ; licences par utilisateur nommé (le produit ne connaît que des postes).
