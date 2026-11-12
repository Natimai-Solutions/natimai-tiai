# Déploiement logiciel — guide d'utilisation

Tia'i installe et désinstalle des logiciels sur les postes depuis la console,
de trois façons :

| Façon | Pour quoi | Ce qui fait foi sur le poste |
|---|---|---|
| **winget** | Les logiciels courants du dépôt Microsoft : Firefox, Chrome, 7-Zip, VLC, LibreOffice, Adobe Reader… | La GPO active winget sur le poste. winget télécharge l'installateur et vérifie son empreinte. |
| **Paquet signé** (méthode B) | Tout le reste : un `.exe` ou un `.msi` avec sa ligne de commande, et des fichiers annexes (un `.iss` de réponses, un fichier de licence…). | Le paquet est signé par **votre** certificat, que la GPO approuve. |
| **Éditeur approuvé** (méthode A, repli) | Un `.exe` signé par son éditeur, quand on ne veut ou ne peut pas signer soi-même (ex. Pronote, signé par INDEX EDUCATION SAS). | La GPO approuve le nom de l'éditeur, et Windows valide la signature du fichier. |

Les trois sont **coupées par défaut**. Tant qu'aucune GPO ne les ouvre, un
poste refuse toute installation et l'écrit dans le résultat de la commande. Le
serveur Tia'i ne peut rien y changer : c'est voulu. Le poste n'exécute que ce
que **votre domaine** a approuvé, même si le serveur était compromis.

---

## 1. Activer sur les postes (GPO)

Toutes les valeurs se posent dans `HKLM\SOFTWARE\Tiai`, la clé que l'agent
protège déjà (SYSTEM et Administrateurs seulement). Dans la GPO des postes :
**Configuration ordinateur → Préférences → Paramètres Windows → Registre →
Nouveau → Élément Registre**, ruche `HKEY_LOCAL_MACHINE`, clé `SOFTWARE\Tiai`.

| Valeur | Type | Contenu |
|---|---|---|
| `DeployWinget` | `REG_DWORD` | `1` active winget. Absente ou `0` : coupé. |
| `DeployWingetAllow` | `REG_MULTI_SZ` | *Facultatif.* Les seuls identifiants winget autorisés, un par ligne : `Mozilla.Firefox`, ou un préfixe terminé par `*` (`Mozilla.*`). Absente : tout le dépôt winget est autorisé. |
| `DeploySigners` | `REG_MULTI_SZ` | Méthode B : l'**empreinte SHA-256** de chaque certificat dont la signature est acceptée, une par ligne (voir § 2). |
| `DeployPublishers` | `REG_MULTI_SZ` | Méthode A : le **nom du signataire** de chaque éditeur approuvé, une par ligne, tel que l'onglet *Signatures numériques* de l'installateur l'affiche (ex. `INDEX EDUCATION SAS`). |

L'agent relit ces valeurs à chaque commande : une GPO appliquée (`gpupdate`)
prend effet au déploiement suivant, sans redémarrer le service.

> **Une GPO par périmètre, si besoin.** Les valeurs étant par poste, on peut
> n'activer winget que sur les salles informatiques, ou n'approuver un éditeur
> que sur les postes de la vie scolaire, en liant la GPO à la bonne OU.

### Méthode A : trouver le nom de l'éditeur

Clic droit sur l'installateur → *Propriétés* → onglet **Signatures
numériques** : la colonne *Nom du signataire* donne le nom à reporter dans
`DeployPublishers`, par exemple `INDEX EDUCATION SAS` pour
`Install_PRNclient_FR_2026.2.8_win64.exe`. Le même nom apparaît dans la console,
à côté du fichier déposé (« signé par … »).

Un fichier sans onglet *Signatures numériques* n'est pas signé : la méthode A
lui est fermée, il faut passer par la méthode B.

### Méthode B : préparer le certificat de signature

Il faut un certificat de **signature de code** dont vous détenez la clé
privée, sur le poste depuis lequel vous signerez. Celui de l'AC interne qui
signe déjà l'agent convient (DEPLOYMENT.md, « Signature de l'agent »), comme un
certificat dédié, idéalement sur carte à puce ou token.

Pour lire son empreinte SHA-256 à mettre dans `DeploySigners` :

```powershell
.\Sign-TiaiPackage.ps1 -ShowThumbprint
```

Le script cherche le certificat dans votre magasin (`CurrentUser\My`, puis
`LocalMachine\My`). S'il en trouve plusieurs, ajoutez
`-CertificateThumbprint <empreinte certmgr>`.

> **Pourquoi SHA-256 et pas l'empreinte affichée par certmgr ?** certmgr montre
> une empreinte SHA-1. Pour une ancre de confiance, c'est trop faible : on sait
> fabriquer deux certificats de même SHA-1. Le script affiche la bonne valeur.

Au renouvellement du certificat, ajoutez la nouvelle empreinte à
`DeploySigners` **avant** de signer avec lui, puis retirez l'ancienne une fois
les paquets re-signés.

---

## 2. Créer un paquet dans la console

Menu **Paquets** (droit `package:write` pour créer, `package:read` pour
consulter). Bouton **Nouveau paquet**.

### Un paquet winget

1. Choisir **winget**, donner un nom (« Firefox ») et l'**identifiant exact**,
   tel que `winget search firefox` l'affiche : `Mozilla.Firefox`.
2. Sur la page du paquet, facultatif : une version précise (vide = la plus
   récente), et le **nom dans l'inventaire**, qui sert à compter les postes
   équipés (par défaut, le nom du paquet).

C'est tout. Le paquet est prêt.

### Un paquet de fichiers : l'exemple de Pronote

1. **Préparer l'installation silencieuse.** Pronote s'installe sans question
   en rejouant un fichier de réponses : lancez une fois l'installateur en
   mode enregistrement sur un poste de test (procédure d'Index Éducation,
   « installation silencieuse des clients »), et récupérez le fichier `.iss`
   produit.
2. **Nouveau paquet → Fichiers**, nom « Client PRONOTE », version
   « 2026.2.8 ».
3. Sur la page du paquet, **déposer** l'installateur
   `Install_PRNclient_FR_2026.2.8_win64.exe` et le fichier de réponses, par
   exemple `ClientPRONOTE.iss`. La console affiche « signé par INDEX EDUCATION
   SAS » à côté de l'installateur.
4. Renseigner la **définition** :
   - *Fichier à lancer pour installer* : l'installateur ;
   - *Arguments d'installation* : `-s -f1"{dir}\ClientPRONOTE.iss"`.
     `{dir}` désigne le dossier où le poste a déposé les fichiers. Les
     arguments vont **directement** à l'installateur, jamais à un `cmd.exe` ;
   - *Nom dans l'inventaire* : `PRONOTE` ;
   - *Codes de sortie acceptés* : `0, 3010, 1641` (3010 et 1641 signifient
     « réussi, redémarrage requis »).
5. **Enregistrer.** Quand le paquet est complet, la mention « Pas encore
   déployable » disparaît.

**Un `.msi`** ne se lance pas lui-même : choisissez `msiexec` comme *fichier à
lancer*, avec les arguments `/i "{dir}\application.msi" /qn /norestart`. Le
paquet doit alors être **signé** (méthode B) : la méthode A ne fait confiance
qu'à un `.exe` d'éditeur, et `msiexec` accepterait n'importe quel MSI.

**Désinstallation** (facultative) : un fichier du paquet avec ses arguments,
ou `msiexec` avec `/x {code-produit} /qn /norestart`. En méthode A, seule la
forme `msiexec /x {code produit}` est acceptée, et l'agent reconstruit
lui-même les arguments.

### Signer le paquet (méthode B)

Recommandé dès que possible, même pour un installateur d'éditeur : la
signature couvre **la ligne de commande et chaque fichier**, `.iss` compris.
La méthode A, elle, ne garantit que l'installateur.

En méthode A, les fichiers qui accompagnent l'installateur ne peuvent être
que des **données** (`.iss`, `.ini`, `.xml`, `.cab`…) : l'agent refuse un
paquet non signé qui place à côté de l'exécutable un fichier que Windows
pourrait charger ou lancer depuis ce dossier (`.dll`, `.ocx`, `.cpl`, `.sys`,
`.manifest`, `.local`, `.config`, autre `.exe`, `.msi`, `.mst`, script…).
Un tel paquet doit être signé (méthode B). Avant chaque exécution, l'agent
retire aussi du dossier du paquet tout ce que le manifeste ne nomme pas.

1. Page du paquet, carte *Confiance des postes* : **Télécharger le
   manifeste**. C'est un fichier JSON lisible, qui décrit exactement ce que
   les postes exécuteront.
2. Sur votre poste, signer :
   ```powershell
   .\Sign-TiaiPackage.ps1 -Manifest .\Client-PRONOTE-2026.2.8.tiai-manifest.json
   ```
   Le script affiche les fichiers et les commandes, demande confirmation, puis
   écrit `Client-PRONOTE-2026.2.8.sig.json`.
3. **Déposer la signature** sur la page du paquet. La console la vérifie et
   affiche « Signé par … » avec l'empreinte du certificat.

**Toute modification** de la ligne de commande ou des fichiers change le
manifeste et **annule la signature** : la console le signale, il suffit de
re-télécharger le manifeste et de re-signer.

---

## 3. Déployer

Il faut le droit **commandes à risque** (`risky_command:execute`) en plus de
`package:read` : installer un logiciel modifie le poste durablement.

- **Sur un poste** : fiche du poste → bouton **Logiciel** → choisir le paquet,
  *Installer* ou *Désinstaller*.
- **Sur une sélection** : liste des postes, cocher des postes (ou filtrer sur
  une salle, puis tout cocher) → **Installer un logiciel**.
- **Sur un site ou tout le parc** : page du paquet → **Déployer** → *Un
  emplacement* ou *Tout le parc*.

Un compte limité à certains emplacements (page Groupes) ne déploie que sur
ses postes, y compris quand il choisit « Tout le parc ».

Le poste reçoit la commande à son prochain contact (une minute environ, s'il
est allumé), télécharge les fichiers, vérifie leur empreinte et la confiance,
lance l'installation, puis relance l'inventaire. Un poste éteint la reçoit en
démarrant, tant que la commande n'a pas expiré.

### Suivre

La carte **Déploiements** de la page du paquet liste chaque poste visé, son
statut (*En attente*, *Transmise*, *En cours*, *Réussie*, *Échec*, *Expirée*)
et le résultat : la méthode de confiance utilisée, « Redémarrage requis » le
cas échéant, ou la raison d'un refus. La ligne **Présent sur N poste(s)**
compte les postes dont l'inventaire montre le logiciel.

Les redémarrages ne sont **jamais** automatiques : la commande *Redémarrer* du
poste reste à part.

### Les refus courants, et quoi faire

| Résultat de la commande | Cause | Remède |
|---|---|---|
| « déploiement non activé sur ce poste » | Aucune valeur `Deploy*` sur le poste | La GPO n'est pas liée à son OU, ou `gpupdate` n'est pas passé |
| « winget non activé sur ce poste » | `DeployWinget` absent ou à 0 | GPO |
| « identifiant winget … absent de DeployWingetAllow » | Liste d'autorisation posée, identifiant absent | Ajouter l'identifiant à la GPO |
| « winget absent de ce poste » | App Installer non installé (LTSC, Windows Server) | Utiliser un paquet de fichiers |
| « certificat de signature non approuvé sur ce poste » | Empreinte absente de `DeploySigners` | GPO ; attention au renouvellement du certificat |
| « éditeur … non approuvé sur ce poste » | Nom absent de `DeployPublishers` | GPO, avec le nom exact du signataire |
| « signature … refusée par Windows » | Fichier altéré, certificat révoqué ou expiré sans horodatage | Retélécharger l'installateur chez l'éditeur |
| « … a renvoyé le code 1618 » | Une autre installation Windows était en cours | Relancer plus tard |
| « … a renvoyé le code 1603 » | Échec de l'installateur lui-même | Tester l'installation silencieuse à la main sur un poste |

---

## 4. Retirer un paquet

**Retirer** un paquet le sort du catalogue : il ne peut plus être installé, mais
il reste désinstallable et son historique est conservé. **Remettre au
catalogue** l'y replace.

## 5. Côté serveur

Les fichiers sont stockés sur le volume Docker `packages`, un fichier par
empreinte SHA-256, et servis aux seuls postes qui ont une commande ouverte sur
le paquet. Ce volume n'est pas dans le dump PostgreSQL : sauvegardez-le avec la
base, ou conservez les installateurs d'origine pour pouvoir les redéposer.
Réglages : `PACKAGES_DIR`, `PACKAGE_MAX_BYTES` (2 Gio par défaut),
`PACKAGE_MAX_CONCURRENT_DOWNLOADS` (20) — voir DEPLOYMENT.md.
