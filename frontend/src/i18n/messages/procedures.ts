import type { Translation } from './types';

/**
 * Procédures par modèle de poste (C11, dev/plan-procedures-pieces-jointes.md
 * §4.2): the card at the head of a poste's « Interventions » tab, its edit
 * dialog and the list of every note.
 */
const fr = {
  card: {
    title: 'Procédure pour ce modèle',
    titleWithModel: 'Procédure pour ce modèle — {model}',
    what: 'la procédure de ce modèle',
    unknownModel:
      'Modèle inconnu (inventaire non remonté) : aucune procédure ne peut s’y rattacher.',
    none: 'Aucune procédure pour ce modèle.',
    write: 'Écrire la procédure',
    edit: 'Modifier',
    delete: 'Supprimer',
    all: 'Toutes les procédures',
    updated: 'Modifiée par {who} le {date}',
    scopeLimited:
      'Votre compte est limité à certains lieux : vous lisez les procédures, seuls les comptes sans limite de lieux les rédigent.',
  },
  edit: {
    newTitle: 'Nouvelle procédure — {model}',
    editTitle: 'Modifier la procédure — {model}',
    body: 'Procédure',
    bodyHint: 'Texte brut, affiché tel quel sur la fiche de chaque poste de ce modèle.',
    secrets:
      'N’écrivez ni mot de passe ni secret : cette note est lue par tous les techniciens et conservée au journal d’audit.',
    required: 'Le texte est obligatoire (pour retirer la note, supprimez-la).',
    cancel: 'Annuler',
    save: 'Enregistrer',
    created: 'Procédure enregistrée',
    saved: 'Procédure modifiée',
    saveFailed: 'Enregistrement impossible',
    changed:
      'Cette procédure a été modifiée ou supprimée entre-temps : elle vient d’être relue, vérifiez-la avant de recommencer.',
  },
  delete: {
    title: 'Supprimer la procédure',
    ask: 'Supprimer la procédure du modèle « {model} » ? Le texte reste lisible au journal d’audit.',
    ok: 'Supprimer',
    done: 'Procédure supprimée',
    failed: 'Suppression impossible',
  },
  list: {
    title: 'Toutes les procédures',
    what: 'la liste des procédures',
    empty: 'Aucune procédure enregistrée.',
    machines: '{count} poste(s) en service',
    updatedLine: 'modifiée le {date} par {who}',
    edit: 'Modifier',
    delete: 'Supprimer',
    close: 'Fermer',
    noMachine: 'aucun poste',
  },
};

const en: Translation<typeof fr> = {
  card: {
    title: 'Procedure for this model',
    titleWithModel: 'Procedure for this model — {model}',
    what: 'the procedure of this model',
    unknownModel: 'Unknown model (inventory not reported): no procedure can be attached to it.',
    none: 'No procedure for this model.',
    write: 'Write the procedure',
    edit: 'Edit',
    delete: 'Delete',
    all: 'All procedures',
    updated: 'Edited by {who} on {date}',
    scopeLimited:
      'Your account is limited to some places: you read the procedures, only accounts not limited to some places write them.',
  },
  edit: {
    newTitle: 'New procedure — {model}',
    editTitle: 'Edit the procedure — {model}',
    body: 'Procedure',
    bodyHint: 'Plain text, shown as is on the page of every computer of this model.',
    secrets:
      'Write no password and no secret: this note is read by every technician and kept in the audit log.',
    required: 'The text is required (to remove the note, delete it).',
    cancel: 'Cancel',
    save: 'Save',
    created: 'Procedure saved',
    saved: 'Procedure edited',
    saveFailed: 'Could not save',
    changed:
      'This procedure was changed or deleted in the meantime: it has just been read again, check it before retrying.',
  },
  delete: {
    title: 'Delete the procedure',
    ask: 'Delete the procedure of the model “{model}”? The text stays readable in the audit log.',
    ok: 'Delete',
    done: 'Procedure deleted',
    failed: 'Could not delete',
  },
  list: {
    title: 'All procedures',
    what: 'the list of procedures',
    empty: 'No procedure recorded.',
    machines: '{count} computer in service | {count} computers in service',
    updatedLine: 'edited on {date} by {who}',
    edit: 'Edit',
    delete: 'Delete',
    close: 'Close',
    noMachine: 'no computer',
  },
};

export default { fr, en };
