import type { Translation } from './types';

/** La coquille : menu, en-tête, titres des pages (lot E1 du plan console bilingue). */
const fr = {
  /** The pages' names: the menu's entries, and the browser tab's title (`meta.title` of a route). */
  pages: {
    login: 'Connexion',
    forgotPassword: 'Mot de passe oublié',
    resetPassword: 'Nouveau mot de passe',
    dashboard: 'Tableau de bord',
    machines: 'Postes',
    alerts: 'Alertes',
    assets: 'Matériels',
    schedules: 'Planifications',
    reports: 'Signalements',
    assetLabels: 'Étiquettes',
    assetToken: 'Étiquette',
    software: 'Logiciels',
    packages: 'Paquets',
    package: 'Paquet',
    settings: 'Paramètres',
    tasks: 'Mes tâches',
    rooms: 'Salles',
    room: 'Salle',
    machine: 'Poste',
    users: 'Utilisateurs',
    groups: 'Groupes',
    audit: "Journal d'audit",
    account: 'Mon compte',
    noAccess: 'Aucune page accessible',
    notFound: 'Page introuvable',
  },
  shell: {
    skipToContent: 'Aller au contenu',
    menu: 'Menu',
    account: 'Mon compte',
    logout: 'Déconnexion',
    myChecks: 'Vérifications qui vous sont affectées',
    myOverdue: 'Postes en retard de maintenance dont vous êtes responsable',
    profileError: 'Impossible de charger votre profil : les menus et les actions sont incomplets.',
    profileErrorReason:
      'Impossible de charger votre profil : les menus et les actions sont incomplets — {reason}.',
  },
  /** A page of the console that could not be loaded (`utils/staleChunks`). */
  staleChunk: {
    failed:
      'Impossible de charger cette page (connexion ou mise à jour en cours). Rechargez la page.',
    offline: 'Pas de connexion : la page se rechargera d’elle-même dès son retour.',
    reload: 'Recharger',
    close: 'Fermer',
  },
  noAccess: {
    body: "Votre compte n'a le droit de consulter aucune page de la console. Demandez à un administrateur de vous ajouter au groupe qui convient ; la console le prendra en compte d'elle-même.",
  },
  notFound: {
    home: "Retour à l'accueil",
  },
};

const en: Translation<typeof fr> = {
  pages: {
    login: 'Sign in',
    forgotPassword: 'Forgotten password',
    resetPassword: 'New password',
    dashboard: 'Dashboard',
    machines: 'Computers',
    alerts: 'Alerts',
    assets: 'Equipment',
    schedules: 'Schedules',
    reports: 'Reports',
    assetLabels: 'Labels',
    assetToken: 'Label',
    software: 'Software',
    packages: 'Packages',
    package: 'Package',
    settings: 'Settings',
    tasks: 'My tasks',
    rooms: 'Rooms',
    room: 'Room',
    machine: 'Computer',
    users: 'Users',
    groups: 'Groups',
    audit: 'Audit log',
    account: 'My account',
    noAccess: 'No page available',
    notFound: 'Page not found',
  },
  shell: {
    skipToContent: 'Skip to content',
    menu: 'Menu',
    account: 'My account',
    logout: 'Sign out',
    myChecks: 'Checks assigned to you',
    myOverdue: 'Computers you own that are overdue for maintenance',
    profileError: 'Could not load your profile: menus and actions are incomplete.',
    profileErrorReason: 'Could not load your profile: menus and actions are incomplete — {reason}.',
  },
  staleChunk: {
    failed: 'Could not load this page (connection lost or update in progress). Reload the page.',
    offline: 'No connection: the page will reload by itself once it is back.',
    reload: 'Reload',
    close: 'Close',
  },
  noAccess: {
    body: 'Your account may not view any page of the console. Ask an administrator to add you to the right group; the console will pick it up by itself.',
  },
  notFound: {
    home: 'Back to home',
  },
};

export default { fr, en };
