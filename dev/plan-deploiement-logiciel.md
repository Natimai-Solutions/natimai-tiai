# Déploiement logiciel : plan de travail

> **Statut : proposition de cadrage (2026-11-03), à valider avant tout code.**
> Les décisions marquées **[à valider]** au §9 engagent le modèle de sécurité du
> produit ; le reste en découle.
>
> Objectif : depuis la console, **installer ou désinstaller un logiciel** sur un
> poste, une salle ou une sélection de postes, et savoir où il a réussi.
> Dernière brique de la Phase 3 (cf. `plan-projet-tiai.md` §Phase 3).
> Réutilise l'agent, la file de commandes, le statut `running`, le catalogue
> logiciel de l'inventaire (`software.id`) et la commande `inventory_scan`.

---

## 1. Le problème de fond : ce chantier rompt le catalogue fermé

Toute la sûreté du canal de commandes repose aujourd'hui sur une règle
(`plan-commandes-distantes.md` §1) : **aucun argument ne traverse le réseau**,
l'agent n'exécute qu'une entrée de son propre catalogue, donc **même un serveur
compromis ne peut pas faire exécuter de code arbitraire** à un parc qui tourne
en `LocalSystem`.

Installer un paquet, c'est exactement exécuter du code fourni par le serveur.
On ne peut pas garder la règle telle quelle ; on peut en garder **la garantie**
en déplaçant la confiance du serveur vers le poste :

> **Le poste n'installe qu'un paquet signé par un éditeur que la GPO a
> approuvé, et dont l'empreinte correspond à celle que le serveur annonce.**

- **La liste des éditeurs approuvés vit sur le poste, posée par GPO**
  (registre `HKLM\SOFTWARE\Policies\Tiai\Agent\DeployPublishers`, ou
  `deploy_publishers` dans `config.yaml`), **jamais envoyée par le serveur**.
  Un serveur compromis peut alors au pire installer, sur les postes, un paquet
  *légitime* d'un éditeur approuvé : il ne peut pas fabriquer de binaire signé.
- **Fonction coupée par défaut** : un agent sans `DeployPublishers` refuse toute
  commande de déploiement avec un message explicite (« déploiement non activé
  sur ce poste »). L'activer est un geste d'administrateur du domaine, pas de
  la console : c'est ce qui garde le parc actuel exactement aussi sûr
  qu'aujourd'hui tant que personne ne décide autrement.
- **Vérifications côté agent, dans cet ordre, avant toute exécution** :
  1. empreinte SHA-256 du fichier téléchargé = celle annoncée dans la commande ;
  2. signature Authenticode valide, chaîne vérifiée par `WinVerifyTrust`
     (révocation comprise), horodatage accepté ;
  3. sujet du certificat signataire présent dans `DeployPublishers`.
  Un échec à n'importe quelle étape = `failed`, fichier supprimé, rien lancé.
- **Ligne de commande fixée par l'agent**, pas par le serveur : pour un MSI,
  `%SystemRoot%\System32\msiexec.exe /i <fichier> /qn /norestart /l*v <journal>`
  et rien d'autre. Aucune propriété MSI, aucun argument libre (cf. §2 pour le
  cas des `.exe`).
- **Jamais de redémarrage automatique**, comme pour Windows Update : un code
  3010 remonte « redémarrage requis » ; le redémarrage reste la commande
  `reboot`, à part.

Pourquoi l'**empreinte** en plus de la signature : la signature dit *qui*,
l'empreinte dit *quoi*. Sans elle, un serveur compromis pourrait substituer un
autre paquet du même éditeur (une version ancienne et vulnérable, par exemple)
à celui que l'administrateur a choisi. Avec elle, la console et le poste
parlent du même fichier, à l'octet près.

## 2. Cadrage proposé

| Sujet | Proposition |
|---|---|
| Formats | **MSI seul** dans cette itération. Silencieux, désinstallable (`ProductCode`), journalisé et codes de retour normalisés : tout ce dont le suivi a besoin. Les `.exe` ont chacun leurs commutateurs silencieux : les accepter, c'est accepter un argument libre, donc revenir sur §1. Un `.exe` passe par un MSI de repackaging signé avec le certificat interne. |
| Désinstallation | `msiexec /x {ProductCode} /qn /norestart` : le `ProductCode` est lu **dans le MSI** par le serveur au dépôt, validé comme GUID, jamais saisi. |
| Stockage | Volume Docker `packages` monté sur le backend, un fichier par empreinte (`<sha256>.msi`), **immuable** : une version déposée ne se remplace jamais, elle se retire. Sauvegardé avec le reste (`deploy/backup`). |
| Taille maximale | 1 Gio par paquet (`PACKAGE_MAX_BYTES`), la limite `request_body` de Caddy ne valant que pour la route de dépôt. |
| Distribution | L'agent télécharge **depuis le serveur Tia'i**, en HTTPS, avec son token : `GET /api/v1/agent/packages/{id}/content`, refusé si le poste n'a pas de commande ouverte sur ce paquet. Pas de partage SMB : il faudrait des droits machine sur un partage, et une seconde source de vérité. |
| Reprise | En-têtes `Range` : un téléchargement interrompu reprend où il s'est arrêté (portables, Wi-Fi). Cache dans `C:\ProgramData\Tiai\packages`, ACL SYSTEM + Administrateurs, purgé après l'installation. |
| Effet de masse | Le polling étale déjà naturellement ; le serveur borne en plus le nombre de téléchargements simultanés (`PACKAGE_MAX_CONCURRENT_DOWNLOADS`, 20) et répond `429 + Retry-After` au-delà, que l'agent respecte sans faire échouer la commande. |
| Permissions | Nouvelle ressource `package` : `package:read` (voir le dépôt), `package:write` (déposer, retirer). Lancer un déploiement = `risky_command:execute` : installer change le poste pour de bon. |
| Audit | `package.upload`, `package.retire`, `command.bulk` (existant) pour un déploiement groupé. |
| Confirmation | Après un `software_install` réussi, l'agent enchaîne une collecte d'inventaire : la fiche du poste montre le logiciel sans attendre le cycle quotidien. |

## 3. Modèle de données

### 3.1 `packages`

| Colonne | Type | Rôle |
|---|---|---|
| `id` | uuid | |
| `sha256` | char(64), unique | Identité du fichier ; nom sur disque. |
| `size_bytes` | bigint | |
| `filename` | text | Nom d'origine, pour l'affichage seulement. |
| `product_name`, `product_version`, `manufacturer` | text | Lus dans la table `Property` du MSI au dépôt. |
| `product_code` | uuid | Idem ; sert à la désinstallation et au rapprochement. |
| `signer_subject` | text | Sujet du certificat, lu au dépôt — information pour la console, **pas** une autorisation (c'est le poste qui décide, §1). |
| `software_id` | bigint, FK `software.id`, nullable | Rattachement au catalogue d'inventaire sur (nom, version, éditeur), quand ce triplet y est déjà connu. |
| `notes` | text | |
| `uploaded_by`, `uploaded_at` | | |
| `retired_at` | timestamptz nullable | Retiré = plus proposé, fichier supprimé ; la ligne reste pour l'historique des commandes. |

La lecture des propriétés MSI côté serveur (Linux) se fait sans exécuter le
paquet : le MSI est un fichier composé OLE, la table `Property` se lit avec
`olefile` (pur Python). La signature, elle, n'est **qu'affichée** côté
serveur ; sa vérification qui compte est celle du poste.

### 3.2 `commands`

Deux types : `software_install` et `software_uninstall`, dans
`RISKY_COMMAND_TYPES`. Une colonne nullable `package_id` (FK `packages.id`,
`ON DELETE SET NULL`) : c'est le **deuxième argument** que le protocole porte
après `target_mac`, et il obéit à la même règle — un identifiant que l'agent
résout et vérifie, jamais une chaîne exécutée. La livraison porte
`{id, type, package: {id, sha256, size, product_code}}`.

Dédoublonnage : la règle « une commande ouverte par (poste, type) » devient
« par (poste, type, paquet) » pour ces deux types — déployer Firefox et 7-Zip
sur la même salle ne doit pas s'exclure.

## 4. Contrat API

| Méthode | Route | |
|---|---|---|
| `POST` | `/api/v1/packages` | Multipart. Empreinte calculée en flux, refus d'un doublon (`PACKAGE_ALREADY_EXISTS`), d'un fichier qui n'est pas un MSI (`PACKAGE_INVALID_MSI`), d'un MSI sans `ProductCode`. |
| `GET` | `/api/v1/packages` | Liste, avec le décompte des postes où l'inventaire voit le produit. |
| `GET` | `/api/v1/packages/{id}` | Détail + suivi : commandes par statut. |
| `POST` | `/api/v1/packages/{id}/retire` | |
| `POST` | `/api/v1/commands` | Existant ; accepte `package_id` pour les deux nouveaux types (`PACKAGE_REQUIRED` sinon, `PACKAGE_RETIRED` sur un paquet retiré). |
| `GET` | `/api/v1/agent/packages/{id}/content` | Agent. `Range`, 429 au-delà de la limite de simultanéité, 404 sans commande ouverte. |

## 5. Agent

- `deploy.go` : téléchargement avec reprise, vérification (§1), exécution,
  traduction des codes `msiexec` (0 succès, 3010/1641 succès + redémarrage
  requis, 1603/1618/1619/1638… en clair dans `error`), journal MSI tronqué
  dans `result_output`.
- `deploy_windows.go` : `WinVerifyTrust` + lecture du sujet signataire
  (`CryptQueryObject`), ACL du cache. `deploy_other.go` : refus explicite.
- 1618 (« une autre installation est en cours ») : une nouvelle tentative après
  5 min, une seule, puis `failed` — Windows Update tient souvent le verrou MSI.
- Le mutex Windows Update existant est pris pendant l'installation : un
  `wu_install` et un `msiexec` ne se marchent pas dessus.

## 6. Console

- Page **Logiciels › Paquets** : dépôt (glisser-déposer, barre de progression),
  liste (produit, version, éditeur, signataire, taille, postes équipés),
  retrait.
- Fiche d'un paquet : bouton « Déployer » (poste, salle, sélection, filtre de
  la liste des postes), suivi par statut, liens vers les postes en échec.
- Fiche d'un poste et actions de masse : entrées « Installer un paquet… » et
  « Désinstaller… » dans le catalogue de commandes, avec choix du paquet et
  confirmation qui rappelle le nombre de postes visés.
- Un poste dont l'agent est trop ancien ou sur lequel le déploiement n'est pas
  activé le dit en clair dans le résultat de la commande, pas en silence.

## 7. Jalons

| Jalon | Contenu | Estimation |
|---|---|---|
| J1 | Backend : table `packages`, dépôt (flux, empreinte, lecture MSI), stockage, retrait, permissions, audit. | ~2 j |
| J2 | Backend : types de commande, `package_id`, dédoublonnage par paquet, route de téléchargement agent (Range, 429). | ~1,5 j |
| J3 | Agent : téléchargement, vérification empreinte + Authenticode + éditeur, `msiexec`, codes retour, inventaire après coup. | ~2,5 j |
| J4 | Console : page Paquets, déploiement, suivi, catalogue de commandes. | ~2 j |
| J5 | Validation sur poste réel (MSI signé interne, MSI éditeur, paquet non signé refusé, empreinte altérée refusée, 3010, 1618) + documentation (DEPLOYMENT.md : la clé GPO et ce qu'elle ouvre). | ~1 j |

## 8. Vérification

- Tests agent sur la logique pure : décision de vérification (ordre, refus à
  chaque étape), traduction des codes MSI, comparaison de sujet.
- Tests backend : dépôt (doublon, non-MSI, taille), route agent (sans commande
  ouverte → 404, paquet retiré, Range), dédoublonnage par paquet, permissions.
- Test « serveur compromis » : un paquet non signé, ou signé par un éditeur
  absent de la liste, déposé et déployé, **n'est pas exécuté** par l'agent.

## 9. Décisions à valider

1. **[à valider]** Confiance portée par le poste : liste d'éditeurs approuvés
   posée par GPO, fonction coupée tant qu'elle est vide (§1). *Alternative
   écartée* : faire confiance au serveur, ce qui revient à abandonner la
   garantie du catalogue fermé pour tout le parc.
2. **[à valider]** MSI seulement dans cette itération ; `.exe` via un MSI de
   repackaging signé en interne.
3. **[à valider]** Fichiers servis par le serveur Tia'i lui-même (volume
   Docker), et non par un partage SMB ou un dépôt externe.
4. **[à valider]** Lancer un déploiement = `risky_command:execute` ; déposer un
   paquet = nouvelle permission `package:write`.

## 10. Points d'attention

- **Certificats d'éditeurs renouvelés** : la liste porte des *sujets*
  (« CN=Mozilla Corporation, O=Mozilla Corporation, … ») et non des empreintes
  de certificat, pour survivre au renouvellement annuel ; la chaîne, elle, est
  vérifiée par Windows.
- **Paquets d'éditeurs signés seulement à l'intérieur** : certains MSI
  distribués ne sont pas signés eux-mêmes alors que leurs `.exe` le sont. Ils
  sont refusés : c'est le MSI qui est exécuté. Les repackager.
- **Disque** : un paquet ne se dépose que si le volume a deux fois sa taille de
  libre ; la console affiche l'occupation du dépôt.
- **RGPD** : rien de nouveau ; les données sont celles de l'inventaire.
