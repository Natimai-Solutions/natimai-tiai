import type { Translation } from './types';

/**
 * Les pages Paquets et la fiche d’un paquet (lot E2 du plan console bilingue).
 *
 * Literal braces are written `{'{'}` and `{'}'}`: vue-i18n reads a bare brace
 * as a placeholder. A placeholder that `PackageRichText` shows in bold or as
 * code is filled by the page (`{publisher}`, `{signers}`…).
 */
const fr = {
  /** How a package reaches a poste (`services/packages` trustLabel). */
  trust: {
    winget: 'winget',
    signed: 'Signé (méthode B)',
    publisher: 'Éditeur (méthode A)',
    none: 'Non signé',
  },
  /** Sizes, as `formatSize` and `methodAMaxLabel` write them. */
  size: {
    bytes: '{n} o',
    kib: '{n} Kio',
    mib: '{n} Mio',
    gib: '{n} Gio',
  },
  /** A package in a list to choose from, when another reads the same. */
  choice: {
    label: '{base} ({kind} — créé le {created})',
    winget: 'winget {id}',
    files: 'fichiers, {run}',
    noRun: 'sans fichier à lancer',
  },
  /** The state of a deployment command. */
  status: {
    pending: 'En attente',
    delivered: 'Transmise',
    running: 'En cours',
    succeeded: 'Réussie',
    failed: 'Échec',
    expired: 'Expirée',
  },
  /** The catalogue (PackagesPage). */
  list: {
    title: 'Paquets',
    showRetired: 'Paquets retirés',
    create: 'Nouveau paquet',
    intro:
      "Ce que la console sait installer. Un paquet {winget} désigne un logiciel du dépôt Microsoft ; un paquet de {files} embarque son installateur et sa ligne de commande. Chaque poste décide de l'exécuter d'après ce que sa GPO approuve : winget, la signature de l'administrateur (méthode B) ou l'éditeur de l'exécutable (méthode A).",
    introWinget: 'winget',
    introFiles: 'fichiers',
    empty: "Aucun paquet pour l'instant",
    columns: {
      name: 'Paquet',
      version: 'Version',
      trust: 'Confiance',
      state: 'État',
      installed: 'Postes équipés',
    },
    retired: 'Retiré',
    ready: 'Prêt',
    noFiles: 'Aucun fichier',
    fileCount: '{count} fichier(s)',
    loadFailed: 'Chargement impossible',
    createFailed: 'Création impossible',
    form: {
      title: 'Nouveau paquet',
      kindWinget: 'winget',
      kindFiles: 'Fichiers (.exe, .msi…)',
      name: 'Nom',
      version: 'Version',
      required: 'Requis',
      wingetId: 'Identifiant winget',
      wingetIdHint: "Exact, tel que « winget search » l'affiche : Mozilla.Firefox, 7zip.7zip…",
      wingetIdInvalid: 'Identifiant invalide',
      filesLater:
        'Les fichiers et la ligne de commande se renseignent sur la page du paquet, une fois créé.',
      cancel: 'Annuler',
      create: 'Créer',
    },
  },
  /** A package's page (PackageDetailPage). */
  detail: {
    back: 'Retour',
    titleFallback: 'Paquet',
    retired: 'Retiré',
    deploy: 'Déployer',
    uninstall: 'Désinstaller',
    restore: 'Remettre au catalogue',
    retire: 'Retirer',
    definition: {
      title: 'Définition',
      name: 'Nom',
      version: 'Version',
      wingetId: 'Identifiant winget',
      wingetVersion: 'Version winget (vide = la plus récente)',
      installRun: 'Fichier à lancer pour installer',
      installArgs: "Arguments d'installation",
      installArgsHint:
        "Ex. -s -f1\"{'{'}dir{'}'}\\ClientPRONOTE.iss\" — {'{'}dir{'}'} = dossier des fichiers sur le poste",
      uninstallRun: 'Désinstallation : fichier à lancer (facultatif)',
      uninstallArgs: 'Arguments de désinstallation',
      uninstallArgsHint: "Avec msiexec : /x {'{'}code produit{'}'} /qn",
      successCodes: 'Codes de sortie acceptés',
      successCodesHint: 'Séparés par des virgules. 3010 et 1641 = redémarrage requis.',
      detectName: "Nom dans l'inventaire",
      detectNameHint:
        "Tel qu'il apparaît dans « Applications et fonctionnalités » ; sert à compter les postes équipés",
      notes: 'Notes',
      signedEditWarning: 'Modifier la ligne de commande annule la signature.',
      unsaved: 'Modifications non enregistrées',
      save: 'Enregistrer',
    },
    /** What the server would refuse a field for, said under it. */
    rules: {
      nameRequired: 'Nom requis',
      wingetIdInvalid: 'Identifiant winget invalide (ex. Mozilla.Firefox)',
      msiexecArgs: "Avec msiexec, indiquer les arguments (ex. /i \"{'{'}dir{'}'}\\app.msi\" /qn)",
      successCodesNone: 'Au moins un code (ex. 0, 3010, 1641)',
      successCodesMax: '32 codes au plus',
      successCodesIntegers: 'Des nombres entiers, séparés par des virgules',
    },
    blockers: {
      notDeployable: 'Pas encore déployable',
      noComputer: 'Aucun poste ne l’installera',
    },
    files: {
      title: 'Fichiers',
      choose: 'Choisir des fichiers',
      upload: 'Déposer',
      cancel: 'Annuler',
      run: 'lancé',
      signedBy: '· signé par {publisher}',
      remove: 'Retirer {name}',
      empty: "Aucun fichier. Pour Pronote : l'installateur et le fichier de réponses .iss.",
    },
    trust: {
      title: 'Confiance des postes',
      winget:
        "Les postes l'installent si leur GPO active winget ({deployWinget} = 1) et, quand elle est posée, si {id} figure dans {allow}. winget télécharge l'installateur et vérifie son empreinte.",
      installed: "Présent d'après l'inventaire sur {count} poste(s).",
    },
    methodB: {
      title: "Méthode B — signature de l'administrateur",
      signed:
        "Signé par {subject} le {date} ({by}). Les postes l'exécutent si la GPO liste l'empreinte de ce certificat dans {signers} :",
      unsigned:
        'Non signé. Téléchargez le manifeste, signez-le sur votre poste avec {script}, puis déposez le fichier de signature produit.',
      downloadManifest: 'Télécharger le manifeste',
      uploadSignature: 'Déposer la signature (.sig.json)',
      removeSignature: 'Retirer la signature',
    },
    methodA: {
      title: 'Méthode A — éditeur approuvé (repli)',
      tooLarge:
        'Indisponible : les fichiers pèsent plus de {max} au total, ce que les postes refusent de télécharger pour un paquet non signé. Signez le paquet (méthode B).',
      publisher:
        "Le fichier lancé est signé par {publisher}. Sans signature de l'administrateur, les postes l'exécutent si la GPO liste ce nom dans {publishers}.",
      signed: 'Inutile : le paquet est signé.',
      loadable:
        "Indisponible : le fichier lancé est signé par {publisher}, mais {files} est à côté, et les postes refusent sous la méthode A tout fichier que Windows pourrait charger ou lancer (.dll, .exe, .msi, scripts…) à côté de l'exécutable. Retirez ce fichier du paquet, ou signez-le (méthode B). | Indisponible : le fichier lancé est signé par {publisher}, mais {files} sont à côté, et les postes refusent sous la méthode A tout fichier que Windows pourrait charger ou lancer (.dll, .exe, .msi, scripts…) à côté de l'exécutable. Retirez ces fichiers du paquet, ou signez-le (méthode B).",
      notExe:
        "Indisponible : le fichier lancé n'est pas un exécutable (.exe) signé par un éditeur.",
    },
    deployments: {
      title: 'Déploiements',
      refresh: 'Actualiser les déploiements',
      summary:
        '{count} poste visé — dernier déploiement de chacun ; un état filtre le tableau sur ces postes : | {count} postes visés — dernier déploiement de chacun ; un état filtre le tableau sur ces postes :',
      chip: '{label} : {n}',
      filtered: 'Dernier déploiement de chaque poste, {status}',
      history: 'Historique : tous les envois, du plus récent au plus ancien',
      noDataFiltered: 'Aucun déploiement dans cet état',
      noData: 'Jamais déployé',
      columns: {
        machine: 'Poste',
        type: 'Action',
        status: 'Statut',
        createdBy: 'Par',
        createdAt: 'Le',
        result: 'Résultat',
      },
    },
    /** Leaving the page with an upload under way or changes not saved. */
    leave: {
      uploading:
        'Un dépôt de fichiers est en cours : quitter la page l’interrompt (les fichiers déjà envoyés sont gardés).',
      dirty: 'La définition du paquet a été modifiée sans être enregistrée.',
      titleUploading: 'Dépôt en cours',
      titleDirty: 'Modifications non enregistrées',
      question: '{what} Quitter la page ?',
      stay: 'Rester',
      okUploading: 'Quitter et interrompre',
      okDirty: 'Quitter sans enregistrer',
    },
    saved: 'Enregistré',
    savedResign: 'Enregistré — le manifeste a changé : la signature est à refaire',
    saveFailed: 'Enregistrement impossible',
    upload: {
      tooLarge: 'Trop volumineux : {files}',
      tooLargeCaption: 'Limite de ce serveur : {size} par fichier.',
      done: 'Fichier déposé | Fichiers déposés',
      rememberSave: 'Pensez à enregistrer la définition.',
      kept: 'Déposé : {files}. | Déposés : {files}.',
      notSent: 'Non envoyé : {files}. | Non envoyés : {files}.',
      interrupted: 'Dépôt interrompu : les fichiers déjà envoyés sont gardés',
      cancelled: 'Dépôt annulé',
      failed: 'Dépôt impossible',
    },
    removeFile: {
      title: 'Retirer le fichier',
      message: 'Retirer « {name} » du paquet ?',
      ok: 'Retirer',
      failed: 'Suppression impossible',
    },
    downloadFailed: 'Téléchargement impossible',
    signature: {
      attached: 'Signature vérifiée et jointe au paquet',
      notSignature: 'Ce fichier n’est pas une signature',
      refused: 'Signature refusée',
    },
    operationFailed: 'Opération impossible',
    cancel: 'Annuler',
    restoreConfirm: {
      title: 'Remettre au catalogue',
      message:
        '« {name} » pourra de nouveau être déployé. Les installations annulées lors du retrait ne sont pas relancées : redéployez le paquet sur les postes voulus.',
      ok: 'Remettre au catalogue',
      done: 'Paquet remis au catalogue',
      doneCaption: 'Les installations annulées au retrait ne sont pas relancées.',
    },
    retireConfirm: {
      pendingUnknown:
        'Les installations en attente (pas encore reçues par leur poste) seront annulées.',
      pending:
        '{count} installation en attente (pas encore reçue par son poste) sera annulée. | {count} installations en attente (pas encore reçues par leur poste) seront annulées.',
      noPending: 'Aucune installation n’est en attente.',
      title: 'Retirer le paquet',
      message:
        '{cancelled} Celles déjà transmises vont à leur terme ; les désinstallations ne sont pas touchées. Le paquet ne sera plus proposé au déploiement, et le remettre au catalogue ne relancera pas les installations annulées.',
      ok: 'Retirer',
      done: 'Paquet retiré',
      doneCaption:
        '{count} installation en attente annulée. | {count} installations en attente annulées.',
    },
    unsavedDeploy: {
      title: 'Modifications non enregistrées',
      message:
        'La définition du paquet a été modifiée sans être enregistrée : le déploiement enverrait la version enregistrée, sans ces modifications.',
      ok: 'Enregistrer puis déployer',
    },
  },
  /** The deploy dialog (PackageDeployDialog). */
  deploy: {
    titleInstall: 'Installer un logiciel',
    titleUninstall: 'Désinstaller un logiciel',
    install: 'Installer',
    uninstall: 'Désinstaller',
    package: 'Paquet',
    noPackage: 'Aucun paquet prêt — voir la page Paquets',
    scopeAll: 'Tout le parc',
    scopeLocation: 'Un emplacement',
    location: 'Emplacement',
    onMachines: 'Sur ce poste. | Sur {count} postes.',
    notDeployable: 'Pas encore déployable',
    cannotUninstall: 'Désinstallation impossible',
    noComputer: 'Aucun poste ne l’installera',
    cancel: 'Annuler',
    okMachines: '{verb} sur {count} postes',
    okAll: '{verb} sur tout le parc',
    okLocation: '{verb} sur {location}',
    trust: {
      wingetInstall:
        'Paquet winget : seuls les postes où la GPO active winget (DeployWinget) l’installeront.',
      wingetUninstall:
        'Paquet winget : seuls les postes où la GPO active winget (DeployWinget) le désinstalleront.',
      signed:
        'Paquet signé : seuls les postes dont la GPO approuve ce certificat (DeploySigners) l’exécuteront.',
      publisher:
        'Non signé par l’administrateur : seuls les postes dont la GPO approuve l’éditeur « {publisher} » (DeployPublishers) l’exécuteront.',
      productCode:
        'Désinstallation par code produit (msiexec /x) : seuls les postes dont la GPO approuve au moins un éditeur (DeployPublishers) l’exécuteront.',
      tooLarge:
        'Plus de {max} de fichiers : sans signature de l’administrateur, aucun poste ne les téléchargera (plafond de la méthode A). Signez le paquet avant de le déployer.',
      noneInstall:
        'Ni signé, ni lancé par un exécutable d’éditeur : aucun poste ne l’exécutera. Signez le paquet avant de le déployer.',
      noneUninstall:
        "Désinstallation ni signée, ni lancée par un exécutable d’éditeur, ni par « msiexec /x {'{'}code produit{'}'} » : aucun poste ne l’exécutera. Signez le paquet avant de le déployer.",
    },
    confirm: {
      whereAll: 'tout le parc',
      whereTargets: 'les postes visés',
      // Zero is said in the singular in French, as before: three forms.
      whereCount: '{count} poste | {count} poste | {count} postes',
      whereCountAll:
        '{count} poste (tout le parc) | {count} poste (tout le parc) | {count} postes (tout le parc)',
      title: '{verb} {name}',
      message: '{verb} sur {where} ?',
    },
    loadFailed: 'Chargement impossible',
    sendFailed: 'Envoi impossible',
  },
};

const en: Translation<typeof fr> = {
  trust: {
    winget: 'winget',
    signed: 'Signed (method B)',
    publisher: 'Publisher (method A)',
    none: 'Unsigned',
  },
  size: {
    bytes: '{n} B',
    kib: '{n} KiB',
    mib: '{n} MiB',
    gib: '{n} GiB',
  },
  choice: {
    label: '{base} ({kind} — created {created})',
    winget: 'winget {id}',
    files: 'files, {run}',
    noRun: 'no file to run',
  },
  status: {
    pending: 'Pending',
    delivered: 'Delivered',
    running: 'Running',
    succeeded: 'Succeeded',
    failed: 'Failed',
    expired: 'Expired',
  },
  list: {
    title: 'Packages',
    showRetired: 'Retired packages',
    create: 'New package',
    intro:
      'What the console can install. A {winget} package names a piece of software in Microsoft’s repository; a {files} package carries its own installer and command line. Each computer decides whether to run it from what its GPO approves: winget, the administrator’s signature (method B) or the executable’s publisher (method A).',
    introWinget: 'winget',
    introFiles: 'files',
    empty: 'No packages yet',
    columns: {
      name: 'Package',
      version: 'Version',
      trust: 'Trust',
      state: 'State',
      installed: 'Computers with it',
    },
    retired: 'Retired',
    ready: 'Ready',
    noFiles: 'No files',
    fileCount: '{count} file | {count} files',
    loadFailed: 'Could not load',
    createFailed: 'Could not create',
    form: {
      title: 'New package',
      kindWinget: 'winget',
      kindFiles: 'Files (.exe, .msi…)',
      name: 'Name',
      version: 'Version',
      required: 'Required',
      wingetId: 'winget identifier',
      wingetIdHint: 'Exactly as “winget search” shows it: Mozilla.Firefox, 7zip.7zip…',
      wingetIdInvalid: 'Invalid identifier',
      filesLater: 'The files and the command line are entered on the package’s page, once created.',
      cancel: 'Cancel',
      create: 'Create',
    },
  },
  detail: {
    back: 'Back',
    titleFallback: 'Package',
    retired: 'Retired',
    deploy: 'Deploy',
    uninstall: 'Uninstall',
    restore: 'Return to the catalogue',
    retire: 'Retire',
    definition: {
      title: 'Definition',
      name: 'Name',
      version: 'Version',
      wingetId: 'winget identifier',
      wingetVersion: 'winget version (empty = the latest)',
      installRun: 'File to run to install',
      installArgs: 'Installation arguments',
      installArgsHint:
        "E.g. -s -f1\"{'{'}dir{'}'}\\ClientPRONOTE.iss\" — {'{'}dir{'}'} = folder of the files on the computer",
      uninstallRun: 'Uninstallation: file to run (optional)',
      uninstallArgs: 'Uninstallation arguments',
      uninstallArgsHint: "With msiexec: /x {'{'}product code{'}'} /qn",
      successCodes: 'Accepted exit codes',
      successCodesHint: 'Separated by commas. 3010 and 1641 = restart required.',
      detectName: 'Name in the inventory',
      detectNameHint:
        'As it appears in “Apps & features”; used to count the computers that have it',
      notes: 'Notes',
      signedEditWarning: 'Changing the command line cancels the signature.',
      unsaved: 'Unsaved changes',
      save: 'Save',
    },
    rules: {
      nameRequired: 'Name required',
      wingetIdInvalid: 'Invalid winget identifier (e.g. Mozilla.Firefox)',
      msiexecArgs: "With msiexec, give the arguments (e.g. /i \"{'{'}dir{'}'}\\app.msi\" /qn)",
      successCodesNone: 'At least one code (e.g. 0, 3010, 1641)',
      successCodesMax: '32 codes at most',
      successCodesIntegers: 'Whole numbers, separated by commas',
    },
    blockers: {
      notDeployable: 'Not deployable yet',
      noComputer: 'No computer will install it',
    },
    files: {
      title: 'Files',
      choose: 'Choose files',
      upload: 'Upload',
      cancel: 'Cancel',
      run: 'runs',
      signedBy: '· signed by {publisher}',
      remove: 'Remove {name}',
      empty: 'No files. For Pronote: the installer and the .iss response file.',
    },
    trust: {
      title: 'Computers’ trust',
      winget:
        'Computers install it if their GPO turns winget on ({deployWinget} = 1) and, when it is set, if {id} is listed in {allow}. winget downloads the installer and checks its hash.',
      installed:
        'Present, according to the inventory, on {count} computers. | Present, according to the inventory, on {count} computer. | Present, according to the inventory, on {count} computers.',
    },
    methodB: {
      title: 'Method B — the administrator’s signature',
      signed:
        'Signed by {subject} on {date} ({by}). Computers run it if the GPO lists this certificate’s thumbprint in {signers}:',
      unsigned:
        'Unsigned. Download the manifest, sign it on your own computer with {script}, then upload the signature file it produces.',
      downloadManifest: 'Download the manifest',
      uploadSignature: 'Upload the signature (.sig.json)',
      removeSignature: 'Remove the signature',
    },
    methodA: {
      title: 'Method A — approved publisher (fallback)',
      tooLarge:
        'Unavailable: the files weigh more than {max} in total, which the computers refuse to download for an unsigned package. Sign the package (method B).',
      publisher:
        'The file that runs is signed by {publisher}. Without the administrator’s signature, computers run it if the GPO lists this name in {publishers}.',
      signed: 'Not needed: the package is signed.',
      loadable:
        'Unavailable: the file that runs is signed by {publisher}, but {files} is next to it, and under method A the computers refuse any file Windows could load or run (.dll, .exe, .msi, scripts…) next to the executable. Remove this file from the package, or sign the package (method B). | Unavailable: the file that runs is signed by {publisher}, but {files} are next to it, and under method A the computers refuse any file Windows could load or run (.dll, .exe, .msi, scripts…) next to the executable. Remove these files from the package, or sign the package (method B).',
      notExe: 'Unavailable: the file that runs is not an executable (.exe) signed by a publisher.',
    },
    deployments: {
      title: 'Deployments',
      refresh: 'Refresh the deployments',
      summary:
        '{count} computer targeted — the latest deployment of each; a state filters the table to these computers: | {count} computers targeted — the latest deployment of each; a state filters the table to these computers:',
      chip: '{label}: {n}',
      filtered: 'Latest deployment of each computer, {status}',
      history: 'History: every send, newest first',
      noDataFiltered: 'No deployment in this state',
      noData: 'Never deployed',
      columns: {
        machine: 'Computer',
        type: 'Action',
        status: 'Status',
        createdBy: 'By',
        createdAt: 'On',
        result: 'Result',
      },
    },
    leave: {
      uploading:
        'Files are being uploaded: leaving the page stops the upload (the files already sent are kept).',
      dirty: 'The package’s definition has been changed and not saved.',
      titleUploading: 'Upload in progress',
      titleDirty: 'Unsaved changes',
      question: '{what} Leave the page?',
      stay: 'Stay',
      okUploading: 'Leave and stop the upload',
      okDirty: 'Leave without saving',
    },
    saved: 'Saved',
    savedResign: 'Saved — the manifest has changed: the package must be signed again',
    saveFailed: 'Could not save',
    upload: {
      tooLarge: 'Too large: {files}',
      tooLargeCaption: 'This server’s limit: {size} per file.',
      done: 'File uploaded | Files uploaded',
      rememberSave: 'Remember to save the definition.',
      kept: 'Uploaded: {files}. | Uploaded: {files}.',
      notSent: 'Not sent: {files}. | Not sent: {files}.',
      interrupted: 'Upload stopped: the files already sent are kept',
      cancelled: 'Upload cancelled',
      failed: 'Could not upload',
    },
    removeFile: {
      title: 'Remove the file',
      message: 'Remove “{name}” from the package?',
      ok: 'Remove',
      failed: 'Could not delete',
    },
    downloadFailed: 'Could not download',
    signature: {
      attached: 'Signature checked and attached to the package',
      notSignature: 'This file is not a signature',
      refused: 'Signature refused',
    },
    operationFailed: 'The operation failed',
    cancel: 'Cancel',
    restoreConfirm: {
      title: 'Return to the catalogue',
      message:
        '“{name}” can be deployed again. The installations cancelled when it was retired are not started again: deploy the package again on the computers you want.',
      ok: 'Return to the catalogue',
      done: 'Package returned to the catalogue',
      doneCaption: 'The installations cancelled when it was retired are not started again.',
    },
    retireConfirm: {
      pendingUnknown:
        'The pending installations (not yet received by their computer) will be cancelled.',
      pending:
        '{count} pending installation (not yet received by its computer) will be cancelled. | {count} pending installations (not yet received by their computer) will be cancelled.',
      noPending: 'No installation is pending.',
      title: 'Retire the package',
      message:
        '{cancelled} Those already delivered run to completion; uninstallations are not affected. The package will no longer be offered for deployment, and returning it to the catalogue will not start the cancelled installations again.',
      ok: 'Retire',
      done: 'Package retired',
      doneCaption:
        '{count} pending installation cancelled. | {count} pending installations cancelled.',
    },
    unsavedDeploy: {
      title: 'Unsaved changes',
      message:
        'The package’s definition has been changed and not saved: the deployment would send the saved version, without these changes.',
      ok: 'Save, then deploy',
    },
  },
  deploy: {
    titleInstall: 'Install software',
    titleUninstall: 'Uninstall software',
    install: 'Install',
    uninstall: 'Uninstall',
    package: 'Package',
    noPackage: 'No package ready — see the Packages page',
    scopeAll: 'The whole fleet',
    scopeLocation: 'One location',
    location: 'Location',
    onMachines: 'On this computer. | On {count} computers.',
    notDeployable: 'Not deployable yet',
    cannotUninstall: 'Cannot be uninstalled',
    noComputer: 'No computer will install it',
    cancel: 'Cancel',
    okMachines: '{verb} on {count} computers',
    okAll: '{verb} on the whole fleet',
    okLocation: '{verb} on {location}',
    trust: {
      wingetInstall:
        'winget package: only the computers whose GPO turns winget on (DeployWinget) will install it.',
      wingetUninstall:
        'winget package: only the computers whose GPO turns winget on (DeployWinget) will uninstall it.',
      signed:
        'Signed package: only the computers whose GPO approves this certificate (DeploySigners) will run it.',
      publisher:
        'Not signed by the administrator: only the computers whose GPO approves the publisher “{publisher}” (DeployPublishers) will run it.',
      productCode:
        'Uninstallation by product code (msiexec /x): only the computers whose GPO approves at least one publisher (DeployPublishers) will run it.',
      tooLarge:
        'More than {max} of files: without the administrator’s signature, no computer will download them (method A’s cap). Sign the package before deploying it.',
      noneInstall:
        'Neither signed, nor run by a publisher’s executable: no computer will run it. Sign the package before deploying it.',
      noneUninstall:
        "Uninstallation neither signed, nor run by a publisher’s executable, nor by “msiexec /x {'{'}product code{'}'}”: no computer will run it. Sign the package before deploying it.",
    },
    confirm: {
      whereAll: 'the whole fleet',
      whereTargets: 'the targeted computers',
      whereCount: '{count} computers | {count} computer | {count} computers',
      whereCountAll:
        '{count} computers (the whole fleet) | {count} computer (the whole fleet) | {count} computers (the whole fleet)',
      title: '{verb} {name}',
      message: '{verb} on {where}?',
    },
    loadFailed: 'Could not load',
    sendFailed: 'Could not send',
  },
};

export default { fr, en };
