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
};

export default { fr, en };
