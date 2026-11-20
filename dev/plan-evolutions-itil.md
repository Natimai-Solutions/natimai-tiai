# Évolutions inspirées d'ITIL et des autres plateformes : document de travail

> **📝 Document de travail — 2026-11-19, révisé le 2026-11-20. Rien n'est livré.** Décision du 2026-11-20 : **Tia'i fonctionne seul ou avec GLPI** (§2.1). Il ordonne douze chantiers, donne pour chacun le cadrage, l'esquisse technique et les jalons, et liste en §6 les décisions à prendre avant de coder. Conformément à l'usage du dépôt, chaque chantier retenu aura son propre `plan-*.md` détaillé au moment de l'ouvrir ; celui-ci sert à choisir et à ordonner.

> Origine : comparaison avec GLPI, Snipe-IT, Lansweeper, Intune, PDQ Deploy, Action1, NinjaOne et Tactical RMM, relue au travers des pratiques ITIL 4. Les estimations sont des ordres de grandeur en jours de développement, tests et documentation compris, validation sur poste réel non comprise.

---

## 1. Ordre de priorité

Trois critères, dans cet ordre : la valeur immédiate pour un technicien de terrain, le coût (un chantier sans modification de l'agent passe avant un chantier qui impose un redéploiement par GPO), et les dépendances entre chantiers.

| Rang | Chantier | Pratique ITIL | Agent modifié | Estimation | Dépend de |
|---|---|---|---|---|---|
| 1 | **C1 — Règles d'alerte** sur les données déjà collectées | Surveillance et gestion des événements | Non | 5 j | — |
| 2 | **C2 — Cycle de vie des actifs** (achat, garantie, statut, étiquette QR) | Gestion des actifs informatiques | Non | 8 j | — |
| 3 | **CG — Connecteur GLPI** (lien, rapprochement, inventaire, actifs, tickets) | Gestion des actifs, gestion des incidents | Non | 9 j | C2 (G3), C4 (G4) |
| 4 | **C3 — Planification, fenêtres et anneaux** | Gestion des déploiements, habilitation des changements | Non (à confirmer, §3.4) | 11 j | — |
| 5 | **C4 — Signalement par l'utilisateur** | Gestion des incidents, centre de services | Non | 6 j | C2 (QR) |
| 6 | **C5 — Conformité des postes et mises à jour tierces** | Sécurité de l'information, gestion des déploiements | **Oui** | 9 j | C1 |
| 7 | **C6 — Licences logicielles** | Gestion des actifs logiciels | Non | 4 j | C1 (logiciels interdits) |
| 8 | **C7 — Second facteur et connexion par l'annuaire** | Sécurité de l'information | Non | 6 j | — |
| 9 | **C8 — Webhooks et jetons d'API** | Intégration | Non | 5 j | C1 |
| 10 | **C9 — Tendances, indicateurs et pannes récurrentes** | Mesure et rapports, gestion des problèmes | Non | 6 j | C1, C4 |
| 11 | **C10 — Approbation à deux des actions de masse** | Habilitation des changements | Non | 3 j | C3 |
| 12 | **C11 — Procédures et pièces jointes** | Gestion des connaissances | Non | 4 j | — |

Total : environ 76 jours. Les cinq premiers (39 j) forment le lot prioritaire ; le reste se prend à l'unité.

**Pourquoi C1 d'abord, alors que le cycle de vie des actifs est le manque le plus visible** : C1 n'ajoute aucune donnée à saisir et aucune collecte — tout est déjà en base — et il crée la table d'alertes que C2 (fin de garantie), C5 (contrôle non conforme), C6 (logiciel interdit) et C8 (événements à émettre) réutilisent.

**Pourquoi le connecteur GLPI juste après C2** : les actifs et les signalements doivent savoir dès leur conception qu'ils peuvent être tenus par GLPI (§2.1). Construire C2 seul puis y greffer GLPI obligerait à reprendre l'écran et l'import.

**C7 peut remonter** : si la console devient joignable depuis Internet (voir « interne » en §6), ou si C4 est ouvert au-delà du réseau de l'établissement, le second facteur passe avant C4.

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
| Seul ou avec GLPI | Chaque chantier dit ce qu'il devient quand GLPI est branché (§2.1). |

### 2.1 Seul ou avec GLPI

Tia'i doit rester **complet sans GLPI** : un établissement sans GLPI ne doit rien perdre. Et un établissement qui a déjà GLPI ne doit **rien saisir deux fois**. Les deux à la fois tiennent à une règle : pour chaque donnée, **une seule source de vérité**, choisie dans les réglages.

| Domaine | Tia'i seul | Tia'i avec GLPI |
|---|---|---|
| État technique : Defender, mises à jour, utilisation, alertes, commandes | Tia'i | **Tia'i** — GLPI n'en a pas l'équivalent |
| Inventaire matériel et logiciel | Tia'i | Tia'i le collecte et peut le **pousser** dans GLPI (G2), sauf si l'agent GLPI est déjà déployé |
| Achat, garantie, statut, numéro d'inventaire | Tia'i (C2) | **GLPI**, lu par Tia'i et affiché en lecture seule (G3) |
| Signalements et incidents | Tia'i (C4, vérifications) | **GLPI** : un signalement ou une alerte devient un ticket lié à l'ordinateur (G4) |
| Vérifications et maintenance | Tia'i | Tia'i — ce sont des tâches de technicien courtes, pas des tickets |
| Licences | Tia'i (C6) | GLPI ; C6 n'est pas activé |
| Pannes récurrentes, délais de traitement | Tia'i (C9) | GLPI pour les tickets, Tia'i pour les commandes et la maintenance |

Trois principes de conception :

- **C'est toujours Tia'i qui appelle GLPI**, jamais l'inverse : le même principe que l'agent qui interroge le serveur. GLPI peut donc être hébergé ailleurs (y compris en nuage) sans que le serveur Tia'i soit joignable depuis lui. Seul le navigateur de l'utilisateur suit les liens d'un outil à l'autre.
- **Les écritures vers GLPI passent par une file en base**, réessayée, comme les e-mails (`notification/outbox.py`) : GLPI indisponible ne bloque ni la console ni un battement d'agent.
- **Un seul interrupteur par domaine** (`ASSET_SOURCE=tiai|glpi`, `TICKET_TARGET=tiai|glpi`, `GLPI_INVENTORY_PUSH=off|on`), réglable dans la console. Le code de chaque chantier lit l'interrupteur au lieu de supposer GLPI absent.

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

**Avec GLPI** (`ASSET_SOURCE=glpi`) : la table `assets` reste, alimentée par G3 au lieu de la saisie ; seuls les matériels sans agent (B5) demeurent saisissables, et encore, seulement si GLPI ne les tient pas déjà.

**Console.** Onglet « Actif » sur la fiche d'un poste, filtres par statut et par fin de garantie sur la liste, colonnes ajoutées à l'export (`api/fields.py`), page « Matériels » au dernier jalon. La fin de garantie à N jours devient une règle de C1.

**Jalons.**

| Jalon | Contenu | Durée |
|---|---|---|
| B1 | Table, API, onglet de la fiche, filtres, export, fusion de postes. | 2,5 j |
| B2 | Import Excel/CSV avec aperçu. | 1,5 j |
| B3 | Jeton public, planche d'étiquettes QR. | 1 j |
| B4 | Indicateur Windows 11, âge par date d'achat, vue « à renouveler ». | 1 j |
| B5 | Matériels sans agent. | 2 j |

### 3.3 CG — Connecteur GLPI

**Constat.** Beaucoup d'établissements ont déjà GLPI pour les tickets et les actifs, souvent alimenté par l'agent GLPI. Tia'i à côté ferait double emploi sur l'inventaire et double saisie sur les actifs.

**Cadrage proposé.**

| Sujet | Proposition |
|---|---|
| Version de GLPI | La 10 et les suivantes. L'API « historique » (`apirest.php`, jetons d'application et d'utilisateur) existe encore ; les versions récentes ajoutent une API v2 authentifiée en OAuth2 (`/api.php/token`), avec une portée `inventory` accessible en *client credentials*. **À valider sur la version réellement déployée** avant de choisir : le connecteur doit en viser une seule au départ. |
| Rapprochement | Par **numéro de série** (`hw_serial`) puis **UUID SMBIOS** (`smbios_uuid`), que GLPI conserve aussi. Tia'i garde `glpi_computer_id` sur le poste. Un poste trouvé deux fois, ou pas du tout, est listé à part pour décision : jamais de rattachement deviné. |
| Liens croisés | De Tia'i vers GLPI : un bouton sur la fiche. De GLPI vers Tia'i : un « lien externe » GLPI configuré avec le numéro de série, qui ouvre une route Tia'i `/machines/by-serial/{serial}` (redirection, droits et portée inchangés). |
| Inventaire poussé | Tia'i convertit son inventaire au **format d'inventaire natif de GLPI** (celui de l'agent GLPI) et l'envoie au point d'entrée d'inventaire, seulement quand il a changé (`inventory_hash`). Désactivé par défaut, et **refusé** pour un poste que l'agent GLPI inventorie déjà : deux sources sur la même fiche se contrediraient à chaque passage. |
| Actifs lus | Numéro d'inventaire, statut, date d'achat, fin de garantie, fournisseur (fiche et informations financières GLPI), lus périodiquement par le worker. Avec `ASSET_SOURCE=glpi`, l'onglet « Actif » de C2 les affiche en lecture seule avec un lien « modifier dans GLPI », et l'import de C2 est masqué. |
| Tickets | Avec `TICKET_TARGET=glpi`, un signalement trié (C4) ou une alerte (C1, au choix par règle) crée un ticket GLPI lié à l'ordinateur. Tia'i garde le numéro, relit l'état et l'affiche sur la fiche ; la clôture se fait dans GLPI. |
| Identifiants | Compte de service GLPI à droits minimaux, secrets chiffrés en base (`core/secretbox.py`) comme ceux de l'envoi d'e-mails, bouton « Tester la connexion », jamais renvoyés à la console ni journalisés. Certificat de GLPI vérifié. |
| Droits | `settings:write` pour configurer. Aucun droit nouveau pour lire ce qui vient de GLPI : c'est une donnée du poste. |

**Jalons.**

| Jalon | Contenu | Durée |
|---|---|---|
| G1 | Réglages, test de connexion, rapprochement par série et UUID, liens croisés. | 1,5 j |
| G2 | Inventaire poussé au format natif, file réessayée, garde contre l'agent GLPI déjà présent. | 3 j |
| G3 | Lecture des actifs, onglet « Actif » en lecture seule (après C2). | 1,5 j |
| G4 | Tickets depuis les signalements et les alertes, relecture de l'état (après C4). | 3 j |

### 3.4 C3 — Planification, fenêtres et anneaux

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

### 3.5 C4 — Signalement par l'utilisateur

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

**Avec GLPI** (`TICKET_TARGET=glpi`) : le formulaire et la file de tri restent dans Tia'i — c'est lui qui connaît le poste derrière le QR — mais « transformer en ticket » crée un ticket GLPI (G4) au lieu d'une vérification. S1 reste utile dans les deux cas.

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

Une table `licenses` : logiciel (lié à une ou plusieurs entrées du catalogue `Software`), nombre de postes couverts, échéance, fournisseur, référence. **Jamais la clé elle-même.** La page Logiciels affiche « 32 installations pour 30 licences » ; le dépassement et l'échéance proche deviennent des règles de C1. La liste des logiciels interdits est celle de C1. **Avec GLPI**, qui gère les licences, ce chantier ne s'active pas.

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
- **Avec GLPI**, les indicateurs sur les tickets sont ceux de GLPI ; Tia'i garde ceux des commandes, de la maintenance et des vérifications.
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

1. ~~Outil de tickets existant ?~~ **Tranché le 2026-11-20** : Tia'i fonctionne seul ou avec GLPI (§2.1, chantier CG).
2. **Exposition de la console.** « Interne » veut dire que l'adresse de la console n'est joignable que depuis le réseau de l'établissement — son réseau local, ou un réseau qui y est relié par VPN —, même si le serveur est hébergé ailleurs. « Exposée » veut dire joignable depuis n'importe quelle connexion Internet. La documentation actuelle suppose la première (`plan-projet-tiai.md` §8). Si la console doit devenir joignable de l'extérieur, C7 passe avant C4.
3. **Version de GLPI visée** par le connecteur, et l'agent GLPI est-il déjà déployé sur les postes ? La seconde réponse décide si G2 sert.
4. **Actifs : table distincte ou colonnes sur `machines` ?** Le plan propose la table (§3.2). Les colonnes seraient plus rapides (−1 j) mais ferment la porte aux matériels sans agent.
5. **Droits sur les actifs.** Réutiliser `machine:write`, ou une ressource `asset` à part pour que le prix d'achat ne soit pas lisible de tous ?
6. **Poste réformé.** Faut-il révoquer son jeton d'agent en même temps, ou seulement le sortir des compteurs ?
7. **Chiffrement.** L'alerte « volume non chiffré » doit-elle viser tous les postes ou seulement les portables ?
8. **Fuseau de la console.** Un seul fuseau pour tout le serveur, ou un par emplacement ? Un seul suffit tant que le parc est en Polynésie.
9. **Enchaînements de C3.** « Réveiller, mettre à jour, éteindre » suffit-il, ou faut-il des séquences libres ? Le plan propose de s'en tenir aux deux options.
10. **Administrateurs locaux (C5).** Collecte à arbitrer avec le DPO, comme le nom de session.
11. **Périmètre de la prochaine version.** Le lot prioritaire entier (39 j), ou C1, C2 et G1 à G3 seulement (19 j) ?

---

## 7. Séquencement

- **C1 et C2 sont indépendants** et peuvent avancer en parallèle ; ils ne touchent pas les mêmes fichiers, sauf `machine/crud.py` (`merge_into`) et la fiche d'un poste.
- **CG se mène par morceaux** : G1 et G2 dès qu'on veut, G3 après B1, G4 après S3.
- **C3 se mène seul** : il modifie le chemin de création des commandes, que le déploiement de paquets emprunte aussi.
- **C4 attend B3** (jeton public et étiquettes).
- **C5 impose une version d'agent** : le grouper avec toute autre évolution de l'agent en attente (lecture de l'annuaire en mode relais, `plan-lecture-annuaire.md`) pour ne redéployer qu'une fois.
- À chaque chantier livré : feuille de route du `README.md`, notes de version, et une section « Écarts constatés à l'implémentation » dans son plan.
