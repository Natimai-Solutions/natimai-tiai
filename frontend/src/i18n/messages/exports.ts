import type { Translation } from './types';

/**
 * The fleet export (lot G du plan console bilingue). The file itself — its
 * headers, sheet, values — is written by the server in the language the
 * console asks for (`lang`); the column picker's labels come from the server
 * in that language too. What is here is the dialog around them.
 */
const fr = {
  machines: {
    title: 'Exporter le parc',
    /** `{count}` is the number of postes, already formatted. */
    count: '1 poste | {count} postes',
    caption: "{count} — les filtres de la liste s'appliquent, pas la pagination.",
    available: 'Colonnes disponibles',
    search: 'Rechercher une colonne',
    searchPlaceholder: 'Rechercher une colonne…',
    noMatch: 'Aucune colonne ne correspond.',
    exported: 'Colonnes exportées ({count})',
    defaults: 'Par défaut',
    removeAll: 'Tout retirer',
    moveUp: 'Monter la colonne',
    moveDown: 'Descendre la colonne',
    remove: 'Retirer la colonne',
    noneChosen: 'Aucune colonne : choisissez-en à gauche, ou revenez aux colonnes par défaut.',
    cancel: 'Annuler',
    exportXlsx: 'Exporter en Excel',
    exportCsv: 'Exporter en CSV',
    loadError: 'Impossible de charger la liste des colonnes',
    exportError: "Échec de l'export",
    /** The downloaded file — the server names it alike. */
    fileName: 'parc.{ext}',
  },
};

const en: Translation<typeof fr> = {
  machines: {
    title: 'Export the fleet',
    count: '1 computer | {count} computers',
    caption: "{count} — the list's filters apply, not its pages.",
    available: 'Available columns',
    search: 'Search for a column',
    searchPlaceholder: 'Search for a column…',
    noMatch: 'No column matches.',
    exported: 'Exported columns ({count})',
    defaults: 'Defaults',
    removeAll: 'Remove all',
    moveUp: 'Move the column up',
    moveDown: 'Move the column down',
    remove: 'Remove the column',
    noneChosen: 'No columns: pick some on the left, or go back to the default columns.',
    cancel: 'Cancel',
    exportXlsx: 'Export to Excel',
    exportCsv: 'Export to CSV',
    loadError: 'Could not load the list of columns',
    exportError: 'Export failed',
    fileName: 'fleet.{ext}',
  },
};

export default { fr, en };
