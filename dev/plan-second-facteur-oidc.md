# C7 — Second facteur et connexion par l'annuaire : plan détaillé

> **📝 Document de travail — 2026-11-25.** Chantier C7 de `plan-evolutions-itil.md` (§4.3). Deux parties livrées l'une après l'autre : le second facteur TOTP (S1 à S3), puis la connexion OpenID Connect, Entra ID d'abord (O1 à O3). Les écarts constatés à l'implémentation vont en §8 de ce document.

---

## 1. Ce que le chantier doit tenir

- **Sans fuite** : la réponse de connexion ne dit pas qu'un compte a un second facteur avant que le mot de passe soit bon ; un mot de passe faux, un compte inconnu, désactivé ou verrouillé répondent toujours le même 401, au même coût (un bcrypt).
- **Le mot de passe seul ne vaut rien** pour un compte à second facteur : ni session, ni remise à zéro des compteurs d'échecs, ni adresse marquée « connue » (qui exempte de la règle de siège) tant que le second facteur n'est pas passé.
- **Toujours un moyen d'entrer** : un compte local au moins, détenant `user:write`, reste actif ; la connexion par mot de passe marche quel que soit l'état du fournisseur d'identité.
- **Rien d'implicite** : imposer le second facteur, relier un groupe de l'annuaire à un groupe de Tia'i, sont des écritures journalisées, soumises à la règle « on ne donne que ce qu'on détient ».

## 2. Second facteur (TOTP)

### 2.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Algorithme | TOTP RFC 6238, SHA-1, 6 chiffres, pas de 30 s, fenêtre ±1 pas | Ce que toutes les applications (Microsoft Authenticator, Google Authenticator, FreeOTP, Aegis) lisent. Implémenté en une vingtaine de lignes (`core/totp.py`), testé sur les vecteurs de la RFC : pas de dépendance nouvelle. |
| Rejeu | Le dernier pas accepté est gardé (`totp_last_step`) ; un code d'un pas égal ou antérieur est refusé | Un code vu par-dessus l'épaule ne sert pas deux fois. |
| Secret au repos | Chiffré (Fernet, HKDF) sous une clé dérivée de `TOTP_ENCRYPTION_KEY`, à défaut de `SECRET_KEY`, avec son propre libellé | Une copie de la base ne suffit pas. La clé dédiée permet de changer `SECRET_KEY` (« déconnecter tout le monde ») sans effacer les seconds facteurs. |
| Codes de secours | 10 codes de 10 caractères (base32 sans ambiguïté), montrés une fois, stockés hachés (SHA-256), à usage unique | Un téléphone perdu ne ferme pas le compte ; hachés, ils survivent à un changement de clé. |
| Étape 2 | Un défi côté serveur (`login_challenges`) : jeton opaque de 256 bits, haché en base, valable 5 minutes, 5 essais, à usage unique | Usage unique et budget d'essais sans état en mémoire ; rien de ce jeton n'ouvre l'API. |
| Force brute | 5 codes faux de suite, sur n'importe quels défis, verrouillent le second facteur du compte 15 minutes (journalisé) ; plus une limite par adresse | 6 chiffres = 10⁶ : sans verrou par compte, un défi neuf par mot de passe rejoué suffirait. |
| Obligation | Case « Second facteur obligatoire » par groupe ; un compte y est soumis si l'un de ses groupes l'est | Ce que le plan demande (« obligation réglable par groupe »). |
| Compte soumis sans second facteur | Le mot de passe ouvre une session **d'enrôlement** : l'API ne lui répond que pour « Mon compte » (profil, enrôlement, déconnexion) ; la console l'y conduit | Plus strict qu'un bandeau : rien du parc n'est lisible avant l'enrôlement. |
| Désactiver | Mot de passe actuel + code ; refusé si un groupe l'impose | Le même contrôle que le changement de mot de passe. |
| Perte totale | Un administrateur réinitialise le second facteur d'un compte (journalisé, sessions révoquées) | Le recours sans console de secours. |
| Compte de secours | Le premier administrateur créé par `FIRST_ADMIN_EMAIL` n'est jamais soumis d'office ; DEPLOYMENT.md recommande de le garder hors des groupes à obligation, ou d'imprimer ses codes de secours | Ne pas s'enfermer dehors. |

### 2.2 Modèle (migration `0057_second_factor`)

- `users` : `totp_secret` (chiffré), `totp_enabled_at`, `totp_last_step`, `totp_failed_attempts`, `totp_locked_until`.
- `user_backup_codes` : `id`, `user_id` (cascade), `code_hash`, `used_at`, `created_at`.
- `login_challenges` : `id`, `user_id` (cascade), `token_hash` (unique), `ip`, `attempts`, `expires_at`, `used_at`, `created_at` ; purgé avec les sessions expirées.
- `groups.mfa_required` (booléen, faux par défaut).
- `auth_sessions.auth_method` (`password`, `password+totp`, `oidc`) et `auth_sessions.enrolment_only` (booléen).

### 2.3 API

| Route | Effet |
|---|---|
| `POST /auth/login` | Inchangé pour un compte sans second facteur (`{access_token, token_type}` + cookie). Avec un second facteur : `{second_factor_required: true, challenge, expires_in}`, ni cookie ni session. |
| `POST /auth/login/second-factor` | `{challenge, code}` (6 chiffres ou code de secours) → la session, comme une connexion. 401 `auth.second_factor.invalid` (code faux, défi expiré, épuisé ou déjà servi, verrou : même réponse). |
| `POST /auth/totp/setup` | Secret neuf en attente → `{secret, otpauth_uri}`. |
| `POST /auth/totp/confirm` | `{code}` → active, rend les 10 codes de secours ; une session d'enrôlement devient une session pleine. |
| `POST /auth/totp/disable` | `{current_password, code}` ; 409 `auth.second_factor.required_by_group`. |
| `POST /auth/totp/backup-codes` | `{code}` → 10 codes neufs, les anciens annulés. |
| `POST /users/{id}/reset-second-factor` | Administrateur : efface secret et codes, révoque les sessions. |
| `GET /auth/me` | + `totp_enabled`, `second_factor_required`, `backup_codes_left`, `enrolment_only`. |
| Groupes | + `mfa_required` (lecture, création, modification). |

### 2.4 Jalons

| Jalon | Contenu |
|---|---|
| S1 | `core/totp.py`, migration, défi, étape 2, compteurs déplacés après le second facteur, verrou, tests (dont les vecteurs RFC et l'absence de fuite). |
| S2 | Enrôlement, codes de secours, désactivation, obligation par groupe, session d'enrôlement, réinitialisation par un administrateur. |
| S3 | Console : étape du code à la connexion, carte « Double authentification » de « Mon compte » (QR), case des groupes, badge et réinitialisation dans Comptes. Docs. |

## 3. OpenID Connect (Entra ID d'abord)

### 3.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Protocole | Code d'autorisation + PKCE (S256), `state` et `nonce` à usage unique gardés côté serveur, retour en `response_mode=query` | Le flux recommandé ; rien du jeton ne passe par le navigateur. |
| Fournisseur | Générique par découverte (`/.well-known/openid-configuration`) ; Entra ID documenté et testé en premier | Un autre fournisseur (Google Workspace, Keycloak) ne demande que d'autres valeurs. |
| Configuration | Variables d'environnement (`OIDC_*`), lues au démarrage ; la page Paramètres montre l'état, sans le secret | C'est une configuration de déploiement, comme `ROOM_SOURCE` ou `DIRECTORY_VERIFY` ; le secret client reste dans `deploy/.env`. |
| Validation du jeton | Signature RS256 par les clés publiées (JWKS, en cache), `iss` égal à l'émetteur configuré (pas de locataire `common`), `aud` = l'identifiant client, `exp`/`iat`/`nbf` (60 s de tolérance), `nonce` | Les vérifications de la norme, sans raccourci. |
| Identité d'un compte | Le couple (émetteur, `sub`) ; l'adresse e-mail n'est qu'un libellé | Une adresse se change dans l'annuaire ; `sub` non. |
| Création des comptes | À la première connexion, si le jeton porte au moins un groupe de l'annuaire relié à un groupe de Tia'i ; sinon refus (`auth.oidc.no_group`) | Pas de compte sans droits, et pas de liste d'invitations à tenir. |
| Compte local existant de même adresse | Jamais rattaché d'office : refus (`auth.oidc.email_taken`) ; son titulaire le rattache depuis « Mon compte » (« Associer mon compte Microsoft »), connecté par mot de passe | Une adresse identique ne prouve pas qu'il s'agit de la même personne. |
| Groupes | Liaison par groupe de Tia'i : identifiants (GUID) des groupes de l'annuaire. À chaque connexion, les groupes reliés sont recalculés ; les groupes non reliés, donnés à la main, ne bougent pas | Le droit suit l'annuaire, sans effacer une exception posée dans la console. |
| Trop de groupes | Jeton sans la liste (dépassement Entra) : refus `auth.oidc.too_many_groups`, et DEPLOYMENT.md dit de restreindre les groupes émis à ceux de l'application | Pas d'appel à Microsoft Graph : une permission de plus, et un serveur qui sort davantage. |
| Second facteur | Pas de TOTP pour un compte de l'annuaire : l'établissement l'impose chez Entra (accès conditionnel). Une session OIDC satisfait l'obligation d'un groupe | Le plan : « OIDC apporte le second facteur de l'établissement sans le réécrire ». |
| Compte de l'annuaire | Ni mot de passe, ni réinitialisation, ni changement d'adresse dans la console | Ce compte vit dans l'annuaire. |
| Secours | Au moins un compte local actif détenant `user:write` est gardé : le désactiver, lui retirer ce droit ou le supprimer est refusé (`user.last_local_admin`) | Le fournisseur injoignable ne ferme pas la console. |
| Réseau | Le serveur doit joindre `login.microsoftonline.com` en HTTPS (proxy possible : `OIDC_PROXY_URL`) | La décision 2 du plan (§6) reste ouverte ; OIDC est désactivé par défaut. |

### 3.2 Modèle (migration `0058_oidc`)

- `users` : `auth_source` (`local`, `oidc`), `oidc_issuer`, `oidc_subject` (unique ensemble).
- `oidc_logins` : `id`, `state_hash` (unique), `nonce`, `code_verifier`, `redirect`, `link_user_id`, `expires_at`, `used_at`, `created_at` (10 minutes).
- `group_idp_links` : `group_id`, `idp_group_id` (clé composée).

### 3.3 API

| Route | Effet |
|---|---|
| `GET /auth/oidc/start?redirect=` | 302 vers le fournisseur. |
| `GET /auth/oidc/callback` | Vérifie, crée ou retrouve le compte, recalcule les groupes, ouvre la session (cookie), 302 vers la console ; une erreur → `/login?sso_error=<code>`. |
| `POST /auth/oidc/link` | Connecté par mot de passe : rend l'adresse du fournisseur pour rattacher ce compte. |
| `GET /auth/methods` | `{oidc_enabled, oidc_label}` pour la page de connexion. |
| Groupes | + `idp_groups` (liste de GUID, 50 au plus). |

### 3.4 Jalons

| Jalon | Contenu |
|---|---|
| O1 | Découverte, JWKS, validation, défi `state`/`nonce`/PKCE, rappel, création et liaison, synchronisation des groupes ; tests contre un fournisseur simulé (clés RSA générées). |
| O2 | Console : bouton de connexion, erreurs, rattachement depuis « Mon compte », liaison des groupes, comptes de l'annuaire dans Comptes. |
| O3 | Garde du dernier compte local, docs (Entra : inscription d'application, URI de redirection, groupes émis), Paramètres. |

## 4. Hors périmètre

- Clés matérielles (WebAuthn) : un autre chantier.
- SAML, LDAP direct pour la connexion (`plan-lecture-annuaire.md` le permettrait, OIDC suffit).
- Synchronisation des comptes en tâche de fond (désactiver un compte parti de l'annuaire sans qu'il se connecte) : la session d'un compte de l'annuaire vit au plus `REFRESH_TOKEN_EXPIRE_DAYS` ; un administrateur désactive à la main.

## 8. Écarts constatés à l'implémentation

### Second facteur

- **Mot de passe seul** : `crud.authenticate(..., finish=False)` vérifie le mot de passe sans ses effets de succès ; `note_login_success` (compteur à zéro, adresse « habituelle ») n'est appelé qu'une fois toute la connexion réussie. Les refus coûtent toujours un bcrypt.
- **Un seul refus pour l'étape du code** : code faux, rejoué, défi expiré, épuisé, déjà servi, second facteur verrouillé répondent tous `auth.second_factor.invalid` (401) ; un code à 6 chiffres ou un code de secours, reconnus à leur forme.
- **Limites** : 10 essais par adresse en 5 minutes pour l'étape du code ; 10 par session en 15 minutes pour l'activation et les codes de « Mon compte ». Désactiver demande le mot de passe actuel, dont un essai faux compte dans le verrou du mot de passe comme sur « changer mon mot de passe ».
- **Session d'enrôlement** : l'API ne lui répond que pour `/auth/me`, `/auth/totp/setup`, `/auth/totp/confirm`, `/auth/sessions` et `/auth/logout` (403 `auth.second_factor.not_enrolled` sinon) ; la console la garde sur « Mon compte », avec un bandeau. La confirmation en fait une session pleine.
- **Journal** : `user.second_factor_enabled`, `user.second_factor_disabled`, `user.backup_codes_regenerated`, `user.second_factor_locked`, `user.second_factor_reset` (par un administrateur, jamais sur son propre compte), `auth.backup_code_used` (avec le nombre de codes restants).
- **Clé** : `TOTP_ENCRYPTION_KEY`, à défaut dérivée de `SECRET_KEY` sous un libellé propre ; un secret illisible (clé changée) laisse les codes de secours.

### Connexion par l'annuaire

- **Configuration par l'environnement seulement** (`OIDC_*`), comme prévu ; la page Paramètres n'en montre rien pour l'instant — la page de connexion lit `GET /auth/methods`. À ajouter au catalogue « Environnement » de Paramètres si le besoin s'en fait sentir.
- **Liaison au navigateur** : en plus du `state`, un cookie `tiai_oidc` (`HttpOnly`, `SameSite=Lax`, chemin `/api/v1/auth/oidc`, 10 minutes) dont l'empreinte est gardée avec la tentative : un lien de retour ouvert dans un autre navigateur n'ouvre rien.
- **Compte local associé** : garde son mot de passe, ses groupes (jamais recalculés par l'annuaire) et sa double authentification de la console, qui n'est pas demandée quand il se connecte par l'annuaire. `DELETE /auth/oidc/link` le dissocie (`user.directory_unlinked`).
- **Plus de groupe relié** : la connexion est refusée et les groupes reliés retirés au compte (`user.groups_synced`) ; ses sessions ouvertes vivent jusqu'à leur échéance (§4).
- **Dernier compte local** : le code d'erreur reste `user.lockout` (le même refus qu'avant, compté désormais sur les seuls comptes locaux), plutôt qu'un code `user.last_local_admin` de plus.
- **Compte de l'annuaire** : ni réinitialisation de mot de passe, ni lien « mot de passe oublié » (rien n'est envoyé), ni changement d'adresse, ni double authentification de la console (409 `user.external_account`).
- **Limite** : 60 démarrages ou retours par adresse en 5 minutes (un établissement derrière une seule adresse), au lieu de celle de la connexion par mot de passe.
- **Codes de retour** (`/login?sso_error=…`) : `auth.oidc.disabled`, `unavailable`, `invalid`, `denied`, `no_group`, `email_taken`, `too_many_groups`, `no_email`, `account_disabled`, `already_linked`, tous mis en mots par la console.
- **Journal** : `user.directory_provisioned`, `user.directory_linked`, `user.directory_unlinked`, `user.groups_synced` (acteur `oidc:<adresse>`).
