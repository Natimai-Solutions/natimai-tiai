import type { Translation } from './types';

/**
 * Maintenance : cycles, séances, échéances (lot D du plan console bilingue):
 * what `services/maintenance` says of a due date, a state, a cycle; the
 * dialogs that record, read and set a maintenance; a poste's card.
 */
const fr = {
  actions: {
    cancel: 'Annuler',
    save: 'Enregistrer',
    delete: 'Supprimer',
    close: 'Fermer',
  },
  states: {
    overdue: 'En retard',
    due_soon: 'À échéance',
    ok: 'À jour',
    excluded: 'Exclu',
  },
  /** Where a resolved cycle or owner comes from. */
  origins: {
    machine: 'propre au poste',
    room: 'hérité de la salle',
    global: 'défaut du parc',
  },
  due: {
    overdueToday: "en retard depuis aujourd'hui",
    overdueDays: 'en retard depuis {count} jour | en retard depuis {count} jours',
    dueOn: 'échéance le {date}',
  },
  cycle: {
    days: '{days} jours ({from})',
    excluded: 'exclu de la maintenance ({from})',
  },
  ownerDeactivated: '{name} (désactivé)',
  /** Recording a visit. */
  session: {
    title: 'Maintenance',
    titleIn: 'Maintenance — {room}',
    date: 'Date',
    backdating: 'Antidater est permis',
    generalNote: 'Observation générale',
    toggleAll: 'Tout cocher ou tout décocher',
    tickAll: 'Tout cocher',
    done: '{name} : fait',
    noteFor: 'Note pour {name}',
    notePlaceholder: 'Observation (facultatif)',
    whyNotDone: 'Pourquoi non fait',
    whyNotDoneOptional: 'Pourquoi non fait (facultatif)',
    machine: 'Poste',
    machineNote: 'Observation sur ce poste',
    explain:
      '{count} poste(s) coché(s) : chacun reçoit une ligne « Maintenance » dans son historique et repart pour un cycle. Un poste décoché avec une observation reçoit une ligne « Maintenance non faite », sans changer son échéance.',
    nothingDone:
      "Aucun poste coché : la séance est enregistrée sans maintenance, à condition de dire pourquoi — une observation générale ou la note d'un poste non fait.",
    partlySent:
      "Séance enregistrée en partie : {sent} poste(s) sur {total}. « Reprendre l'envoi » envoie le reste dans la même séance.",
    noAnswer:
      "L'envoi s'est interrompu sans réponse du serveur : la séance est peut-être déjà enregistrée, en partie. « Reprendre l'envoi » la termine, sans en créer une seconde.",
    refusedMoved:
      'Ces postes ne sont plus dans la salle depuis le début de la saisie : {names}. Ils ne peuvent pas être ajoutés à la séance.',
    refusedGone:
      'Ces postes n’existent plus, ou ne vous sont plus visibles : {names}. Ils ne peuvent pas être ajoutés à la séance.',
    dropRefused: "Retirer ces postes et reprendre l'envoi",
    resume: "Reprendre l'envoi",
    abandonSendingTitle: "Abandonner l'envoi ?",
    abandonSendingPartly:
      '{sent} poste(s) sur {total} sont enregistrés dans la séance ; les autres ne le seront pas.',
    abandonSendingUnknown:
      'Le serveur n’a pas répondu : la séance est peut-être enregistrée, avec une partie de ses postes. Les autres ne le seront pas ; la liste des séances, rechargée, dira ce qu’il en est.',
    abandon: 'Abandonner',
    abandonInputTitle: 'Abandonner la saisie ?',
    abandonInputBody: 'Les notes et les postes cochés ou décochés seront perdus.',
    continueInput: 'Continuer la saisie',
    removedFromSession: 'Retiré de cette séance',
    recorded: 'Maintenance enregistrée sur {count} poste(s)',
    recordedNothingDone: 'Séance enregistrée : aucun poste fait',
    saveFailed: 'Enregistrement impossible',
  },
  /** A visit read back. */
  view: {
    title: 'Séance de maintenance',
    titleIn: 'Séance de maintenance — {room}',
    partial: 'Cette séance déborde de votre périmètre : seuls vos postes sont affichés.',
    partialNoNote:
      "Cette séance déborde de votre périmètre : seuls vos postes sont affichés, sans l'observation générale.",
    date: 'Date',
    by: 'Par',
    generalNote: 'Observation générale',
    done: 'Postes faits ({count})',
    noneDone: 'Aucun poste ne garde de ligne de cette séance.',
    skipped: 'Postes non faits',
    delete: 'Supprimer la séance',
    loadFailed: 'Séance indisponible',
    deleteTitle: 'Supprimer la séance',
    deleteAsk:
      "Supprimer la séance du {date} et ses {count} ligne(s) d'historique ? La dernière maintenance de chaque poste revient à la précédente. La suppression est tracée dans le journal d'audit.",
    deleted: 'Séance supprimée',
    deleteFailed: 'Suppression impossible',
  },
  /** The cycle and the owner at one level. */
  settings: {
    title: 'Maintenance — {subject}',
    cycle: 'Cycle',
    inherit: 'Hériter (salle, puis parc)',
    custom: 'Cycle propre',
    exclude: 'Exclure de la maintenance',
    every: 'Tous les',
    days: 'jours',
    daysRule: 'Un nombre de jours',
    owner: 'Responsable',
    unreachableOwner: 'Compte désactivé ou hors de portée',
    usersFailed: 'Comptes indisponibles',
    saveFailed: 'Enregistrement impossible',
  },
  /** A poste's maintenance card. */
  card: {
    title: 'Maintenance',
    adjust: 'Régler',
    record: 'Enregistrer une maintenance',
    what: 'la maintenance de ce poste',
    state: 'État',
    dueOn: 'due le {date}',
    cycle: 'Cycle',
    owner: 'Responsable',
    nobody: 'personne',
    last: 'Dernière maintenance',
    never: 'jamais',
    inheritHint: 'Vide : hérite de la salle, puis du parc',
    saved: 'Réglages de maintenance enregistrés',
  },
};

const en: Translation<typeof fr> = {
  actions: {
    cancel: 'Cancel',
    save: 'Save',
    delete: 'Delete',
    close: 'Close',
  },
  states: {
    overdue: 'Overdue',
    due_soon: 'Due soon',
    ok: 'Up to date',
    excluded: 'Excluded',
  },
  origins: {
    machine: "the computer's own",
    room: 'from the room',
    global: 'fleet default',
  },
  due: {
    overdueToday: 'overdue since today',
    overdueDays: '1 day overdue | {count} days overdue',
    dueOn: 'due on {date}',
  },
  cycle: {
    days: '1 day ({from}) | {days} days ({from})',
    excluded: 'excluded from maintenance ({from})',
  },
  ownerDeactivated: '{name} (deactivated)',
  session: {
    title: 'Maintenance',
    titleIn: 'Maintenance — {room}',
    date: 'Date',
    backdating: 'Backdating is allowed',
    generalNote: 'General note',
    toggleAll: 'Tick or untick all',
    tickAll: 'Tick all',
    done: '{name}: done',
    noteFor: 'Note for {name}',
    notePlaceholder: 'Note (optional)',
    whyNotDone: 'Why not done',
    whyNotDoneOptional: 'Why not done (optional)',
    machine: 'Computer',
    machineNote: 'Note on this computer',
    explain:
      'Computers ticked: {count}. Each gets a “Maintenance” line in its history and starts a new cycle. A computer left unticked with a note gets a “Maintenance not done” line, its due date unchanged.',
    nothingDone:
      'No computer ticked: the session is recorded without maintenance, provided it says why — a general note or the note of a computer not done.',
    partlySent:
      'Session partly recorded: {sent} of {total} computers. “Resume sending” sends the rest into the same session.',
    noAnswer:
      'Sending stopped without an answer from the server: the session may already be recorded, in part. “Resume sending” completes it, without creating a second one.',
    refusedMoved:
      'These computers have left the room since the input started: {names}. They cannot be added to the session.',
    refusedGone:
      'These computers no longer exist, or are no longer visible to you: {names}. They cannot be added to the session.',
    dropRefused: 'Remove these computers and resume sending',
    resume: 'Resume sending',
    abandonSendingTitle: 'Abandon sending?',
    abandonSendingPartly:
      '{sent} of {total} computers are recorded in the session; the others will not be.',
    abandonSendingUnknown:
      'The server did not answer: the session may be recorded, with some of its computers. The others will not be; the list of sessions, once reloaded, will tell.',
    abandon: 'Abandon',
    abandonInputTitle: 'Abandon the input?',
    abandonInputBody: 'The notes and the ticked or unticked computers will be lost.',
    continueInput: 'Continue the input',
    removedFromSession: 'Removed from this session',
    recorded: 'Maintenance recorded on 1 computer | Maintenance recorded on {count} computers',
    recordedNothingDone: 'Session recorded: no computer done',
    saveFailed: 'Could not save',
  },
  view: {
    title: 'Maintenance session',
    titleIn: 'Maintenance session — {room}',
    partial: 'This session goes beyond your scope: only your computers are shown.',
    partialNoNote:
      'This session goes beyond your scope: only your computers are shown, without the general note.',
    date: 'Date',
    by: 'By',
    generalNote: 'General note',
    done: 'Computers done ({count})',
    noneDone: 'No computer keeps a line of this session.',
    skipped: 'Computers not done',
    delete: 'Delete the session',
    loadFailed: 'Session unavailable',
    deleteTitle: 'Delete the session',
    deleteAsk:
      "Delete the session of {date} and its history line? Each computer's last maintenance goes back to the previous one. The deletion is recorded in the audit log. | Delete the session of {date} and its {count} history lines? Each computer's last maintenance goes back to the previous one. The deletion is recorded in the audit log.",
    deleted: 'Session deleted',
    deleteFailed: 'Could not delete',
  },
  settings: {
    title: 'Maintenance — {subject}',
    cycle: 'Cycle',
    inherit: 'Inherit (room, then fleet)',
    custom: 'Own cycle',
    exclude: 'Exclude from maintenance',
    every: 'Every',
    days: 'days',
    daysRule: 'A number of days',
    owner: 'Owner',
    unreachableOwner: 'Account deactivated or out of reach',
    usersFailed: 'Accounts unavailable',
    saveFailed: 'Could not save',
  },
  card: {
    title: 'Maintenance',
    adjust: 'Adjust',
    record: 'Record a maintenance',
    what: "this computer's maintenance",
    state: 'State',
    dueOn: 'due on {date}',
    cycle: 'Cycle',
    owner: 'Owner',
    nobody: 'nobody',
    last: 'Last maintenance',
    never: 'never',
    inheritHint: 'Empty: inherits from the room, then the fleet',
    saved: 'Maintenance settings saved',
  },
};

export default { fr, en };
