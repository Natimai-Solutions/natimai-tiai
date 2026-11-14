# Inventaire matériel & logiciel — plan de travail

> **Statut : implémenté (2026-08-31)** — J1 à J6, découpage préalable de la
> console compris. Cf. §11 en fin de document.
>
> Objectif : chaque poste dit **ce qu'il est** (constructeur, carte mère, CPU,
> GPU, mémoire, disques, cartes réseau) et **ce qu'il porte** (logiciels
> installés, occupation des volumes), et la console sait interroger le parc
> entier là-dessus.
>
> Dernier module de la Phase 3 côté « lecture » (cf. `plan-projet-tiai.md`
> §Phase 3). Réutilise l'agent, le heartbeat et la file de commandes : comme
> Windows Update, ça se résume à **un bloc de données de plus** et **un type de
> commande de plus**.

---

## 1. Ce que fait GLPI, et ce qu'on en garde

Le sujet est vieux de vingt ans et a un standard de fait : le **GLPI Agent**
(ex-FusionInventory/OCS), dont le [schéma d'inventaire JSON][schema] est public.
Il définit une cinquantaine de sections ; il n'y a aucune raison d'en réinventer
le vocabulaire.

**Ce qu'on ne fait pas : déployer GLPI Agent à côté du nôtre.** Deux agents sur
un poste, ce sont deux services, deux chaînes de déploiement GPO, deux
signatures et deux fenêtres de mise à jour, pour une donnée qui atterrirait dans
un second serveur sans lien avec les commandes de la console. Tia'i a déjà
l'agent, le canal et la file : le coût marginal d'un bloc de données est d'un
ordre de grandeur inférieur. **Ce qu'on reprend de GLPI, c'est son modèle de
données** — les noms de sections, le découpage attribut/table, et surtout ses
choix de sources, qui sont le produit de vingt ans de terrain.

| Section GLPI | Décision Tia'i | Pourquoi |
|---|---|---|
| `bios` (BIOS + carte mère + châssis + n° de série) | **v1** — attributs de `machines` | Un poste a un châssis, une carte mère, un BIOS. Cardinalité 1, donc pas de table. |
| `hardware` (constructeur, modèle, RAM totale, type de châssis) | **v1** — attributs | Idem. C'est la ligne « quelle machine est-ce » de la fiche. |
| `cpus` | **v1** — attributs (voir §3, décision « un seul CPU ») | Une table pour un poste mono-socket coûte une jointure à chaque affichage. |
| `memories` (barrettes) | **v1** — table | Répond à « puis-je ajouter de la RAM sans rien jeter ». Sans le détail des slots, la question n'a pas de réponse. |
| `storages` (disques physiques) | **v1** — table | Modèle, type SSD/HDD/NVMe, taille, santé. |
| `drives` (volumes logiques) | **v1** — table | **La** donnée que l'exploitation regarde : capacité, utilisé, libre. |
| `networks` (cartes réseau) | **v1** — table | Demandé explicitement. Gratuit : l'agent énumère déjà les adaptateurs (§4). |
| `videos` (GPU) | **v1** — table | Un poste a couramment iGPU + dGPU ; version du pilote incluse. |
| `softwares` | **v1** — catalogue normalisé + table de liaison | Le cœur du module. Voir §3. |
| `operatingsystem` (date d'installation, dernier démarrage, architecture) | **v1** — attributs | Trois colonnes, réponses à trois questions courantes. `os_version` existe déjà. |
| `antivirus` | **déjà livré** | Colonnes `av_product_*`, cf. instantané 2026-08-17 (3). |
| `monitors` (écrans, via EDID) | **v2** | Vrai besoin d'inventaire comptable, mais aucune adhérence avec le reste : se rajoute seul, plus tard. |
| `batteries` (santé de batterie) | **v2** | Utile sur un parc de portables ; une table de plus, pas une refonte. |
| `licenseinfos` (clés Windows/Office) | **v2, à arbitrer** | Une clé de produit en base est un actif sensible : à décider avec le RSSI avant de la collecter, pas en passant. |
| `local_users`, `local_groups` | **écarté** | Qui est administrateur local est une question de sécurité qui mérite son propre chantier, avec ses alertes — pas une ligne d'inventaire. |
| `processes`, `envs`, `ports`, `usbdevices` | **écarté** | État instantané, pas inventaire. Un inventaire quotidien de la liste des processus n'apprend rien et pèse. |
| `virtualmachines`, `network_device`, `printers` réseau, `databases_services` | **écarté** | Tia'i inventorie **le poste où tourne son agent**. Découvrir le réseau (SNMP, ESXi) est un autre produit. |

**Interopérabilité gardée ouverte** : les noms de champs suivent ceux de GLPI
quand ils existent (`bmanufacturer`, `msn`, `disksize`, `filesystem`…). Un export
au format d'inventaire GLPI devient alors un mapping de noms, pas une
rétro-ingénierie — c'est le genre de chose qu'un client demande le jour où il a
déjà un GLPI.

[schema]: https://github.com/glpi-project/inventory_format/blob/main/inventory.schema.json

---

## 2. Cadrage retenu

| Sujet | Décision |
|---|---|
| **Rythme** | **Cycle lent dédié, défaut 24 h** (`inventory_collect_interval_seconds`), jamais dans le heartbeat de 60 s. Calqué sur le cycle Windows Update, dont la plomberie (goroutine, cache sous mutex, compteur de génération, acquittement) est reprise telle quelle. |
| **Volume envoyé** | Bloc attaché **seulement quand l'inventaire a changé** : l'agent hache l'inventaire sérialisé et n'envoie rien si le hachage est identique au dernier envoi accusé. Un poste stable produit **un** envoi puis plus rien. |
| **Sémantique serveur** | **Remplacement de set**, comme les mises à jour en attente et à l'inverse des menaces : un logiciel désinstallé doit disparaître, un disque retiré aussi. `first_seen` survit à la mise à jour d'une ligne. |
| **Source logiciels** | **Registre** (`…\CurrentVersion\Uninstall`, vues 64 et 32 bits), lu nativement en Go. **Jamais `Win32_Product`** — voir §4. |
| **Source matériel** | **WMI**, déjà en place (`yusufpapurcu/wmi`), plus `GetAdaptersAddresses` déjà en place pour les cartes réseau. **Aucune nouvelle dépendance, aucun PowerShell.** |
| **Commande** | Un seul type nouveau : `inventory_scan` (collecte immédiate). `type` étant stocké en `str` nu, **aucune migration** — comme les quinze types précédents. |
| **Périmètre par utilisateur** | **Hors v1** : ni logiciels installés par utilisateur (ruches `HKU`), ni applications du Store, ni processus. Motif technique *et* RGPD (§7). |

---

## 3. Modèle de données

### 3.1 Attributs de `machines` (cardinalité 1)

Migration `0014_inventory` (`down_revision = "0013_audit_log"`). Toutes les
colonnes sont **nullables** : `NULL` = jamais remonté (agent trop ancien, lecture
impossible), qui est distinct de « vide ». C'est la règle établie par
`session_user_present` et `av_product_name`.

| Groupe | Colonnes |
|---|---|
| Système | `hw_manufacturer`, `hw_model`, `hw_serial` (n° de série châssis), `hw_chassis_type` (desktop / laptop / mini / virtual…), `hw_is_virtual bool` + `hw_hypervisor` |
| Carte mère | `mb_manufacturer`, `mb_model`, `mb_serial` |
| BIOS / UEFI | `bios_vendor`, `bios_version`, `bios_date`, `secure_boot bool`, `tpm_version` |
| CPU | `cpu_model`, `cpu_manufacturer`, `cpu_cores int`, `cpu_threads int`, `cpu_speed_mhz int`, `cpu_count int` |
| Mémoire | `ram_total_mb int`, `ram_slots_total int`, `ram_slots_used int` |
| OS | `os_architecture`, `os_install_date`, `last_boot_time` |
| Inventaire | `inventory_last_seen timestamptz`, `inventory_hash text` |

**Décision « un seul CPU »** : GLPI a une table `cpus`, on met des colonnes. Un
poste de travail est mono-socket ; sur les rares bi-sockets, les processeurs sont
identiques par construction (Windows refuse de démarrer autrement). On remonte
donc le modèle du premier et le **nombre** dans `cpu_count`, et on économise une
table et une jointure sur la page la plus consultée de la console. Si un parc de
stations bi-socket hétérogènes apparaît un jour, la table se rajoute sans casser
les colonnes, qui restent le résumé.

`hw_is_virtual` n'est pas cosmétique : une VM n'a ni batterie, ni SMART, ni
BIOS à mettre à jour, et la moitié des alertes matérielles doivent la sauter.

### 3.2 Tables enfants (cardinalité N)

Toutes en `machine_id FK → machines.id ON DELETE CASCADE`, index sur
`machine_id`, `first_seen`/`last_seen`, et une clé métier `UNIQUE` par table
pour rendre le remplacement de set idempotent.

| Table | Clé métier | Colonnes |
|---|---|---|
| `inventory_memory_modules` | `(machine_id, slot)` | `slot`, `capacity_mb`, `type` (DDR4/DDR5), `speed_mhz`, `manufacturer`, `serial`, `form_factor` |
| `inventory_disks` | `(machine_id, serial)` avec repli `(machine_id, device_id)` | `model`, `serial`, `firmware`, `media_type` (SSD/HDD/NVMe/unknown), `bus_type`, `size_mb`, `health_status`, `device_id` |
| `inventory_volumes` | `(machine_id, letter)` | `letter`, `label`, `filesystem`, `total_mb`, `free_mb`, `is_system bool`, `encryption_status` |
| `inventory_nics` | `(machine_id, mac)` avec repli sur `(machine_id, name)` | `name` (description Windows = le modèle), `mac`, `type` (ethernet/wifi/autre), `speed_mbps`, `is_up bool`, `is_virtual bool`, `ip_address`, `ip_prefix_length`, `is_dhcp bool`, `gateway`, `driver_version` |
| `inventory_gpus` | `(machine_id, name)` | `name`, `chipset`, `memory_mb`, `driver_version`, `driver_date`, `resolution` |

**`used_mb` n'est pas stocké** sur les volumes : c'est `total_mb - free_mb`. Deux
colonnes qui peuvent se contredire pour une soustraction, c'est le même
raisonnement que `wu_pending_count` dérivé côté serveur. Le **pourcentage
d'occupation** est calculé à l'affichage, mais le **tri et le filtre** de la
console passent par une expression SQL sur les deux colonnes, pas par le client.

**Les cartes réseau ne remplacent pas `machines.ip_address` / `mac_address`.**
Ces deux colonnes-là sont l'adaptateur **élu** pour joindre et réveiller le
poste, relu à chaque heartbeat de 60 s ; la table est l'inventaire complet, relu
une fois par jour. Les faire dériver l'une de l'autre casserait soit la
fraîcheur du Wake-on-LAN, soit l'exhaustivité de l'inventaire. Elles cohabitent,
et la fiche affiche l'élue en évidence dans la carte « Réseau » existante.

### 3.3 Logiciels — catalogue normalisé

Deux tables plutôt qu'une :

- **`software`** — le catalogue du parc, `UNIQUE (name, version, publisher)` :
  `id bigserial`, `name`, `version`, `publisher`, `first_seen`.
- **`machine_software`** — la liaison, `UNIQUE (machine_id, software_id)` :
  `machine_id`, `software_id`, `install_date`, `arch` (x86/x64), `source`
  (`registry` / `registry_wow64`), `install_location`, `first_seen`, `last_seen`.

Dénormaliser (une ligne par poste et par logiciel, nom et éditeur répétés)
serait plus simple à écrire et parfaitement tenable en volume — mille postes à
250 logiciels font 250 000 lignes, ce qui n'est rien. Ce n'est pas le volume qui
tranche, ce sont **deux usages** :

1. **La question qu'on pose vraiment** est « qui a encore Java 8 » ou « combien
   de postes ont cette version-là ». Sur le catalogue, c'est un `GROUP BY` sur
   une table de quelques milliers de lignes ; dénormalisé, c'est un `GROUP BY`
   sur des centaines de milliers de chaînes répétées.
2. **Le déploiement logiciel arrive dans la même phase** (`plan-projet-tiai.md`
   §Phase 3). Un `software.id` stable est ce à quoi un futur paquet se rattache.
   Le créer maintenant coûte une table ; le rétro-ajouter coûterait une migration
   de données sur tout l'historique.

Le prix est un `INSERT … ON CONFLICT DO NOTHING RETURNING id` par logiciel
inconnu au moment de l'écriture. Il est payé **au changement seulement** (§2), et
la deuxième machine du parc ne découvre presque plus rien.

**Normalisation des noms : aucune, volontairement.** GLPI et OCS ont tous deux
des dictionnaires de règles pour fusionner « Mozilla Firefox » et « Firefox
(x64 fr) ». C'est un produit à part entière et une source d'erreurs silencieuses.
On stocke ce que le poste déclare, et on laisse la recherche à l'opérateur ; un
dictionnaire pourra se poser **au-dessus** du catalogue plus tard, sans toucher
à la collecte.

---

## 4. Collecte côté agent — sources et pièges

Nouveau paquet `agent/internal/collector/inventory*.go`, découpé selon la
convention en vigueur : logique pure et mappings dans le fichier neutre
(testables hors Windows), accès WMI/registre sous `//go:build windows`, stub
`errUnsupported` dans `_other.go`.

### 4.1 Logiciels — le registre, jamais `Win32_Product`

C'est **la** décision technique du chantier, et GLPI la prend depuis toujours.
Énumérer `Win32_Product` déclenche une **vérification de cohérence MSI de chaque
paquet installé** : la requête prend des minutes et écrit un événement 1035 dans
le journal Application de tous les postes du parc, tous les jours. Microsoft le
documente comme un effet de bord attendu. Sur un déploiement GPO de mille
postes, c'est indéfendable.

On lit donc le registre, nativement avec
`golang.org/x/sys/windows/registry` — pas de WMI, pas de PowerShell, quelques
dizaines de millisecondes :

- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall`
- `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall`
  (applications 32 bits sur un Windows 64 bits — les oublier, c'est perdre le
  tiers du parc logiciel, et c'est l'erreur classique)

**Filtrage, aligné sur ce qu'affiche « Applications et fonctionnalités »** :
entrée sans `DisplayName` → ignorée ; `SystemComponent = 1` → ignorée ;
`ReleaseType` valant `Security Update` / `Update Rollup` / `Hotfix` → ignorée
(ce sont des correctifs, ils ont déjà leur module) ; `ParentKeyName` présent →
ignorée (composant d'un paquet déjà listé). Ces quatre règles sont de la logique
pure, donc testées sur des fixtures, sans Windows.

Restent visibles mais **hors v1** : les installations **par utilisateur**
(`HKU\<SID>\…`, qui exigent de charger les ruches des profils depuis
`LocalSystem`) et les applications **Store/APPX** (énumération par utilisateur,
coûteuse). Les deux sont notées en §8.

### 4.2 Matériel — WMI

| Donnée | Classe |
|---|---|
| Constructeur, modèle, RAM totale | `Win32_ComputerSystem` |
| Type de châssis, n° de série châssis | `Win32_SystemEnclosure` |
| Carte mère | `Win32_BaseBoard` |
| BIOS, date, n° de série | `Win32_BIOS` |
| CPU | `Win32_Processor` |
| Barrettes et slots | `Win32_PhysicalMemory`, `Win32_PhysicalMemoryArray` |
| GPU et pilote | `Win32_VideoController` |
| Volumes | `Win32_LogicalDisk` (`DriveType = 3`, disques fixes seuls) |
| Disques physiques, type de média, santé | `MSFT_PhysicalDisk` (`root\Microsoft\Windows\Storage`) |
| Chiffrement | `Win32_EncryptableVolume` (`root\CIMV2\Security\MicrosoftVolumeEncryption`) |
| Date d'installation, dernier démarrage | `Win32_OperatingSystem` |
| TPM | `Win32_Tpm` (`root\CIMV2\Security\MicrosoftTpm`) |

Pièges connus, à traiter dès l'écriture :

- **`Win32_DiskDrive` ne sait pas dire SSD ou HDD.** `MSFT_PhysicalDisk.MediaType`
  le sait, et donne `HealthStatus` par la même occasion. Sur un Windows où
  l'espace de noms Storage manque, on retombe sur `Win32_DiskDrive` avec un type
  `unknown` — un disque sans son type vaut mieux que pas de disque.
- Les trois derniers espaces de noms (Storage, chiffrement, TPM) **échouent
  proprement** sur certains SKU. Chacun est best-effort et journalisé une seule
  fois puis rétrogradé en DEBUG, exactement comme le Security Center absent des
  SKU Serveur.
- `Win32_PhysicalMemory.Capacity` est un **`uint64` en octets** rendu comme
  chaîne par WMI ; `Win32_LogicalDisk.Size`/`FreeSpace` aussi. Une conversion
  naïve en `int` déborde ou tronque. Conversion centralisée et testée, avec la
  leçon du « 0 Mio » de la Phase 2 : arrondir vers le haut plutôt que planchonner
  à zéro.
- **Le type de châssis est un entier** (1–36) dont seuls quelques codes comptent.
  Table de correspondance en Go, valeur inconnue remontée telle quelle.
- **La date BIOS et `InstallDate` sont au format `CIM_DATETIME`**
  (`20240115000000.000000+000`). Parseur dédié, testé sur les variantes,
  fuseau inclus.

### 4.3 Cartes réseau — extension de l'existant, pas de nouveau code Win32

`collector/network*.go` appelle déjà `GetAdaptersAddresses` et en tire nom,
adresse MAC, IP, longueur de préfixe, passerelle, métrique, statut. La fonction
n'en retourne aujourd'hui qu'un — l'adaptateur **élu**. On la fait retourner
**la liste complète** en plus de l'élu ; l'élection existante ne bouge pas d'une
ligne (elle a été validée sur poste réel avec cinq APIPA et deux commutateurs
Hyper-V). Il ne manque que la vitesse de lien et le drapeau Wi-Fi, qui sont dans
la même structure (`TransmitLinkSpeed`, `IfType`), et la version du pilote, qui
vient de WMI.

Autrement dit : les cartes réseau demandées coûtent **une signature de fonction
et un mapping**, pas un collecteur.

---

## 5. Jalons

### J1 — Backend : modèle, réception, exposition *(~2 j)*

- Migration `0014_inventory` : les colonnes de §3.1 sur `machines`, les cinq
  tables de §3.2, les deux tables de §3.3. Conventions maison : nommage manuel
  `NNNN_slug`, `sa.DateTime(timezone=True)`, `server_default` sur les non
  nullables, `downgrade()` implémenté et rejoué.
- Module `backend/app/features/inventory/` calqué sur `features/windows_update/` :
  `models.py`, `schemas.py` (`InventoryReport` et ses sous-modèles, partagés
  route agent ↔ crud), `crud.py` avec un `replace_*` par table, tous en
  upsert + `DELETE` du disparu. Import dans `features/models.py`.
- Heartbeat (`api/routes/agent.py`) : champ `inventory: InventoryReport | None`.
  Absent ⇒ **rien n'est écrasé** (règle de tous les blocs). Une sous-section
  invalide est **ignorée et journalisée**, jamais renvoyée en 422 : un volume
  malformé ne doit pas coûter l'état Defender et les menaces du même heartbeat —
  c'est la règle posée pour l'adresse IP.
- `CommandType += INVENTORY_SCAN`. Aucune migration.
- Exposition : `MachineDetailOut` gagne les attributs et les cinq listes ;
  `MachineOut` gagne **trois** champs seulement (`hw_model`, `ram_total_mb`,
  occupation du volume système) — la liste sert 1 000 lignes, on n'y charge pas
  un inventaire ; `GET /stats/overview` gagne les KPI de §6.
- Pytest, sur les patrons `_enroll`/`_heartbeat` existants : premier inventaire ;
  inventaire modifié (barrette ajoutée, logiciel désinstallé, disque retiré →
  la ligne disparaît, `first_seen` des survivantes conservé) ; heartbeat sans le
  bloc → rien d'écrasé ; catalogue partagé entre deux postes (une seule ligne
  `software`) ; suppression d'un poste → cascade complète.

### J2 — Backend : requêtes de parc *(~1 j)*

C'est ce qui distingue un inventaire d'une fiche technique.

- `GET /software` — catalogue paginé, trié, recherche libre sur nom/éditeur,
  colonne `machine_count`. C'est la page « qui a encore Java 8 ».
- `GET /software/{id}/machines` — les postes qui le portent.
- `GET /machines` — nouveaux filtres : `model`, `manufacturer`,
  `disk_free_below` (seuil en %), `has_software` (id du catalogue).
- `GET /machines/models` — valeurs distinctes + comptes, sur le modèle exact de
  `GET /machines/antivirus-products` livré avec l'antivirus tiers. Alimente le
  sélecteur de la console et vaut déjà, seul, comme inventaire de parc.
- `GET /machines/{id}/inventory.csv` et `GET /software.csv` — l'export sera
  demandé le premier jour ; il est trivial ici et coûteux à rajouter après.
- Tests : agrégats, filtres, pagination, permissions (lecture `machine:read`,
  rien de neuf).

### J3 — Agent : collecte matérielle *(~2 j)*

- `collector/inventory*.go` : les classes WMI de §4.2, les mappings et les
  parseurs (CIM_DATETIME, châssis, `uint64` en chaîne) en neutre et testés.
- `collector/network*.go` : retourne la liste complète en plus de l'élu.
  L'élection est **inchangée** ; test de non-régression dessus.
- Modèles de transport dans `models/models.go` : `InventoryState` et ses
  sous-structures, champ `Inventory *InventoryState` sur `HeartbeatRequest`,
  avec la même discipline d'`omitempty` que les blocs existants (absent = pas
  d'information, liste vide = information que c'est vide).
- Tests Go sur fixtures WMI réalistes, **champs manquants compris** : le poste
  qui n'a ni TPM, ni Secure Boot, ni espace de noms Storage n'est pas un cas
  d'erreur, c'est un poste de 2015.

### J4 — Agent : logiciels, cycle lent et commande *(~1,5 j)*

- Lecture registre + les quatre règles de filtrage de §4.1, testées sur fixtures.
- Cycle lent (`agent/internal/agent/inventory.go`, calqué sur `wu.go`) :
  goroutine dédiée, première collecte ~3 min après le démarrage, puis toutes les
  24 h ; cache sous mutex ; **compteur de génération** et non booléen (la leçon
  de la Phase 2 : une collecte qui se termine pendant qu'un heartbeat est en vol
  ne doit pas être enterrée par son acquittement).
- **Hachage** : SHA-256 de l'inventaire sérialisé de façon déterministe (listes
  triées par leur clé métier, sinon l'ordre de WMI suffit à faire croire à un
  changement tous les jours). Bloc attaché seulement si le hachage diffère du
  dernier accusé. Le hachage est en mémoire : un redémarrage de l'agent provoque
  un envoi de plus, ce qui est correct et sans conséquence.
- Nouvelles clés de configuration : `inventory_collect_interval_seconds`
  (défaut 86400), `report_software` (défaut `true`, pointeur `*bool` comme
  `report_session_username`, surchargeable par registre/GPO — cf. §7).
- `inventory_scan` : un `case` dans le dispatch. Collecte forcée, cache et
  hachage rafraîchis, sortie « N logiciels, M volumes, X Go libres ».
  Prend le mutex de collecte : jamais deux inventaires simultanés.
- Tests Go : « attacher seulement si changé », stabilité du hachage sur deux
  collectes identiques dans un ordre différent, `report_software=false` →
  le reste de l'inventaire remonte et la liste est vide.

### J5 — Console *(~2 j)*

- **`MachineDetailPage.vue` fait déjà 1 156 lignes.** Quatre cartes de plus la
  rendent inmaintenable : les sections sont donc **extraites en composants**
  (`frontend/src/components/machine/`, répertoire à créer) — Matériel, Stockage,
  Réseau, Logiciels — et les cartes existantes suivent au passage. C'est du
  travail de découpage sans changement de rendu, à faire *avant* d'ajouter, pas
  après.
- Carte **Matériel** : constructeur, modèle, n° de série, châssis, carte mère,
  BIOS + date, Secure Boot, TPM, CPU, RAM totale et occupation des slots
  (« 2 barrettes sur 4 »).
- Carte **Stockage** : disques physiques (modèle, type, taille, santé) puis
  volumes avec une **barre d'occupation** — verte, orange sous 20 %, rouge sous
  10 %. C'est la seule donnée de tout le module qu'on regarde en un coup d'œil.
- Carte **Réseau** : la table des adaptateurs, l'élu mis en évidence.
- Carte **Logiciels** : `q-table` filtrable (nom, version, éditeur, date
  d'installation, architecture), pattern des tables existantes.
- Nouvelle page **Logiciels du parc** (`SoftwarePage.vue`) + entrée de menu :
  catalogue, recherche, tri par nombre de postes, clic → liste des postes filtrée.
- `MachinesPage.vue` : colonnes optionnelles modèle et espace libre, nouveaux
  filtres, `inventory_scan` dans le catalogue `commandActions` (une entrée,
  éligible au masse, sans confirmation — c'est une lecture).
- `DashboardPage.vue` : les KPI de §6.
- Vitest sur les services (patron existant : mock `boot/axios`, assertion URL +
  params + retour) et sur les utilitaires d'affichage (formatage des tailles,
  seuils de couleur).

### J6 — Validation et documentation *(~1 j)*

§9, puis mise à jour de `plan-projet-tiai.md` (suivi d'avancement, tableau des
modules), du README (feuille de route : Inventaire → 🟢) et de `DEPLOYMENT.md`
(les deux nouvelles clés agent, dont `report_software`).

**Total : ~9,5 jours.**

---

## 6. Ce que la console en tire

Un inventaire qui ne sert qu'à consulter une fiche ne vaut pas neuf jours. Les
KPI du tableau de bord sont donc choisis pour être **actionnables** :

| KPI | Pourquoi celui-là |
|---|---|
| Postes sous 10 % d'espace libre | C'est la première cause d'échec des mises à jour Windows — donc directement le module d'à côté. |
| Postes sans chiffrement de disque | Question de RSSI, réponse en un clic. |
| Postes de plus de N ans (date BIOS) | La donnée du plan de renouvellement. |
| Postes avec moins de X Go de RAM | Idem, côté « qui rame ». |
| Nombre d'entrées au catalogue logiciel | La porte d'entrée vers la page Logiciels. |

---

## 7. RGPD et CSE

Le point est déjà ouvert au registre pour la session utilisateur
(`plan-projet-tiai.md` §8) ; l'inventaire logiciel **l'élargit** et doit être
porté au même dossier. Croiser « quels logiciels sont installés » avec « qui est
connecté sur ce poste » permet d'inférer des choses sur une personne nommée. Les
garde-fous sont les mêmes, et par construction :

- **Rien qui décrive un usage.** Pas de processus en cours, pas de fréquence de
  lancement, pas d'historique, pas de navigation. On collecte ce qui est
  *installé*, c'est-à-dire une décision d'administration, pas un comportement.
- **Rien par utilisateur en v1** : les ruches `HKU` et les paquets Store sont
  hors périmètre, ce qui écarte mécaniquement les logiciels installés par une
  personne dans son profil.
- **Interrupteur à la source** : `report_software`, poussé par GPO comme
  `ReportSessionUsername`. Coupé, la liste n'est ni lue ni sérialisée ; le reste
  de l'inventaire matériel continue de remonter. La garantie est vérifiable sur
  le poste, pas sur parole — c'est ce qui a été retenu pour le nom de session, et
  un test dédié le vérifie.
- Le nom d'utilisateur n'apparaît dans **aucune** table de ce chantier.

---

## 8. Extensibilité (absorbé sans refonte)

| Évolution | Comment le design l'absorbe |
|---|---|
| Écrans, batteries, périphériques USB | Une table de plus sur le patron des cinq existantes, une sous-section de plus dans le bloc. |
| Logiciels par utilisateur / Store | Une valeur de plus dans `machine_software.source`. Le modèle ne bouge pas ; c'est la décision RGPD qui commande, pas le schéma. |
| Historique (« ce poste avait 8 Go, il en a 16 ») | Table d'événements alimentée par le diff du `replace_*`, qui connaît déjà l'avant et l'après. Volontairement pas maintenant : l'état courant est ce qu'on nous demande. |
| Dictionnaire de normalisation des noms de logiciels | Table de règles au-dessus du catalogue, sans toucher à la collecte (§3.3). |
| Export au format d'inventaire GLPI | Mapping de noms de champs, les nôtres ayant été choisis pour ça (§1). |
| Déploiement logiciel (suite de la Phase 3) | Se rattache à `software.id`, qui existe pour cette raison. |
| Alertes e-mail sur seuil (disque plein) | Le moteur d'e-mails, l'outbox et les préférences par compte existent déjà : c'est une requête de plus dans le digest. |

---

## 9. Vérification

1. **Qualité locale** — `ruff` + `mypy --strict` + `pytest` sur Postgres 16 côté
   backend ; migration rejouée `upgrade`/`downgrade`/`upgrade` sur base vierge
   (les migrations ne sont pas exercées par pytest) ; `gofmt` + `go vet` +
   `go test` + builds croisés `windows/amd64` et `windows/arm64` côté agent ;
   `prettier` + `vue-tsc` + `vitest` + build SPA côté frontend.
2. **End-to-end simulé** — stack `docker compose` dev + heartbeat forgé (curl)
   portant un bloc `inventory` complet, puis un second modifié : vérifier en base
   le remplacement de set, la conservation des `first_seen`, le partage du
   catalogue entre deux postes forgés, et l'affichage des quatre cartes.
3. **Poste réel** (DoD) —
   - la fiche se remplit après la première collecte, accents intacts jusqu'en
     base (c'est le piège qui a coûté quatre encodages aux commandes de
     maintenance) ;
   - **la liste des logiciels est comparée une par une avec « Applications et
     fonctionnalités »** — c'est le seul juge du filtrage de §4.1, et la
     vérification qui vaut tout le reste ;
   - un portable *et* un poste fixe *et* une VM : châssis, batterie absente,
     `hw_is_virtual`, absence de TPM ;
   - `inventory_scan` depuis la console → fiche rafraîchie ;
   - **un poste stable ne réécrit rien pendant 48 h** — le compteur d'écritures
     le prouve, comme les « 18 heartbeats, 2 écritures » de la Phase 2 ;
   - désinstallation d'un logiciel → il disparaît au cycle suivant ;
   - `report_software=false` par registre → le matériel remonte, la liste est
     vide, rien en base.

---

## 10. Points d'attention

- **Le premier envoi du parc arrive d'un coup.** Mille postes qui découvrent le
  module poussent chacun 250 logiciels dans les minutes qui suivent la mise à
  jour de l'agent. Le décalage initial de ~3 min est aléatoire par poste (jitter),
  et le rythme de 24 h étale naturellement ensuite. À surveiller au déploiement
  pilote avant de généraliser.
- **Taille du corps HTTP** : un inventaire complet fait quelques dizaines de
  kilo-octets. Vérifier la limite de taille de requête côté Caddy et FastAPI, et
  la relever explicitement si besoin plutôt que de la découvrir en 413.
- **Postes en veille prolongée** : un portable rarement allumé peut ne jamais
  atteindre son cycle de 24 h. Le premier inventaire à ~3 min après le démarrage
  couvre ce cas ; c'est aussi pourquoi il n'est pas à `T+1 h`.
- **`inventory_last_seen` n'est pas `last_seen`** : un inventaire de trois
  semaines sur un poste vu il y a une minute est une anomalie à afficher, pas à
  masquer. La console date explicitement l'inventaire.
- **Fusion de postes** (§8 du plan projet) : contrairement aux menaces, les
  lignes d'inventaire du doublon **ne sont pas rattachées** au poste conservé —
  c'est de l'état courant, elles entreraient en collision avec le sien. La
  cascade les efface, le cycle suivant rétablit la vérité. Même raisonnement, et
  même décision, que pour les mises à jour en attente.

---

## 11. État de réalisation *(2026-08-31)*

**Découpage de `MachineDetailPage.vue` (préalable du J5) et J1 livrés.** Ne sont
notées ici que les décisions prises **en cours de route**, là où ce plan laissait
le choix ouvert ou s'est révélé inexact.

### Découpage préalable

`MachineDetailPage.vue` passe de 1 156 à 503 lignes, sans un changement de rendu.
Dix composants dans `frontend/src/components/machine/` (répertoire créé) :
`MachineInfoCard` — le carton mi-largeur générique dont les quatre cartes
d'information ne sont plus qu'un jeu de lignes — puis les cartes Identité,
Defender, Windows Update, Antivirus, Mises à jour en attente, Menaces et
Commandes, plus les deux dialogues (fusion, résultat de commande). Les quatre
cartes matérielles du J5 se poseront donc à côté, sur le même carton.

Deux points de découpage méritent d'être notés :

- **`MachineInfoCard` porte sa propre colonne de grille** (`col-12 col-md-6`).
  Une carte qui se masque emporte alors sa gouttière, là où une colonne vide
  laissée derrière ouvrirait un trou dans la grille — c'est le cas de la carte
  Antivirus, qui disparaît quand le produit enregistré est Defender lui-même.
- **La pagination reste à la page, la tournée de page part de la carte.** Les
  deux tables d'historique écrivent dans un `defineModel` et émettent `refresh` ;
  la page garde l'état et le rechargement, donc le garde-fou `requestId` qui
  empêche la réponse la plus lente d'écraser la page qu'on vient de demander.

### J1 — backend

| Point du plan | Ce qui a été fait |
|---|---|
| Migration `0014_inventory` | Conforme (`down_revision = "0013_audit_log"`), rejouée `upgrade`/`downgrade`/`upgrade` sur base vierge. Les colonnes ajoutées à `machines` sont produites par une **fabrique** et non une liste de module : un `Column` appartient à la table où il a été posé, et un rejeu dans le même processus tenterait de le reposer. |
| Colonnes `system_volume_total_mb` / `system_volume_free_mb` | **Ajoutées, non prévues.** Le plan mettait « occupation du volume système » dans la liste des postes sans dire d'où elle viendrait : d'une table enfant, ce serait une sous-requête corrélée par ligne, donc ni triable ni filtrable à bon compte. Dérivées côté serveur du volume marqué système, exactement comme `wu_pending_count` — la colonne et la table ne peuvent alors pas se contredire. C'est aussi ce sur quoi le KPI « moins de 10 % d'espace libre » et le filtre `disk_free_below` du J2 s'appuieront. |
| Trois états sur chaque section | Le plan ne parlait de la discipline `null` / `[]` que pour les logiciels ; elle est appliquée à **toutes** les sections. `null` = pas lu (agent trop ancien, espace de noms WMI absent) et l'ensemble stocké est laissé tel quel ; `[]` = lu et vide, et il est effacé. Une VM n'a réellement aucune barrette, et un poste dont la collecte logicielle est coupée par GPO doit réellement voir sa liste **disparaître de la base** — sans quoi l'interrupteur du §7 ne garantit rien. |
| Court-circuit sur le hachage | Le plan ne le prévoyait que côté agent (« ne pas envoyer si inchangé »). Le serveur le porte **aussi** : un hachage reçu identique à celui stocké ne redate que l'inventaire et saute les sept remplacements d'ensemble. C'est ce qui rend gratuit le renvoi d'un agent qui a redémarré, et le plan §J4 dit que ce cas est normal. Gardé sur un hachage non vide : un agent qui n'en envoie pas n'a aucune prétention à faire, et `"" == ""` sauterait chaque inventaire. |
| `_replace_set` générique | Une seule fonction pour les six ensembles, paramétrée par sa contrainte et sa clé. Elle lit ses colonnes sur `Table.c` et non sur la classe : la clé est une chaîne, ces six tables n'ayant en commun que `machine_id`. |
| `INVENTORY_SCAN` | Une valeur d'énumération, **aucune migration** — `type` est stocké en `str` nu. La promesse du §4 des plans précédents, tenue une fois de plus. |

**Deux pièges attrapés, tous deux par un outil et non par relecture :**

1. Les cinq tables enfants partageaient d'abord une classe de base `_MachineChild`
   déclarant `id`, `machine_id`, `first_seen` et `last_seen`. Un `sa_column`
   appartient à **une** table : la première créée réclamait les objets `Column`,
   les quatre suivantes échouaient. C'est exactement la règle que documente
   `utc_field`, un étage plus haut. Remplacé par des fabriques `_child_id()` /
   `_machine_fk()`, quatre lignes répétées par table — comme `WindowsUpdate`.
2. **`alembic check`** a trouvé six colonnes déclarées `BigInteger` dans la
   migration et `int` dans les modèles. Le schéma bâti par `create_all` (les
   tests) et le schéma migré (la production) auraient différé silencieusement,
   ce qui est précisément la classe de bogue contre laquelle `utc_field` existe.
   Ramenées à `Integer`, qui suffit largement : ce sont des mébioctets, donc
   `int4` plafonne vers deux pébioctets.

> **À noter, hors périmètre** : `alembic check` signale aussi une divergence
> **préexistante** sur `password_reset_tokens` — le modèle déclare
> `foreign_key="users.id"` sans `ondelete`, la migration `0004` pose un
> `ON DELETE CASCADE`. Rien de ce chantier ne touche cette table ; c'est une
> ligne à corriger, mais pas ici.

### Vérification effectuée

- **Console** : `vue-tsc`, `prettier` et build SPA verts, **150 vitest** verts
  (le découpage ne change aucun contrat de service, donc aucun test à réécrire).
  `exactOptionalPropertyTypes` a exigé que la légende optionnelle de
  `MachineInfoCard` soit annotée `string | undefined` — un `withDefaults` posant
  `undefined` n'y passe pas.
- **Backend** : `ruff` et `mypy --strict` verts sur 65 fichiers ; **16 nouveaux
  tests** dans `tests/test_api_inventory.py` (report complet, sémantique de
  remplacement avec conservation de `first_seen`, `[]` qui efface et `null` qui
  n'efface pas, catalogue partagé entre deux postes, clés dupliquées et clés
  vides, court-circuit du hachage, bornes absurdes, cascade de suppression,
  charge utile de la liste, aller-retour de `inventory_scan`) ; **349 tests**
  verts au total sur Postgres 16.
- **Migration** rejouée `upgrade` → `downgrade` → `upgrade` sur base vierge, puis
  `alembic check` — seule subsiste la divergence préexistante ci-dessus.

**Le test-garde a fait son travail** : `test_catalogue_is_fully_covered_below`
est tombé sur `inventory_scan`, comme prévu par sa conception — un type ajouté au
catalogue fermé doit coûter une édition délibérée et un aller-retour testé.

### J2 — requêtes de parc

| Point du plan | Ce qui a été fait |
|---|---|
| `GET /software` | Livré. `HAVING count > 0` : supprimer un poste laisse ses logiciels au catalogue — ce sont les identifiants stables auxquels un paquet s'accrochera, donc ils ne sont pas cascadés — mais une page intitulée « logiciels du parc » qui liste des programmes qu'aucun poste ne porte dit quelque chose de faux. |
| `GET /software/{id}/machines` | **Non implémenté, et volontairement.** Le filtre `software_id` sur `/machines` fait strictement mieux : il hérite de la pagination, du tri et des douze autres facettes, donc « qui a Java 8 **et** est allumé » ne coûte rien. Un second point d'entrée n'aurait apporté qu'une seconde pagination à maintenir. |
| Filtres `model` / `manufacturer` / `disk_free_below` / `has_software` | Livrés sous les noms `hw_model`, `hw_manufacturer`, `disk_free_below`, `software_id`. Les facettes du listing sont **factorisées** dans un `MachineFilters` : l'export CSV est la même requête sans la pagination, et un export qui ignorerait la moitié des filtres posés serait pire que pas d'export. |
| Tri | `hw_model`, `ram_total_mb` et **`disk_free_percent`** ajoutés. Le dernier n'a pas de colonne : c'est une expression sur deux colonnes, ce qui a demandé de faire porter la table de tri sur des expressions plutôt que sur des colonnes. C'est le pourcentage qui est trié, pas les octets — 40 Go libres sur un 4 To et sur un SSD de 128 Go ne sont pas la même nouvelle. |
| `GET /machines/{id}/inventory.csv` | **Remplacé par `GET /machines/export.csv`**, le parc entier filtré. Une fiche se lit à l'écran ; et l'inventaire d'*une* machine est hétérogène — barrettes, disques, volumes, cartes, programmes — donc son CSV est une forme que personne ne peut croiser dans un tableur. Ce qu'on demande, c'est le parc : une ligne par poste, triable sur la colonne dont parle la réunion. |
| KPI (§6) | Quatre livrés : disque presque plein, sans chiffrement, à renouveler, taille du catalogue. Le cinquième du §6 — « moins de X Go de RAM » — est **abandonné** : son seuil est propre à chaque parc, et l'export CSV du parc y répond mieux qu'une carte figée. Les deux seuils (`LOW_DISK_FREE_PERCENT`, `HARDWARE_AGING_YEARS`) sont des réglages serveur **renvoyés dans la charge utile** : une carte affichant « moins de 10 % » pendant que le serveur compte à 15 serait un mensonge invisible. |
| « Sans chiffrement » | Compté par un `EXISTS` sur les volumes, et non depuis une colonne dénormalisée comme le disque : ce n'est pas un chiffre sur lequel la liste trie, c'est un lien vers une liste de postes. Un statut `NULL` **ne compte pas** : l'espace de noms BitLocker est absent de certains SKU et exige l'élévation, donc « pas lu » remonté comme « pas chiffré » serait une alerte sur une machine peut-être chiffrée — la façon dont un tableau de bord se fait ignorer. |

**Deux exports, deux détails qui ne sont pas cosmétiques** : séparateur
point-virgule (Excel sur un Windows français lit un fichier séparé par virgules
en une seule colonne) et **BOM UTF-8** (sans lui Excel devine la page de codes
ANSI et transforme chaque nom accentué en charabia). C'est la leçon des quatre
encodages des commandes de maintenance, appliquée à la sortie.

### J3 et J4 — agent

| Point du plan | Ce qui a été fait |
|---|---|
| Sources WMI | Conformes au §4.2, plus `Win32_NetworkAdapter` pour un seul bit : `PhysicalAdapter`. `GetAdaptersAddresses` n'expose aucun « est virtuelle », et faire correspondre les descriptions à une liste de produits d'hyperviseur est l'heuristique que l'élection d'adresse avait déjà refusée. |
| `driver_version` des cartes réseau | **Abandonné.** Le joindre demanderait `Win32_PnPSignedDriver` et une troisième requête ; la colonne reste, vide. Une version de pilote à laquelle on ne peut pas se fier vaut moins qu'une cellule vide. |
| Cartes réseau | Un **second parcours** de `GetAdaptersAddresses`, délibérément pas un élargissement du premier : les deux filtrent à l'opposé, et un parcours partagé paramétré par un booléen est la façon dont l'élection — validée sur poste réel avec cinq APIPA et deux commutateurs Hyper-V — changerait un jour en silence. |
| Cycle lent | Conforme, avec le compteur de génération. Le cache `wuCache` a été **généralisé** en `stateCache[T]` (`agent/internal/agent/cache.go`) : c'est le deuxième utilisateur du même mécanisme et de la même course, et les cinq tests du cache Windows Update passent inchangés derrière un alias de type. |
| Verrou | `inventoryOp` **distinct** de `wuOp`, et pas partagé : les deux ne touchent rien en commun — l'un ouvre une session WUA, l'autre lit WMI et le registre — et un verrou unique ferait bloquer par une recherche Windows Update de six heures un inventaire qu'un administrateur vient de demander. |
| Hachage | SHA-256 du bloc sérialisé, listes triées d'abord. Le tri n'est pas de la propreté : WMI rend ses lignes dans l'ordre où le fournisseur les a énumérées, et une simple permutation renverrait tout l'inventaire et réécrirait toutes les lignes côté serveur. Volontairement **pas** stable d'une version à l'autre — ajouter un champ change le hachage de tout le parc, ce qui coûte un inventaire par poste et est exactement le bon résultat, puisqu'il y a désormais un champ que le serveur n'a pas. |
| `inventory_scan` | Court-circuite le test de hachage : quelqu'un a demandé, et « rien n'a changé, donc la console montre toujours le relevé de la semaine dernière » serait indiscernable d'une commande silencieusement ratée. Non marquée « longue » : quelques secondes, et un `running` que personne n'a le temps de lire est du bruit. |
| Secure Boot | Lu **dans le registre** (`SecureBoot\State`) et non via `Confirm-SecureBootUEFI` : le cmdlet est du PowerShell — un lancement de processus que cet agent évite — et il *lève* sur une machine en BIOS au lieu de répondre « non ». Absent est la réponse honnête : une machine sans UEFI n'a pas de Secure Boot à avoir éteint. |

### J5 — console

Les quatre cartes se posent sur le `MachineInfoCard` sorti du découpage
préalable, et la page « Logiciels du parc » (`SoftwarePage.vue`) rejoint le menu.
Trois choix méritent d'être notés :

- **La barre d'occupation est dans la liste, pas seulement sur la fiche.** C'est
  la seule donnée de tout le module qui se lit sans être analysée, et la colonne
  existe pour être triée : « montre-moi les postes qui n'ont plus de place ».
- **Le compte de postes du catalogue est un lien, pas un nombre.** Lire « 148
  postes » sans pouvoir voir lesquels, ce serait la fonctionnalité qui s'arrête
  un clic trop tôt.
- **Secure Boot et le TPM ne s'affichent que là où ils veulent dire quelque
  chose.** Une machine sans UEFI n'a pas de Secure Boot à avoir éteint et une VM
  n'a pas de puce TPM : afficher « Non » se lirait comme un constat, et c'est le
  genre de constat qui génère un ticket.

### J6 — vérification

- **Backend** : `ruff` + `mypy --strict` verts sur 67 fichiers ; **362 tests**
  verts sur Postgres 16, dont 29 nouveaux (16 pour la réception, 13 pour les
  requêtes de parc) ; migration `0014_inventory` rejouée
  `upgrade`/`downgrade`/`upgrade` sur base vierge, puis `alembic check`.
- **Agent** : `gofmt`, `go vet` et `go test` verts, **26 tests neufs** sur toute
  la logique pure (châssis, hyperviseurs, CIM_DATETIME, conversions, fusion des
  deux vues d'un disque, règles de filtrage logiciel, clés de cartes réseau,
  stabilité du hachage) ; builds croisés `windows/amd64`, `windows/arm64`, Linux.
- **Console** : `vue-tsc`, `prettier`, build SPA verts ; **168 vitest**
  (94 % de couverture sur les couches testées).
- **Documentation** : README (feuille de route et fonctionnalités), DEPLOYMENT.md
  (les deux nouvelles clés, dont `ReportSoftware` et ce qu'il efface),
  `plan-projet-tiai.md` (suivi d'avancement).

**Ce qui reste à valider sur poste réel** — et ne peut l'être nulle part
ailleurs : toute la couche WMI et registre. En tête, la **comparaison ligne à
ligne de la liste des logiciels avec « Applications et fonctionnalités »**, qui
est le seul juge des quatre règles de filtrage du §4.1 ; puis un portable, un
poste fixe et une VM pour le châssis, l'absence de batterie et `hw_is_virtual` ;
et la preuve qu'un poste stable ne réécrit rien pendant 48 h, que le compteur
d'écritures donnera comme il a donné les « 18 heartbeats, 2 écritures » de la
Phase 2.

---

## 12. Suites de l'audit 2026-11

L'audit du 2026-11-10 (`plan-audit-2026-11.md`) avait relevé dans ce chantier des défauts d'export, de filtre et de recherche, et un catalogue logiciel dont la croissance n'était pas bornée. Les tâches ci-dessous sont corrigées depuis le 2026-11-11. Une seconde passe de vérification, le 2026-11-13, a relevé des écarts résiduels, suivis dans `plan-audit-2026-11.md` §6.

Tâches dans l'ordre de priorité, avec la numérotation `Txx` du plan d'ensemble, reprise dans les commits et les PR.

- [x] **T12** · *P1 court terme* — **Export Excel : neutraliser les caractères de contrôle** ([S11](plan-audit-2026-11.md#s11))
  Dans `xlsx_response`, retirer les caractères refusés par openpyxl (`ILLEGAL_CHARACTERS_RE`), et idéalement dès la réception du heartbeat, dans `bound_text`.

- [x] **T15** · *P1 court terme* — **Remettre « Rafraîchir l'inventaire » dans les menus** ([B12](plan-audit-2026-11.md#b12))
  Ajouter `'inventory'` à `groupOrder` (`frontend/src/services/commands.ts:324`), avec un test qui vérifie que chaque action du catalogue apparaît dans un groupe.

- [x] **T19** · *P1 court terme* — **Carte « Disque presque plein » : respecter le seuil réglé** ([B01](plan-audit-2026-11.md#b01))
  Accepter tout seuil de 1 à 99 dans `machineFiltersFromQuery` (`machineListFilters.ts:314`) et l'afficher dans la puce de filtre.

- [x] **T36** · *P3 fond* — **Données déclarées par l'agent : placement en salle et catalogue logiciel** ([S20](plan-audit-2026-11.md#s20), [S21](plan-audit-2026-11.md#s21))
  Vérifier que le DN rapporté est cohérent avec la machine avant de la rattacher à une salle de l'annuaire, et ne plus adopter automatiquement une salle créée à la main. Limiter le débit du heartbeat par poste et purger les logiciels qui ne sont plus installés sur aucun poste.

- [x] **T39** · *P3 fond* — **Recherches : échapper `%` et `_`** ([S26](plan-audit-2026-11.md#s26))
  Factoriser `_escape_like` et l'appliquer à toutes les recherches par sous-chaîne : logiciels, postes et comptes.

- [x] **T42** · *P3 fond* — **Page Logiciels et filtre par logiciel** ([B20](plan-audit-2026-11.md#b20), [U08](plan-audit-2026-11.md#u08), [U09](plan-audit-2026-11.md#u09))
  Mettre la recherche, le tri et la page dans l'URL. Afficher « Vu depuis » dans le fuseau du navigateur. Nommer le logiciel dans la puce de filtre, et distinguer « aucun résultat » d'« erreur ».
