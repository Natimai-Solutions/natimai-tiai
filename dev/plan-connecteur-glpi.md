# Connecteur GLPI : document de travail

> **⏸️ Reporté — 2026-11-20.** Décision du 2026-11-20 : Tia'i doit pouvoir fonctionner **seul ou avec GLPI**. Le chantier est mis de côté pour se concentrer sur les fonctionnalités propres à la console (`plan-evolutions-itil.md`) ; ce document garde le cadrage pour le jour où on le reprend.

> Tiré de `plan-evolutions-itil.md`, où il était le chantier CG. Les références C1, C2, C4, C6 et C9 renvoient aux chantiers de ce document, et B1, B5, S3 à leurs jalons. Estimation : environ 9 jours.

---

## 1. Principe : seul ou avec GLPI

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

## 2. Cadrage

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

---

## 3. Ce que GLPI change dans les autres chantiers

- **C2 — Cycle de vie des actifs.** **Avec GLPI** (`ASSET_SOURCE=glpi`) : la table `assets` reste, alimentée par G3 au lieu de la saisie ; seuls les matériels sans agent (B5) demeurent saisissables, et encore, seulement si GLPI ne les tient pas déjà.
- **C4 — Signalement par l'utilisateur.** **Avec GLPI** (`TICKET_TARGET=glpi`) : le formulaire et la file de tri restent dans Tia'i — c'est lui qui connaît le poste derrière le QR — mais « transformer en ticket » crée un ticket GLPI (G4) au lieu d'une vérification. S1 reste utile dans les deux cas.
- **C6 — Licences logicielles.** **Avec GLPI**, qui gère les licences, ce chantier ne s'active pas.
- **C9 — Tendances et indicateurs.** **Avec GLPI**, les indicateurs sur les tickets sont ceux de GLPI ; Tia'i garde ceux des commandes, de la maintenance et des vérifications.

En attendant le connecteur, C2 et C4 font passer la saisie des actifs et la création d'une vérification depuis un signalement chacune par une seule fonction : c'est elle que l'interrupteur redirigera, sans reprendre les écrans.

---

## 4. Séquencement

G1 et G2 peuvent se faire à tout moment. G3 attend le jalon B1 de C2, G4 attend le jalon S3 de C4.

---

## 5. Décisions et vérifications avant de reprendre

1. **Version de GLPI visée** par le connecteur, et l'agent GLPI est-il déjà déployé sur les postes ? La seconde réponse décide si G2 sert.
2. **API visée** : l'API historique ou l'API v2 en OAuth2, selon la version de GLPI retenue.
3. **Format d'inventaire** : le schéma et l'adresse du point d'entrée d'inventaire natif n'ont pas été vérifiés ; les relever sur l'instance (documentation Swagger servie par GLPI) ou dans la documentation de l'agent GLPI.
4. **Matériels sans agent** : tenus dans GLPI ou dans Tia'i quand les deux coexistent ?

Sources consultées le 2026-11-20 :
- [GLPI — RESTful API v2](https://help.glpi-project.org/documentation/modules/configuration/general/api/restful-api-v2)
- [GLPI — OAuth clients](https://help.glpi-project.org/documentation/modules/configuration/oauth-clients)
