# C11 — Procédures et pièces jointes : plan détaillé

> **📝 Document de travail — 2026-11-25, révisé après relecture.** Chantier C11 de `plan-evolutions-itil.md` (§4.7). Deux parties indépendantes : les pièces jointes d'une intervention (PJ1 à PJ3, puis la sauvegarde PJ4 en dernier), et les notes de procédure par modèle de poste (PR1 à PR2). Migration `0062_attachments_procedures` (après `0061_mass_approval`). Agent non modifié. Écarts constatés à l'implémentation en §8.

---

## 1. Ce que le chantier doit tenir

- **Une pièce jointe est une donnée de l'intervention** : elle se voit, se télécharge et se supprime exactement là où l'intervention se voit et se modifie (`intervention:read`, `intervention:write`, portée du poste par `machine_visible`). Un poste hors de portée répond « introuvable », pièce jointe comprise.
- **Le serveur ne sert jamais un fichier qu'un navigateur interpréterait** : types fermés reconnus **au contenu** (images JPEG, PNG, WebP et PDF ; SVG, HTML et tout le reste refusés), type déclaré par le client ignoré, téléchargement toujours en `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, CSP `sandbox`.
- **Le stockage est borné** : taille par fichier, nombre par intervention, quota total, rétention réglable ; les fichiers que plus rien ne nomme partent (ménage du dépôt, sur le modèle de `package/crud.py:sweep_store`, verrou consultatif compris).
- **Un dépôt n'écrit jamais hors du volume** : hors `ENVIRONMENT=local`, un `ATTACHMENTS_DIR` qui n'est pas un point de montage refuse les dépôts (une photo écrite dans la couche du conteneur serait perdue au prochain `up --force-recreate`).
- **Une photo de panne n'est pas reconstructible** : contrairement aux installateurs des paquets, les pièces jointes entrent dans la sauvegarde quotidienne.
- **Une note de procédure s'attache au modèle, pas au poste** : écrite une fois pour `hw_model` (inventaire, `machines.hw_model`), elle s'affiche sur la fiche de chaque poste de ce modèle. Texte brut, droit à part (`procedure`, accordé aux seuls techniciens), écrite par les seuls comptes sans limite de lieux, chaque écriture au journal d'audit avec le texte remplacé.
- **Les écritures concurrentes ne se perdent pas et ne finissent pas en 500** : décompte par ligne sous verrou, modification d'une note par `UPDATE` conditionnel, contraintes uniques interceptées en 409.
- Rien de neuf côté agent, rien de neuf dans le catalogue de commandes.

## 2. Pièces jointes

### 2.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Rattachement | À une ligne du journal (`interventions.id`), quelle que soit sa nature : saisie à la main, ligne d'une maintenance (`maintenance/crud.py:add_lines`), clôture d'une vérification (`routes/checks.py`, `Intervention(kind=verification, check_id=…)`) | Le plan dit « sur une intervention ». Toute ligne existe dans `interventions` : une seule table à rattacher, et la fusion de postes (`machine/crud.py:merge_into` → `intervention_crud.move_to`) emporte les pièces jointes sans code de plus. |
| Moment de l'ajout | Sur une ligne **existante** : dialogue de modification, ou juste après la création dans le même dialogue (la console crée la ligne, puis envoie les fichiers un par un) | Une pièce jointe sans ligne n'aurait ni portée ni auteur. Pas de dépôt « en attente » à purger. |
| Stockage | Un fichier par SHA-256 sous `ATTACHMENTS_DIR` (défaut `/data/attachments`), volume Docker `attachments` distinct de `packages` ; écriture en temporaire puis renommage, comme `package/storage.py:save` | Le modèle demandé par la feuille de route. Volume à part : les paquets sont reconstructibles et hors sauvegarde, les pièces jointes non (§2.6). Deux lignes qui joignent la même photo partagent le fichier. |
| Code du dépôt | **Pas d'extraction ni de déplacement** : `package/storage.py` reste où il est, relu lors des audits S09 et T09. Ses fonctions (`root`, `path_for`, `exists`, `save`, `remove_unreferenced`, `stored_shas`, `remove_stale_uploads`) gagnent un paramètre facultatif `directory: str \| None = None` (absent → `settings.PACKAGES_DIR`, lu à chaque appel comme aujourd'hui), et `save` un paramètre facultatif `sniff: Callable[[bytes], str \| None] \| None = None` appelé sur le premier bloc lu. Aucun appelant des paquets ne change. `features/attachment/storage.py` n'est qu'une série d'enveloppes qui passent `settings.ATTACHMENTS_DIR` **lu à chaque appel** (jamais à l'import : la fixture des tests le redirige, §7.1) et le reniflage | Un seul code d'écriture atomique et de ménage des `.upload-*`, sans risquer de régresser le dépôt des paquets : les tests `test_api_packages*.py` passent sans changement. |
| Types acceptés | Reconnus sur les 16 premiers octets, **avant** toute écriture (le `sniff` de `save` lève l'erreur sur le premier bloc, le temporaire est supprimé) : JPEG (`FF D8 FF`), PNG (`89 50 4E 47 0D 0A 1A 0A`), WebP (`RIFF????WEBP`), PDF (`%PDF-`). Le `Content-Type` stocké et servi est celui reconnu, jamais celui du client ni de l'extension | « Renifler le contenu, pas l'extension. » Quatre signatures écrites à la main : pas de dépendance (`pyproject.toml` n'a ni Pillow ni libmagic). SVG, HTML, GIF, HEIC, Office : refusés (415). |
| Nom du fichier | Celui envoyé, nettoyé : chemin retiré (`PurePosixPath`/`PureWindowsPath(...).name`), caractères de contrôle retirés, 200 caractères au plus, vide → `piece-jointe` ; extension corrigée si elle ne dit pas le type reconnu (`panne.html` reconnu PNG → `panne.html.png`) | Un fichier enregistré sur le disque de l'opérateur ne doit pas s'ouvrir comme autre chose que ce qu'il est. Les `"`, `\` et `;` restent dans le nom stocké : l'en-tête de téléchargement est construit par Starlette (ligne Téléchargement). |
| Taille | `ATTACHMENT_MAX_BYTES`, défaut 5 Mio, de 64 Kio à 7 Mio | Caddy plafonne toute requête hors dépôt de paquet à `max_size 8MB` (`deploy/Caddyfile`, bloc `@not_package_upload`) : 7 Mio laissent la marge des en-têtes multipart, et aucun bloc Caddy de plus n'est à maintenir. |
| Réduction des photos | **Dans la console**, avant l'envoi : tout JPEG et tout WebP est **toujours** redessiné (`createImageBitmap(file, { imageOrientation: 'from-image' })` puis `canvas.toBlob('image/jpeg', 0.85)`), réduit à 2 560 px de côté au plus ; un PNG reste un PNG s'il tient dans la limite et 2 560 px, sinon il est redessiné en JPEG. Le serveur ne modifie **jamais** un fichier reçu | Le redessin systématique retire les métadonnées EXIF (position GPS d'un téléphone), y compris d'une petite photo ou d'une photo recadrée. Une photo de téléphone pèse 3 à 12 Mo. Le serveur reste sans bibliothèque d'images et le fichier stocké reste celui de son empreinte. Un PNG (capture d'écran) ne porte pas d'EXIF de position. |
| Miniatures | **Non**. La console affiche un aperçu à la demande (§4.1) | Générer des miniatures demanderait une bibliothèque d'images au serveur et un second fichier par photo. Une ligne porte rarement plus de deux ou trois photos. |
| Nombre par ligne | 10 au plus (`MAX_PER_INTERVENTION`, constante) ; 409 `attachment.too_many`. Contrôlé deux fois : un pré-contrôle rapide avant la réception (refus sans téléverser), puis le **décompte refait sous le verrou du quota** juste avant l'insertion (§2.3) | Une intervention n'est pas un album. Sans le second décompte, deux dépôts simultanés lisent tous deux 9 et en insèrent 11. |
| Doublon sur une ligne | Contrainte unique `uq_intervention_attachments_intervention_sha` (`intervention_id`, `sha256`) ; le même fichier joint deux fois à la même ligne → 409 `attachment.duplicate` (contrôlé sous le verrou, et l'`IntegrityError` de la contrainte interceptée en 409 par sûreté) | Deux puces identiques qui comptent deux fois dans la limite de 10. Le même fichier sur deux lignes différentes reste permis (fichier partagé). |
| Quota | `ATTACHMENT_QUOTA_BYTES`, défaut 2 Gio, 0 = pas de quota : somme des tailles des fichiers **distincts** nommés par `intervention_attachments`. Vérifié après réception, sous `pg_advisory_xact_lock(ATTACHMENT_QUOTA_LOCK)`, constante 64 bits `ATTACHMENT_QUOTA_LOCK = 0x746961692D617474` (« tiai-att ») de `features/attachment/crud.py`, distincte de `counter/quota.py:QUOTA_LOCK` et de `user/crud.py:ACCOUNT_MANAGEMENT_LOCK` ; refus 413 `attachment.quota_exceeded`, et le fichier écrit pour rien est supprimé aussitôt s'il n'est nommé par personne (`discard_if_orphan`, §2.4). **Reste une variable d'environnement** : écart voulu à la règle « Réglages » de §2 de la feuille de route (voir §5) | Un disque plein arrête la base sur la même machine. |
| Rétention | Réglage `app_settings` **`attachments.retention_days`** (constante `KEY_ATTACHMENT_RETENTION` de `setting/crud.py`, lu par `setting_crud.attachment_retention_days(session, values)` sur le modèle de `license_expiry_days`), valeur initiale `ATTACHMENT_RETENTION_DAYS` de l'environnement, défaut **0 = conserver** ; éditable dans Paramètres (champ `attachment_retention_days` de `routes/settings_routes.py`). Purge des **rangées** plus vieilles par le worker, fichiers retirés par le ménage horaire de l'API (§2.4) | Règle « une purge pour tout ce qui grossit ». Les photos peuvent montrer des élèves ou des écrans nominatifs : la durée de conservation est un choix de l'établissement (et de son DPO, feuille de route §6.9), pas du logiciel ; 0 par défaut pour ne rien effacer à la mise à jour, 1 825 jours proposés dans les décisions (§ Décisions). |
| Volume monté | Hors `ENVIRONMENT=local`, si `os.path.ismount(settings.ATTACHMENTS_DIR)` est faux : avertissement journalisé au démarrage (lifespan de `main.py`), dépôts refusés en 503 `attachment.store_unavailable`, et `GET /attachments/policy` renvoie `store_available: false` pour que la console grise l'ajout. Lecture, téléchargement et suppression restent permis | Une image mise à jour sans le nouveau `docker-compose.yml` a `/data/attachments` (créé par le Dockerfile) mais pas le volume : les photos iraient dans la couche du conteneur et disparaîtraient sans bruit. `local` (développement et tests, `tests/conftest.py` pose `ENVIRONMENT=local`) n'a pas de volume. |
| Droits | Ceux de l'intervention : lire et télécharger `intervention:read`, ajouter et supprimer `intervention:write` (comme modifier une ligne : `routes/interventions.py` n'exige pas d'être l'auteur) | Pas de ressource de plus : une pièce jointe n'apprend rien de plus que la note de la ligne. |
| Portée | Toute route passe par la ligne (`_require_intervention`, qui appelle `machine_visible`) ; hors portée → 404 `attachment.not_found` / `intervention.not_found` | Invariant de portée. |
| Téléchargement | `FileResponse(path, media_type=<reconnu>, filename=a.filename, content_disposition_type="attachment")` de Starlette, qui construit lui-même `filename="…"` ou `filename*=utf-8''…` (pourcent-encodé) ; plus `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, `Cache-Control: private, no-store` | Pas d'en-tête construit à la main : les `"`, `\`, `;` et non-ASCII du nom sont neutralisés par Starlette. Ouvrir le fichier dans l'origine de la console ne doit rien pouvoir exécuter. `nosniff` est déjà posé par Caddy, mais l'API le pose elle-même (le port de développement 8800 n'a pas Caddy devant). |
| Fichier absent du disque | 404 `attachment.file_missing` (la ligne reste, la console dit « fichier absent du serveur ») | Cas d'une base restaurée sans ses fichiers (§2.6). |
| Journal | `intervention.attachment_add`, `intervention.attachment_delete` (ressource `intervention`, identifiant de la ligne ; détails : `machine_id`, `attachment_id`, `filename`, `size`, `sha256`, `content_type`) ; `intervention.delete` et `maintenance.delete` gagnent `attachments` (nombre emporté) | « `audit.record` pour toute écriture. » La création d'une ligne elle-même n'est pas journalisée aujourd'hui (son auteur est sur la ligne) : inchangé. La purge par l'âge n'est pas journalisée, comme les autres purges du worker (`purge_reports`, `purge_alerts`…) : une ligne de log avec le nombre. |
| Webhooks, résumé, alertes | Rien | Une pièce jointe n'est pas un évènement du parc. |

### 2.2 Modèle (migration `0062_attachments_procedures`)

`intervention_attachments` (`features/attachment/models.py`, classe `InterventionAttachment`, importée dans `features/models.py` pour qu'Alembic et les tests la voient) :

| Colonne | Type | Note |
|---|---|---|
| `id` | UUID, clé | |
| `intervention_id` | UUID, `ForeignKey("interventions.id", ondelete="CASCADE")`, NOT NULL | Supprimer la ligne supprime ses pièces jointes ; le fichier part au ménage (§2.4). |
| `sha256` | `String(64)`, NOT NULL | Nom du fichier dans `ATTACHMENTS_DIR`. |
| `size` | `BigInteger`, NOT NULL | |
| `content_type` | `String(40)`, NOT NULL | `image/jpeg`, `image/png`, `image/webp`, `application/pdf`. |
| `filename` | `String(200)`, NOT NULL | Nom nettoyé (§2.1). |
| `uploaded_by` | `String(255)`, NOT NULL | Courriel, convention de `interventions.performed_by` : survit au compte. |
| `created_at` | `timestamptz`, NOT NULL, `utc_field(default_factory=utcnow)` | Sert aussi à la rétention. |

Index : `ix_intervention_attachments_intervention` (`intervention_id`, `created_at`) — la lecture d'une page du journal ; `ix_intervention_attachments_sha256` (`sha256`) — le ménage et le quota ; `ix_intervention_attachments_created_at` (`created_at`) — la purge ; contrainte unique `uq_intervention_attachments_intervention_sha` (`intervention_id`, `sha256`). Pas de JSONB, pas de booléen.

### 2.3 API

Nouveau fichier `api/routes/attachments.py`, deux routeurs enregistrés dans `api/__init__.py` à côté de `interventions_router` :

| Route | Droit | Effet |
|---|---|---|
| `GET /attachments/policy` | `intervention:read` | `{max_bytes, max_per_intervention, types: ["image/jpeg", …], quota_bytes, used_bytes, retention_days, store_available}` ; `used_bytes` est `null` pour un compte limité à des lieux (agrégat de tout le parc). La console ne recopie aucune limite. |
| `POST /interventions/{id}/attachments` | `intervention:write` | Multipart, **un** fichier (`file`) par requête, comme le dépôt des paquets. 201 → `AttachmentOut`. |
| `GET /attachments/{id}/content` | `intervention:read` | Le fichier (§2.1, Téléchargement). |
| `DELETE /attachments/{id}` | `intervention:write` | 204 ; journal ; après `commit`, `attachment_crud.discard_if_orphan(session, sha)` pour l'empreinte de la pièce jointe supprimée. |

`AttachmentOut` : `id`, `intervention_id`, `filename`, `content_type`, `size`, `uploaded_by`, `created_at`. `routes/interventions.py:InterventionOut` gagne `attachments: list[AttachmentOut] = []`, rempli pour toute la page en **une** requête (`attachment_crud.of_interventions(session, ids)`), dans `list_interventions`, et à vide dans les réponses de création et de modification (la console relit la page).

Déroulé de `POST` :

1. `_require_intervention` (portée) ; `store_available` faux → 503 `attachment.store_unavailable`.
2. Pré-contrôle rapide : la ligne a déjà 10 pièces jointes → 409 `attachment.too_many`, sans rien recevoir.
3. `storage.save(upload, ATTACHMENT_MAX_BYTES, hold=lambda sha: attachment_crud.hold_file(session, sha), sniff=…)` : le premier bloc est reniflé, refus 415 avant toute écriture définitive ; puis écriture et fichier tenu.
4. `pg_advisory_xact_lock(ATTACHMENT_QUOTA_LOCK)` — il sérialise tous les dépôts de pièces jointes.
5. Sous ce verrou : relecture de la ligne par `select(Intervention).where(col(Intervention.id) == id).with_for_update(read=True)` (un `FOR SHARE` : une suppression concurrente attend la fin du dépôt ; pas `intervention_crud.get`, qui peut rendre l'objet déjà chargé) ; ligne disparue → 404 `intervention.not_found` ; puis décompte refait (≥ 10 → 409 `attachment.too_many`), doublon (`intervention_id`, `sha256`) → 409 `attachment.duplicate`, quota → 413.
6. Insertion, `audit.record`, `commit`. Une `IntegrityError` à l'insertion (contrainte unique, clé étrangère) → `rollback`, 409 `attachment.duplicate` ou 404 `intervention.not_found` selon la contrainte, jamais 500.

En cas de refus après l'étape 3 : `rollback`, puis `discard_if_orphan(session, sha)`.

`DELETE /interventions/{id}` (`routes/interventions.py:delete_intervention`) : avant la suppression, lit les empreintes de la ligne (`attachment_crud.shas_of(session, [id])`), en met le nombre dans `attachments` de `intervention.delete` ; après `commit`, `discard_if_orphan` pour chacune.

`DELETE /maintenance/{id}` (`routes/maintenance.py:delete_session`, qui appelle `maintenance/crud.py:delete_session`) : les lignes de la visite partent avec leurs pièces jointes en CASCADE. La route lit avant l'audit les empreintes des lignes de `crud.session_items` (`attachment_crud.shas_of(session, line_ids)`), ajoute `attachments` (nombre de pièces jointes) aux détails de `maintenance.delete`, et appelle `discard_if_orphan` pour chaque empreinte après son `commit`.

Codes d'erreur (`core/errors.py`, texte FR+EN dans `frontend/src/i18n/messages/errorCodes.ts`) :

| Code | Statut | Quand |
|---|---|---|
| `attachment.not_found` | 404 | Inconnue, ou sa ligne hors de portée. |
| `attachment.file_missing` | 404 | Ligne en base, fichier absent du disque. |
| `attachment.too_large` | 413 | `details.max_bytes`. |
| `attachment.type_refused` | 415 | `details.types` (les quatre acceptés). |
| `attachment.too_many` | 409 | `details.max` (10). |
| `attachment.duplicate` | 409 | Le même fichier est déjà joint à cette ligne. |
| `attachment.quota_exceeded` | 413 | `details.quota_bytes`. |
| `attachment.store_unavailable` | 503 | `ATTACHMENTS_DIR` n'est pas un volume monté (hors `local`). |

### 2.4 Ménage du dépôt et rétention

`features/attachment/crud.py`, calqué sur `package/crud.py` :

- `ATTACHMENT_QUOTA_LOCK` (§2.1).
- `hold_file(session, sha)` / `_claim_file(session, sha)` : les mêmes verrous consultatifs à deux clés, dans un **autre espace** (`_FILE_LOCK_SPACE = 0x54415454`, « TATT » ; celui des paquets est `0x54504B46`, « TPKF »).
- `sha_in_use(session, sha)` : une ligne de `intervention_attachments` le nomme.
- `of_interventions(session, ids)`, `shas_of(session, intervention_ids)`.
- `sweep_store(session)` : comme celui des paquets (réservé, verrou pris sans attendre, question reposée sous le verrou, `commit` après chaque fichier, jamais d'exception). Garde contre une mauvaise base : rien n'est supprimé quand la table `machines` est vide alors que le dépôt contient des fichiers (une base neuve ou vidée, pas des orphelins). Puis `storage.remove_stale_uploads()`.
- `discard_if_orphan(session, sha)` : le même traitement pour un seul fichier — après un dépôt refusé, après chaque suppression (pièce jointe, ligne, visite de maintenance). La session ne tient aucun fichier à ce moment (appelé après `commit` ou `rollback`).
- `purge_before(session, cutoff)` : supprime les rangées dont `created_at < cutoff`, par lots, et rend le nombre ; ne touche pas aux fichiers.
- `sweep_store` tourne au démarrage et toutes les heures dans le processus de l'API (`main.py`, lifespan, à côté de `package_crud.sweep_periodically` : une seconde tâche `attachment_crud.sweep_periodically`). **Pas dans le worker** : seul le conteneur `backend` monte le volume, comme pour les paquets (`deploy/docker-compose.yml`).

**Rétention.** Job worker `Job("purge_attachments", purge_attachments, housekeeping(now), housekeeping)` dans `core/worker.py` : lit `setting_crud.attachment_retention_days(session)` ; 0 → rien ; sinon `attachment_crud.purge_before(session, utcnow() - timedelta(days=n))`, une ligne de log avec le nombre. **Le worker n'a pas le volume** : il ne supprime que les rangées ; les fichiers devenus orphelins sont retirés par le ménage horaire de l'API (`attachment_crud.sweep_periodically`), donc au plus une heure plus tard. La console affiche, à côté du quota, la rétention en vigueur (`retention_days` de la politique) et prévient quand `used_bytes` dépasse 90 % de `quota_bytes` (« Pièces jointes : 1,8 Gio sur 2 Gio ; supprimez des pièces jointes ou demandez une hausse du quota »).

### 2.5 Image et volumes

- `backend/Dockerfile` : `mkdir -p /data/packages /data/attachments && chown tiai:tiai /data/packages /data/attachments`.
- `app/scripts/entrypoint.sh` : le bloc root qui rend `PACKAGES_DIR` à `tiai` s'étend à `ATTACHMENTS_DIR` ; pour ce dossier, la condition devient « un fichier n'appartient pas à `tiai` » (`[ -n "$(find "$dir" ! -user tiai -print -quit)" ]`) et non le seul propriétaire du dossier : des fichiers remis par la restauration (§2.6) dans un volume déjà en place appartiendraient sinon à root.
- `deploy/docker-compose.yml` : volume nommé `attachments`, monté `attachments:/data/attachments` sur `backend`, et **en lecture seule** `attachments:/attachments:ro` sur `db-backup` (§2.6). Rien sur `worker`.
- `features/setting/environment.py` : groupe `attachments` (« Pièces jointes ») : `ATTACHMENTS_DIR`, `ATTACHMENT_MAX_BYTES` (`fmt="bytes"`), `ATTACHMENT_QUOTA_BYTES` (`fmt="bytes"`), `ATTACHMENT_RETENTION_DAYS` ; libellés anglais dans `i18n/messages/settingsEnv.ts`.
- Notes de version et DEPLOYMENT.md : reprendre le nouveau `docker-compose.yml` avec l'image, sans quoi les dépôts répondent 503 `attachment.store_unavailable` (§2.1, Volume monté).

### 2.6 Sauvegarde (dernier jalon, PJ4)

Constat : `deploy/backup/backup.sh` ne fait qu'un `pg_dump` ; DEPLOYMENT.md (« Déploiement logiciel ») dit que le volume `packages` n'est pas dans le dump et se reconstruit depuis les installateurs. Une photo de panne ne se reconstruit pas.

| Sujet | Choix | Pourquoi |
|---|---|---|
| Où | `deploy/backups/attachments/`, à côté des dumps : copié hors de la machine par le même moyen | L'exploitant n'a qu'un dossier à copier. |
| Comment | `backup.sh`, **après un dump réussi** : pour chaque fichier de `/attachments` dont le nom est 64 caractères hexadécimaux, présent dans la copie sous **l'une ou l'autre forme** (`<sha>` ou `<sha>.age`) → `touch` de la forme présente ; sinon copie vers `attachments/<sha>` (ou `<sha>.age`, chiffré pour `BACKUP_ENCRYPT_RECIPIENT` comme les dumps), écrite en `.tmp` puis renommée. Chiffrement activé : une copie en clair `<sha>` encore présente est remplacée par `<sha>.age`, puis supprimée une fois la copie chiffrée écrite. `chmod 700` sur `attachments/`, `600` sur chaque fichier (comme le resserrement des dumps) | Fichiers immuables nommés par leur empreinte : la copie est incrémentale sans outil de plus. Activer le chiffrement ne laisse pas de photo en clair derrière soi. |
| Rétention | Un fichier de la copie que le volume ne contient plus n'est plus touché ; il est supprimé quand sa date dépasse `BACKUP_KEEP_DAYS` | Un dump de 14 jours retrouve ses photos ; rien ne grossit sans fin. |
| Volume absent | `/attachments` non monté (compose d'avant C11) : une ligne au journal, dump inchangé, code 0 | Une mise à jour sans le nouveau compose ne casse pas la sauvegarde. |
| Échec de copie | Journal, code 1 après le dump, pas de purge de la copie | Même règle que la purge des dumps. |

DEPLOYMENT.md, « Sauvegardes et restauration » : la liste des choses à copier hors de la machine gagne `deploy/backups/attachments/` ; « Restaurer » gagne la remise des fichiers dans le volume, **`backend` arrêté**, avec l'image `<projet>-db-backup` (elle a `sh` et `age` ; son point d'entrée est remplacé par `--entrypoint sh`, celui de l'image backend répondrait « Unknown mode: sh ») :

```bash
docker compose stop backend
# Copie en clair
docker run --rm --entrypoint sh -v <projet>_attachments:/data \
  -v "$PWD/backups/attachments:/restore:ro" <projet>-db-backup \
  -c 'for f in /restore/*; do case "$f" in *.age|*.tmp) continue;; esac; cp -n "$f" /data/; done; chown -R 10001:10001 /data'
# Copie chiffrée : la clé privée par l'entrée standard, jamais écrite sur le serveur hors du conteneur éphémère
docker run --rm -i --entrypoint sh -v <projet>_attachments:/data \
  -v "$PWD/backups/attachments:/restore:ro" <projet>-db-backup \
  -c 'umask 077; cat > /tmp/k; for f in /restore/*.age; do d=/data/$(basename "$f" .age); [ -e "$d" ] || age -d -i /tmp/k -o "$d" "$f"; done; chown -R 10001:10001 /data' < tiai-sauvegardes.key
docker compose start backend
```

`10001` est l'uid et le gid du compte `tiai` de l'image backend (`backend/Dockerfile`) ; l'entrypoint (§2.5) rattrape de toute façon un fichier qui ne lui appartiendrait pas. Restaurer la base sans les fichiers laisse des lignes en `attachment.file_missing`, rien de plus. La procédure est vérifiée à la main une fois et décrite telle quelle dans DEPLOYMENT.md.

## 3. Notes de procédure par modèle

### 3.1 Choix

| Sujet | Choix | Pourquoi |
|---|---|---|
| Clé | `machines.hw_model` tel que l'inventaire l'écrit (`inventory/crud.py` : `machine.hw_model = report.hw_model`, borné à `inventory/schemas.py:TEXT_MAX` = 200), comparé exactement, espaces de bord retirés | La feuille de route dit « par modèle (`hw_model`) ». Le fabricant n'entre pas dans la clé : deux fabricants n'emploient pas le même nom de modèle dans un parc d'établissement. |
| Format | **Texte brut**, 5 000 caractères (la borne de `interventions.note`), affiché avec `white-space: pre-line` comme les notes du journal (`MachineHistoryCard.vue`) ; pas de Markdown, pas de lien rendu cliquable | La console n'a aucun `v-html` ni moteur Markdown (`services/assets.ts` le revendique) ; en ajouter un pour une note de trois lignes ouvrirait une injection à garder. |
| Secrets | Le dialogue d'édition avertit, FR/EN : « N'écrivez ni mot de passe ni secret : cette note est lue par tous les techniciens et conservée au journal d'audit. » | Une note de procédure attire « mot de passe BIOS : … » ; le texte remplacé reste en plus dans le journal (`previous`). |
| Une ou plusieurs | **Une** note par modèle | « Sur ce modèle, le BIOS s'ouvre par F10 » : un texte. Plusieurs notes demanderaient titres, ordre et liste. |
| Droit | Ressource **`procedure`** (`read`, `write`) dans `Resource` et `PERMISSION_CATALOGUE` (`user/permissions.py`) ; les deux dans `BUILTIN_GROUP_DEFAULTS[BuiltinGroup.TECHNICIAN]` **seulement** ; `_SUPERVISION_READ` inchangé, donc « Lecture seule » ne reçoit rien ; les administrateurs ont tout, implicitement | Savoir de terrain écrit par ceux qui réparent, susceptible de contenir des informations sensibles : comme `asset`, `license`, `webhook` (C2, C6, C8), pas de droit nouveau aux comptes de supervision ni à leurs jetons d'API en lecture. Ressource à part, pas `intervention:write` : on peut vouloir qu'un compte complète le journal sans réécrire la procédure de tout un modèle. |
| Comptes existants | La migration accorde `procedure:read` et `procedure:write` au groupe intégré `builtin_key = 'technician'` seulement, `INSERT … SELECT id, … FROM groups WHERE builtin_key = 'technician' ON CONFLICT DO NOTHING`, comme `0037_accounts_hardening.grant_technicians_package_read` | Sans quoi une base existante n'afficherait la carte qu'aux administrateurs. Les groupes créés par l'exploitant ne reçoivent rien : pas de droit implicite. |
| Portée en lecture | La note du poste affiché (portée du poste). La liste : un compte sans limite voit toutes les notes ; un compte limité ne voit que celles des modèles présents sur au moins un poste de sa portée (`machine_clause`) | Le nom d'un modèle absent de sa portée lui apprendrait le parc d'un autre bâtiment. |
| Portée en écriture | `POST`, `PATCH`, `DELETE /procedures` réservés aux comptes **sans limite de lieux** : un compte limité reçoit 403 `procedure.scope_limited` (même règle que `routes/webhooks.py:_whole_parc`, avec un code à soi pour que la console dise pourquoi) ; il lit seulement. La console masque les boutons d'écriture pour lui | La note est partagée entre bâtiments. Une écriture par un compte limité déborderait de sa portée sans trace visible pour les autres bâtiments : `routes/audit.py:_scope_clause` ne montre aux lecteurs confinés que les entrées `resource_type='machine'` de leur portée et leurs propres actions, pas une entrée `procedure`. |
| Création : contrôles | Dans cet ordre : 1) compte sans limite, sinon 403 ; 2) le modèle est connu, sinon 422 `procedure.model_unknown` ; 3) seulement ensuite, la note existe déjà → 409 `procedure.exists` | Le 409 ne doit jamais répondre avant le contrôle du modèle. (Avec la réserve aux comptes sans limite, l'ordre ne cache plus rien à un compte limité, mais il reste fixé pour le jour où la règle s'assouplirait.) |
| Modèle connu | Présent sur au moins un poste, **réformés compris** (`machines.hw_model = :m`, sans filtre `asset_crud.retired_clause()`) | Un poste réformé peut être remis en service ; sa note reste utile. |
| Création d'un modèle inconnu | Refusée (422) | Une faute de frappe créerait une note qu'aucune fiche n'affiche. Création depuis la fiche d'un poste : le modèle est le sien. |
| Écritures concurrentes | `PATCH` et `DELETE` portent `expected_updated_at` ; l'écriture est un `UPDATE procedures SET … WHERE id = :id AND updated_at = :expected` (resp. `DELETE … WHERE …`) ; 0 ligne touchée → relecture : absente → 404 `procedure.not_found`, sinon 409 `procedure.changed` (la console relit et le dit). Le texte remplacé pour `previous` est lu dans la même transaction par `select(Procedure).where(…).with_for_update()` avant l'`UPDATE`. `POST` : l'`IntegrityError` de `uq_procedures_hw_model` est interceptée → `rollback`, 409 `procedure.exists` | Deux techniciens qui corrigent la même note : le second ne doit pas effacer le premier sans le voir. Une comparaison en Python puis une écriture laisserait passer deux requêtes simultanées. |
| Historique | Le journal d'audit : `procedure.create` (`hw_model`, `length`), `procedure.update` (`hw_model`, `previous` — le texte remplacé —, `length`), `procedure.delete` (`hw_model`, `previous`). Pas de table de versions | Le texte d'avant est retrouvable dans « Journal » pendant `AUDIT_RETENTION_DAYS` (730 j) ; une table de versions ferait une purge de plus pour un usage rare. |
| Fusion de postes, réforme | Sans objet : la note ne référence pas `machines.id` | Règle « fusion de postes » de §2 de la feuille de route : rien à faire, dit par un test. |

### 3.2 Modèle (même migration)

`procedures` (`features/procedure/models.py`, classe `Procedure`, importée dans `features/models.py`) : `id` (UUID), `hw_model` (`String(200)`, la borne `TEXT_MAX` de `inventory/schemas.py`, NOT NULL, index unique `uq_procedures_hw_model`), `body` (`String(5000)`, NOT NULL), `created_by`, `created_at`, `updated_by`, `updated_at` (courriels en texte, `utc_field`). Taille bornée par le nombre de modèles du parc : pas de purge.

### 3.3 API

Nouveau fichier `api/routes/procedures.py` :

| Route | Droit | Effet |
|---|---|---|
| `GET /machines/{id}/procedure` | `procedure:read` (+ portée du poste) | `{hw_model, procedure: ProcedureOut \| null}` ; `hw_model` nul quand l'inventaire n'en a pas remonté. Route à part plutôt qu'un champ de `MachineDetail` : la fiche ne change pas pour qui n'a pas le droit. |
| `GET /procedures` | `procedure:read` | Liste (portée §3.1), triée par modèle, avec `machine_count` : postes du modèle dans la portée de l'appelant (`restrict(..., machine_clause(scope))`), **réformés exclus** (`asset_crud.in_parc_clause()`). 500 au plus (nombre de modèles d'un parc). |
| `POST /procedures` | `procedure:write`, sans limite de lieux | `{hw_model, body}` ; contrôles dans l'ordre de §3.1 ; 409 `procedure.exists` si le modèle a déjà sa note (la console ouvre alors la modification). |
| `PATCH /procedures/{id}` | `procedure:write`, sans limite de lieux | `{body, expected_updated_at}`. Texte vide → 422 (supprimer est un geste à part). `UPDATE` conditionnel (§3.1). |
| `DELETE /procedures/{id}?expected_updated_at=…` | `procedure:write`, sans limite de lieux | 204 ; `DELETE` conditionnel (§3.1). |

`ProcedureOut` : `id`, `hw_model`, `body`, `created_by`, `created_at`, `updated_by`, `updated_at`. Codes : `procedure.not_found` (404), `procedure.model_unknown` (422), `procedure.exists` (409), `procedure.changed` (409), `procedure.scope_limited` (403).

## 4. Console

### 4.1 Pièces jointes

- **`utils/format.ts`** : `formatSize(bytes)` y est déplacé depuis `services/packages.ts` (qui le réexporte, ses appelants ne changent pas) : un composant de la fiche ne dépend pas du service des paquets.
- **`services/attachments.ts`** : `AttachmentOut`, `AttachmentPolicy`, `getAttachmentPolicy`, `uploadAttachment(interventionId, file, onProgress)` (`FormData`, comme `services/packages.ts`), `downloadAttachment(a)` (`responseType: 'blob'` puis `downloadBlob` de `utils/format.ts`), `deleteAttachment`, et `prepareImage(file, policy)` (redessin §2.1 : JPEG et WebP toujours, PNG au-delà de la limite ou de 2 560 px, PDF jamais). `services/interventions.ts:Intervention` gagne `attachments?: AttachmentOut[]`.
- **`components/machine/InterventionAttachments.vue`** : la liste d'une ligne — puce par fichier (icône `image` ou `picture_as_pdf`, nom, taille `formatSize`) ; clic → téléchargement ; pour une image, bouton « Aperçu » qui lit le fichier et l'affiche dans un dialogue sous forme d'URL `data:` (la CSP de `deploy/Caddyfile` n'autorise en `img-src` que `'self'` et `data:` ; une URL `blob:` serait bloquée, et le jeton ne part pas sur un `<img src>`). Mode édition : bouton de suppression par puce (`liveDialog` de confirmation) et zone d'ajout (`q-file` multiple, `accept="image/jpeg,image/png,image/webp,application/pdf"`), grisée avec une explication quand `store_available` est faux ; avertissement quand `used_bytes` dépasse 90 % de `quota_bytes`.
- **`MachineHistoryCard.vue`** : chaque ligne affiche ses pièces jointes sous la note (lecture) ; le dialogue de création/modification accueille `InterventionAttachments` en édition. À la création : la ligne d'abord, puis les fichiers un par un avec progression ; un fichier refusé n'annule pas la ligne, la notification nomme les fichiers non envoyés et pourquoi (`apiErrorMessage` de `services/errors.ts`). Le contrôle de taille et de type est fait avant envoi d'après `GET /attachments/policy`, le serveur restant juge.
- **Paramètres** : le champ « Rétention des pièces jointes (jours, 0 = conserver) » rejoint les réglages servis par `routes/settings_routes.py` (`services/settings.ts`, sur le modèle de `license_expiry_days` / `env_license_expiry_days`).
- Visible avec `intervention:read` ; ajout et suppression avec `intervention:write`. Rien sur le tableau de bord.

### 4.2 Procédures

- **`services/procedures.ts`** : types et appels de §3.3.
- **`components/machine/MachineProcedureCard.vue`** : carte « Procédure pour ce modèle » en tête de l'onglet « Interventions » de `MachineDetailPage.vue` (au-dessus de `MachineMaintenanceCard`) — là où le technicien se trouve quand il répare. Titre avec le modèle ; texte en `pre-line` ; « Modifié par … le … ». Sans note : « Aucune procédure pour ce modèle » et, avec `procedure:write` et sans limite de lieux, « Écrire la procédure ». Sans `hw_model` : « Modèle inconnu (inventaire non remonté) », sans bouton. Dialogue d'édition (`q-input type="textarea" autogrow maxlength=5000`) avec l'avertissement « ni mot de passe ni secret » (§3.1), suppression confirmée, `procedure.changed` → relecture et message.
- `canSeeHistory` de `MachineDetailPage.vue` inclut `auth.can('procedure', 'read')`.
- **Liste de toutes les notes** : dialogue `ProceduresListDialog.vue`, ouvert par « Toutes les procédures » depuis la carte : modèle, nombre de postes en service, dernière modification ; ouvrir, modifier, supprimer (les notes de modèles sans poste se nettoient là). Pas de page ni de carte dans Paramètres : Paramètres demande `settings:read`, que les techniciens n'ont pas.

### 4.3 Catalogues et droits

- `utils/permissions.ts` : `'procedure'` dans le type et `entry('procedure', 'read')`, `entry('procedure', 'write')` ; `i18n/messages/permissions.ts` : libellés et indications FR/EN.
- `i18n/messages/audit.ts` : `intervention.attachment_add`, `intervention.attachment_delete`, `procedure.create|update|delete`, ressource `procedure`, clés de détails (`filename`, `size`, `content_type`, `sha256`, `attachment_id`, `hw_model`, `previous`, `length`, `attachments`) ; `utils/auditLabels.ts` : taille en octets formatée, et `previous` **tronqué à 120 caractères** suivis de « … » dans `auditDetailsSummary` (le texte complet reste dans le détail déplié).
- `i18n/messages/errorCodes.ts` : les treize codes de §2.3 et §3.3, FR et EN.
- Nouveau catalogue `i18n/messages/procedures.ts` (enregistré dans `i18n/index.ts`) ; textes des pièces jointes dans `interventions.ts` (`interventions.attachments.*`).

## 5. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `ATTACHMENTS_DIR` | `/data/attachments` | Dossier des pièces jointes, un fichier par SHA-256, volume `attachments`. |
| `ATTACHMENT_MAX_BYTES` | `5242880` (5 Mio) | Taille maximale d'un fichier, de 65 536 à 7 340 032 (7 Mio, sous le plafond de 8 Mo de Caddy). |
| `ATTACHMENT_QUOTA_BYTES` | `2147483648` (2 Gio) | Total des pièces jointes ; 0 = pas de quota. |
| `ATTACHMENT_RETENTION_DAYS` | `0` (conserver) | Valeur initiale du réglage `attachments.retention_days` (Paramètres), de 0 à 3 650. |

À ajouter à `core/config.py` (champs `Field(ge=…, le=…)`), `deploy/.env.example` (commentées, avec leur défaut), DEPLOYMENT.md (tableau « Pièces jointes », à côté de « Déploiement logiciel ») et la page des variables (`environment.py`).

**Écart voulu à la règle « Réglages » (§2 de la feuille de route).** Seule la rétention passe dans `app_settings`. `ATTACHMENTS_DIR` et `ATTACHMENT_MAX_BYTES` dépendent du déploiement (volume, plafond de Caddy), comme `PACKAGE_MAX_BYTES`. Le quota reste aussi dans l'environnement : il protège le disque qui porte la base, et sa bonne valeur dépend de la taille de ce disque, que l'exploitant voit et que la console ne voit pas ; le laisser monter depuis Paramètres permettrait à un administrateur de la console de remplir le disque du serveur. `MAX_PER_INTERVENTION` reste une constante (10) : une borne de forme, pas un choix d'exploitation. Écart inscrit aux décisions.

## 6. Jalons

| Jalon | Contenu |
|---|---|
| PJ1 | `package/storage.py` paramétré par un dossier et le reniflage (tests des paquets inchangés et verts) ; migration `0062` (les deux tables, les contraintes, les droits des techniciens, la descente) ; `features/attachment/{models,storage,crud}.py`, ajout de `InterventionAttachment` et `Procedure` à `features/models.py` ; verrous, quota, ménage, `purge_before`. |
| PJ2 | Routes (`attachments.py`), `InterventionOut.attachments`, déroulé sous verrou, journal, codes d'erreur ; ménage au démarrage, toutes les heures, après chaque suppression (pièce jointe, ligne, visite de maintenance) ; contrôle du volume monté ; réglage et job `purge_attachments` ; Dockerfile, entrypoint, compose, variables. |
| PJ3 | Console : `formatSize` dans `utils/format.ts`, service, composant, dialogue et lignes du journal, redessin des photos, aperçu, quota et volume indisponible, réglage de rétention dans Paramètres, catalogues FR/EN. |
| PR1 | Procédures serveur : ressource `procedure`, table, routes, portée, réserve aux comptes sans limite, écritures conditionnelles, journal. |
| PR2 | Procédures console : carte, avertissement, dialogue de liste, droits, catalogues (dont la troncature de `previous`). README (feuille de route), notes de version. |
| PJ4 | **En dernier, livrable seul** : sauvegarde — `backup.sh`, compose `db-backup`, DEPLOYMENT.md (variables, sauvegarde, restauration testée à la main), `.env.example` ; §8. |

Estimation révisée : environ **5 jours** au lieu des 4 de §4.7 (la concurrence, la rétention et le contrôle du volume ajoutent une demi-journée, la sauvegarde une demi-journée) ; l'icône de la carte Matériel est reportée (Hors périmètre).

## 7. Tests

### 7.1 Serveur

Outillage : la fixture autouse `_packages_in_tmp` de `tests/conftest.py` redirige aussi `ATTACHMENTS_DIR` (`monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path / "attachments"))`) ; les enveloppes de `features/attachment/storage.py` lisent `settings` à chaque appel. Les tests tournent en `ENVIRONMENT=local` (`conftest.py`) : le contrôle du volume monté est testé avec `ENVIRONMENT` et `os.path.ismount` monkeypatchés.

`tests/test_api_attachments.py` :
- Dépôt d'un JPEG, d'un PNG, d'un WebP, d'un PDF : 201, `content_type` reconnu même quand le client envoie `text/html` ou `application/octet-stream`.
- Refus 415 d'un SVG, d'un HTML, d'un GIF, d'un fichier vide, d'un HTML renommé `.jpg`, aucun fichier ni `.upload-*` laissé ; un PNG renommé `.pdf` passe, servi en `image/png` sous le nom `x.pdf.png`.
- Nom : chemin Windows et POSIX retiré, caractères de contrôle retirés, 200 caractères, vide → `piece-jointe`.
- 413 au-delà de `ATTACHMENT_MAX_BYTES` (monkeypatch), aucun fichier ni `.upload-*` laissé.
- 409 `attachment.too_many` au 11ᵉ fichier d'une ligne ; **deux sessions qui déposent le 10ᵉ fichier en parallèle : une seule passe**.
- 409 `attachment.duplicate` pour le même fichier joint deux fois à la même ligne ; le même fichier sur une autre ligne passe.
- Ligne supprimée entre le pré-contrôle et l'insertion (suppression dans une autre session pendant `hold`) → 404 `intervention.not_found`, pas 500, fichier retiré.
- Quota : 413 quand le fichier dépasse ; un fichier déjà stocké (même empreinte) ne compte pas deux fois ; le fichier refusé est supprimé du disque (`discard_if_orphan`) ; deux dépôts simultanés ne passent pas tous deux (deux sessions, verrou) ; `ATTACHMENT_QUOTA_LOCK` distinct de `counter/quota.py:QUOTA_LOCK` et de `user/crud.py:ACCOUNT_MANAGEMENT_LOCK`.
- Volume non monté hors `local` : 503 `attachment.store_unavailable` au dépôt, `store_available: false` dans `/attachments/policy`, téléchargement et suppression permis.
- Téléchargement : octets identiques, `Content-Disposition: attachment` produit par Starlette (nom avec `"`, `;` et accents → `filename*=utf-8''…`, aucun `"` non échappé), `X-Content-Type-Options: nosniff`, CSP `sandbox`, `Cache-Control: no-store`, `Content-Type` reconnu ; fichier absent du disque → 404 `attachment.file_missing`.
- Portée : compte limité à un autre site → 404 sur la liste, le dépôt, le téléchargement, la suppression ; `used_bytes` nul pour lui dans `/attachments/policy`.
- Droits : sans `intervention:read` 403 ; sans `intervention:write` 403 sur dépôt et suppression ; un jeton d'API en lecture seule télécharge mais ne dépose pas.
- Journal : `intervention.attachment_add` / `attachment_delete` avec leurs détails, dans la même transaction (dépôt refusé → pas d'entrée) ; `intervention.delete` compte les pièces jointes.
- Liste du journal : `attachments` rempli pour chaque ligne en une requête (compte des requêtes, ou au moins une page de 25 lignes à 2 pièces jointes) ; ordre par `created_at`.
- Suppressions : après `DELETE /attachments/{id}` et `DELETE /interventions/{id}`, le fichier orphelin est retiré aussitôt (`discard_if_orphan`, sans `sweep_store`) ; un fichier partagé par deux lignes reste tant que l'une le nomme.
- Maintenance : supprimer une visite dont une ligne porte une photo → `maintenance.delete` porte `attachments: 1`, rangée et fichier retirés.
- Fusion (`merge_into`) : les pièces jointes suivent la ligne vers le poste gardé.
- Rétention : `purge_attachments` avec 0 ne supprime rien ; avec N jours supprime les rangées plus vieilles, pas les plus récentes, ne touche aucun fichier ; le ménage suivant retire les fichiers devenus orphelins. Réglage `attachment_retention_days` servi et modifiable par `routes/settings_routes.py`, valeur initiale de l'environnement.

`tests/test_attachment_store.py` :
- `sweep_store` : supprime un orphelin, garde un fichier nommé, garde un fichier tenu par `hold_file` dans une autre session, garde tout quand `machines` est vide, supprime les `.upload-*` de plus de 24 h, n'échoue pas sur un volume en lecture seule.
- Espaces de verrous distincts : tenir un fichier de paquet n'empêche pas le ménage d'une pièce jointe de même préfixe d'empreinte, et inversement.
- `package/storage.py` paramétré : les tests existants des paquets (`test_api_packages.py`, `test_api_packages_acceptance.py`, `test_api_packages_verification.py`) passent sans changement ; `save(..., directory=…, sniff=…)` écrit dans le dossier donné et refuse avant écriture.

`tests/test_api_procedures.py` :
- Création depuis un modèle présent : 201, journal `procedure.create` ; modèle absent du parc → 422 `procedure.model_unknown` ; modèle présent sur un seul poste réformé → 201 ; doublon → 409 `procedure.exists` ; espaces de bord retirés ; 201 caractères de modèle → 422.
- Modification avec `expected_updated_at` juste → 200, journal avec `previous` ; périmé → 409 `procedure.changed`, rien d'écrit ; texte vide → 422 ; 5 001 caractères → 422.
- Concurrence (deux sessions) : deux `PATCH` avec le même `expected_updated_at` → un 200 et un 409 `procedure.changed` ; deux `POST` du même modèle → un 201 et un 409 `procedure.exists`, jamais 500.
- Suppression → 204, journal avec `previous` ; `expected_updated_at` périmé → 409.
- `GET /machines/{id}/procedure` : note du modèle, `null` sans note, `hw_model` nul sans inventaire ; poste hors portée → 404.
- Portée : compte limité ne voit que les modèles de sa portée, `machine_count` compté dans sa portée et sans les postes réformés ; il reçoit 403 `procedure.scope_limited` sur `POST`, `PATCH`, `DELETE`, même pour un modèle de sa portée ; un compte sans limite modifie la note d'un modèle sans poste.
- Droits : sans `procedure:read` 403 ; sans `procedure:write` 403 en écriture.

Autres :
- `tests/test_permissions.py` : `procedure:read` et `procedure:write` chez les techniciens, absents de « Lecture seule » ; catalogue = console (test existant de parité).
- `tests/test_migration_0062.py` : montée et descente ; droits accordés au seul groupe `builtin_key = 'technician'` même renommé, ni à « Lecture seule » ni aux groupes de l'exploitant ; pas de doublon si déjà présents ; après la descente, plus aucune ligne `procedure:*` dans `group_permissions` ni de tables.
- `tests/test_backup_script.py` : copie des pièces jointes après un dump réussi, pas de recopie d'un fichier présent sous l'une ou l'autre forme (date rafraîchie), variante chiffrée `.age`, passage au chiffrement (copie en clair remplacée puis supprimée), droits `700`/`600`, purge des copies plus vieilles que `BACKUP_KEEP_DAYS` absentes du volume, rien de purgé si le dump échoue, volume absent → dump seul et code 0.
- `tests/test_errors_unit.py` : chaque nouveau `ErrorCode` a un texte FR et EN (test existant de parité).
- `features/setting/environment.py` : les quatre variables listées.

### 7.2 Console

- `services/attachments.spec.ts` : `prepareImage` redessine **tout** JPEG et WebP, même petit (mock de `createImageBitmap`, `canvas.toBlob`), réduit au-delà de 2 560 px, garde un petit PNG tel quel, ne touche pas un PDF ; `downloadAttachment` appelle `downloadBlob` avec le nom de la pièce jointe.
- `utils/format.spec.ts` : `formatSize` (déplacé), et `services/packages.spec.ts` inchangé.
- `components/machine/InterventionAttachments.spec.ts` : puces, tailles, icônes ; aperçu d'une image en URL `data:` ; pas de bouton de suppression en lecture ; suppression confirmée ; refus avant envoi d'un type ou d'une taille hors politique ; ajout grisé quand `store_available` est faux ; avertissement à 90 % du quota ; message d'erreur serveur affiché.
- `MachineHistoryCard.spec.ts` : création d'une ligne puis envoi de deux fichiers, l'un refusé (notification qui le nomme, ligne gardée) ; les pièces jointes apparaissent sur la ligne ; `canWrite=false` : liste sans ajout.
- `MachineProcedureCard.spec.ts` : note affichée en `pre-line`, sans note avec et sans `procedure:write`, compte limité sans bouton d'écriture, modèle inconnu, édition avec l'avertissement, `procedure.changed` → relecture et message, suppression.
- `ProceduresListDialog.spec.ts` : liste, ouverture, suppression d'une note sans poste.
- `MachineDetailPage.spec.ts` : onglet « Interventions » visible avec `procedure:read` seul ; carte placée en tête.
- Catalogues : `permissions.en.spec.ts`, `auditLabels.spec.ts` et `auditLabels.en.spec.ts` (nouvelles clés, `previous` tronqué à 120 caractères), `services/errors.spec.ts` et `i18n/index.spec.ts` couvrent les nouvelles clés ; `MachineCards.i18n.spec.ts` pour les textes anglais des deux cartes.

### 7.3 Migration : descente

`downgrade()` de `0062_attachments_procedures` : `DELETE FROM group_permissions WHERE permission IN ('procedure:read', 'procedure:write')` (l'ancien `PERMISSION_CATALOGUE` refuserait ces droits à la prochaine écriture du groupe), `DELETE FROM app_settings WHERE key = 'attachments.retention_days'`, puis `drop_table` de `procedures` et de `intervention_attachments` (index et contraintes compris). Les fichiers du volume `attachments` restent : l'ancienne version ne les lit ni ne les supprime ; une remontée ultérieure, sans rangée pour les nommer, les retire au premier ménage. À dire dans les notes de version.

## Hors périmètre

- Pièces jointes ailleurs que sur une ligne du journal : sur une vérification ouverte, un signalement (C4, page publique sans compte), une maintenance entière, un actif (facture d'achat), un paquet. `package/storage.py`, paramétré par un dossier, les permettra plus tard.
- Ajout de fichiers depuis l'assistant de maintenance ou le dialogue de clôture d'une vérification : la ligne qu'ils écrivent reçoit ses fichiers depuis la fiche.
- Miniatures, conversion HEIC, toute retouche côté serveur (le retrait des métadonnées EXIF se fait dans la console, §2.1), analyse antivirale des fichiers.
- Liste globale des pièces jointes (par taille, par date) pour choisir quoi supprimer : la rétention et le quota en tiennent lieu.
- Icône « procédure » à côté du modèle sur `MachineHardwareCard.vue` : la carte de procédure en tête de l'onglet « Interventions » suffit pour cette version.
- Markdown, liens cliquables, images dans les procédures ; procédures par fabricant, par salle ou par logiciel ; versions consultables autrement que par le journal d'audit.
- Écriture des procédures par un compte limité à des lieux.
- Recherche dans le texte des procédures et des pièces jointes.

## Décisions prises par défaut (à confirmer)

1. **Pas de miniatures** ; aperçu à la demande dans la console en URL `data:`.
2. **Types** : JPEG, PNG, WebP, PDF seulement (HEIC et GIF refusés).
3. **Limites** : 5 Mio par fichier (7 Mio au plus sans toucher Caddy), 10 par ligne, quota de 2 Gio, le même fichier une seule fois par ligne.
4. **Quota et taille dans l'environnement**, pas dans `app_settings` : écart voulu à la règle « Réglages » (§5) — le quota protège le disque de la base, que seul l'exploitant voit.
5. **Rétention réglable** dans Paramètres (`attachments.retention_days`), 0 = conserver par défaut ; **1 825 jours (5 ans) proposés**, à fixer avec le DPO. Purge des rangées par le worker, des fichiers par le ménage horaire de l'API.
6. **Dépôts refusés (503) quand le volume n'est pas monté**, hors développement.
7. **Redessin systématique des JPEG et WebP dans la console** (2 560 px, JPEG 0,85, EXIF et position GPS retirés) ; le serveur ne retouche jamais un fichier.
8. **Pièces jointes dans la sauvegarde** quotidienne, copie incrémentale dans `deploy/backups/attachments/`, chiffrée avec les dumps, même rétention ; livrée en dernier.
9. **Droits des pièces jointes = ceux de l'intervention** ; pas de ressource à part.
10. **Procédures en texte brut**, une note par modèle, clé `hw_model` exacte, avertissement contre les secrets.
11. **Ressource `procedure`** : lecture et écriture aux seuls « Techniciens » (et implicitement aux administrateurs), accordées par la migration au groupe intégré ; « Lecture seule » ne reçoit rien.
12. **Écriture des procédures réservée aux comptes sans limite de lieux** (403 `procedure.scope_limited`) ; un compte limité lit seulement.
13. **Historique par le journal d'audit** (texte remplacé dans `previous`), pas de table de versions.
14. **Édition sur la fiche**, liste complète dans un dialogue ouvert depuis la carte, pas de page ni de carte dans Paramètres ; pas d'icône sur la carte Matériel.

## 8. Écarts constatés à l'implémentation

Partie serveur (PJ1, PJ2, PR1, PJ4) :

1. **Ménage périodique nommé `attachment_crud.sweep_attachments_periodically`**, pas `sweep_periodically` : `test_api_packages_acceptance.py` reconnaît la tâche du ménage des paquets au nom de sa coroutine et en attend une seule. Garder ce nom aurait obligé à modifier un test des paquets, que §2.1 veut inchangés.
2. **`package/storage.py:save` lit le premier bloc avant de créer le temporaire** : un type refusé ne crée aucun `.upload-*` (plus strict que « le temporaire est supprimé »). `Stored` gagne `content_type` (None sans reniflage) et le module une exception `Unrecognised`. Sans `sniff`, le comportement des paquets est inchangé (tests des paquets verts sans modification).
3. **`AttachmentOut` est dans `features/attachment/schemas.py`** : partagé par `routes/attachments.py` et `routes/interventions.py:InterventionOut` sans import circulaire (la route des pièces jointes réutilise `_require_intervention`).
4. **Nom de fichier** : tous les caractères Unicode de catégorie C sont retirés (contrôle, mais aussi format, dont U+202E qui retourne l'affichage d'un nom) ; un nom vide devient `piece-jointe` **plus l'extension du type reconnu** (`piece-jointe.png`), la règle de l'extension s'appliquant à tous les noms ; au-delà de 200 caractères, le nom est coupé avant son extension, qui reste.
5. **`DELETE /interventions/{id}` verrouille la ligne (`FOR UPDATE`) avant de lire ses empreintes** : un dépôt en cours tient la ligne `FOR SHARE` ; la suppression l'attend et compte sa pièce jointe dans `attachments`, et son fichier part avec les autres. La suppression d'une visite de maintenance ne verrouille pas ses lignes : un dépôt achevé au même instant sur l'une d'elles laisse un fichier que le ménage horaire retire.
6. **Procédures : bords du texte retirés** à la création et à la modification (`" F10 \n"` → `"F10"`), comme pour le modèle ; `GET /procedures` rend une liste JSON (sans enveloppe de pagination, 500 au plus).
7. **`backup.sh`, échec de copie** : journal « ECHEC de la copie des pièces jointes », pas de purge de la copie, mais **le script ne s'arrête pas en code 1** : il tourne en boucle, et un arrêt ferait redémarrer le conteneur avec un dump de plus à chaque redémarrage. Le tour se clôt par « sauvegarde OK » (le dump, lui, est bon). Les fichiers temporaires de copie sont `<sha>.tmp` / `<sha>.age.tmp` (ceux que la commande de restauration saute), purgés avec les copies trop vieilles.
8. **Tests de `backup.sh` non exécutables dans la session d'implémentation** : l'environnement place un garde-fou devant `rm` qui ne trouve pas de « vrai » `rm` dans le `PATH` réduit des tests ; les 13 tests de sauvegarde qui atteignent `rm` échouaient déjà ainsi avant C11. Les nouveaux cas qui n'appellent pas `rm` passent ; les autres sont à confirmer par la CI.
9. **Restauration des pièces jointes non rejouée à la main** (pas de Docker dans la session) : la procédure de DEPLOYMENT.md reprend §2.6 telle quelle et reste à vérifier une fois.
10. **Catalogues de la console laissés au jalon console** (comme pour C10) : `errorCodes.ts` (les treize codes), `audit.ts` (`intervention.attachment_add|delete`, `procedure.*`, ressource `procedure`), `settingsEnv.ts` (groupe `attachments`), `permissions.ts`. D'ici là, `test_errors_unit.py::test_every_code_has_a_message_in_the_console` et `::test_every_audit_action_has_a_label_in_the_console` échouent, et `serverEnvironment.spec.ts` de la console attend les textes du groupe `attachments`.

Partie console (PJ3, PR2) :

11. **`GET /machines/{id}/procedure` gagne `scope_limited`** (petit ajout au serveur, test `test_the_fiche_reads_the_note_of_its_model` complété) : le profil (`/auth/me`) ne dit pas si un compte est limité à des lieux, et la console devait masquer « Écrire la procédure », « Modifier » et « Supprimer » pour lui (§4.2) sans attendre un 403. La carte le dit en une ligne quand le compte détient `procedure:write`. `GET /procedures` reste une liste nue : le dialogue reçoit de la carte le droit d'écrire.
12. **`ProcedureEditDialog.vue`** en plus des deux composants nommés : le dialogue d'écriture est partagé par la carte et par la liste. Sur `procedure.changed` (et sur `procedure.exists` à la création), le dialogue reste ouvert avec le texte tapé, la carte ou la liste relit la note, et une notification le dit.
13. **`formatSize`** est dans `utils/format.ts` avec ses textes sous `format.size.*` (`bytes`, `kib` ajoutés à côté de `mib`, `gib`, `tib`) ; `packagePages.size` ne garde que `gib`, celui de `methodAMaxLabel`. `services/packages.ts` le réexporte.
14. **Liste des notes** : une ligne repliable par modèle (modèle, « n poste(s) en service » ou « aucun poste », dernière modification) qui s'ouvre sur le texte, avec « Modifier » et « Supprimer » ; pas de tableau.
15. **Ajout des fichiers** : `q-file` multiple, chaque fichier préparé puis vérifié à son tour ; sur une ligne existante il part aussitôt (puce ajoutée, journal relu à la fermeture du dialogue), sur une ligne en création il attend (puce « Envoyé une fois l'intervention enregistrée ») et part après la création, un par un, avec une barre de progression. Les refus d'après la politique (type, taille même après réduction, onze fichiers) sont dits avant tout envoi ; une photo que le navigateur ne sait pas décoder est refusée plutôt qu'envoyée telle quelle (elle partirait avec sa position). Sans droit de lire la politique, la photo est quand même redessinée et le serveur juge seul.
16. **Le contrôle de type avant envoi lit le type que le navigateur déduit de l'extension** (`File.type`) : un fichier sans type reconnu est refusé par la console même si son contenu est accepté ; le serveur reste seul juge du contenu.
17. **Aperçu** : l'URL `data:` est construite à partir des octets reçus et du type reconnu par le serveur (`content_type`), jamais du type de la réponse ; un PDF n'a pas d'aperçu. Une erreur reçue en `Blob` (téléchargement) est relue en JSON, pour que « fichier absent du serveur » s'affiche.
18. **Un 413 du proxy** (sans enveloppe d'erreur) est dit « Fichier trop volumineux pour une pièce jointe », et non par le texte des paquets que `apiErrorMessage` emploie par défaut.
19. **Carte « Pièces jointes » de Paramètres** : affichée seulement quand le serveur sert `attachment_retention_days` (serveur plus ancien : rien), comptée dans les cartes non enregistrées.
20. **Textes anglais vérifiés dans les specs des composants** (`InterventionAttachments.spec.ts`, `MachineProcedureCard.spec.ts`, `ProceduresListDialog.spec.ts`) plutôt que dans `MachineCards.i18n.spec.ts`, qui monte des cartes sans service ; `errors.spec.ts` et `i18n/index.spec.ts` couvrent les nouvelles clés sans modification (parité des catalogues).
21. **Restauration des pièces jointes toujours pas rejouée à la main** (point 9) : à faire une fois sur une installation Docker. `deploy/.env.example` était déjà complet depuis la partie serveur.
