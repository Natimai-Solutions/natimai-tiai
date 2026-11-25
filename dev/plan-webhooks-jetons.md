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
| Réessais | 8 tentatives, 1 min doublant jusqu'à 1 h (~ une journée) ; puis abandon noté ; historique purgé après 30 jours | Le modèle de l'outbox des e-mails. |
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

