import type { Translation } from './types';

/**
 * Les droits et leurs libellés (lot C2 du plan console bilingue): the grid of
 * the groups page (`utils/permissions.ts`), nested by resource then action as
 * the keys `resource:action` read, and what a manager may not lay hands on
 * (`utils/authority.ts`).
 */
const fr = {
  /** What the resource is, as a row header. */
  resources: {
    machine: 'Postes',
    threat: 'Menaces',
    command: 'Commandes',
    risky_command: 'Commandes à risque',
    room: 'Salles et bâtiments',
    intervention: 'Historique des interventions',
    check: 'Vérifications demandées',
    maintenance: 'Maintenance',
    settings: 'Paramètres',
    user: 'Comptes et groupes',
    audit: "Journal d'audit",
    package: 'Paquets logiciels',
    asset: 'Actifs (achat, garantie, prêts)',
    schedule: 'Planifications',
    report: 'Signalements des utilisateurs',
    license: 'Licences logicielles',
    webhook: 'Webhooks',
    api_token: 'Jetons d’API',
  },
  /** What granting it lets someone do (`label`), and a sentence where the label
   *  alone would be read two ways (`hint`). */
  entries: {
    machine: {
      read: {
        label: 'Consulter',
        hint: 'Le tableau de bord, la liste et la fiche des postes, les logiciels, les exports.',
      },
      write: {
        label: 'Gérer',
        hint: 'Révoquer un token, autoriser un ré-enrôlement, fusionner des doublons.',
      },
    },
    threat: {
      read: { label: 'Consulter' },
    },
    command: {
      read: { label: "Consulter l'historique" },
      execute: {
        label: 'Exécuter les commandes courantes',
        hint: 'Scans, mise à jour des signatures, recherche de mises à jour, cache DNS, stratégies, diagnostics, réveil Wake-on-LAN…',
      },
    },
    risky_command: {
      execute: {
        label: 'Exécuter les commandes à risque',
        hint: 'Redémarrage, arrêt, installation des mises à jour, réinitialisation de Windows Update, réparations DISM, réinitialisation du spouleur. Requiert aussi les commandes courantes.',
      },
    },
    room: {
      read: { label: 'Consulter' },
      write: {
        label: 'Gérer',
        hint: 'Créer et modifier les salles et les bâtiments, y affecter des postes.',
      },
    },
    intervention: {
      read: { label: 'Consulter' },
      write: {
        label: 'Saisir',
        hint: 'Ajouter, modifier et supprimer des interventions sur tout poste ; les suppressions sont tracées.',
      },
    },
    check: {
      read: { label: 'Consulter' },
      write: {
        label: 'Demander, affecter et clore',
        hint: 'Demander une vérification sur tout poste, l’affecter à un compte, la clore avec une note.',
      },
    },
    maintenance: {
      read: {
        label: 'Consulter',
        hint: 'Ce qui est dû, les séances enregistrées, les cycles et responsables.',
      },
      write: {
        label: 'Effectuer et régler',
        hint: 'Enregistrer une séance, fixer le cycle et le responsable d’une salle ou d’un poste, transmettre une maintenance.',
      },
    },
    settings: {
      read: { label: 'Consulter' },
      write: {
        label: 'Modifier',
        hint: 'Les défauts du parc : cycle et responsable de maintenance, fenêtre « à échéance ».',
      },
    },
    user: {
      read: { label: 'Consulter' },
      write: {
        label: 'Gérer',
        hint: 'Créer, modifier et supprimer des comptes et des groupes, réinitialiser des mots de passe.',
      },
    },
    audit: {
      read: { label: 'Consulter' },
    },
    package: {
      read: {
        label: 'Consulter',
        hint: 'Voir le catalogue des paquets. Déployer demande en plus les commandes à risque.',
      },
      write: {
        label: 'Gérer',
        hint: 'Créer des paquets, déposer leurs fichiers, joindre la signature, les retirer.',
      },
    },
    asset: {
      read: {
        label: 'Consulter',
        hint: 'Voir les dates d’achat, garanties, prix, statuts et prêts, et le matériel sans agent.',
      },
      write: {
        label: 'Gérer',
        hint: 'Saisir et importer les actifs, déclarer un prêt ou une réforme, imprimer les étiquettes.',
      },
    },
    schedule: {
      read: {
        label: 'Consulter',
        hint: 'Voir les planifications et leurs exécutions.',
      },
      write: {
        label: 'Gérer',
        hint: 'Planifier une commande, la modifier, la suspendre. Il faut aussi le droit d’exécuter la commande planifiée.',
      },
    },
    report: {
      read: {
        label: 'Consulter',
        hint: 'Voir les signalements laissés par l’étiquette des postes, avec le contact donné.',
      },
      write: {
        label: 'Trier',
        hint: 'Clore ou rejeter un signalement ; l’ouvrir en vérification demande aussi « Vérifications demandées : gérer ».',
      },
    },
    license: {
      read: {
        label: 'Consulter',
        hint: 'Voir les licences, leur fournisseur et leur référence de commande, et combien de postes ont ce qu’elles couvrent. Elles sont sur la page Logiciels : il faut aussi « Postes : consulter ».',
      },
      write: {
        label: 'Gérer',
        hint: 'Créer, modifier et supprimer une licence. Réservé aux comptes sans limite de lieux.',
      },
    },
    webhook: {
      read: {
        label: 'Consulter',
        hint: 'Voir les webhooks, leurs adresses et l’historique de leurs envois.',
      },
      write: {
        label: 'Gérer',
        hint: 'Créer, modifier, essayer et supprimer un webhook : il envoie les évènements du parc à un autre outil. Réservé aux comptes sans limite de lieux.',
      },
    },
    api_token: {
      write: {
        label: 'Créer des jetons',
        hint: 'Créer, pour son propre compte, des jetons qui permettent à un script d’agir avec ses droits.',
      },
    },
  },
  /** `{resource} — {action}`, for lists that show what a group grants. */
  named: '{resource} — {action}',
  /** The tooltip on what is withheld because it reaches beyond the caller. */
  authority: {
    moreRightsAccount: 'Ce compte détient plus de droits que vous',
    moreRightsGroup: 'Ce groupe accorde plus de droits que vous n’en détenez',
  },
};

const en: Translation<typeof fr> = {
  resources: {
    machine: 'Computers',
    threat: 'Threats',
    command: 'Commands',
    risky_command: 'Risky commands',
    room: 'Rooms and buildings',
    intervention: 'Intervention log',
    check: 'Requested checks',
    maintenance: 'Maintenance',
    settings: 'Settings',
    user: 'Accounts and groups',
    audit: 'Audit log',
    package: 'Software packages',
    asset: 'Assets (purchase, warranty, loans)',
    schedule: 'Schedules',
    report: 'Users’ reports',
    license: 'Software licences',
    webhook: 'Webhooks',
    api_token: 'API tokens',
  },
  entries: {
    machine: {
      read: {
        label: 'View',
        hint: 'The dashboard, the computer list and pages, software, exports.',
      },
      write: {
        label: 'Manage',
        hint: 'Revoke a token, allow a re-enrolment, merge duplicates.',
      },
    },
    threat: {
      read: { label: 'View' },
    },
    command: {
      read: { label: 'View the history' },
      execute: {
        label: 'Run the everyday commands',
        hint: 'Scans, signature updates, update searches, DNS cache, policies, diagnostics, Wake-on-LAN…',
      },
    },
    risky_command: {
      execute: {
        label: 'Run the risky commands',
        hint: 'Restart, shutdown, installing updates, Windows Update reset, DISM repairs, print spooler reset. Also needs the everyday commands.',
      },
    },
    room: {
      read: { label: 'View' },
      write: {
        label: 'Manage',
        hint: 'Create and edit rooms and buildings, assign computers to them.',
      },
    },
    intervention: {
      read: { label: 'View' },
      write: {
        label: 'Record',
        hint: 'Add, edit and delete interventions on any computer; deletions are logged.',
      },
    },
    check: {
      read: { label: 'View' },
      write: {
        label: 'Request, assign and close',
        hint: 'Request a check on any computer, assign it to an account, close it with a note.',
      },
    },
    maintenance: {
      read: {
        label: 'View',
        hint: 'What is due, the recorded sessions, the cycles and owners.',
      },
      write: {
        label: 'Perform and configure',
        hint: 'Record a session, set the cycle and owner of a room or computer, hand a maintenance over.',
      },
    },
    settings: {
      read: { label: 'View' },
      write: {
        label: 'Edit',
        hint: 'The fleet defaults: maintenance cycle and owner, “due soon” window.',
      },
    },
    user: {
      read: { label: 'View' },
      write: {
        label: 'Manage',
        hint: 'Create, edit and delete accounts and groups, reset passwords.',
      },
    },
    audit: {
      read: { label: 'View' },
    },
    package: {
      read: {
        label: 'View',
        hint: 'See the package catalogue. Deploying also needs the risky commands.',
      },
      write: {
        label: 'Manage',
        hint: 'Create packages, upload their files, attach the signature, retire them.',
      },
    },
    asset: {
      read: {
        label: 'View',
        hint: 'See purchase dates, warranties, prices, statuses and loans, and the equipment without an agent.',
      },
      write: {
        label: 'Manage',
        hint: 'Enter and import assets, record a loan or a retirement, print the labels.',
      },
    },
    schedule: {
      read: {
        label: 'View',
        hint: 'See the schedules and their runs.',
      },
      write: {
        label: 'Manage',
        hint: 'Schedule a command, change it, suspend it. The right to run the scheduled command is needed too.',
      },
    },
    report: {
      read: {
        label: 'View',
        hint: 'See the reports left through the computers’ labels, with the contact given.',
      },
      write: {
        label: 'Sort',
        hint: 'Close or reject a report; opening it as a check also needs “Requested checks: manage”.',
      },
    },
    license: {
      read: {
        label: 'View',
        hint: 'See the licences, their supplier and order reference, and how many computers have what they cover. They are on the Software page: “Computers: view” is needed too.',
      },
      write: {
        label: 'Manage',
        hint: 'Create, change and delete a licence. Only for accounts not limited to some places.',
      },
    },
    webhook: {
      read: {
        label: 'View',
        hint: 'See the webhooks, their addresses and their delivery history.',
      },
      write: {
        label: 'Manage',
        hint: 'Create, change, test and delete a webhook: it sends the fleet’s events to another tool. Only for accounts not limited to some places.',
      },
    },
    api_token: {
      write: {
        label: 'Create tokens',
        hint: 'Create, for one’s own account, tokens that let a script act with its rights.',
      },
    },
  },
  named: '{resource} — {action}',
  authority: {
    moreRightsAccount: 'This account holds more permissions than you',
    moreRightsGroup: 'This group grants more permissions than you hold',
  },
};

export default { fr, en };
