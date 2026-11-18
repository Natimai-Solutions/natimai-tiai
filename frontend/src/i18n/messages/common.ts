import type { Translation } from './types';

/** Words every page uses. */
const fr = {
  language: {
    label: 'Langue',
    browser: 'Celle du navigateur',
    fr: 'Français',
    en: 'English',
    hint: 'La console suit la langue de votre navigateur tant que vous n’en choisissez pas une.',
    saved: 'Langue enregistrée.',
  },
  /** The banner of a page that never loaded, and the one of a card (`LoadErrorBanner`, `CardLoadError`). */
  loadError: {
    fallback: 'Chargement impossible : le serveur ne répond pas.',
    card: 'Impossible de charger {what}.',
    retry: 'Réessayer',
  },
};

const en: Translation<typeof fr> = {
  language: {
    label: 'Language',
    browser: 'Same as the browser',
    fr: 'Français',
    en: 'English',
    hint: 'The console follows your browser’s language until you choose one.',
    saved: 'Language saved.',
  },
  loadError: {
    fallback: 'Could not load: the server is not responding.',
    card: 'Could not load {what}.',
    retry: 'Try again',
  },
};

export default { fr, en };
