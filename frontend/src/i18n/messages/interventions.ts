import type { Translation } from './types';

/**
 * Journal des interventions d’un poste (lot D du plan console bilingue): the
 * kinds of a line, the titles the server writes itself, and the card of a
 * poste's page that reads and writes the journal.
 */
const fr = {
  actions: {
    cancel: 'Annuler',
    save: 'Enregistrer',
    edit: 'Modifier',
    delete: 'Supprimer',
  },
  kinds: {
    incident: 'Panne / incident',
    software_install: 'Installation logicielle',
    upgrade: 'Mise à niveau',
    maintenance: 'Maintenance',
    verification: 'Vérification',
    other: 'Autre',
  },
  /** « Maintenance — A101 »: the kind, then the title. */
  heading: '{label} — {title}',
  /** A title the server writes itself, by its `title_code`. */
  titles: {
    maintenanceSkipped: 'Maintenance non faite',
    maintenanceSkippedIn: 'Maintenance non faite — {room}',
  },
  history: {
    title: 'Historique des interventions',
    add: 'Ajouter une intervention',
    what: "l'historique des interventions",
    cannotRead:
      "Votre compte ne permet pas de consulter l'historique de ce poste : vous pouvez seulement y ajouter une intervention.",
    empty: 'Aucune intervention enregistrée sur ce poste.',
    edited: 'modifié',
    viewSession: 'Voir la séance',
    actions: "Actions sur l'intervention",
    showMore: 'Afficher plus',
    editTitle: "Modifier l'intervention",
    newTitle: 'Nouvelle intervention',
    kind: 'Type',
    titleField: 'Titre',
    note: 'Observations',
    date: 'Date',
    dateHint: 'Laisser tel quel pour maintenant ; antidater est permis',
    updated: 'Intervention mise à jour',
    created: 'Intervention enregistrée',
    saveFailed: 'Enregistrement impossible',
    deleteTitle: "Supprimer l'intervention",
    deleteAsk:
      "Supprimer « {heading} » du {date} ? La suppression est tracée dans le journal d'audit.",
    deleted: 'Intervention supprimée',
    deleteFailed: 'Suppression impossible',
  },
};

const en: Translation<typeof fr> = {
  actions: {
    cancel: 'Cancel',
    save: 'Save',
    edit: 'Edit',
    delete: 'Delete',
  },
  kinds: {
    incident: 'Fault / incident',
    software_install: 'Software install',
    upgrade: 'Upgrade',
    maintenance: 'Maintenance',
    verification: 'Check',
    other: 'Other',
  },
  heading: '{label} — {title}',
  titles: {
    maintenanceSkipped: 'Maintenance not done',
    maintenanceSkippedIn: 'Maintenance not done — {room}',
  },
  history: {
    title: 'Intervention log',
    add: 'Add an intervention',
    what: 'the intervention log',
    cannotRead:
      "Your account cannot read this computer's log: you can only add an intervention to it.",
    empty: 'No intervention recorded on this computer.',
    edited: 'edited',
    viewSession: 'View the session',
    actions: 'Actions on the intervention',
    showMore: 'Show more',
    editTitle: 'Edit the intervention',
    newTitle: 'New intervention',
    kind: 'Type',
    titleField: 'Title',
    note: 'Notes',
    date: 'Date',
    dateHint: 'Leave as is for now; backdating is allowed',
    updated: 'Intervention updated',
    created: 'Intervention recorded',
    saveFailed: 'Could not save',
    deleteTitle: 'Delete the intervention',
    deleteAsk: 'Delete “{heading}” of {date}? The deletion is recorded in the audit log.',
    deleted: 'Intervention deleted',
    deleteFailed: 'Could not delete',
  },
};

export default { fr, en };
