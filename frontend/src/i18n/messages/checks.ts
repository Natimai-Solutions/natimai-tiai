import type { Translation } from './types';

/**
 * Vérifications demandées (lot D du plan console bilingue): what
 * `services/checks` says of an assignee or a bulk request, and the dialogs
 * that ask for a check and close it.
 */
const fr = {
  actions: {
    cancel: 'Annuler',
    save: 'Enregistrer',
  },
  /** Why a check named after someone is « à prendre ». */
  former: {
    deactivated: '{name}, désactivé',
    unreachable: '{name} ne voit plus ce poste',
  },
  bulk: {
    created: '{count} vérification(s) demandée(s)',
    skipped: '{created} — {count} poste(s) en avaient déjà une ouverte',
  },
  /** A closing note the server wrote, by its `closing_note_code`. */
  closingNotes: {
    merged: 'Fermée par la fusion du poste dans un autre.',
  },
  /** Asking for a check, or editing one. */
  request: {
    edit: 'Modifier la demande',
    ask: 'Demander une vérification',
    assignTo: 'Affecter à',
    assignHint: 'Personne : la demande reste à prendre par qui veut',
    instructions: 'Consignes',
    instructionsHint: "Ce qu'il faut regarder, et pourquoi",
    deactivated: '{name} (désactivé)',
    unreachable: '{name} (ne voit plus ce poste)',
    usersFailed: 'Comptes indisponibles',
    saveFailed: 'Enregistrement impossible',
  },
  /** Closing a check. */
  close: {
    title: 'Clore la vérification',
    instructions: 'Consignes : {text}',
    found: 'Ce qui a été constaté',
    foundHint: "Conservé sur la demande et inscrit dans l'historique du poste",
    date: 'Date',
    dateHint: 'Laisser tel quel pour maintenant ; antidater est permis',
    invalidDate: 'Date invalide',
    future: 'Pas dans le futur',
    beforeRequest: 'Pas avant la demande',
    close: 'Clore',
    closed: 'Vérification close',
    closeFailed: 'Clôture impossible',
  },
};

const en: Translation<typeof fr> = {
  actions: {
    cancel: 'Cancel',
    save: 'Save',
  },
  former: {
    deactivated: '{name}, deactivated',
    unreachable: '{name} can no longer see this computer',
  },
  bulk: {
    created: '1 check requested | {count} checks requested',
    skipped:
      '{created} — 1 computer already had one open | {created} — {count} computers already had one open',
  },
  closingNotes: {
    merged: 'Closed when the computer was merged into another.',
  },
  request: {
    edit: 'Edit the request',
    ask: 'Request a check',
    assignTo: 'Assign to',
    assignHint: 'Nobody: the request stays open for anyone to take',
    instructions: 'Instructions',
    instructionsHint: 'What to look at, and why',
    deactivated: '{name} (deactivated)',
    unreachable: '{name} (can no longer see this computer)',
    usersFailed: 'Accounts unavailable',
    saveFailed: 'Could not save',
  },
  close: {
    title: 'Close the check',
    instructions: 'Instructions: {text}',
    found: 'What was found',
    foundHint: "Kept on the request and written to the computer's history",
    date: 'Date',
    dateHint: 'Leave as is for now; backdating is allowed',
    invalidDate: 'Invalid date',
    future: 'Not in the future',
    beforeRequest: 'Not before the request',
    close: 'Close',
    closed: 'Check closed',
    closeFailed: 'Could not close',
  },
};

export default { fr, en };
