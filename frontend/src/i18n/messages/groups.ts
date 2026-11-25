import type { Translation } from './types';

/**
 * La page Groupes (lot C2 du plan console bilingue). The permissions' own
 * words are in `permissions`. The built-in groups' names and descriptions are
 * data: `builtin` holds the ones an installation gives them (French, word for
 * word as `backend/app/features/user/permissions.py` seeds them), and the
 * console translates a built-in group only while it still carries them
 * (`utils/groupText`).
 */
const fr = {
  page: {
    title: 'Groupes',
    create: 'Nouveau groupe',
    intro:
      "Un compte peut ce que ses groupes lui accordent, tous groupes confondus. Les trois groupes intégrés se renomment et, sauf les administrateurs, se modifient comme les autres ; ils ne se suppriment pas. Un groupe peut être limité à des emplacements, bâtiments ou salles : ses membres ne voient alors que ces postes — à condition qu'aucun de leurs autres groupes ne soit ouvert à tout le parc.",
    notLoaded: 'Groupes non chargés.',
    empty: 'Aucun groupe.',
  },
  columns: {
    name: 'Groupe',
    permissions: 'Droits',
    scope: 'Postes',
    members: 'Comptes',
  },
  row: {
    builtin: 'Groupe intégré',
    allPermissions: 'Tous les droits',
    noPermission: 'Aucun',
    wholeFleet: 'Tout le parc',
    actionsFor: 'Actions pour {name}',
    edit: 'Modifier',
    delete: 'Supprimer',
  },
  /** A place of a scope that no longer exists. */
  deleted: {
    place: 'Lieu supprimé',
    building: 'Bâtiment supprimé',
    room: 'Salle supprimée',
  },
  form: {
    createTitle: 'Nouveau groupe',
    mfaRequired: 'Double authentification obligatoire',
    mfaHint:
      'Ses membres se connectent avec un code en plus du mot de passe ; un membre qui ne l’a pas encore activée ne peut que le faire, depuis « Mon compte ».',
    mfaBadge: 'Double authentification',
    idpGroups: 'Groupes de l’annuaire',
    idpGroupInvalid:
      "Identifiant invalide : lettres, chiffres, « . », « _ », « : », « {'@'} », « - »",
    idpGroupsHint:
      'Identifiants (Entra ID : « ID d’objet ») des groupes de l’annuaire dont les membres reçoivent ce groupe en se connectant par l’annuaire. Entrée pour en ajouter un autre.',
    editTitle: 'Modifier le groupe',
    name: 'Nom',
    description: 'Description',
    required: 'Requis',
    permissions: 'Droits',
    adminBanner:
      "Les administrateurs ont tous les droits, y compris ceux des ressources à venir. Cette grille n'est pas modifiable.",
    dependencies:
      "Cocher un droit de modification ou d'exécution coche aussi la consultation dont il a besoin ; décocher une consultation retire les droits qui en dépendent.",
    cannotGrant: "Vous ne détenez pas ce droit : vous ne pouvez pas l'accorder",
    riskyWithoutEveryday:
      "Les commandes à risque ne s'exécutent pas sans les commandes courantes : ce droit seul n'ouvre rien.",
    scope: 'Postes concernés',
    scopeHint:
      "Rien de coché : tout le parc. Sinon, les postes d'au moins un de ces emplacements, bâtiments ou salles — et les salles, vérifications, maintenances et e-mails qui s'y rapportent.",
    locations: 'Emplacements',
    locationsHint: 'Tels que les agents les déclarent ; saisie libre possible',
    buildings: 'Bâtiments',
    rooms: 'Salles',
    cancel: 'Annuler',
    save: 'Enregistrer',
  },
  wholeFleet: {
    title: 'Tout le parc',
    message:
      'Aucun emplacement, bâtiment ni salle n’est choisi : les membres de ce groupe verront tous les postes et pourront y exercer ses droits. Enregistrer ainsi ?',
    back: 'Revenir au formulaire',
    confirm: 'Enregistrer pour tout le parc',
  },
  delete: {
    title: 'Supprimer le groupe',
    question: 'Supprimer {name} ?',
    members: "Les {count} compte(s) qui en font partie perdent ce qu'il leur accordait.",
    ok: 'Supprimer',
  },
  notify: {
    updated: 'Groupe mis à jour',
    created: 'Groupe créé',
    saveFailed: 'Enregistrement impossible',
    deleted: 'Groupe supprimé',
    deleteFailed: 'Suppression impossible',
  },
  builtin: {
    admin: {
      name: 'Administrateurs',
      description: 'Tous les droits, y compris ceux des ressources à venir.',
    },
    readonly: {
      name: 'Lecture seule',
      description: 'Consulte le parc sans rien pouvoir y changer.',
    },
    technician: {
      name: 'Techniciens',
      description: 'Consulte le parc et exécute les commandes, courantes et à risque.',
    },
  },
};

const en: Translation<typeof fr> = {
  page: {
    title: 'Groups',
    create: 'New group',
    intro:
      'An account may do what its groups grant it, all groups together. The three built-in groups can be renamed and, except for the administrators, edited like the others; they cannot be deleted. A group can be limited to locations, buildings or rooms: its members then see only those computers — provided none of their other groups is open to the whole fleet.',
    notLoaded: 'Groups not loaded.',
    empty: 'No group.',
  },
  columns: {
    name: 'Group',
    permissions: 'Permissions',
    scope: 'Computers',
    members: 'Accounts',
  },
  row: {
    builtin: 'Built-in group',
    allPermissions: 'All permissions',
    noPermission: 'None',
    wholeFleet: 'Whole fleet',
    actionsFor: 'Actions for {name}',
    edit: 'Edit',
    delete: 'Delete',
  },
  deleted: {
    place: 'Deleted place',
    building: 'Deleted building',
    room: 'Deleted room',
  },
  form: {
    createTitle: 'New group',
    mfaRequired: 'Two-step verification required',
    mfaHint:
      'Its members sign in with a code on top of the password; a member who has not turned it on yet can only do that, from My account.',
    mfaBadge: 'Two-step verification',
    idpGroups: 'Directory groups',
    idpGroupInvalid: "Invalid id: letters, digits, “.”, “_”, “:”, “{'@'}”, “-”",
    idpGroupsHint:
      'Ids (Entra ID: “Object ID”) of the directory groups whose members get this group when they sign in through the directory. Enter to add another.',
    editTitle: 'Edit the group',
    name: 'Name',
    description: 'Description',
    required: 'Required',
    permissions: 'Permissions',
    adminBanner:
      'Administrators hold every permission, including those of resources still to come. This grid cannot be edited.',
    dependencies:
      'Ticking an edit or run permission also ticks the view permission it needs; unticking a view permission removes the permissions that depend on it.',
    cannotGrant: 'You do not hold this permission: you cannot grant it',
    riskyWithoutEveryday:
      'Risky commands do not run without the everyday commands: this permission alone opens nothing.',
    scope: 'Computers covered',
    scopeHint:
      'Nothing ticked: the whole fleet. Otherwise, the computers of at least one of these locations, buildings or rooms — and the rooms, checks, maintenance and e-mails about them.',
    locations: 'Locations',
    locationsHint: 'As the agents report them; free text allowed',
    buildings: 'Buildings',
    rooms: 'Rooms',
    cancel: 'Cancel',
    save: 'Save',
  },
  wholeFleet: {
    title: 'Whole fleet',
    message:
      'No location, building or room is chosen: the members of this group will see every computer and can use its permissions on them. Save like this?',
    back: 'Back to the form',
    confirm: 'Save for the whole fleet',
  },
  delete: {
    title: 'Delete the group',
    question: 'Delete {name}?',
    members:
      'The {count} account in it loses what it granted. | The {count} accounts in it lose what it granted.',
    ok: 'Delete',
  },
  notify: {
    updated: 'Group updated',
    created: 'Group created',
    saveFailed: 'Could not save',
    deleted: 'Group deleted',
    deleteFailed: 'Could not delete the group',
  },
  builtin: {
    admin: {
      name: 'Administrators',
      description: 'Every permission, including those of resources still to come.',
    },
    readonly: {
      name: 'Read only',
      description: 'Views the fleet without being able to change anything.',
    },
    technician: {
      name: 'Technicians',
      description: 'Views the fleet and runs commands, routine and risky ones.',
    },
  },
};

export default { fr, en };
