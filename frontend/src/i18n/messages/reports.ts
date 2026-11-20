import type { Translation } from './types';

/** Les signalements des utilisateurs (plan `dev/plan-evolutions-itil.md`, C4). */
const fr = {
  title: 'Signalements',
  subtitle:
    'Ce que les utilisateurs signalent en scannant l’étiquette d’un poste. À transformer en vérification, rattacher à celle en cours, ou clore.',
  refresh: 'Actualiser',
  disabledBanner:
    'Le formulaire de signalement est fermé (Paramètres) : aucun nouveau signalement n’arrivera.',
  states: { new: 'À trier', handled: 'Traités', all: 'Tous' },
  empty: {
    none: 'Aucun signalement à trier.',
    loadFailed: 'Les signalements n’ont pas pu être chargés.',
  },
  status: {
    new: 'À trier',
    converted: 'Vérification ouverte',
    attached: 'Rattaché',
    closed: 'Clos',
    rejected: 'Rejeté',
  },
  contact: 'Contact : {contact}',
  handled: 'Traité par {by}, {date}',
  equipment: 'Matériel sans agent',
  actions: {
    convert: 'Ouvrir une vérification',
    attach: 'Rattacher à la vérification en cours',
    close: 'Clore',
    reject: 'Rejeter',
    note: 'Note',
    noteHint: 'Facultative : ce qui a été fait, ou pourquoi rien',
    cancel: 'Annuler',
    confirm: 'Valider',
    done: 'Signalement traité',
    failed: 'L’opération a échoué',
    assignTo: 'Affecter à',
  },
  form: {
    title: 'Signaler un problème',
    intro: 'Décrivez ce qui ne va pas sur ce poste. Un technicien le verra.',
    category: 'De quoi s’agit-il ?',
    text: 'Que se passe-t-il ?',
    textHint: '3 à 2 000 caractères',
    contact: 'Pour vous recontacter (facultatif)',
    contactHint:
      'Nom, salle ou adresse : seulement si vous voulez une réponse. Supprimé avec le signalement.',
    send: 'Envoyer',
    sent: 'Merci, votre signalement a été transmis.',
    another: 'Signaler autre chose',
    failed: 'L’envoi a échoué. Réessayez dans un moment.',
    tooMany: 'Trop de signalements depuis ce poste : réessayez plus tard.',
    invalid: 'Cette étiquette ne correspond à aucun matériel.',
    staff: 'Personnel : se connecter',
    loading: 'Chargement…',
  },
};

const en: Translation<typeof fr> = {
  title: 'Reports',
  subtitle:
    'What users report by scanning a computer’s label. To turn into a check, attach to the open one, or close.',
  refresh: 'Refresh',
  disabledBanner: 'The report form is closed (Settings): no new report will come in.',
  states: { new: 'To sort', handled: 'Handled', all: 'All' },
  empty: { none: 'No report to sort.', loadFailed: 'The reports could not be loaded.' },
  status: {
    new: 'To sort',
    converted: 'Check opened',
    attached: 'Attached',
    closed: 'Closed',
    rejected: 'Rejected',
  },
  contact: 'Contact: {contact}',
  handled: 'Handled by {by}, {date}',
  equipment: 'Equipment without an agent',
  actions: {
    convert: 'Open a check',
    attach: 'Attach to the open check',
    close: 'Close',
    reject: 'Reject',
    note: 'Note',
    noteHint: 'Optional: what was done, or why nothing',
    cancel: 'Cancel',
    confirm: 'Confirm',
    done: 'Report handled',
    failed: 'The operation failed',
    assignTo: 'Assign to',
  },
  form: {
    title: 'Report a problem',
    intro: 'Describe what is wrong with this computer. A technician will see it.',
    category: 'What is it about?',
    text: 'What is happening?',
    textHint: '3 to 2,000 characters',
    contact: 'To get back to you (optional)',
    contactHint: 'Name, room or address: only if you want an answer. Deleted with the report.',
    send: 'Send',
    sent: 'Thank you, your report was sent.',
    another: 'Report something else',
    failed: 'Sending failed. Try again in a moment.',
    tooMany: 'Too many reports from this computer: try again later.',
    invalid: 'This label matches no equipment.',
    staff: 'Staff: sign in',
    loading: 'Loading…',
  },
};

export default { fr, en };
