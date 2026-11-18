import type { Translation } from './types';

/**
 * « Mon compte » (lot C2 du plan console bilingue): the profile, the e-mail
 * notifications, the password, the open sessions — and the words those reuse
 * elsewhere: a device read from its User-Agent (`utils/userAgent`), the
 * password policy (`composables/usePasswordPolicy`). The language choice is
 * in `common.language`.
 */
const fr = {
  title: 'Mon compte',
  profile: {
    email: 'E-mail',
    name: 'Nom',
    groups: 'Groupes',
    noGroup: 'Aucun — ce compte ne peut rien consulter',
  },
  notifications: {
    title: 'Notifications par e-mail',
    hint: "Ce que Tia'i vous envoie. Le choix est personnel : il ne change rien pour les autres comptes de la console.",
    saving: 'Enregistrement…',
    saved: 'Préférence enregistrée',
    saveFailed: 'Enregistrement impossible',
  },
  password: {
    title: 'Changer mon mot de passe',
    current: 'Mot de passe actuel',
    new: 'Nouveau mot de passe',
    minLength: '{count} caractères minimum',
    confirm: 'Confirmer le nouveau mot de passe',
    sessionsClosed: 'Toutes vos sessions seront fermées : vous devrez vous reconnecter.',
    submit: 'Changer le mot de passe',
    required: 'Requis',
    mismatch: 'Les mots de passe ne correspondent pas',
    changed: 'Mot de passe changé. Reconnectez-vous.',
    failed: 'Changement impossible',
  },
  sessions: {
    title: 'Sessions ouvertes',
    hint: "Les appareils connectés à votre compte. Fermez celles que vous ne reconnaissez pas : l'accès y est coupé immédiatement.",
    refresh: 'Actualiser les sessions',
    /** What could not be loaded, in the sentence of `CardLoadError`. */
    what: 'vos sessions ouvertes',
    current: 'Cette session',
    unknownAddress: 'Adresse inconnue',
    lastActivity: '{ip} · dernière activité {ago}',
    openedOn: 'Ouverte le {date}',
    logout: 'Se déconnecter',
    close: 'Fermer',
    none: 'Aucune session ouverte.',
    closed: 'Session fermée',
    closeFailed: 'Fermeture impossible',
    logoutTitle: 'Se déconnecter',
    logoutMessage: 'Fermer cette session vous déconnecte de la console sur cet appareil.',
    cancel: 'Annuler',
  },
  /** A device as its User-Agent tells it: « Firefox sur Windows ». */
  device: {
    unknown: 'Appareil inconnu',
    browserOn: '{browser} sur {system}',
    someBrowserOn: 'Navigateur sur {system}',
  },
  /** The lifetime of a reset link, in words. */
  passwordPolicy: {
    oneHour: 'une heure',
    hours: '{count} heures',
    minutes: '{count} minutes',
  },
};

const en: Translation<typeof fr> = {
  title: 'My account',
  profile: {
    email: 'E-mail',
    name: 'Name',
    groups: 'Groups',
    noGroup: 'None — this account cannot view anything',
  },
  notifications: {
    title: 'E-mail notifications',
    hint: "What Tia'i sends you. The choice is yours alone: it changes nothing for the console's other accounts.",
    saving: 'Saving…',
    saved: 'Preference saved',
    saveFailed: 'Could not save',
  },
  password: {
    title: 'Change my password',
    current: 'Current password',
    new: 'New password',
    minLength: 'At least {count} characters',
    confirm: 'Confirm the new password',
    sessionsClosed: 'All your sessions will be closed: you will have to log in again.',
    submit: 'Change password',
    required: 'Required',
    mismatch: 'The passwords do not match',
    changed: 'Password changed. Please log in again.',
    failed: 'Could not change the password',
  },
  sessions: {
    title: 'Open sessions',
    hint: 'The devices logged in to your account. Close any you do not recognise: their access is cut off at once.',
    refresh: 'Refresh the sessions',
    what: 'your open sessions',
    current: 'This session',
    unknownAddress: 'Unknown address',
    lastActivity: '{ip} · last active {ago}',
    openedOn: 'Opened on {date}',
    logout: 'Log out',
    close: 'Close',
    none: 'No open session.',
    closed: 'Session closed',
    closeFailed: 'Could not close the session',
    logoutTitle: 'Log out',
    logoutMessage: 'Closing this session logs you out of the console on this device.',
    cancel: 'Cancel',
  },
  device: {
    unknown: 'Unknown device',
    browserOn: '{browser} on {system}',
    someBrowserOn: 'Browser on {system}',
  },
  passwordPolicy: {
    oneHour: 'one hour',
    hours: '{count} hours',
    minutes: '{count} minutes',
  },
};

export default { fr, en };
