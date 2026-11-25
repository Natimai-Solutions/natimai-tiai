# C11 — Procédures et pièces jointes : plan détaillé

> **📝 Document de travail — 2026-11-25.** Chantier C11 de `plan-evolutions-itil.md` (§4.7). Deux parties indépendantes : les pièces jointes d'une intervention (PJ1 à PJ4), puis les notes de procédure par modèle de poste (PR1 à PR2). Migration `0062_attachments_procedures` (après `0061_mass_approval`). Agent non modifié. Écarts constatés à l'implémentation en §8.

---

## 1. Ce que le chantier doit tenir

- **Une pièce jointe est une donnée de l'intervention** : elle se voit, se télécharge et se supprime exactement là où l'intervention se voit et se modifie (`intervention:read`, `intervention:write`, portée du poste par `machine_visible`). Un poste hors de portée répond « introuvable », pièce jointe comprise.
- **Le serveur ne sert jamais un fichier qu'un navigateur interpréterait** : types fermés reconnus **au contenu** (images JPEG, PNG, WebP et PDF ; SVG, HTML et tout le reste refusés), type déclaré par le client ignoré, téléchargement toujours en `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, CSP `sandbox`.
- **Le stockage est borné** : taille par fichier, nombre par intervention, quota total ; les fichiers que plus rien ne nomme partent (ménage du dépôt, sur le modèle de `package/crud.py:sweep_store`, verrou consultatif compris).
- **Une photo de panne n'est pas reconstructible** : contrairement aux installateurs des paquets, les pièces jointes entrent dans la sauvegarde quotidienne.
- **Une note de procédure s'attache au modèle, pas au poste** : écrite une fois pour `hw_model` (inventaire, `machines.hw_model`), elle s'affiche sur la fiche de chaque poste de ce modèle. Texte brut, droit à part (`procedure`), chaque écriture au journal d'audit avec le texte remplacé.
- Rien de neuf côté agent, rien de neuf dans le catalogue de commandes.

## 2. Pièces jointes

### 2.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Rattachement | À une ligne du journal (`interventions.id`), quelle que soit sa nature : saisie à la main, ligne d'une maintenance (`maintenance/crud.py:add_lines`), clôture d'une vérification (`routes/checks.py`, `Intervention(kind=verification, check_id=…)`) | Le plan dit « sur une intervention ». Toute ligne existe dans `interventions` : une seule table à rattacher, et la fusion de postes (`machine/crud.py:merge_into` → `intervention_crud.move_to`) emporte les pièces jointes sans code de plus. |
| Moment de l'ajout | Sur une ligne **existante** : dialogue de modification, ou juste après la création dans le même dialogue (la console crée la ligne, puis envoie les fichiers un par un) | Une pièce jointe sans ligne n'aurait ni portée ni auteur. Pas de dépôt « en attente » à purger. |
| Stockage | Un fichier par SHA-256 sous `ATTACHMENTS_DIR` (défaut `/data/attachments`), volume Docker `attachments` distinct de `packages` ; écriture en temporaire puis renommage, comme `package/storage.py:save` | Le modèle demandé par la feuille de route. Volume à part : les paquets sont reconstructibles et hors sauvegarde, les pièces jointes non (§2.6). Deux lignes qui joignent la même photo partagent le fichier. |
| Code du dépôt | Les fonctions génériques de `package/storage.py` (`save`, `stored_shas`, `remove_unreferenced`, `remove_stale_uploads`, `path_for`, `exists`) prennent le dossier en paramètre et vont dans `app/core/blobstore.py` ; `package/storage.py` garde ses noms en enveloppes sur `PACKAGES_DIR` (aucun appelant des paquets ne change) ; `features/attachment/storage.py` fait de même sur `ATTACHMENTS_DIR` | Un seul code d'écriture atomique et de ménage des `.upload-*`, déjà relu (audits S09, T09). |
| Types acceptés | Reconnus sur les 16 premiers octets, avant tout écriture définitive : JPEG (`FF D8 FF`), PNG (`89 50 4E 47 0D 0A 1A 0A`), WebP (`RIFF????WEBP`), PDF (`%PDF-`). Le `Content-Type` stocké et servi est celui reconnu, jamais celui du client ni de l'extension | « Renifler le contenu, pas l'extension. » Quatre signatures écrites à la main : pas de dépendance (`pyproject.toml` n'a ni Pillow ni libmagic). SVG, HTML, GIF, HEIC, Office : refusés (415). |
| Nom du fichier | Celui envoyé, nettoyé : chemin retiré (`PurePosixPath`/`PureWindowsPath(...).name`), caractères de contrôle retirés, 200 caractères au plus, vide → `piece-jointe` ; extension corrigée si elle ne dit pas le type reconnu (`panne.html` reconnu PNG → `panne.html.png`) | Un fichier enregistré sur le disque de l'opérateur ne doit pas s'ouvrir comme autre chose que ce qu'il est. |
| Taille | `ATTACHMENT_MAX_BYTES`, défaut 5 Mio, de 64 Kio à 7 Mio | Caddy plafonne toute requête hors dépôt de paquet à `max_size 8MB` (`deploy/Caddyfile`, bloc `@not_package_upload`) : 7 Mio laissent la marge des en-têtes multipart, et aucun bloc Caddy de plus n'est à maintenir. |
| Réduction des photos | **Dans la console**, avant l'envoi : une image JPEG/PNG/WebP de plus de 2 560 px de côté ou plus lourde que la limite est redessinée (`createImageBitmap(file, { imageOrientation: 'from-image' })` puis `canvas.toBlob('image/jpeg', 0.85)`), ce qui retire aussi les métadonnées EXIF (position GPS d'un téléphone). Le serveur ne modifie jamais un fichier reçu | Une photo de téléphone pèse 3 à 12 Mo. Le serveur reste sans bibliothèque d'images et le fichier stocké reste celui de son empreinte. |
| Miniatures | **Non**. La console affiche un aperçu à la demande (§5) | Générer des miniatures demanderait une bibliothèque d'images au serveur et un second fichier par photo. Une ligne porte rarement plus de deux ou trois photos. |
| Nombre par ligne | 10 au plus (`MAX_PER_INTERVENTION`, constante) ; 409 `attachment.too_many` | Une intervention n'est pas un album. |
| Quota | `ATTACHMENT_QUOTA_BYTES`, défaut 2 Gio, 0 = pas de quota : somme des tailles des fichiers **distincts** nommés par `intervention_attachments`. Vérifié après réception, sous `pg_advisory_xact_lock` d'une clé fixe (deux dépôts simultanés ne passent pas tous deux sous la limite) ; refus 413 `attachment.quota_exceeded`, et le fichier écrit pour rien est supprimé aussitôt s'il n'est nommé par personne (`discard_if_orphan`, §2.4) | Un disque plein arrête la base sur la même machine. |
| Droits | Ceux de l'intervention : lire et télécharger `intervention:read`, ajouter et supprimer `intervention:write` (comme modifier une ligne : `routes/interventions.py` n'exige pas d'être l'auteur) | Pas de ressource de plus : une pièce jointe n'apprend rien de plus que la note de la ligne. |
| Portée | Toute route passe par la ligne (`_require_intervention`, qui appelle `machine_visible`) ; hors portée → 404 `attachment.not_found` / `intervention.not_found` | Invariant de portée. |
| Téléchargement | `FileResponse` avec `media_type` reconnu, `Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<pourcent>`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, `Cache-Control: private, no-store` | Ouvrir le fichier dans l'origine de la console ne doit rien pouvoir exécuter. `nosniff` est déjà posé par Caddy, mais l'API le pose elle-même (le port de développement 8800 n'a pas Caddy devant). |
| Fichier absent du disque | 404 `attachment.file_missing` (la ligne reste, la console dit « fichier absent du serveur ») | Cas d'une base restaurée sans ses fichiers (§2.6). |
| Journal | `intervention.attachment_add`, `intervention.attachment_delete` (ressource `intervention`, identifiant de la ligne ; détails : `machine_id`, `attachment_id`, `filename`, `size`, `sha256`, `content_type`) ; `intervention.delete` gagne `attachments` (nombre emporté) | « `audit.record` pour toute écriture. » La création d'une ligne elle-même n'est pas journalisée aujourd'hui (son auteur est sur la ligne) : inchangé. |
| Webhooks, résumé, alertes | Rien | Une pièce jointe n'est pas un évènement du parc. |

### 2.2 Modèle (migration `0062_attachments_procedures`)

`intervention_attachments` (`features/attachment/models.py`, classe `InterventionAttachment`) :

| Colonne | Type | Note |
|---|---|---|
| `id` | UUID, clé | |
| `intervention_id` | UUID, `ForeignKey("interventions.id", ondelete="CASCADE")`, NOT NULL | Supprimer la ligne supprime ses pièces jointes ; le fichier part au ménage suivant. |
| `sha256` | `String(64)`, NOT NULL | Nom du fichier dans `ATTACHMENTS_DIR`. |
| `size` | `BigInteger`, NOT NULL | |
| `content_type` | `String(40)`, NOT NULL | `image/jpeg`, `image/png`, `image/webp`, `application/pdf`. |
| `filename` | `String(200)`, NOT NULL | Nom nettoyé (§2.1). |
| `uploaded_by` | `String(255)`, NOT NULL | Courriel, convention de `interventions.performed_by` : survit au compte. |
| `created_at` | `timestamptz`, NOT NULL, `utc_field(default_factory=utcnow)` | |

Index : `ix_intervention_attachments_intervention` (`intervention_id`, `created_at`) — la lecture d'une page du journal ; `ix_intervention_attachments_sha256` (`sha256`) — le ménage et le quota. Pas de JSONB, pas de booléen.

### 2.3 API

Nouveau fichier `api/routes/attachments.py`, deux routeurs enregistrés dans `api/__init__.py` à côté de `interventions_router` :

| Route | Droit | Effet |
|---|---|---|
| `GET /attachments/policy` | `intervention:read` | `{max_bytes, max_per_intervention, types: ["image/jpeg", …], quota_bytes, used_bytes}` ; `used_bytes` est `null` pour un compte limité à des lieux (agrégat de tout le parc). La console ne recopie aucune limite. |
| `POST /interventions/{id}/attachments` | `intervention:write` | Multipart, **un** fichier (`file`) par requête, comme le dépôt des paquets. 201 → `AttachmentOut`. |
| `GET /attachments/{id}/content` | `intervention:read` | Le fichier (§2.1, Téléchargement). |
| `DELETE /attachments/{id}` | `intervention:write` | 204 ; journal ; après `commit`, `attachment_crud.sweep_store(session)`. |

`AttachmentOut` : `id`, `intervention_id`, `filename`, `content_type`, `size`, `uploaded_by`, `created_at`. `routes/interventions.py:InterventionOut` gagne `attachments: list[AttachmentOut] = []`, rempli pour toute la page en **une** requête (`attachment_crud.of_interventions(session, ids)`), dans `list_interventions`, et à vide dans les réponses de création et de modification (la console relit la page).

Déroulé de `POST` : `_require_intervention` (portée) → nombre de pièces jointes de la ligne < 10 sinon 409 → `storage.save(upload, ATTACHMENT_MAX_BYTES, hold=lambda sha: crud.hold_file(session, sha), sniff=…)` qui lit le premier bloc, refuse (415) avant d'écrire si le type n'est pas reconnu, puis écrit et tient le fichier → verrou du quota, contrôle du quota → insertion, `audit.record`, `commit`. En cas de refus après écriture : `rollback`, puis `discard_if_orphan(session, sha)`.

Codes d'erreur (`core/errors.py`, texte FR+EN dans `frontend/src/i18n/messages/errorCodes.ts`) :

| Code | Statut | Quand |
|---|---|---|
| `attachment.not_found` | 404 | Inconnue, ou sa ligne hors de portée. |
| `attachment.file_missing` | 404 | Ligne en base, fichier absent du disque. |
| `attachment.too_large` | 413 | `details.max_bytes`. |
| `attachment.type_refused` | 415 | `details.types` (les quatre acceptés). |
| `attachment.too_many` | 409 | `details.max` (10). |
| `attachment.quota_exceeded` | 413 | `details.quota_bytes`. |

### 2.4 Ménage du dépôt

`features/attachment/crud.py`, calqué sur `package/crud.py` :

- `hold_file(session, sha)` / `_claim_file(session, sha)` : les mêmes verrous consultatifs à deux clés, dans un **autre espace** (`_FILE_LOCK_SPACE = 0x54415454`, « TATT » ; celui des paquets est « TPKF »).
- `sha_in_use(session, sha)` : une ligne de `intervention_attachments` le nomme.
- `sweep_store(session)` : comme celui des paquets (réservé, verrou pris sans attendre, question reposée sous le verrou, `commit` après chaque fichier, jamais d'exception). Garde contre une mauvaise base : rien n'est supprimé quand la table `machines` est vide alors que le dépôt contient des fichiers (une base neuve ou vidée, pas des orphelins). Puis `storage.remove_stale_uploads()`.
- `discard_if_orphan(session, sha)` : le même traitement pour un seul fichier, après un dépôt refusé.
- Appelé : après `DELETE /attachments/{id}`, après `DELETE /interventions/{id}` quand la ligne en portait, au démarrage et toutes les heures dans le processus de l'API (`main.py`, à côté de `package_crud.sweep_periodically` : une seconde tâche `attachment_crud.sweep_periodically`). **Pas dans le worker** : seul le conteneur `backend` monte le volume, comme pour les paquets (`deploy/docker-compose.yml`).

Rétention : aucune purge par l'âge. Une pièce jointe vit autant que sa ligne (le journal n'est jamais purgé) ; la croissance est bornée par le quota et les fichiers sans ligne partent au ménage.

### 2.5 Image et volumes

- `backend/Dockerfile` : `mkdir -p /data/packages /data/attachments && chown tiai:tiai …`.
- `app/scripts/entrypoint.sh` : la boucle de `chown -R` sur `PACKAGES_DIR` s'étend à `ATTACHMENTS_DIR` (même condition : propriétaire différent de `tiai`).
- `deploy/docker-compose.yml` : volume nommé `attachments`, monté `attachments:/data/attachments` sur `backend`, et **en lecture seule** `attachments:/attachments:ro` sur `db-backup` (§2.6). Rien sur `worker`.
- `features/setting/environment.py` : groupe `attachments` (« Pièces jointes ») : `ATTACHMENTS_DIR`, `ATTACHMENT_MAX_BYTES` (`fmt="bytes"`), `ATTACHMENT_QUOTA_BYTES` (`fmt="bytes"`) ; libellés anglais dans `i18n/messages/settingsEnv.ts`.

### 2.6 Sauvegarde

Constat : `deploy/backup/backup.sh` ne fait qu'un `pg_dump` ; DEPLOYMENT.md (« Déploiement logiciel ») dit que le volume `packages` n'est pas dans le dump et se reconstruit depuis les installateurs. Une photo de panne ne se reconstruit pas.

| Sujet | Choix | Pourquoi |
|---|---|---|
| Où | `deploy/backups/attachments/`, à côté des dumps : copié hors de la machine par le même moyen | L'exploitant n'a qu'un dossier à copier. |
| Comment | `backup.sh`, **après un dump réussi** : pour chaque fichier de `/attachments` dont le nom est 64 caractères hexadécimaux, copie vers `attachments/<sha>` (ou `<sha>.age`, chiffré pour `BACKUP_ENCRYPT_RECIPIENT` comme les dumps) s'il n'y est pas — écrit en `.tmp` puis renommé ; s'il y est, `touch` | Fichiers immuables nommés par leur empreinte : la copie est incrémentale sans outil de plus. |
| Rétention | Un fichier de la copie que le volume ne contient plus n'est plus touché ; il est supprimé quand sa date dépasse `BACKUP_KEEP_DAYS` | Un dump de 14 jours retrouve ses photos ; rien ne grossit sans fin. |
| Volume absent | `/attachments` non monté (compose d'avant C11) : une ligne au journal, dump inchangé, code 0 | Une mise à jour sans le nouveau compose ne casse pas la sauvegarde. |
| Échec de copie | Journal, code 1 après le dump, pas de purge de la copie | Même règle que la purge des dumps. |

DEPLOYMENT.md, « Sauvegardes et restauration » : la liste des choses à copier hors de la machine gagne `deploy/backups/attachments/` ; « Restaurer » gagne la remise des fichiers dans le volume (`docker run --rm -v <projet>_attachments:/data -v "$PWD/backups/attachments:/restore:ro" <image backend> sh -c 'cp -n /restore/* /data/'`, variante `age -d` par fichier pour la copie chiffrée), avant de relancer `backend` (dont l'entrypoint rend les fichiers au compte `tiai`). Restaurer la base sans les fichiers laisse des lignes en `attachment.file_missing`, rien de plus.

## 3. Notes de procédure par modèle

### 3.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Clé | `machines.hw_model` tel que l'inventaire l'écrit (`inventory/crud.py` : `machine.hw_model = report.hw_model`), comparé exactement, espaces de bord retirés | La feuille de route dit « par modèle (`hw_model`) ». Le fabricant n'entre pas dans la clé : deux fabricants n'emploient pas le même nom de modèle dans un parc d'établissement. |
| Format | **Texte brut**, 5 000 caractères (la borne de `interventions.note`), affiché avec `white-space: pre-line` comme les notes du journal (`MachineHistoryCard.vue`) ; pas de Markdown, pas de lien rendu cliquable | La console n'a aucun `v-html` ni moteur Markdown (`services/assets.ts` le revendique) ; en ajouter un pour une note de trois lignes ouvrirait une injection à garder. |
| Une ou plusieurs | **Une** note par modèle | « Sur ce modèle, le BIOS s'ouvre par F10 » : un texte. Plusieurs notes demanderaient titres, ordre et liste. |
| Droit | Ressource **`procedure`** (`read`, `write`) dans `PERMISSION_CATALOGUE` ; `procedure:read` dans `_SUPERVISION_READ` (lecture seule et techniciens), `procedure:write` aux techniciens | Une note de procédure est du savoir de terrain, écrit par ceux qui réparent. Ressource à part, pas `intervention:write` : on peut vouloir qu'un compte complète le journal sans réécrire la procédure de tout un modèle. |
| Comptes existants | La migration accorde ces droits aux groupes intégrés trouvés par `builtin_key` (`readonly` : `procedure:read` ; `technician` : les deux), `ON CONFLICT DO NOTHING`, comme `0037_accounts_hardening.grant_technicians_package_read` | Sans quoi une base existante n'afficherait la carte qu'aux administrateurs. Les groupes créés par l'exploitant ne reçoivent rien : pas de droit implicite. |
| Portée en lecture | La note du poste affiché (portée du poste). La liste : un compte sans limite voit toutes les notes ; un compte limité ne voit que celles des modèles présents sur au moins un poste de sa portée (`machine_clause`) | Le nom d'un modèle absent de sa portée lui apprendrait le parc d'un autre bâtiment. |
| Portée en écriture | Créer, modifier, supprimer : le modèle doit être présent sur au moins un poste de la portée de l'appelant ; sinon 404 `procedure.not_found` (modification) ou 422 `procedure.model_unknown` (création). Un compte sans limite peut encore modifier ou supprimer la note d'un modèle qui n'a plus de poste | La note est partagée entre bâtiments (elle parle du modèle) ; un compte limité l'écrit pour les modèles qu'il a sous la main. |
| Création d'un modèle inconnu | Refusée (422) même sans limite | Une faute de frappe créerait une note qu'aucune fiche n'affiche. Création depuis la fiche d'un poste : le modèle est le sien. |
| Écritures concurrentes | `expected_updated_at` dans la requête de modification ; s'il ne correspond plus → 409 `procedure.changed`, la console relit et le dit | Deux techniciens qui corrigent la même note : le second ne doit pas effacer le premier sans le voir. |
| Historique | Le journal d'audit : `procedure.create` (`hw_model`, `length`), `procedure.update` (`hw_model`, `previous` — le texte remplacé —, `length`), `procedure.delete` (`hw_model`, `previous`). Pas de table de versions | Le texte d'avant est retrouvable dans « Journal » pendant `AUDIT_RETENTION_DAYS` (730 j) ; une table de versions ferait une purge de plus pour un usage rare. |
| Fusion de postes, réforme | Sans objet : la note ne référence pas `machines.id` | Règle « fusion de postes » de §2 de la feuille de route : rien à faire, dit par un test. |

### 3.2 Modèle (même migration)

`procedures` (`features/procedure/models.py`, classe `Procedure`) : `id` (UUID), `hw_model` (`String`, NOT NULL, index unique `ux_procedures_hw_model`), `body` (`String(5000)`, NOT NULL), `created_by`, `created_at`, `updated_by`, `updated_at` (courriels en texte, `utc_field`). Taille bornée par le nombre de modèles du parc : pas de purge.

### 3.3 API

Nouveau fichier `api/routes/procedures.py` :

| Route | Droit | Effet |
|---|---|---|
| `GET /machines/{id}/procedure` | `procedure:read` (+ portée du poste) | `{hw_model, procedure: ProcedureOut \| null}` ; `hw_model` nul quand l'inventaire n'en a pas remonté. Route à part plutôt qu'un champ de `MachineDetail` : la fiche ne change pas pour qui n'a pas le droit. |
| `GET /procedures` | `procedure:read` | Liste (portée §3.1), triée par modèle, avec `machine_count` (postes du modèle dans la portée de l'appelant, par `restrict(..., machine_clause(scope))`). 500 au plus (nombre de modèles d'un parc). |
| `POST /procedures` | `procedure:write` | `{hw_model, body}` ; 409 `procedure.exists` si le modèle a déjà sa note (la console ouvre alors la modification). |
| `PATCH /procedures/{id}` | `procedure:write` | `{body, expected_updated_at}`. Texte vide → 422 (supprimer est un geste à part). |
| `DELETE /procedures/{id}` | `procedure:write` | 204. |

`ProcedureOut` : `id`, `hw_model`, `body`, `created_by`, `created_at`, `updated_by`, `updated_at`. Codes : `procedure.not_found` (404), `procedure.model_unknown` (422), `procedure.exists` (409), `procedure.changed` (409).

## 4. Console

### 4.1 Pièces jointes

- **`services/attachments.ts`** : `AttachmentOut`, `getAttachmentPolicy`, `uploadAttachment(interventionId, file, onProgress)` (`FormData`, comme `services/packages.ts`), `downloadAttachment(a)` (`responseType: 'blob'` puis `downloadBlob` de `utils/format.ts`), `deleteAttachment`, et `prepareImage(file, policy)` (réduction §2.1). `services/interventions.ts:Intervention` gagne `attachments?: AttachmentOut[]`.
- **`components/machine/InterventionAttachments.vue`** : la liste d'une ligne — puce par fichier (icône `image` ou `picture_as_pdf`, nom, taille `formatBytes`) ; clic → téléchargement ; pour une image, bouton « Aperçu » qui lit le fichier et l'affiche dans un dialogue sous forme d'URL `data:` (la CSP de `deploy/Caddyfile` n'autorise en `img-src` que `'self'` et `data:` ; une URL `blob:` serait bloquée, et le jeton ne part pas sur un `<img src>`). Mode édition : bouton de suppression par puce (`liveDialog` de confirmation) et zone d'ajout (`q-file` multiple, `accept="image/jpeg,image/png,image/webp,application/pdf"`).
- **`MachineHistoryCard.vue`** : chaque ligne affiche ses pièces jointes sous la note (lecture) ; le dialogue de création/modification accueille `InterventionAttachments` en édition. À la création : la ligne d'abord, puis les fichiers un par un avec progression ; un fichier refusé n'annule pas la ligne, la notification nomme les fichiers non envoyés et pourquoi (`apiErrorMessage`). Le contrôle de taille et de type est fait avant envoi d'après `GET /attachments/policy`, le serveur restant juge.
- Visible avec `intervention:read` ; ajout et suppression avec `intervention:write`. Rien sur le tableau de bord.

### 4.2 Procédures

- **`services/procedures.ts`** : types et appels de §3.3.
- **`components/machine/MachineProcedureCard.vue`** : carte « Procédure pour ce modèle » en tête de l'onglet « Interventions » de `MachineDetailPage.vue` (au-dessus de `MachineMaintenanceCard`) — là où le technicien se trouve quand il répare. Titre avec le modèle ; texte en `pre-line` ; « Modifié par … le … ». Sans note : « Aucune procédure pour ce modèle » et, avec `procedure:write`, « Écrire la procédure ». Sans `hw_model` : « Modèle inconnu (inventaire non remonté) », sans bouton. Dialogue d'édition (`q-input type="textarea" autogrow maxlength=5000`), suppression confirmée, `procedure.changed` → relecture et message.
- `canSeeHistory` de `MachineDetailPage.vue` inclut `auth.can('procedure', 'read')`. `MachineHardwareCard.vue` : à côté du modèle, une icône `menu_book` quand une note existe, qui ouvre l'onglet « Interventions » (l'information vient de la carte, chargée une fois par la page et passée en propriété).
- **Liste de toutes les notes** : dialogue `ProceduresListDialog.vue`, ouvert par « Toutes les procédures » depuis la carte : modèle, nombre de postes, dernière modification ; ouvrir, modifier, supprimer (les notes de modèles sans poste se nettoient là). Pas de page ni de carte dans Paramètres : Paramètres demande `settings:read`, que les techniciens n'ont pas.

### 4.3 Catalogues et droits

- `utils/permissions.ts` : `'procedure'` dans le type et `entry('procedure', 'read')`, `entry('procedure', 'write')` ; `i18n/messages/permissions.ts` : libellés et indications FR/EN.
- `i18n/messages/audit.ts` : `intervention.attachment_add`, `intervention.attachment_delete`, `procedure.create|update|delete`, ressource `procedure`, clés de détails (`filename`, `size`, `content_type`, `hw_model`, `previous`, `length`, `attachments`) ; `utils/auditLabels.ts` si une clé demande un formatage (taille en octets).
- `i18n/messages/errorCodes.ts` : les dix codes de §2.3 et §3.3, FR et EN.
- Nouveau catalogue `i18n/messages/procedures.ts` (enregistré dans `i18n/index.ts`) ; textes des pièces jointes dans `interventions.ts` (`interventions.attachments.*`).

## 5. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `ATTACHMENTS_DIR` | `/data/attachments` | Dossier des pièces jointes, un fichier par SHA-256, volume `attachments`. |
| `ATTACHMENT_MAX_BYTES` | `5242880` (5 Mio) | Taille maximale d'un fichier, de 65 536 à 7 340 032 (7 Mio, sous le plafond de 8 Mo de Caddy). |
| `ATTACHMENT_QUOTA_BYTES` | `2147483648` (2 Gio) | Total des pièces jointes ; 0 = pas de quota. |

À ajouter à `core/config.py` (champs `Field(ge=…, le=…)`), `deploy/.env.example` (commentées, avec leur défaut), DEPLOYMENT.md (tableau « Pièces jointes », à côté de « Déploiement logiciel ») et la page des variables (`environment.py`). Pas de réglage dans `app_settings` : ces bornes dépendent du disque et de Caddy, comme `PACKAGE_MAX_BYTES`.

## 6. Jalons

| Jalon | Contenu |
|---|---|
| PJ1 | `core/blobstore.py` extrait de `package/storage.py` (tests des paquets inchangés et verts) ; reniflage des types ; table, migration `0062` (les deux tables et les droits) ; `features/attachment/{models,storage,crud}.py` ; verrous, ménage, quota. |
| PJ2 | Routes (`attachments.py`), `InterventionOut.attachments`, journal, codes d'erreur ; ménage au démarrage, toutes les heures, après suppression ; Dockerfile, entrypoint, compose, variables. |
| PJ3 | Console : service, composant, dialogue et lignes du journal, réduction des photos, aperçu, catalogues FR/EN. |
| PJ4 | Sauvegarde : `backup.sh`, compose `db-backup`, DEPLOYMENT.md (variables, sauvegarde, restauration), `.env.example`. |
| PR1 | Procédures serveur : ressource `procedure`, table, routes, portée, concurrence, journal. |
| PR2 | Procédures console : carte, dialogue de liste, indicateur sur la carte Matériel, droits, catalogues. README (feuille de route), notes de version, §8. |

## 7. Tests

### 7.1 Serveur

`tests/test_api_attachments.py` :
- Dépôt d'un JPEG, d'un PNG, d'un WebP, d'un PDF : 201, `content_type` reconnu même quand le client envoie `text/html` ou `application/octet-stream`.
- Refus 415 d'un SVG, d'un HTML, d'un GIF, d'un fichier vide, d'un HTML renommé `.jpg` ; un PNG renommé `.pdf` passe, servi en `image/png` sous le nom `x.pdf.png`.
- Nom : chemin Windows et POSIX retiré, caractères de contrôle retirés, 200 caractères, vide → `piece-jointe`.
- 413 au-delà de `ATTACHMENT_MAX_BYTES` (monkeypatch), aucun fichier ni `.upload-*` laissé.
- 409 au 11ᵉ fichier d'une ligne.
- Quota : 413 quand le fichier dépasse ; un fichier déjà stocké (même empreinte) ne compte pas deux fois ; le fichier refusé est supprimé du disque (`discard_if_orphan`) ; deux dépôts simultanés ne passent pas tous deux (deux sessions, verrou).
- Téléchargement : octets identiques, en-têtes `Content-Disposition: attachment` avec `filename*` UTF-8, `X-Content-Type-Options: nosniff`, CSP `sandbox`, `Cache-Control: no-store`, `Content-Type` reconnu ; fichier absent du disque → 404 `attachment.file_missing`.
- Portée : compte limité à un autre site → 404 sur la liste, le dépôt, le téléchargement, la suppression ; `used_bytes` nul pour lui dans `/attachments/policy`.
- Droits : sans `intervention:read` 403 ; sans `intervention:write` 403 sur dépôt et suppression ; un jeton d'API en lecture seule télécharge mais ne dépose pas.
- Journal : `intervention.attachment_add` / `attachment_delete` avec leurs détails, dans la même transaction (dépôt refusé → pas d'entrée) ; `intervention.delete` compte les pièces jointes.
- Liste du journal : `attachments` rempli pour chaque ligne en une requête (compte des requêtes, ou au moins une page de 25 lignes à 2 pièces jointes) ; ordre par `created_at`.
- Cascade : supprimer la ligne supprime les rangées et, après ménage, le fichier ; un fichier partagé par deux lignes reste tant que l'une le nomme.
- Fusion (`merge_into`) : les pièces jointes suivent la ligne vers le poste gardé.

`tests/test_attachment_store.py` :
- `sweep_store` : supprime un orphelin, garde un fichier nommé, garde un fichier tenu par `hold_file` dans une autre session, garde tout quand `machines` est vide, supprime les `.upload-*` de plus de 24 h, n'échoue pas sur un volume en lecture seule.
- Espaces de verrous distincts : tenir un fichier de paquet n'empêche pas le ménage d'une pièce jointe de même préfixe d'empreinte, et inversement.
- `core/blobstore.py` : les tests existants de `package/storage.py` passent sans changement (`test_api_packages*.py`).

`tests/test_api_procedures.py` :
- Création depuis un modèle présent : 201, journal `procedure.create` ; modèle absent du parc → 422 `procedure.model_unknown` ; doublon → 409 `procedure.exists` ; espaces de bord retirés.
- Modification avec `expected_updated_at` juste → 200, journal avec `previous` ; périmé → 409 `procedure.changed`, rien d'écrit ; texte vide → 422 ; 5 001 caractères → 422.
- Suppression → 204, journal avec `previous`.
- `GET /machines/{id}/procedure` : note du modèle, `null` sans note, `hw_model` nul sans inventaire ; poste hors portée → 404.
- Portée de la liste : compte limité ne voit que les modèles de sa portée, `machine_count` compté dans sa portée ; il ne peut ni créer ni modifier la note d'un modèle hors de sa portée (422 / 404) ; un compte sans limite modifie la note d'un modèle sans poste.
- Droits : sans `procedure:read` 403 ; sans `procedure:write` 403 en écriture.

Autres :
- `tests/test_permissions.py` : `procedure:read` dans lecture seule et techniciens, `procedure:write` chez les techniciens, catalogue = console (test existant de parité).
- `tests/test_migration_0062.py` : montée et descente ; droits accordés aux groupes intégrés par `builtin_key` même renommés, pas aux autres groupes ; pas de doublon si déjà présents.
- `tests/test_backup_script.py` : copie des pièces jointes après un dump réussi, pas de recopie d'un fichier présent (date rafraîchie), variante chiffrée `.age`, purge des copies plus vieilles que `BACKUP_KEEP_DAYS` absentes du volume, rien de purgé si le dump échoue, volume absent → dump seul et code 0.
- `tests/test_errors.py` / catalogue : chaque nouveau `ErrorCode` a un texte FR et EN (test existant de parité).
- `features/setting/environment.py` : les trois variables listées.

### 7.2 Console

- `services/attachments.spec.ts` : `prepareImage` réduit une image trop grande (mock de `createImageBitmap`, `canvas.toBlob`), ne touche ni un PDF ni une petite image ; `downloadAttachment` appelle `downloadBlob` avec le nom de la pièce jointe.
- `components/machine/InterventionAttachments.spec.ts` : puces, tailles, icônes ; aperçu d'une image en URL `data:` ; pas de bouton de suppression en lecture ; suppression confirmée ; refus avant envoi d'un type ou d'une taille hors politique ; message d'erreur serveur affiché.
- `MachineHistoryCard.spec.ts` : création d'une ligne puis envoi de deux fichiers, l'un refusé (notification qui le nomme, ligne gardée) ; les pièces jointes apparaissent sur la ligne ; `canWrite=false` : liste sans ajout.
- `MachineProcedureCard.spec.ts` : note affichée en `pre-line`, sans note avec et sans `procedure:write`, modèle inconnu, édition, `procedure.changed` → relecture et message, suppression.
- `ProceduresListDialog.spec.ts` : liste, ouverture, suppression d'une note sans poste.
- `MachineDetailPage.spec.ts` : onglet « Interventions » visible avec `procedure:read` seul ; carte placée en tête ; icône de la carte Matériel.
- Catalogues : `permissions.en.spec.ts`, `auditLabels(.en).spec.ts`, `errors.spec.ts` couvrent les nouvelles clés ; `MachineCards.i18n.spec.ts` pour les textes anglais des deux cartes.

## Hors périmètre

- Pièces jointes ailleurs que sur une ligne du journal : sur une vérification ouverte, un signalement (C4, page publique sans compte), une maintenance entière, un actif (facture d'achat), un paquet. Le stockage générique de `core/blobstore.py` les permettra plus tard.
- Ajout de fichiers depuis l'assistant de maintenance ou le dialogue de clôture d'une vérification : la ligne qu'ils écrivent reçoit ses fichiers depuis la fiche.
- Miniatures, conversion HEIC, retrait des métadonnées EXIF côté serveur, analyse antivirale des fichiers.
- Markdown, liens cliquables, images dans les procédures ; procédures par fabricant, par salle ou par logiciel ; versions consultables autrement que par le journal d'audit.
- Recherche dans le texte des procédures et des pièces jointes.

## Décisions prises par défaut (à confirmer)

1. **Pas de miniatures** ; aperçu à la demande dans la console en URL `data:`.
2. **Types** : JPEG, PNG, WebP, PDF seulement (HEIC et GIF refusés).
3. **Limites** : 5 Mio par fichier (7 Mio au plus sans toucher Caddy), 10 par ligne, quota de 2 Gio.
4. **Réduction des photos dans la console** (2 560 px, JPEG 0,85, EXIF retiré) ; le serveur ne retouche rien.
5. **Pièces jointes dans la sauvegarde** quotidienne, copie incrémentale dans `deploy/backups/attachments/`, chiffrée avec les dumps, même rétention.
6. **Droits des pièces jointes = ceux de l'intervention** ; pas de ressource à part.
7. **Procédures en texte brut**, une note par modèle, clé `hw_model` exacte.
8. **Ressource `procedure`** : lecture à « Lecture seule » et « Techniciens », écriture aux « Techniciens », accordées par la migration aux groupes intégrés.
9. **Un compte limité écrit la note des seuls modèles présents dans sa portée** ; la note reste partagée entre bâtiments.
10. **Historique par le journal d'audit** (texte remplacé dans `previous`), pas de table de versions.
11. **Édition sur la fiche**, liste complète dans un dialogue ouvert depuis la carte, pas de page ni de carte dans Paramètres.

## 8. Écarts constatés à l'implémentation

*(à remplir)*
