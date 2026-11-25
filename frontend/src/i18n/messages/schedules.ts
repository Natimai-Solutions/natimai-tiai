import type { Translation } from './types';

/** Les planifications (plan `dev/plan-evolutions-itil.md`, chantier C3). */
const fr = {
  title: 'Planifications',
  subtitle:
    'Une commande lancée plus tard ou chaque semaine, au nom de son auteur, sur une cible relue au moment de l’exécution. Heures du fuseau {zone}.',
  refresh: 'Actualiser',
  newSchedule: 'Nouvelle planification',
  plan: 'Planifier',
  empty: {
    none: 'Aucune planification.',
    loadFailed: 'Les planifications n’ont pas pu être chargées.',
  },
  columns: {
    name: 'Nom',
    action: 'Action',
    target: 'Cible',
    when: 'Quand',
    next: 'Prochaine exécution',
    last: 'Dernière exécution',
    state: 'État',
  },
  state: {
    active: 'Active',
    disabled: 'Désactivée',
    suspended: 'Suspendue',
    done: 'Exécutée',
    to_approve: 'À approuver',
  },
  /** Two-person approval (C10). */
  approval: {
    waiting: 'En attente d’approbation, avant le {at}.',
    approvedBy:
      'Approuvée par {by} le {at} pour {count} poste. | Approuvée par {by} le {at} pour {count} postes.',
  },
  suspended: {
    author_gone: 'Le compte de son auteur n’existe plus.',
    author_inactive: 'Le compte de son auteur est désactivé.',
    permission_lost: 'Son auteur n’a plus le droit « {permission} ».',
    target_gone: 'La salle ou le bâtiment visé n’existe plus ou est hors de portée.',
    package_gone: 'Le paquet à déployer n’existe plus.',
    approval_required:
      'Elle vise plus de postes que ce qui a été approuvé, ou son auteur a changé : une approbation est nécessaire.',
    approval_rejected: 'Sa demande d’approbation a été refusée.',
    approval_expired: 'Sa demande d’approbation a expiré sans décision.',
    in_past: 'Son heure était passée au moment de l’approbation.',
    forbidden_window: 'Elle tombait dans une plage interdite au moment de l’approbation.',
    reenable: 'La réactiver la reprend à votre nom.',
  },
  target: {
    all: 'Tout le parc',
    domain: 'Domaine {value}',
    location: 'Emplacement {value}',
    status: 'Postes « {value} »',
    room: 'Salle {value}',
    building: 'Bâtiment {value}',
    machines: '{names} | {names} | {names} et {more} autre(s)',
    unknownPlace: 'Salle ou bâtiment supprimé',
  },
  when: {
    once: 'Le {date} à {time}',
    weekly: 'Chaque {days} à {time}',
    everyDay: 'Tous les jours à {time}',
  },
  options: {
    wakeFirst: 'réveil d’abord',
    shutdownAfter: 'extinction après',
    rings: '{count} étapes',
  },
  actions: {
    edit: 'Modifier',
    disable: 'Désactiver',
    enable: 'Réactiver',
    delete: 'Supprimer',
    runs: 'Exécutions',
    deleteConfirm:
      'Supprimer la planification « {name} » et son historique ? Les commandes déjà créées restent dans l’historique des postes.',
    cancel: 'Annuler',
    saved: 'Planification enregistrée',
    savedToApprove:
      'Planification enregistrée, en attente d’approbation : un second compte doit l’approuver avant le {at}.',
    enabledToApprove: 'Planification réactivée, en attente d’approbation par un second compte.',
    deleted: 'Planification supprimée',
    enabled: 'Planification réactivée',
    disabled: 'Planification désactivée',
    failed: 'L’opération a échoué',
  },
  form: {
    titleNew: 'Nouvelle planification',
    titleEdit: 'Modifier la planification',
    name: 'Nom',
    action: 'Action',
    package: 'Paquet',
    target: 'Cible',
    targetKind: {
      machines: 'Postes choisis',
      room: 'Une salle',
      building: 'Un bâtiment',
      location: 'Un emplacement',
      domain: 'Un domaine',
      all: 'Tout le parc',
    },
    room: 'Salle',
    building: 'Bâtiment',
    location: 'Emplacement',
    domain: 'Domaine',
    machinesChosen: '{count} poste(s) choisi(s)',
    recurrence: 'Quand',
    once: 'Une fois',
    weekly: 'Chaque semaine',
    date: 'Date',
    time: 'Heure',
    days: 'Jours',
    zoneHint: 'Heure du fuseau {zone}',
    ttl: 'Attente des postes',
    ttlHint:
      'Une commande non prise dans ce délai expire : un poste réveillé met quelques minutes à se connecter.',
    hours: 'heures',
    wakeFirst: 'Réveiller d’abord les postes éteints',
    shutdownAfter: 'Éteindre ensuite les postes réveillés',
    shutdownAfterHint:
      'Seulement ceux que la planification a réveillés, une fois leur commande terminée, et jamais un poste où une session est ouverte.',
    rings: 'Déployer par étapes',
    ringsHint:
      'Une étape après l’autre (salle pilote, puis le reste) : la suivante ne part qu’après le délai d’observation, et rien ne part au-delà du seuil d’échec.',
    stage: 'Étape {n}',
    addStage: 'Ajouter une étape',
    removeStage: 'Retirer l’étape',
    observe: 'Observation',
    threshold: 'Seuil d’échec',
    percent: '%',
    nameRequired: 'Le nom est obligatoire',
    daysRequired: 'Au moins un jour',
    required: 'Obligatoire',
    save: 'Enregistrer',
    cancel: 'Annuler',
    forbiddenHint: 'Plages interdites : {windows}',
  },
  runs: {
    title: 'Exécutions de « {name} »',
    none: 'Aucune exécution pour l’instant.',
    status: {
      running: 'En cours',
      done: 'Terminée',
      suspended: 'Suspendue',
      failed: 'Non exécutée',
      halted: 'Arrêtée',
    },
    counts: '{created} commande(s), {skipped} déjà en attente',
    woken: '{count} réveillé(s)',
    shutDown: '{count} éteint(s)',
    keptOn: '{count} laissé(s) allumé(s)',
    leftOut: '{count} hors de portée ou coupé(s)',
    stage: 'étape {n}',
    cause: {
      missed: 'Le serveur était arrêté à l’heure prévue (le {due}) : exécution sautée.',
      forbidden_window: 'Tombée dans une plage interdite ajoutée depuis : exécution sautée.',
      ring_failed:
        'Étape {stage} : {failed} échec(s) sur {finished} ({percent} %), au-delà du seuil de {threshold} %.',
      ring_no_result:
        'Étape {stage} : aucun poste n’a répondu ({created} commande(s) envoyée(s)) ; l’étape suivante n’est pas lancée.',
      schedule_disabled:
        'Planification désactivée pendant l’observation de l’étape {stage} : les étapes suivantes ne sont pas lancées.',
      internal_error:
        'Erreur du serveur pendant l’exécution (voir ses journaux) : exécution sautée.',
      approval_required:
        'Au départ, {count} postes visés au-delà de ce qui a été approuvé (seuil {threshold}) : planification suspendue.',
      approval_required_stage:
        'Planification en attente d’approbation pendant l’observation de l’étape {stage} : les étapes suivantes ne sont pas lancées.',
      schedule_changed:
        'Planification modifiée pendant le déploiement : les étapes suivantes ne sont pas lancées.',
    },
  },
  window: '{days} {start}–{end}',
  windowsNone: 'aucune',
  /** A risky command sent by hand to several postes inside a window. */
  forbiddenConfirm: {
    title: 'Plage interdite',
    message:
      'Nous sommes dans une plage interdite ({window}). Envoyer quand même cette commande à risque à {count} poste(s) ?',
    deploy:
      'Nous sommes dans une plage interdite ({window}). Lancer quand même ce déploiement sur plusieurs postes ?',
    ok: 'Envoyer quand même',
    cancel: 'Annuler',
  },
};

const en: Translation<typeof fr> = {
  title: 'Schedules',
  subtitle:
    'A command run later or every week, on behalf of its author, on a target read again when it runs. Times in the {zone} zone.',
  refresh: 'Refresh',
  newSchedule: 'New schedule',
  plan: 'Schedule',
  empty: {
    none: 'No schedule.',
    loadFailed: 'The schedules could not be loaded.',
  },
  columns: {
    name: 'Name',
    action: 'Action',
    target: 'Target',
    when: 'When',
    next: 'Next run',
    last: 'Last run',
    state: 'State',
  },
  state: {
    active: 'Active',
    disabled: 'Disabled',
    suspended: 'Suspended',
    done: 'Run',
    to_approve: 'To approve',
  },
  approval: {
    waiting: 'Waiting for approval, before {at}.',
    approvedBy:
      'Approved by {by} on {at} for {count} computer. | Approved by {by} on {at} for {count} computers.',
  },
  suspended: {
    author_gone: 'Its author’s account no longer exists.',
    author_inactive: 'Its author’s account is deactivated.',
    permission_lost: 'Its author no longer holds “{permission}”.',
    target_gone: 'The targeted room or building no longer exists or is out of reach.',
    package_gone: 'The package to deploy no longer exists.',
    approval_required:
      'It targets more computers than were approved, or its author changed: an approval is needed.',
    approval_rejected: 'Its approval request was rejected.',
    approval_expired: 'Its approval request expired without a decision.',
    in_past: 'Its time had passed when it was approved.',
    forbidden_window: 'It fell in a forbidden window when it was approved.',
    reenable: 'Turning it back on puts it in your name.',
  },
  target: {
    all: 'The whole fleet',
    domain: 'Domain {value}',
    location: 'Location {value}',
    status: '“{value}” computers',
    room: 'Room {value}',
    building: 'Building {value}',
    machines: '{names} | {names} | {names} and {more} more',
    unknownPlace: 'Room or building deleted',
  },
  when: {
    once: 'On {date} at {time}',
    weekly: 'Every {days} at {time}',
    everyDay: 'Every day at {time}',
  },
  options: {
    wakeFirst: 'wake first',
    shutdownAfter: 'shut down after',
    rings: '{count} stages',
  },
  actions: {
    edit: 'Edit',
    disable: 'Disable',
    enable: 'Turn back on',
    delete: 'Delete',
    runs: 'Runs',
    deleteConfirm:
      'Delete the schedule “{name}” and its history? The commands it already created stay in the computers’ history.',
    cancel: 'Cancel',
    saved: 'Schedule saved',
    savedToApprove:
      'Schedule saved, waiting for approval: a second account must approve it before {at}.',
    enabledToApprove: 'Schedule turned back on, waiting for approval by a second account.',
    deleted: 'Schedule deleted',
    enabled: 'Schedule turned back on',
    disabled: 'Schedule disabled',
    failed: 'The operation failed',
  },
  form: {
    titleNew: 'New schedule',
    titleEdit: 'Edit the schedule',
    name: 'Name',
    action: 'Action',
    package: 'Package',
    target: 'Target',
    targetKind: {
      machines: 'Chosen computers',
      room: 'A room',
      building: 'A building',
      location: 'A location',
      domain: 'A domain',
      all: 'The whole fleet',
    },
    room: 'Room',
    building: 'Building',
    location: 'Location',
    domain: 'Domain',
    machinesChosen: '{count} computer chosen | {count} computers chosen',
    recurrence: 'When',
    once: 'Once',
    weekly: 'Every week',
    date: 'Date',
    time: 'Time',
    days: 'Days',
    zoneHint: 'Time in the {zone} zone',
    ttl: 'Waiting for the computers',
    ttlHint:
      'A command not picked up within this delay expires: a woken computer takes a few minutes to connect.',
    hours: 'hours',
    wakeFirst: 'Wake the computers that are off first',
    shutdownAfter: 'Shut down the woken computers after',
    shutdownAfterHint:
      'Only those the schedule woke, once their command is done, and never a computer with a session open.',
    rings: 'Deploy in stages',
    ringsHint:
      'One stage after the other (a pilot room, then the rest): the next only starts after the observation delay, and nothing starts above the failure threshold.',
    stage: 'Stage {n}',
    addStage: 'Add a stage',
    removeStage: 'Remove the stage',
    observe: 'Observation',
    threshold: 'Failure threshold',
    percent: '%',
    nameRequired: 'The name is required',
    daysRequired: 'At least one day',
    required: 'Required',
    save: 'Save',
    cancel: 'Cancel',
    forbiddenHint: 'Forbidden windows: {windows}',
  },
  runs: {
    title: 'Runs of “{name}”',
    none: 'No run yet.',
    status: {
      running: 'Running',
      done: 'Done',
      suspended: 'Suspended',
      failed: 'Not run',
      halted: 'Halted',
    },
    counts: '{created} command(s), {skipped} already waiting',
    woken: '{count} woken',
    shutDown: '{count} shut down',
    keptOn: '{count} left on',
    leftOut: '{count} out of reach or cut off',
    stage: 'stage {n}',
    cause: {
      missed: 'The server was down at the planned time ({due}): run skipped.',
      forbidden_window: 'Fell in a forbidden window added since: run skipped.',
      ring_failed:
        'Stage {stage}: {failed} failure(s) out of {finished} ({percent} %), above the {threshold} % threshold.',
      ring_no_result:
        'Stage {stage}: no computer answered ({created} command(s) sent); the next stage is not started.',
      schedule_disabled:
        'Schedule disabled while stage {stage} was under observation: the later stages are not started.',
      internal_error: 'Server error during the run (see its logs): run skipped.',
      approval_required:
        'At its start, {count} computers targeted beyond what was approved (threshold {threshold}): schedule suspended.',
      approval_required_stage:
        'Schedule waiting for approval while stage {stage} was under observation: the later stages are not started.',
      schedule_changed: 'Schedule changed during the deployment: the later stages are not started.',
    },
  },
  window: '{days} {start}–{end}',
  windowsNone: 'none',
  forbiddenConfirm: {
    title: 'Forbidden window',
    message:
      'We are inside a forbidden window ({window}). Send this risky command to {count} computer(s) anyway?',
    deploy:
      'We are inside a forbidden window ({window}). Start this deployment on several computers anyway?',
    ok: 'Send anyway',
    cancel: 'Cancel',
  },
};

export default { fr, en };
