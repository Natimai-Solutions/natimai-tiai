# Déploiement logiciel : plan de travail

> **Statut : cadrage validé et implémenté le 2026-11-04** (J1 à J4, J5 hors
> validation sur poste réel — cf. §8). Trois façons d'installer, chacune
> coupée tant qu'une GPO ne l'a pas ouverte sur le poste :
>
> - **winget** — un identifiant du dépôt communautaire ; c'est winget qui
>   télécharge et vérifie l'empreinte publiée dans le manifeste ;
> - **paquet signé par l'administrateur (méthode B)** — un ou plusieurs
>   fichiers déposés dans la console, une ligne de commande, le tout décrit par
>   un manifeste que l'administrateur signe **hors du serveur**, avec un
>   certificat que les postes connaissent par GPO ;
> - **paquet d'un éditeur approuvé (méthode A, repli)** — un `.exe` signé
>   Authenticode par un éditeur dont la GPO a approuvé le nom (ex. INDEX
>   EDUCATION SAS pour Pronote), sans signature de l'administrateur.
>
> Objectif : installer ou désinstaller un logiciel depuis la console sur un
> poste, une sélection ou un filtre, et savoir où il est présent.
> Dernière brique de la Phase 3 (cf. `plan-projet-tiai.md` §Phase 3).

---

## 1. Le problème de fond : ce chantier rompt le catalogue fermé

La sûreté du canal de commandes repose sur une règle
(`plan-commandes-distantes.md` §1) : aucun argument ne traverse le réseau,
donc **même un serveur compromis ne fait pas exécuter de code arbitraire** à un
parc qui tourne en `LocalSystem`. Installer un logiciel, c'est exécuter du code
choisi ailleurs. La garantie est conservée en déplaçant la confiance du serveur
vers le poste : **les ancres de confiance sont posées par GPO** (registre
`HKLM\SOFTWARE\Tiai`, jamais le YAML, jamais le serveur), et un serveur
compromis ne peut au pire déclencher que ce qu'elles autorisent.

| Méthode | Ancre posée par GPO | Ce qu'un serveur compromis peut faire |
|---|---|---|
| B — paquet signé | `DeploySigners` : empreintes SHA-256 des certificats de signature de l'administrateur | Rejouer un paquet déjà signé (installer ou désinstaller un paquet que l'administrateur a approuvé). Rien d'autre : fichiers et ligne de commande sont dans le manifeste signé. |
| A — éditeur approuvé | `DeployPublishers` : sujets des certificats d'éditeurs | Lancer un installateur légitime de cet éditeur avec des arguments de son choix. Résiduel, documenté ; c'est pourquoi A est le repli. |
| winget | `DeployWinget=1`, et facultativement `DeployWingetAllow` (identifiants autorisés) | Installer un paquet du dépôt winget (ou de la liste autorisée si elle est posée). |

La signature B **ne passe pas par le serveur** : la console fabrique le
manifeste, l'administrateur le télécharge, le signe sur son poste avec
`deploy/packages/Sign-TiaiPackage.ps1` et un certificat de signature de code
(celui de l'AC interne qui signe déjà l'agent convient), puis renvoie la
signature. Le serveur vérifie qu'elle est valide pour l'afficher, mais c'est le
poste qui décide.

## 2. Modèle

### 2.1 `packages`

| Colonne | Rôle |
|---|---|
| `id`, `name`, `version`, `notes` | Affichage. |
| `kind` | `winget` ou `files`. |
| `winget_id`, `winget_version` | winget : identifiant exact (`Mozilla.Firefox`), version facultative. |
| `install_run`, `install_args` | files : le fichier du paquet à lancer, et ses arguments (liste). `{dir}` y désigne le dossier où l'agent a déposé les fichiers. |
| `uninstall_run`, `uninstall_args` | files : idem, facultatif. `uninstall_run = "msiexec"` avec un code produit permet la désinstallation d'un MSI. |
| `success_codes` | Codes de sortie acceptés (défaut `0, 3010, 1641` ; 3010/1641 = redémarrage requis). |
| `detect_name` | Nom (motif) sous lequel le logiciel apparaît dans l'inventaire : « installé sur N postes ». |
| `manifest` | Les octets exacts du manifeste (JSON), régénérés à chaque modification. |
| `signature`, `signer_certificate`, `signer_thumbprint`, `signer_subject`, `signed_at`, `signed_by` | Méthode B. Effacés dès que le manifeste change. |
| `publisher_subject` | Méthode A : sujet du certificat Authenticode du fichier lancé, lu au dépôt (information ; c'est le poste qui vérifie). |
| `created_by`, `created_at`, `updated_at`, `retired_at` | Un paquet retiré n'est plus proposé ; l'historique des commandes reste. |

### 2.2 `package_files`

`(package_id, name, sha256, size)`. Les octets vivent sur le volume
`packages`, un fichier par empreinte (`<sha256>`), immuable : deux paquets qui
embarquent le même installateur le partagent.

### 2.3 Manifeste (`tiai-package-1`)

```json
{"format": "tiai-package-1", "package_id": "…", "name": "Client PRONOTE",
 "version": "2026.2.8",
 "files": [{"name": "Install_PRNclient_FR_2026.2.8_win64.exe", "sha256": "…", "size": 123},
           {"name": "ClientPRONOTE.iss", "sha256": "…", "size": 456}],
 "install": {"run": "Install_PRNclient_FR_2026.2.8_win64.exe", "args": ["-s", "-f1{dir}\\ClientPRONOTE.iss"]},
 "uninstall": null, "success_codes": [0, 3010, 1641]}
```

La signature porte sur **ces octets-là**, tels que le serveur les a écrits et
les renvoie : pas de canonicalisation à reproduire ailleurs.

## 3. Commandes

Deux types, `package_install` et `package_uninstall`, dans
`RISKY_COMMAND_TYPES`. Colonne `commands.package_id` (FK, `SET NULL`). La
règle « une commande ouverte par (poste, type) » devient « par (poste, type,
paquet) » pour ces deux types. La livraison porte le paquet entier : manifeste,
signature, certificat, fichiers (nom, empreinte, taille), identifiant winget.

## 4. Agent

Ordre des vérifications, avant toute exécution :

1. **winget** : `DeployWinget=1`, identifiant valide (motif strict), présent
   dans `DeployWingetAllow` si elle existe. `winget.exe` est résolu sous
   `%ProgramFiles%\WindowsApps\Microsoft.DesktopAppInstaller_*` (le plus
   récent), la commande `winget` n'étant pas dans le `PATH` de `LocalSystem`.
   Arguments fixés par l'agent : `--exact --source winget --scope machine
   --silent --accept-package-agreements --accept-source-agreements
   --disable-interactivity`.
2. **files** : téléchargement de chaque fichier (reprise par `Range`) dans
   `C:\ProgramData\Tiai\packages\<id>` (ACL de `C:\ProgramData\Tiai` :
   SYSTEM et Administrateurs), empreinte SHA-256 vérifiée contre le manifeste.
3. **Méthode B** si le paquet est signé : le certificat joint a une empreinte
   SHA-256 présente dans `DeploySigners`, et la signature (RSA PKCS#1 v1.5 ou
   ECDSA, SHA-256) est valide sur les octets du manifeste. Le manifeste fait
   alors foi pour les fichiers et la ligne de commande.
4. **Sinon, méthode A** : le fichier lancé est un `.exe` dont la signature
   Authenticode est valide (`WinVerifyTrust`, révocation comprise) et dont le
   sujet signataire figure dans `DeployPublishers`. La désinstallation par
   `msiexec` n'y accepte qu'un `/x {code produit}` construit par l'agent.
5. **Sinon : refus**, avec la raison dans le résultat de la commande.

Exécution : le fichier est lancé directement (jamais via `cmd.exe` ni
PowerShell), arguments en liste ; jamais de redémarrage automatique. Après un
succès, l'agent relance la collecte d'inventaire pour que la console voie le
logiciel sans attendre le cycle quotidien.

## 5. Console

- **Logiciels › Paquets** : liste (nom, version, méthode, état de la
  signature, présence d'après l'inventaire), création winget ou fichiers,
  dépôt des fichiers, téléchargement du manifeste à signer, dépôt de la
  signature, retrait.
- **Déployer** : depuis la fiche d'un paquet (sur un poste, une sélection ou
  un filtre de la liste des postes) et dans le menu de commandes d'un poste.
- **Permissions** : `package:read`, `package:write` (déposer, signer,
  retirer) ; lancer = `risky_command:execute`.

## 6. Jalons

| Jalon | Contenu |
|---|---|
| J1 | Backend : tables, migration, stockage, dépôt de fichiers, manifeste, vérification de signature B, lecture du signataire Authenticode, API, permissions, audit. |
| J2 | Backend : types de commande, `package_id`, dédoublonnage par paquet, livraison, téléchargement agent (`Range`). |
| J3 | Agent : clés GPO, winget, téléchargement, vérifications B/A, exécution, inventaire après coup. |
| J4 | Console : page Paquets, déploiement, menus de commandes. |
| J5 | Script de signature, documentation (activation par GPO, utilisation), validation sur poste réel. |

## 7. Points d'attention

- **Postes sans winget** (LTSC, Server) : refus explicite, « App Installer
  absent » ; passer par un paquet B.
- **Pronote** : installation silencieuse InstallShield, `.exe` + `.iss`
  enregistré ; l'éditeur signe (INDEX EDUCATION SAS, SHA-256, horodaté) : A
  fonctionne, B aussi.
- **Taille** : la route de dépôt accepte de gros fichiers (2 Gio par défaut),
  les autres gardent la limite de 8 Mio de Caddy.
- **Sauvegarde** : le volume `packages` est à sauvegarder avec la base, ou à
  considérer comme reconstructible depuis les installateurs d'origine.
- **SHA-256, pas SHA-1**, pour l'empreinte des certificats de signature : c'est
  une ancre de confiance, et les collisions SHA-1 à préfixe choisi existent.

## 8. État de réalisation *(2026-11-04)*

- **J1–J2 (backend)** : migration `0029_packages`, stockage par empreinte,
  manifeste régénéré à chaque modification (la signature tombe avec lui),
  vérification RSA/ECDSA, lecture du signataire Authenticode des `.exe`
  déposés, commandes `package_install`/`package_uninstall` dédoublonnées par
  paquet, livraison au heartbeat, téléchargement réservé aux postes ayant une
  commande ouverte (`Range`, 429). Tests : `tests/test_api_packages.py`.
- **J3 (agent)** : `internal/deploy`, Go pur testé hors Windows (manifeste,
  méthode B, lecture Authenticode par émetteur et numéro de série comme
  Windows, winget, téléchargement repris et vérifié) ; `WinVerifyTrust` et la
  localisation de `winget.exe` sous Windows. Clés GPO relues à chaque
  commande.
- **J4 (console)** : pages Paquets et fiche d'un paquet (définition, fichiers,
  confiance, déploiements), boîte « Installer un logiciel » sur la fiche d'un
  poste, la sélection de la liste et la page du paquet.
- **J5** : `deploy/packages/Sign-TiaiPackage.ps1` et le guide
  `deploy/packages/README.md`.

**Écart au cadrage** : l'empreinte des certificats et les noms d'éditeurs. Le
§1 prévoyait de comparer des *sujets* de certificat ; trois outils (PowerShell,
Go, Python) ne les écrivent pas de la même façon (`S=` contre `ST=`, ordre,
espaces), et un administrateur recopie le nom depuis l'onglet *Signatures
numériques*. `DeployPublishers` porte donc le **nom du signataire** (CN), la
chaîne étant validée par Windows. `msiexec` est accepté en installation comme
en désinstallation (un MSI ne se lance pas lui-même), en méthode B seulement.

**Reste à valider sur poste réel** — rien de ce qui suit ne peut l'être
ailleurs :

1. winget en `LocalSystem` : localisation de `winget.exe`, installation et
   désinstallation de `Mozilla.Firefox`, code « déjà installé » ;
2. Pronote en méthode A : `WinVerifyTrust` sur l'installateur réel, nom du
   signataire lu, installation silencieuse `.iss`, code 3010 éventuel ;
3. un paquet signé (méthode B) avec le certificat de l'AC interne, signé par
   `Sign-TiaiPackage.ps1` sous Windows PowerShell 5.1 (RSA, et ECDSA si le
   certificat l'est) ;
4. les refus : paquet non signé sans éditeur approuvé, empreinte absente de
   `DeploySigners`, fichier altéré après dépôt ;
5. Caddy : le dépôt d'un installateur de plusieurs centaines de Mo à travers la
   route à 2 Go, les autres routes restant à 8 Mo.

