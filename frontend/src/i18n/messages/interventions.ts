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
  /** The photos and PDFs of a line (C11). */
  attachments: {
    title: 'Pièces jointes',
    add: 'Ajouter des fichiers',
    limits: 'JPEG, PNG, WebP ou PDF ; {size} au plus par fichier, {max} fichiers par intervention.',
    photosRedrawn:
      'Les photos sont réduites avant l’envoi et perdent leurs métadonnées (position GPS comprise).',
    queued: 'Envoyé une fois l’intervention enregistrée',
    remove: 'Retirer « {name} »',
    download: 'Télécharger « {name} »',
    preview: 'Aperçu',
    previewOf: 'Aperçu de « {name} »',
    previewTitle: 'Aperçu — {name}',
    close: 'Fermer',
    uploading: 'Envoi de « {name} »…',
    uploaded: 'Pièce jointe ajoutée',
    uploadFailed: 'Envoi impossible',
    downloadFailed: 'Téléchargement impossible',
    previewFailed: 'Aperçu impossible',
    deleteTitle: 'Supprimer la pièce jointe',
    deleteAsk:
      'Supprimer « {name} » de cette intervention ? La suppression est tracée dans le journal d’audit.',
    deleted: 'Pièce jointe supprimée',
    deleteFailed: 'Suppression impossible',
    refused: '« {name} » non envoyé : {reason}',
    reasons: {
      type: 'type non accepté (JPEG, PNG, WebP ou PDF seulement)',
      size: 'plus de {max}, même après réduction',
      unreadable: 'image que le navigateur ne sait pas lire',
      tooMany: '{max} fichiers au plus par intervention',
    },
    /** After a line is created: the files the server did not take. */
    notSent: 'Intervention enregistrée, mais fichier(s) non envoyé(s) : {files}',
    notSentItem: '« {name} » ({reason})',
    storeUnavailable:
      'Ajout impossible pour l’instant : le stockage des pièces jointes n’est pas monté sur le serveur. Les pièces jointes déjà présentes restent consultables.',
    quotaWarning:
      'Pièces jointes : {used} sur {quota} ; supprimez des pièces jointes ou demandez une hausse du quota.',
    retentionDays: 'Pièces jointes conservées {count} jours.',
    retentionKept: 'Pièces jointes conservées sans limite de durée.',
    /** Paramètres: how long they are kept. */
    settings: {
      title: 'Pièces jointes',
      caption:
        'Durée de conservation des photos et PDF joints au journal des postes. Elles peuvent montrer des élèves ou des écrans nominatifs : la durée se choisit avec le DPO de l’établissement (5 ans, 1 825 jours, proposés).',
      retentionDays: 'Rétention des pièces jointes (jours, 0 = conserver)',
      envDefault: 'Valeur initiale : {days} jours',
    },
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
  attachments: {
    title: 'Attachments',
    add: 'Add files',
    limits: 'JPEG, PNG, WebP or PDF; {size} at most per file, {max} files per intervention.',
    photosRedrawn:
      'Photos are scaled down before sending and lose their metadata (GPS position included).',
    queued: 'Sent once the intervention is saved',
    remove: 'Remove “{name}”',
    download: 'Download “{name}”',
    preview: 'Preview',
    previewOf: 'Preview of “{name}”',
    previewTitle: 'Preview — {name}',
    close: 'Close',
    uploading: 'Sending “{name}”…',
    uploaded: 'Attachment added',
    uploadFailed: 'Could not send',
    downloadFailed: 'Could not download',
    previewFailed: 'Could not preview',
    deleteTitle: 'Delete the attachment',
    deleteAsk: 'Delete “{name}” from this intervention? The deletion is recorded in the audit log.',
    deleted: 'Attachment deleted',
    deleteFailed: 'Could not delete',
    refused: '“{name}” not sent: {reason}',
    reasons: {
      type: 'type not accepted (JPEG, PNG, WebP or PDF only)',
      size: 'more than {max}, even once scaled down',
      unreadable: 'an image the browser cannot read',
      tooMany: '{max} files at most per intervention',
    },
    notSent:
      'Intervention recorded, but a file was not sent: {files} | Intervention recorded, but {count} files were not sent: {files}',
    notSentItem: '“{name}” ({reason})',
    storeUnavailable:
      'Adding is not possible for now: the attachment storage is not mounted on the server. Existing attachments can still be read.',
    quotaWarning: 'Attachments: {used} of {quota}; delete attachments or ask for a larger quota.',
    retentionDays: 'Attachments kept {count} day. | Attachments kept {count} days.',
    retentionKept: 'Attachments kept with no time limit.',
    settings: {
      title: 'Attachments',
      caption:
        'How long the photos and PDFs attached to the computers’ logs are kept. They may show pupils or screens with names: the duration is chosen with the school’s DPO (5 years, 1,825 days, suggested).',
      retentionDays: 'Attachment retention (days, 0 = keep)',
      envDefault: 'Initial value: {days} days',
    },
  },
};

export default { fr, en };
