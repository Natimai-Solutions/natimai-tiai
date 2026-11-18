import type { Translation } from './types';

/** Paramètres → serveur : les variables d’environnement (lot C1 du plan console bilingue). */
const fr = {};

const en: Translation<typeof fr> = {};

export default { fr, en };
