import type { Translation } from './types';

/**
 * Le catalogue des commandes et leurs résultats (lot F du plan console
 * bilingue): the command catalogue's labels, the history card, the result
 * dialog — and the verdicts the server and the agent store in a command's
 * result, worded from their codes (`services/commands.ts`,
 * `commandMessage`).
 *
 * The French of `results` is, word for word, what the server
 * (`backend/app/features/command/texts.py`) and the agent
 * (`agent/internal/msg/catalogue.go`) write beside the code: the shared
 * cases in `backend/tests/data/command_texts_fr.json` and
 * `agent/internal/msg/testdata/messages_fr.json` check it
 * (`services/commandResults.spec.ts`).
 *
 * A code is a path in `results` (`wol.relay.sent`); `words` holds the pieces
 * some of them are built from. French keeps « (s) » where it always wrote
 * it: its two plural forms are the same sentence.
 */
const fr = {
  groups: {
    defender: 'Defender',
    windows_update: 'Windows Update',
    inventory: 'Inventaire',
    power: 'Alimentation',
    maintenance: 'Maintenance',
    diagnostic: 'Diagnostic',
  },
  actions: {
    quick_scan: { label: 'Scan rapide' },
    full_scan: {
      label: 'Scan complet',
      hint: 'Un scan complet mobilise le poste pendant plusieurs dizaines de minutes.',
    },
    update_signatures: { label: 'Mise à jour des signatures' },
    wu_scan: { label: 'Rechercher les mises à jour' },
    wu_install: {
      label: 'Installer les mises à jour (hors pilotes)',
      hint: 'Le poste télécharge et installe ses mises à jour logicielles ; compter plusieurs dizaines de minutes. Aucun redémarrage automatique : le poste signalera s’il en attend un.',
    },
    wu_install_full: {
      label: 'Installer les mises à jour (pilotes compris)',
      hint: 'Le poste télécharge et installe ses mises à jour, y compris les pilotes proposés par Windows Update — à réserver aux postes où c’est souhaité ; compter plusieurs dizaines de minutes. Aucun redémarrage automatique : le poste signalera s’il en attend un.',
    },
    wu_reset: {
      label: 'Réinitialiser Windows Update',
      hint: 'Procédure Microsoft : les services Windows Update sont arrêtés, le magasin de mises à jour et le cache de signatures sont renommés, puis les services repartent. Windows les reconstruit à la recherche suivante — l’historique des mises à jour du poste est perdu et les correctifs déjà téléchargés le seront à nouveau. Rien n’est installé ni redémarré.',
    },
    inventory_scan: { label: "Rafraîchir l'inventaire" },
    reboot: {
      label: 'Redémarrer le poste',
      okMany: 'Redémarrer {count} postes',
      hint: 'Le redémarrage a lieu dans 60 secondes ; l’utilisateur connecté voit un avertissement et peut enregistrer son travail. Les documents non enregistrés seront perdus.',
    },
    shutdown: {
      label: 'Arrêter le poste',
      okMany: 'Arrêter {count} postes',
      hint: 'Le poste s’éteint dans 60 secondes ; l’utilisateur connecté voit un avertissement et peut enregistrer son travail. Les documents non enregistrés seront perdus. Le poste ne remontera plus rien tant qu’il n’aura pas été rallumé — sur place, ou par « Réveiller le poste » si son matériel le permet.',
    },
    wake_on_lan: { label: 'Réveiller le poste (Wake-on-LAN)' },
    gpo_update: { label: 'Appliquer les stratégies (ordinateur)' },
    flush_dns: { label: 'Vider le cache DNS' },
    time_resync: { label: "Resynchroniser l'horloge" },
    cert_pulse: { label: 'Relancer l’inscription des certificats' },
    spooler_reset: {
      label: 'Réinitialiser le spouleur d’impression',
      hint: 'Le service est arrêté, la file d’impression est vidée, puis le service redémarre : les travaux en attente sont perdus.',
    },
    sfc_scan: {
      label: 'Vérifier l’intégrité système (sfc)',
      hint: 'Compter 10 à 20 minutes, pendant lesquelles le poste est sollicité.',
    },
    dism_restore_health: {
      label: 'Réparer l’image système (DISM)',
      hint: 'Jusqu’à une heure. Les correctifs sont téléchargés depuis Windows Update ou le serveur WSUS du poste.',
    },
    dism_component_cleanup: {
      label: 'Nettoyer le magasin de composants (DISM)',
      hint: 'Libère de l’espace disque ; compter plusieurs dizaines de minutes.',
    },
    chkdsk_scan: {
      label: 'Analyser le disque (chkdsk)',
      hint: 'Analyse en ligne : elle signale les erreurs sans les corriger, le poste reste utilisable.',
    },
    gpo_report: { label: 'Rapport de stratégies (gpresult)' },
    net_config: { label: 'Configuration réseau (ipconfig)' },
    package_install: { label: 'Installation de logiciel' },
    package_uninstall: { label: 'Désinstallation de logiciel' },
  },
  rowLabel: '{label} — {package}',
  status: {
    pending: 'En attente',
    delivered: 'Transmise',
    running: 'En cours',
    succeeded: 'Réussie',
    failed: 'Échec',
    expired: 'Expirée',
  },
  send: {
    sent: 'Commande envoyée',
    revoked: '« {label} » non envoyée : le token de ce poste est révoqué.',
    already: '« {label} » est {where} sur ce poste.',
    where: {
      pending: 'déjà en attente',
      delivered: 'déjà transmise',
      running: 'déjà en cours',
    },
  },
  confirm: {
    questionOne: 'Lancer « {label} » sur ce poste ?',
    questionMany: 'Lancer « {label} » sur {count} postes ?',
    withSessions: 'Dont {count} avec une session ouverte.',
    withSessionOne: 'Une session utilisateur est ouverte sur ce poste.',
    runOne: 'Lancer',
    runMany: 'Lancer sur {count} postes',
    cancel: 'Annuler',
  },
  bulk: {
    nothing: 'Rien à envoyer : {parts}.',
    alreadyEverywhere:
      'cette commande est déjà en attente sur {count} poste(s) | cette commande est déjà en attente sur {count} poste(s)',
    revokedPostes: '{count} poste(s) au token révoqué | {count} poste(s) au token révoqué',
    partsSeparator: ' ; ',
    sent: '{count} commande(s) envoyée(s) | {count} commande(s) envoyée(s)',
    alreadyPending: '{count} déjà en attente',
    revoked: '{count} au token révoqué',
    leftSeparator: ', ',
    sentAndLeft: '{sent} — {left}, ignoré(s)',
  },
  card: {
    title: 'Dernières commandes',
    what: 'les commandes',
    notLoaded: 'Commandes non chargées.',
    empty: 'Aucune commande.',
    showOutput: 'Voir le résultat',
    showError: "Voir l'erreur",
    columns: {
      type: 'Type',
      status: 'Statut',
      createdBy: 'Par',
      createdAt: 'Créée le',
      finishedAt: 'Terminée le',
    },
  },
  output: {
    errorTitle: "Détail de l'erreur",
    outputTitle: 'Résultat de la commande',
    finished: '{label} — terminée le',
    copy: 'Copier',
    close: 'Fermer',
    copied: 'Copié dans le presse-papiers',
    copyFailed: 'Copie impossible',
  },
  /** What ends a text cut short. */
  truncated: {
    server: '\n[…] sortie tronquée par le serveur',
    agent: "\n[…] sortie tronquée à {kib} Kio par l'agent",
  },
  /** A relayed wake's verdict, signed by the relay. */
  relayed: 'Relayé par {relay} — {text}',
  results: {
    command: {
      unanswered:
        "Sans réponse du poste {hours} h après la remise : commande considérée comme perdue (poste éteint, agent arrêté ou mis à jour pendant l'exécution). Relancez-la si besoin.",
      merged: 'Poste fusionné : commande annulée',
    },
    package: {
      deleted: "Paquet supprimé avant l'exécution",
      retired_after_queue: 'Paquet retiré après la mise en file : installation annulée',
      changed_after_queue:
        'Paquet modifié après la mise en file (fichiers, ligne de commande ou signature) : relancez le déploiement pour envoyer la nouvelle version',
      retired: 'Paquet retiré : installation annulée',
      superseded: 'Remplacée par un nouveau déploiement',
    },
    wol: {
      no_mac:
        "Aucune adresse MAC connue pour ce poste : son agent n'en a jamais remonté (agent antérieur à la fonction, ou carte réseau sans adresse exploitable). Un poste ne peut être réveillé qu'après au moins une remontée de son agent.",
      no_ipv4:
        "Aucune adresse de diffusion pour ce poste : sa dernière adresse IP connue est absente ou n'est pas de l'IPv4. Renseigner WOL_BROADCAST_ADDRESSES côté serveur pour émettre malgré tout.",
      address_not_allowed:
        'Réveil refusé : la dernière adresse IP connue du poste ({ip}) est hors des réseaux sur lesquels le serveur peut émettre un réveil ({allowed}). Ajouter le réseau du poste à WOL_ALLOWED_NETWORKS côté serveur, ou renseigner WOL_BROADCAST_ADDRESSES.',
      subnet_not_allowed:
        "Réveil refusé : l'adresse du poste ({ip}) est autorisée, mais son sous-réseau ({masks}) n'est pas contenu en entier dans les réseaux sur lesquels le serveur peut émettre un réveil ({allowed}). Élargir WOL_ALLOWED_NETWORKS au sous-réseau entier du poste, ou renseigner WOL_BROADCAST_ADDRESSES.",
      send_failed: 'Émission du paquet magique impossible : {detail}',
      sent: "Paquet magique émis vers {mac} — {copies} copie(s) sur {targets}.\nL'émission ne prouve pas le réveil : le protocole n'accuse rien, et le poste ne réapparaîtra dans la console qu'à la remontée de son agent. | Paquet magique émis vers {mac} — {copies} copie(s) sur {targets}.\nL'émission ne prouve pas le réveil : le protocole n'accuse rien, et le poste ne réapparaîtra dans la console qu'à la remontée de son agent.",
      no_site:
        "Ce poste n'a ni emplacement ni domaine connu : le serveur ne peut désigner aucun poste voisin pour relayer le réveil. Renseigner l'emplacement dans la configuration de l'agent (location).",
      no_relay:
        "Aucun poste allumé sur {site} pour relayer le réveil : le paquet magique doit partir d'un poste du même réseau que la cible, et aucun poste habilité à relayer (agent à jour, inscrit depuis assez longtemps, identité confirmée) n'est en contact avec le serveur en ce moment.",
      relay_queued:
        "Réveil confié aux postes de {site} : {peers} poste(s) allumé(s) peuvent relayer le paquet magique, le premier à contacter le serveur s'en charge (sous {ttl_minutes} min, sinon le réveil expire).\nL'émission ne prouvera pas le réveil : le protocole n'accuse rien, et le poste ne réapparaîtra dans la console qu'à la remontée de son agent. | Réveil confié aux postes de {site} : {peers} poste(s) allumé(s) peuvent relayer le paquet magique, le premier à contacter le serveur s'en charge (sous {ttl_minutes} min, sinon le réveil expire).\nL'émission ne prouvera pas le réveil : le protocole n'accuse rien, et le poste ne réapparaîtra dans la console qu'à la remontée de son agent.",
      relay_already: "Réveil {state} depuis {elapsed} ; rien de nouveau n'a été mis en file.",
      back_online:
        "Poste revenu en ligne : son agent a contacté le serveur — le seul accusé de réception qu'un réveil puisse avoir.",
      unknown_machine: 'Poste introuvable : il a été supprimé ou fusionné.',
      relay: {
        sent: "Paquet magique émis vers {mac} depuis ce poste — {copies} copie(s) sur {targets}.\nL'émission ne prouve pas le réveil : le protocole n'accuse rien, et le poste visé ne réapparaîtra dans la console qu'à la remontée de son agent. | Paquet magique émis vers {mac} depuis ce poste — {copies} copie(s) sur {targets}.\nL'émission ne prouve pas le réveil : le protocole n'accuse rien, et le poste visé ne réapparaîtra dans la console qu'à la remontée de son agent.",
        no_subnet: "ce poste n'a aucun sous-réseau IPv4 sur lequel diffuser le paquet magique",
        nic_failed: 'lecture des cartes réseau de ce poste : {detail}',
        send_failed: 'émission du paquet magique impossible : {detail}',
        bad_mac: 'adresse MAC à réveiller invalide : {mac}',
      },
    },
    agent: {
      backlog_full:
        "file d'attente de l'agent pleine ({max} commandes) : commande non exécutée, à relancer",
      stopped: "interrompue par l'arrêt de l'agent avant d'avoir commencé : à relancer",
      unsupported_type:
        "type de commande {type} non pris en charge par l'agent {version} : mettez l'agent à jour",
      power_pending:
        'un {noun} de ce poste est déjà programmé : commande non exécutée, à relancer une fois le poste revenu en ligne',
    },
    power: {
      too_soon:
        'opération refusée : un {noun} a déjà été programmé sur ce poste il y a {ago} (délai minimum {min})',
      too_soon_boot:
        "opération refusée : ce poste a démarré il y a {ago} (délai minimum {min} avant de l'arrêter ou de le redémarrer à nouveau)",
      scheduled: '{label} programmé dans {seconds} secondes.\n',
      schedule_failed: "{label} : l'opération n'a pas pu être programmée (code {code})",
    },
    wu: {
      scan: '{count} mise(s) à jour en attente. | {count} mise(s) à jour en attente.',
      timeout: "délai d'exécution dépassé pour l'opération Windows Update",
      interrupted: "opération Windows Update interrompue (arrêt de l'agent)",
      known_error: '{hint} ({detail})',
      install_incomplete: "{failed} mise(s) à jour sur {selected} n'ont pas été installées",
      install_result: 'installation {result} (code {code})',
    },
    inventory: {
      scan: '{disks}, {volumes}, {nics}, {software}.',
      scan_without_software:
        '{disks}, {volumes}, {nics}, inventaire logiciel désactivé sur ce poste.',
      unavailable: 'inventaire indisponible sur cette plateforme',
    },
    defender: {
      quick_scan: {
        timeout:
          "délai dépassé : l'analyse rapide Defender ne s'est pas terminée en {budget}. L'analyse peut se poursuivre sur le poste : vérifier la date de dernière analyse rapide avant de la relancer. Un dépassement répété signale un moteur Defender bloqué (redémarrer le poste).",
        interrupted: "l'analyse rapide Defender a été interrompue (arrêt de l'agent) : à relancer",
      },
      full_scan: {
        timeout:
          "délai dépassé : l'analyse complète Defender ne s'est pas terminée en {budget}. L'analyse peut se poursuivre sur le poste : vérifier la date de dernière analyse complète avant de la relancer. Si les analyses complètes de ce parc sont légitimement plus longues (gros disques mécaniques), augmenter defender_full_scan_timeout_seconds (registre : DefenderFullScanTimeoutSeconds).",
        interrupted:
          "l'analyse complète Defender a été interrompue (arrêt de l'agent) : à relancer",
      },
      signatures: {
        timeout:
          "délai dépassé : la mise à jour des signatures Defender ne s'est pas terminée en {budget}. Vérifier que le poste joint sa source de signatures (WSUS, Windows Update ou partage de définitions configuré par stratégie).",
        interrupted:
          "la mise à jour des signatures Defender a été interrompue (arrêt de l'agent) : à relancer",
      },
    },
    maintenance: {
      timeout: "délai d'exécution dépassé pour {exe}",
      interrupted: "exécution de {exe} interrompue (arrêt de l'agent)",
      launch_failed: 'lancement de {exe} : {detail}',
      exit_code: 'code de retour {code}',
    },
    sfc: {
      failed: 'sfc a terminé en erreur (code {code})',
      failed_summary: 'sfc a terminé en erreur (code {code}) : {summary}',
    },
    dism: {
      source_missing:
        "source de réparation inaccessible ({hresult}) : ce poste ne joint ni Windows Update ni son serveur WSUS, ou la source de réparation n'y est pas publiée",
      failed: 'dism a terminé en erreur (code {code})',
    },
    chkdsk: {
      failed: 'chkdsk a terminé avec le code {code}',
      offline_repair:
        'chkdsk : {meaning} (code {code}) — une réparation hors ligne (chkdsk /spotfix, appliquée au redémarrage) est nécessaire',
    },
    time: {
      service_stopped: 'le service de temps Windows (W32Time) est arrêté sur ce poste ({hresult})',
      failed: "la resynchronisation de l'horloge a échoué (code {code})",
    },
    spooler: {
      reset:
        "Spouleur d'impression arrêté.\nFile d'impression purgée ({removed} fichier(s)).\nSpouleur d'impression redémarré. | Spouleur d'impression arrêté.\nFile d'impression purgée ({removed} fichier(s)).\nSpouleur d'impression redémarré.",
      stop_failed: 'arrêt du spouleur : {detail}',
      start_failed: 'démarrage du spouleur : {detail}',
      purge_failed: "purge de la file d'impression : {detail}",
    },
    deploy: {
      unsupported: 'déploiement logiciel non pris en charge sur ce système',
      not_enabled: 'déploiement non activé sur ce poste (aucune clé Deploy* posée par GPO)',
      no_package: 'commande sans paquet',
      package_id_refused: 'identifiant de paquet refusé : {id}',
      bad_manifest: 'manifeste absent ou mal encodé',
      no_step: 'le paquet ne définit pas de {step}',
      no_trust_method:
        "aucune méthode de confiance pour les paquets de fichiers n'est activée sur ce poste (DeploySigners / DeployPublishers)",
      unsigned_no_publisher:
        'paquet non signé, et aucun éditeur approuvé sur ce poste (DeployPublishers)',
      install_removes:
        "l'installation de ce paquet lance une désinstallation (msiexec /x, /uninstall ou REMOVE=) : refusée — placez cette commande dans la désinstallation du paquet",
      method_a: {
        msiexec: "méthode A : msiexec n'est accepté que pour désinstaller un code produit",
        exe_only:
          'méthode A : seul un exécutable (.exe) signé par un éditeur approuvé peut être lancé — signez le paquet (méthode B)',
        too_large:
          'méthode A : le manifeste annonce plus de {gib} Gio à télécharger — signez le paquet (méthode B)',
        loadable:
          "méthode A : {file} ne peut pas accompagner l'exécutable (fichier que Windows pourrait charger ou lancer) — signez le paquet (méthode B)",
      },
      signature: {
        unsigned: 'paquet non signé',
        bad_certificate: 'certificat de signature mal encodé',
        untrusted:
          'certificat de signature non approuvé sur ce poste (empreinte {thumbprint} absente de DeploySigners)',
        unreadable_certificate: 'certificat de signature illisible : {detail}',
        bad_signature: 'signature mal encodée',
        algorithm_mismatch: 'algorithme incompatible avec la clé',
        invalid: 'signature invalide : le manifeste a changé depuis sa signature',
        unsupported_key: 'type de clé non pris en charge',
      },
      not_signed: 'fichier non signé (pas de signature Authenticode)',
      authenticode_refused: 'signature de {file} refusée par Windows : {detail}',
      publisher_not_approved: 'éditeur {publisher} non approuvé sur ce poste (DeployPublishers)',
      download_failed: 'téléchargement de {file} : {detail}',
      launch_failed: 'lancement de {file} : {detail}',
      exit_code: '{file} a renvoyé le code {code}{trust}',
      done: '{verb} de {what} terminée ({how}){reboot}',
      winget_done: 'winget {action} {id} : terminé{already}',
      winget_no_match: 'aucun paquet winget ne correspond à cet identifiant',
      winget_failed: 'winget a échoué (code {code})',
      winget_not_enabled: 'winget non activé sur ce poste (valeur DeployWinget absente ou à 0)',
      winget_missing:
        'winget absent de ce poste (App Installer non installé — fréquent sur LTSC et Windows Server) : utiliser un paquet de fichiers',
      winget_refused: 'identifiant winget refusé : {id}',
      winget_not_allowed: 'identifiant winget {id} absent de DeployWingetAllow',
      winget_version_refused: 'version winget refusée : {version}',
    },
  },
  /** The pieces some verdicts are built from. */
  words: {
    privateRanges: 'les plages privées 10.0.0.0/8, 172.16.0.0/12 et 192.168.0.0/16',
    defaultMask: '/{prefix} de WOL_SUBNET_PREFIXLEN',
    masksReported: 'masque /{prefix} remonté par le poste, à défaut {fallback}',
    masksDefault: 'masque {fallback}',
    site: {
      location: "l'emplacement « {site} »",
      domain: 'le domaine « {site} »',
    },
    relayState: {
      delivered: 'déjà transmis à un poste relais',
      pending: "déjà en attente d'un poste relais",
    },
    elapsed: {
      lessThanMinute: "moins d'une minute",
      minutes: '{minutes} min',
      hours: '{hours} h {minutes}',
    },
    power: {
      noun: { reboot: 'redémarrage', shutdown: 'arrêt' },
      label: { reboot: 'Redémarrage', shutdown: 'Arrêt' },
    },
    wuHints: {
      h0x80070422: 'le service Windows Update (wuauserv) est désactivé sur ce poste',
      h0x8024402c:
        'la source de mises à jour est injoignable : le poste ne résout pas le nom de son serveur WSUS (ou de Windows Update)',
      h0x80072ee2:
        'délai dépassé en joignant la source de mises à jour : réseau, proxy ou serveur WSUS indisponible',
      h0x8024002e:
        "l'accès à Windows Update est interdit par stratégie : ce poste doit passer par son serveur WSUS",
      h0x80248014:
        "service de mises à jour inconnu : la configuration WSUS du poste pointe vers un service qui n'existe pas",
      h0x80244022: 'le serveur de mises à jour a répondu « service indisponible » (HTTP 503)',
      h0x80240016:
        'une autre installation est déjà en cours (TrustedInstaller occupé) : réessayer plus tard',
      h0x80240438: "aucune source de mises à jour n'est configurée sur ce poste",
    },
    wuResult: {
      succeeded: 'installée',
      succeeded_with_errors: 'installée avec des erreurs',
      failed: 'échec',
      aborted: 'abandonnée',
      in_progress: 'encore en cours',
      not_started: 'non démarrée',
    },
    inventory: {
      disks: '{count} disque(s) | {count} disque(s)',
      volumes: '{count} volume(s) | {count} volume(s)',
      nics: '{count} carte(s) réseau | {count} carte(s) réseau',
      software: '{count} logiciel(s) | {count} logiciel(s)',
    },
    chkdsk: {
      errors_found: 'des erreurs ont été trouvées',
      partly_checked: "le volume n'a pas pu être entièrement vérifié",
      not_checked: "le volume n'a pas pu être vérifié",
    },
    deployStep: { install: 'installation', uninstall: 'désinstallation' },
    deployVerb: { install: 'Installation', uninstall: 'Désinstallation' },
    packageId: 'paquet {id}',
    method: 'méthode {method}',
    trustSigner: 'paquet signé par {by}',
    trustPublisher: 'éditeur approuvé : {by}',
    revocationOffline: ' (révocation non vérifiable hors ligne)',
    trustInParentheses: ' ({note})',
    howSeparator: ', ',
    rebootToFinish: '\nRedémarrage requis pour terminer.',
    wingetAlready: ' (déjà installé, rien à faire)',
  },
};

const en: Translation<typeof fr> = {
  groups: {
    defender: 'Defender',
    windows_update: 'Windows Update',
    inventory: 'Inventory',
    power: 'Power',
    maintenance: 'Maintenance',
    diagnostic: 'Diagnostics',
  },
  actions: {
    quick_scan: { label: 'Quick scan' },
    full_scan: {
      label: 'Full scan',
      hint: 'A full scan keeps the computer busy for several tens of minutes.',
    },
    update_signatures: { label: 'Update signatures' },
    wu_scan: { label: 'Check for updates' },
    wu_install: {
      label: 'Install updates (no drivers)',
      hint: 'The computer downloads and installs its software updates; allow several tens of minutes. No automatic restart: the computer will report if it needs one.',
    },
    wu_install_full: {
      label: 'Install updates (drivers included)',
      hint: 'The computer downloads and installs its updates, including the drivers offered by Windows Update — keep this for computers where that is wanted; allow several tens of minutes. No automatic restart: the computer will report if it needs one.',
    },
    wu_reset: {
      label: 'Reset Windows Update',
      hint: 'Microsoft’s procedure: the Windows Update services are stopped, the update store and the signature cache are renamed, then the services start again. Windows rebuilds them at the next check — the computer’s update history is lost and patches already downloaded will be downloaded again. Nothing is installed or restarted.',
    },
    inventory_scan: { label: 'Refresh the inventory' },
    reboot: {
      label: 'Restart the computer',
      okMany: 'Restart {count} computers',
      hint: 'The restart happens in 60 seconds; the signed-in user sees a warning and can save their work. Unsaved documents will be lost.',
    },
    shutdown: {
      label: 'Shut down the computer',
      okMany: 'Shut down {count} computers',
      hint: 'The computer shuts down in 60 seconds; the signed-in user sees a warning and can save their work. Unsaved documents will be lost. The computer will report nothing until it is switched back on — on site, or with “Wake the computer” if its hardware allows.',
    },
    wake_on_lan: { label: 'Wake the computer (Wake-on-LAN)' },
    gpo_update: { label: 'Apply policies (computer)' },
    flush_dns: { label: 'Flush the DNS cache' },
    time_resync: { label: 'Resynchronise the clock' },
    cert_pulse: { label: 'Restart certificate enrolment' },
    spooler_reset: {
      label: 'Reset the print spooler',
      hint: 'The service is stopped, the print queue is emptied, then the service restarts: waiting jobs are lost.',
    },
    sfc_scan: {
      label: 'Check system integrity (sfc)',
      hint: 'Allow 10 to 20 minutes, during which the computer is under load.',
    },
    dism_restore_health: {
      label: 'Repair the system image (DISM)',
      hint: 'Up to an hour. Patches are downloaded from Windows Update or the computer’s WSUS server.',
    },
    dism_component_cleanup: {
      label: 'Clean up the component store (DISM)',
      hint: 'Frees disk space; allow several tens of minutes.',
    },
    chkdsk_scan: {
      label: 'Scan the disk (chkdsk)',
      hint: 'Online scan: it reports errors without fixing them, and the computer stays usable.',
    },
    gpo_report: { label: 'Policy report (gpresult)' },
    net_config: { label: 'Network configuration (ipconfig)' },
    package_install: { label: 'Software installation' },
    package_uninstall: { label: 'Software uninstallation' },
  },
  rowLabel: '{label} — {package}',
  status: {
    pending: 'Pending',
    delivered: 'Delivered',
    running: 'Running',
    succeeded: 'Succeeded',
    failed: 'Failed',
    expired: 'Expired',
  },
  send: {
    sent: 'Command sent',
    revoked: '“{label}” not sent: this computer’s token is revoked.',
    already: '“{label}” is {where} on this computer.',
    where: {
      pending: 'already pending',
      delivered: 'already delivered',
      running: 'already running',
    },
  },
  confirm: {
    questionOne: 'Run “{label}” on this computer?',
    questionMany: 'Run “{label}” on {count} computers?',
    withSessions: 'Of which {count} with a user signed in.',
    withSessionOne: 'A user is signed in on this computer.',
    runOne: 'Run',
    runMany: 'Run on {count} computers',
    cancel: 'Cancel',
  },
  bulk: {
    nothing: 'Nothing to send: {parts}.',
    alreadyEverywhere:
      'this command is already pending on {count} computer | this command is already pending on {count} computers',
    revokedPostes: '{count} computer with a revoked token | {count} computers with a revoked token',
    partsSeparator: '; ',
    sent: '{count} command sent | {count} commands sent',
    alreadyPending: '{count} already pending',
    revoked: '{count} with a revoked token',
    leftSeparator: ', ',
    sentAndLeft: '{sent} — {left}, skipped',
  },
  card: {
    title: 'Latest commands',
    what: 'the commands',
    notLoaded: 'Commands not loaded.',
    empty: 'No commands.',
    showOutput: 'Show the result',
    showError: 'Show the error',
    columns: {
      type: 'Type',
      status: 'Status',
      createdBy: 'By',
      createdAt: 'Created',
      finishedAt: 'Finished',
    },
  },
  output: {
    errorTitle: 'Error details',
    outputTitle: 'Command result',
    finished: '{label} — finished on',
    copy: 'Copy',
    close: 'Close',
    copied: 'Copied to the clipboard',
    copyFailed: 'Could not copy',
  },
  truncated: {
    server: '\n[…] output cut short by the server',
    agent: '\n[…] output cut short at {kib} KiB by the agent',
  },
  relayed: 'Relayed by {relay} — {text}',
  results: {
    command: {
      unanswered:
        'No answer from the computer {hours} h after delivery: the command is considered lost (computer off, agent stopped or updated while it ran). Run it again if needed.',
      merged: 'Computer merged: command cancelled',
    },
    package: {
      deleted: 'Package deleted before it ran',
      retired_after_queue: 'Package retired after it was queued: installation cancelled',
      changed_after_queue:
        'Package changed after it was queued (files, command line or signature): deploy it again to send the new version',
      retired: 'Package retired: installation cancelled',
      superseded: 'Replaced by a newer deployment',
    },
    wol: {
      no_mac:
        'No MAC address known for this computer: its agent never reported one (agent older than the feature, or a network card with no usable address). A computer can only be woken once its agent has reported at least once.',
      no_ipv4:
        'No broadcast address for this computer: its last known IP address is missing or not IPv4. Set WOL_BROADCAST_ADDRESSES on the server to send anyway.',
      address_not_allowed:
        'Wake refused: the computer’s last known IP address ({ip}) is outside the networks the server may send a wake on ({allowed}). Add the computer’s network to WOL_ALLOWED_NETWORKS on the server, or set WOL_BROADCAST_ADDRESSES.',
      subnet_not_allowed:
        'Wake refused: the computer’s address ({ip}) is allowed, but its subnet ({masks}) is not wholly inside the networks the server may send a wake on ({allowed}). Widen WOL_ALLOWED_NETWORKS to the computer’s whole subnet, or set WOL_BROADCAST_ADDRESSES.',
      send_failed: 'Could not send the magic packet: {detail}',
      sent: 'Magic packet sent to {mac} — {copies} copy to {targets}.\nSending does not prove the wake: the protocol acknowledges nothing, and the computer will only reappear in the console when its agent reports. | Magic packet sent to {mac} — {copies} copies to {targets}.\nSending does not prove the wake: the protocol acknowledges nothing, and the computer will only reappear in the console when its agent reports.',
      no_site:
        'This computer has no known location or domain: the server cannot pick a neighbouring computer to relay the wake. Set the location in the agent’s configuration (location).',
      no_relay:
        'No computer on at {site} to relay the wake: the magic packet must leave from a computer on the same network as the target, and no computer allowed to relay (agent up to date, enrolled long enough, identity confirmed) is in contact with the server right now.',
      relay_queued:
        'Wake handed to the computers at {site}: {peers} computer that is on can relay the magic packet, the first to contact the server does it (within {ttl_minutes} min, or the wake expires).\nSending will not prove the wake: the protocol acknowledges nothing, and the computer will only reappear in the console when its agent reports. | Wake handed to the computers at {site}: {peers} computers that are on can relay the magic packet, the first to contact the server does it (within {ttl_minutes} min, or the wake expires).\nSending will not prove the wake: the protocol acknowledges nothing, and the computer will only reappear in the console when its agent reports.',
      relay_already: 'Wake {state} for {elapsed}; nothing new was queued.',
      back_online:
        'Computer back online: its agent contacted the server — the only acknowledgement a wake can have.',
      unknown_machine: 'Computer not found: it was deleted or merged.',
      relay: {
        sent: 'Magic packet sent to {mac} from this computer — {copies} copy to {targets}.\nSending does not prove the wake: the protocol acknowledges nothing, and the target computer will only reappear in the console when its agent reports. | Magic packet sent to {mac} from this computer — {copies} copies to {targets}.\nSending does not prove the wake: the protocol acknowledges nothing, and the target computer will only reappear in the console when its agent reports.',
        no_subnet: 'this computer has no IPv4 subnet to broadcast the magic packet on',
        nic_failed: 'reading this computer’s network cards: {detail}',
        send_failed: 'could not send the magic packet: {detail}',
        bad_mac: 'invalid MAC address to wake: {mac}',
      },
    },
    agent: {
      backlog_full: 'agent queue full ({max} commands): command not run, run it again',
      stopped: 'interrupted by the agent stopping before it started: run it again',
      unsupported_type: 'command type {type} not supported by agent {version}: update the agent',
      power_pending:
        'a {noun} of this computer is already scheduled: command not run, run it again once the computer is back online',
    },
    power: {
      too_soon:
        'operation refused: a {noun} was already scheduled on this computer {ago} ago (minimum interval {min})',
      too_soon_boot:
        'operation refused: this computer started {ago} ago (minimum interval {min} before shutting it down or restarting it again)',
      scheduled: '{label} scheduled in {seconds} seconds.\n',
      schedule_failed: '{label}: the operation could not be scheduled (code {code})',
    },
    wu: {
      scan: '{count} pending update. | {count} pending updates.',
      timeout: 'time limit exceeded for the Windows Update operation',
      interrupted: 'Windows Update operation interrupted (agent stopping)',
      known_error: '{hint} ({detail})',
      install_incomplete:
        '{failed} of {selected} updates was not installed | {failed} of {selected} updates were not installed',
      install_result: 'installation {result} (code {code})',
    },
    inventory: {
      scan: '{disks}, {volumes}, {nics}, {software}.',
      scan_without_software:
        '{disks}, {volumes}, {nics}, software inventory switched off on this computer.',
      unavailable: 'inventory unavailable on this platform',
    },
    defender: {
      quick_scan: {
        timeout:
          'time limit exceeded: the Defender quick scan did not finish within {budget}. The scan may carry on on the computer: check the date of the last quick scan before running it again. Repeated overruns point to a stuck Defender engine (restart the computer).',
        interrupted: 'the Defender quick scan was interrupted (agent stopping): run it again',
      },
      full_scan: {
        timeout:
          'time limit exceeded: the Defender full scan did not finish within {budget}. The scan may carry on on the computer: check the date of the last full scan before running it again. If full scans on this fleet are legitimately longer (large spinning disks), raise defender_full_scan_timeout_seconds (registry: DefenderFullScanTimeoutSeconds).',
        interrupted: 'the Defender full scan was interrupted (agent stopping): run it again',
      },
      signatures: {
        timeout:
          'time limit exceeded: the Defender signature update did not finish within {budget}. Check that the computer reaches its signature source (WSUS, Windows Update or a definitions share set by policy).',
        interrupted: 'the Defender signature update was interrupted (agent stopping): run it again',
      },
    },
    maintenance: {
      timeout: 'time limit exceeded for {exe}',
      interrupted: '{exe} interrupted (agent stopping)',
      launch_failed: 'starting {exe}: {detail}',
      exit_code: 'exit code {code}',
    },
    sfc: {
      failed: 'sfc ended with an error (code {code})',
      failed_summary: 'sfc ended with an error (code {code}): {summary}',
    },
    dism: {
      source_missing:
        'repair source unreachable ({hresult}): this computer reaches neither Windows Update nor its WSUS server, or the repair source is not published there',
      failed: 'dism ended with an error (code {code})',
    },
    chkdsk: {
      failed: 'chkdsk ended with code {code}',
      offline_repair:
        'chkdsk: {meaning} (code {code}) — an offline repair (chkdsk /spotfix, applied at restart) is needed',
    },
    time: {
      service_stopped: 'the Windows Time service (W32Time) is stopped on this computer ({hresult})',
      failed: 'clock resynchronisation failed (code {code})',
    },
    spooler: {
      reset:
        'Print spooler stopped.\nPrint queue emptied ({removed} file).\nPrint spooler restarted. | Print spooler stopped.\nPrint queue emptied ({removed} files).\nPrint spooler restarted.',
      stop_failed: 'stopping the spooler: {detail}',
      start_failed: 'starting the spooler: {detail}',
      purge_failed: 'emptying the print queue: {detail}',
    },
    deploy: {
      unsupported: 'software deployment not supported on this system',
      not_enabled: 'deployment not enabled on this computer (no Deploy* key set by GPO)',
      no_package: 'command without a package',
      package_id_refused: 'package identifier refused: {id}',
      bad_manifest: 'manifest missing or badly encoded',
      no_step: 'the package defines no {step}',
      no_trust_method:
        'no trust method for file packages is enabled on this computer (DeploySigners / DeployPublishers)',
      unsigned_no_publisher:
        'unsigned package, and no approved publisher on this computer (DeployPublishers)',
      install_removes:
        'this package’s installation runs an uninstallation (msiexec /x, /uninstall or REMOVE=): refused — put this command in the package’s uninstallation',
      method_a: {
        msiexec: 'method A: msiexec is only accepted to uninstall a product code',
        exe_only:
          'method A: only an executable (.exe) signed by an approved publisher can be run — sign the package (method B)',
        too_large:
          'method A: the manifest announces more than {gib} GiB to download — sign the package (method B)',
        loadable:
          'method A: {file} cannot sit next to the executable (a file Windows could load or run) — sign the package (method B)',
      },
      signature: {
        unsigned: 'unsigned package',
        bad_certificate: 'signing certificate badly encoded',
        untrusted:
          'signing certificate not approved on this computer (thumbprint {thumbprint} missing from DeploySigners)',
        unreadable_certificate: 'unreadable signing certificate: {detail}',
        bad_signature: 'signature badly encoded',
        algorithm_mismatch: 'algorithm does not match the key',
        invalid: 'invalid signature: the manifest has changed since it was signed',
        unsupported_key: 'unsupported key type',
      },
      not_signed: 'unsigned file (no Authenticode signature)',
      authenticode_refused: 'signature of {file} refused by Windows: {detail}',
      publisher_not_approved:
        'publisher {publisher} not approved on this computer (DeployPublishers)',
      download_failed: 'downloading {file}: {detail}',
      launch_failed: 'starting {file}: {detail}',
      exit_code: '{file} returned code {code}{trust}',
      done: '{verb} of {what} finished ({how}){reboot}',
      winget_done: 'winget {action} {id}: done{already}',
      winget_no_match: 'no winget package matches this identifier',
      winget_failed: 'winget failed (code {code})',
      winget_not_enabled: 'winget not enabled on this computer (DeployWinget value missing or 0)',
      winget_missing:
        'winget missing from this computer (App Installer not installed — common on LTSC and Windows Server): use a file package',
      winget_refused: 'winget identifier refused: {id}',
      winget_not_allowed: 'winget identifier {id} missing from DeployWingetAllow',
      winget_version_refused: 'winget version refused: {version}',
    },
  },
  words: {
    privateRanges: 'the private ranges 10.0.0.0/8, 172.16.0.0/12 and 192.168.0.0/16',
    defaultMask: '/{prefix} from WOL_SUBNET_PREFIXLEN',
    masksReported: 'mask /{prefix} reported by the computer, otherwise {fallback}',
    masksDefault: 'mask {fallback}',
    site: {
      location: 'the location “{site}”',
      domain: 'the domain “{site}”',
    },
    relayState: {
      delivered: 'already handed to a relay computer',
      pending: 'already waiting for a relay computer',
    },
    elapsed: {
      lessThanMinute: 'less than a minute',
      minutes: '{minutes} min',
      hours: '{hours} h {minutes}',
    },
    power: {
      noun: { reboot: 'restart', shutdown: 'shutdown' },
      label: { reboot: 'Restart', shutdown: 'Shutdown' },
    },
    wuHints: {
      h0x80070422: 'the Windows Update service (wuauserv) is disabled on this computer',
      h0x8024402c:
        'the update source is unreachable: the computer cannot resolve the name of its WSUS server (or of Windows Update)',
      h0x80072ee2:
        'timed out reaching the update source: network, proxy or WSUS server unavailable',
      h0x8024002e:
        'access to Windows Update is forbidden by policy: this computer must go through its WSUS server',
      h0x80248014:
        'unknown update service: the computer’s WSUS configuration points to a service that does not exist',
      h0x80244022: 'the update server answered “service unavailable” (HTTP 503)',
      h0x80240016:
        'another installation is already running (TrustedInstaller busy): try again later',
      h0x80240438: 'no update source is configured on this computer',
    },
    wuResult: {
      succeeded: 'installed',
      succeeded_with_errors: 'installed with errors',
      failed: 'failed',
      aborted: 'aborted',
      in_progress: 'still running',
      not_started: 'not started',
    },
    inventory: {
      disks: '{count} disk | {count} disks',
      volumes: '{count} volume | {count} volumes',
      nics: '{count} network card | {count} network cards',
      software: '{count} program | {count} programs',
    },
    chkdsk: {
      errors_found: 'errors were found',
      partly_checked: 'the volume could not be fully checked',
      not_checked: 'the volume could not be checked',
    },
    deployStep: { install: 'installation', uninstall: 'uninstallation' },
    deployVerb: { install: 'Installation', uninstall: 'Uninstallation' },
    packageId: 'package {id}',
    method: 'method {method}',
    trustSigner: 'package signed by {by}',
    trustPublisher: 'approved publisher: {by}',
    revocationOffline: ' (revocation not checkable offline)',
    trustInParentheses: ' ({note})',
    howSeparator: ', ',
    rebootToFinish: '\nRestart required to finish.',
    wingetAlready: ' (already installed, nothing to do)',
  },
};

export default { fr, en };
