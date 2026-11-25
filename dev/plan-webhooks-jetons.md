# C8 — Webhooks et jetons d'API : plan détaillé

> **📝 Document de travail — 2026-11-25. ✅ Livré le 2026-11-25.** Chantier C8 de `plan-evolutions-itil.md` (§4.4). Deux parties : les webhooks sortants (W1 à W3), puis les jetons d'API personnels (J1 à J2). Écarts constatés à l'implémentation en §8.

---

## 1. Ce que le chantier doit tenir

- **Même garantie que les e-mails** : un évènement est mis en file dans la transaction qui le produit (`webhook_deliveries`), et envoyé par le worker avec réessais. Une destination en panne retarde, ne perd pas, et ne ralentit jamais le battement d'un poste.
- **Le serveur ne devient pas un outil de rebond** : un webhook fait émettre au serveur des requêtes vers l'adresse qu'on lui donne. Les adresses du réseau interne, de la machine elle-même et des services de métadonnées sont refusées, sauf hôtes explicitement autorisés par l'exploitant ; aucune redirection n'est suivie.
- **Le destinataire peut vérifier** : chaque envoi est signé (HMAC-SHA256 d'un horodatage et du corps, secret propre au webhook, montré une fois).
- **Un jeton n'élargit rien** : il agit au nom de son compte, avec au plus ses droits et sa portée ; en lecture seule par défaut ; il expire ; il se révoque ; ses créations et révocations sont journalisées.

## 2. Webhooks

### 2.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Évènements | `threat.detected`, `alert.opened`, `alert.resolved`, `check.created`, `check.closed`, `command.failed`, plus `test` | La liste du plan. Fermée dans le code, comme les règles d'alerte. |
| Grain | Un envoi par fait métier : une remontée de menaces d'un poste (ses détections ensemble), une évaluation des alertes (les alertes ouvertes, ou résolues, ensemble, 100 au plus nommées), une vérification, une commande | Le premier passage des alertes sur un grand parc ne doit pas envoyer mille messages à un canal Teams. |
| Formats | `json` (corps structuré, signé), `teams`, `mattermost` (aussi compris par Slack) : un texte composé dans la langue du webhook | « Teams et Mattermost ne sont que deux formats de webhook. » |
| Réessais | 30 tentatives, 1 min doublant jusqu'à 1 h (~ une journée ; 8 au départ, qui ne donnaient que deux heures — cf. §8) ; puis abandon noté ; historique purgé après 30 jours | Le modèle de l'outbox des e-mails. |
| Signature | `X-Tiai-Signature: t=<horodatage>,v1=<hex HMAC-SHA256(secret, "<t>.<corps>")>`, plus `X-Tiai-Event`, `X-Tiai-Delivery` | La forme que les destinataires connaissent (Stripe, GitHub). L'horodatage borne le rejeu. |
| Secret | 32 octets aléatoires, chiffré au repos (`secretbox`), montré à la création et à la régénération seulement | Le destinataire doit le connaître ; personne d'autre. |
| Destination | `https://` seulement (`http://` toléré pour un hôte listé dans `WEBHOOK_ALLOWED_HOSTS`) ; adresse résolue refusée si privée, de bouclage, lien-local, multicast, réservée ou de métadonnées, sauf hôte listé ; vérifiée à l'enregistrement **et** à chaque envoi ; pas de redirection | Contrôle de la destination demandé par le plan. Un Mattermost interne se déclare explicitement. |
| Droits | Ressource `webhook` (lecture, écriture), administrateurs par défaut ; écrire demande un compte sans limite de lieux | Les évènements portent sur tout le parc. |
| Proxy | `WEBHOOK_PROXY_URL`, comme Mailgun et OIDC | Les réseaux d'établissement. |

### 2.2 Modèle (migration `0059_webhooks_api_tokens`)

- `webhooks` : `id`, `name`, `url`, `format`, `language`, `events` (liste), `secret` (chiffré), `enabled`, `created_by`, `created_at`, `updated_at`, `last_success_at`, `last_failure_at`, `last_error`, `consecutive_failures`.
- `webhook_deliveries` : `id`, `webhook_id` (cascade), `event`, `payload` (JSONB), `status` (`pending`, `sent`, `failed`), `attempts`, `next_attempt_at`, `last_error`, `response_status`, `created_at`, `sent_at`.

### 2.3 API

`GET/POST /webhooks`, `GET/PATCH/DELETE /webhooks/{id}`, `POST /webhooks/{id}/test`, `POST /webhooks/{id}/secret` (régénère), `GET /webhooks/{id}/deliveries` (les 50 dernières).

## 3. Jetons d'API personnels

| Sujet | Choix | Pourquoi |
|---|---|---|
| Forme | `tiai_pat_<43 caractères>` ; seul un hachage SHA-256 est gardé, avec les 12 premiers caractères pour le reconnaître | Montré une fois, comme un code de secours. |
| Usage | `Authorization: Bearer tiai_pat_…` sur l'API, comme un jeton d'accès | Un script n'a pas de navigateur ni de cookie. |
| Droits | Ceux du compte au moment de l'appel (groupes, portée), **lecture seule** par défaut : un jeton en lecture n'obtient que les droits `:read` du compte | « Limités à ses droits et à sa portée, en lecture seule par défaut. » |
| Hors de portée | Les routes du compte lui-même (mot de passe, sessions, second facteur, jetons, annuaire) : jamais par un jeton | Un jeton volé ne doit pas prendre le compte. |
| Durée | 1 à 365 jours, 90 par défaut ; pas de jeton sans fin | « À durée de vie bornée. » |
| Création | Droit `api_token:write` (administrateurs par défaut), et compte local ou de l'annuaire indifféremment | Tous les opérateurs n'ont pas besoin d'un accès par script. |
| Révocation | Par son titulaire ; tous ceux d'un compte à sa désactivation, à la réinitialisation de son mot de passe ou de son second facteur par un administrateur | Les gestes d'un compte compromis. |
| Trace | `api_token.create`, `api_token.revoke` au journal ; dernière utilisation (date, adresse) sur le jeton, notée au plus une fois par minute | « Journalisés. » |

Modèle : `api_tokens` : `id`, `user_id` (cascade), `name`, `token_hash` (unique), `prefix`, `can_write`, `expires_at`, `created_at`, `last_used_at`, `last_used_ip`, `revoked_at`.

API : `GET/POST /auth/api-tokens`, `DELETE /auth/api-tokens/{id}`.

## 4. Jalons

| Jalon | Contenu |
|---|---|
| W1 | Tables, file, worker d'envoi, signature, contrôle de destination, formats. |
| W2 | Émission des évènements aux six endroits, dans la transaction de l'appelant. |
| W3 | API et page de la console (Paramètres : carte « Webhooks »), essai, historique. |
| J1 | Jetons : table, authentification, lecture seule, routes du compte exclues, révocations. |
| J2 | Console : carte « Jetons d'API » de « Mon compte ». Docs. |

## 8. Écarts constatés à l'implémentation

- **Lire les webhooks demande aussi un compte sans limite de lieux** (le plan ne le demandait que pour écrire) : la liste montre les adresses et l'historique des envois, qui nomment des postes de tout le parc. Un compte limité voit dans Paramètres une phrase qui le dit, pas une erreur.
- **`GET /auth/me` répond à un jeton**, seule route du compte qui le fasse : un script doit pouvoir savoir au nom de qui, et avec quels droits, il agit. Toutes les autres routes `/auth/*` répondent `api_token.forbidden_here`, y compris la liste des jetons.
- **Lister et révoquer ses jetons ne demande pas `api_token:write`** : seule la création le demande. Un compte à qui l'on retire ce droit voit encore ses jetons dans « Mon compte » et peut les révoquer ; la carte n'apparaît pour lui que s'il en a.
- **Préfixe gardé : 13 caractères** (`tiai_pat_` et les quatre suivants), pas 12 : avec 12, il ne restait que trois caractères propres au jeton pour le reconnaître.
- **Un secret de webhook est scellé sous une clé dérivée de `SECRET_KEY`** (comme le secret client OIDC), pas sous `TOTP_ENCRYPTION_KEY` : changer `SECRET_KEY` le rend illisible ; l'envoi échoue alors avec « signing secret unreadable … renew it » jusqu'à « Nouveau secret ». Écrit dans DEPLOYMENT.md, à côté du changement de `SECRET_KEY`.
- **Le corps Teams est `{"text": …}`**, ce que lit le connecteur « Incoming Webhook » ; un flux Power Automate doit lire ce champ. Une carte adaptative n'a pas été faite : elle ne s'affiche pas dans Mattermost et la différence ne valait pas un quatrième format.
- **Clés du catalogue de la console** : les évènements y sont écrits `threat_detected`, pas `threat.detected` — vue-i18n lit un point comme un chemin, et la carte affichait le nom technique. Un test de la carte le tient.
- **Le refus d'une adresse dit pourquoi** : `webhook.destination_refused` porte `details.reason` (`webhook.url.internal`, `…scheme`, `…credentials`, `…host`, `…unresolved`), que la console ajoute au message.


### Relecture du 2026-11-25 (C8, et les corrections de C7)

Neuf relectures indépendantes (destinations des webhooks, file d'envoi, évènements, jetons, API et migration, corrections de C7, console, conformité à la documentation, couverture des tests), chaque constat soumis à deux vérificateurs chargés de le réfuter : quarante-six tiennent, trois sont partagés, trois réfutés. Tous les constats retenus sont corrigés, chacun avec son test (`tests/test_c8_review.py`, specs des deux cartes).

- **Contournements du contrôle des destinations.** (1) Le nom vérifié n'était pas le nom contacté : la vérification résolvait `straße` en `strasse` (IDNA 2003), le client HTTP contactait `xn--strae-oqa` (IDNA 2008) ; le nom est désormais lu une fois, comme le client l'envoie. (2) Le client résolvait le nom une seconde fois (*DNS rebinding*) : l'envoi se connecte maintenant à l'adresse vérifiée, le nom restant dans `Host` et dans la négociation TLS. (3) Formes IPv6 d'une adresse interne (NAT64, 6to4, Teredo, site-local) refusées. Le message de refus ne dit plus quelle adresse interne un nom porte.
- **Envoi borné.** La réponse n'est plus lue (un destinataire pouvait envoyer un corps sans fin) et un envoi dure au plus `WEBHOOK_TIMEOUT_SECONDS` en tout.
- **Réessais.** Huit tentatives donnaient deux heures, pas « environ une journée » : le défaut passe à 30.
- **File.** Un passage réserve ses envois (bail de dix minutes, validé) avant de les envoyer : deux workers ne peuvent plus envoyer deux fois le même. Il prend au plus dix envois par webhook et laisse le reste d'un webhook qui vient d'échouer : un destinataire en panne ne retient plus les autres. Un webhook désactivé abandonne ses envois sans compter d'échec contre le destinataire.
- **Évènements.** `threat.detected` suit le même filtre que l'e-mail (pas l'historique ancien de Defender au premier inventaire). Les vérifications ouvertes par les alertes font un seul envoi, comme les alertes. `check.created` porte le `check_id` de chaque vérification. `command.failed` part aussi pour une commande restée sans réponse ; pas pour une commande close par une fusion de postes ou le retrait d'un paquet, conséquences d'un geste d'opérateur, ni pour un réveil refusé sur-le-champ, que la console montre déjà à qui l'a demandé.
- **Jetons.** (1) Un jeton en écriture pouvait agir sur son propre compte par `/users/{son id}` (adresse, mot de passe, groupes) : refusé, quelle que soit l'écriture de l'identifiant. (2) Un jeton contournait l'obligation de double authentification d'un groupe : refusé tant qu'elle n'est pas activée. (3) Une session volée pouvait créer un jeton d'un an : la création demande le mot de passe (et un code si le compte a la double authentification), ou une connexion par l'annuaire de moins de dix minutes. (4) La limite de vingt jetons est comptée sous le verrou du compte. (5) La liste montre tous les jetons actifs, puis les cinquante derniers terminés : un jeton actif ne peut plus en disparaître.
- **API des webhooks.** `PATCH` refuse une liste d'évènements vide ; renommer un webhook en échec ne remet plus son compteur à zéro (seuls une autre adresse ou une réactivation le font) ; la limite de cinquante a son code (`webhook.too_many`) ; le journal ne garde que l'hôte, le chemin d'un webhook entrant étant son secret ; les champs du journal ont leurs libellés.
- **Console.** L'édition n'envoie que les champs modifiés ; la carte des jetons se charge dès l'enrôlement terminé ; pluriel anglais ; la grille des droits dit que les webhooks sont dans Paramètres (« Paramètres : consulter » nécessaire), comme les licences sur la page Logiciels.
- **Documentation de C7.** Le verrou du second facteur double à chaque série de codes faux, jusqu'à 24 heures : DEPLOYMENT.md disait une durée fixe. Renseigner `TOTP_ENCRYPTION_KEY` après coup ne rechiffre un secret qu'à sa prochaine utilisation : dit aussi.
- **Tests ajoutés.** Destinations (IDNA, formes IPv6, nom malformé, connexion à l'adresse vérifiée, refus au moment de l'envoi), destinataire lent, réservation, équité, webhook désactivé, secret illisible, `PATCH`, limite, journal, chaque point d'émission (heartbeat, verdict, commande sans réponse, vérification seule, groupée, signalement converti, vérifications des alertes), jetons (preuve à la création, annuaire, propre compte, double authentification exigée, révocations à la réinitialisation du second facteur et à la désactivation, limite, liste, dernière utilisation), obligation appliquée à l'ajout d'un groupe ; côté console, édition, essai, historique, secret, suppression, révocation, preuve, enrôlement.
- **Réfutés par les vérificateurs.** Les proxys de l'environnement (`HTTPS_PROXY`) appliqués aux envois (vrai avant l'épinglage ; c'est l'épinglage qui l'a rendu nuisible, cf. la contre-relecture ci-dessous) ; le secret gardé en mémoire après fermeture du dialogue ; un constat sur l'absence de tout test des émissions côté agent (des tests directs sont ajoutés quand même, cf. ci-dessus).

### Contre-relecture des corrections (2026-11-25)

Trois relecteurs sur les corrections ci-dessus, deux vérificateurs par constat : neuf tiennent, tous corrigés et testés.

- **Proxy de l'environnement.** L'envoi épinglé à une adresse partait quand même par le `HTTPS_PROXY` de Docker (cas documenté des établissements), avec l'adresse à la place du nom : le certificat ne correspondait plus et tout envoi échouait. Le proxy est désormais choisi une fois — `WEBHOOK_PROXY_URL`, sinon celui de l'environnement, `NO_PROXY` respecté — et un envoi par proxy nomme l'hôte sans épinglage ; le client ne lit plus l'environnement de lui-même.
- **Destinataire lent.** Les envois des webhooks en échec passaient encore en tête de chaque passage : ils passent désormais après ceux des webhooks qui répondent.
- **Adresses de repli.** Toutes les adresses du nom sont vérifiées et essayées tour à tour, comme le ferait un client à qui l'on donne le nom.
- **Hôtes autorisés** écrits en Unicode : comparés sous la même forme IDNA que l'adresse.
- **Délai global** : la résolution du nom est désormais comprise dans `WEBHOOK_TIMEOUT_SECONDS`, comme l'écrit la documentation.
- **Mot de passe à la création d'un jeton** (et à l'activation ou à la désactivation de la double authentification, et au rattachement à l'annuaire) : il n'avait pas de limite d'essais par session. Il a désormais le budget du changement de mot de passe : chaque échec compte pour le verrou du compte, et la session est fermée au cinquième échec ou au verrouillage du compte.
- **Texte des vérifications ouvertes par les alertes** : le motif de chaque poste est repris dans le message Teams ou Mattermost.
- **`command.failed`** : la documentation liste toutes les clôtures par le serveur qui ne l'émettent pas (paquet modifié après la mise en file, lecture de l'annuaire qui n'est plus permise).

