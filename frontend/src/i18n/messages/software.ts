import type { Translation } from './types';

/** Les logiciels du parc (lot E1 du plan console bilingue). */
const fr = {
  title: 'Logiciels du parc',
  export: 'Exporter',
  exportExcel: 'Excel (.xlsx)',
  exportCsv: 'CSV',
  exportHint: 'Télécharger le catalogue filtré (Excel ou CSV)',
  exportFailed: "Échec de l'export",
  /** The downloaded file's name, before its extension. */
  exportFileName: 'logiciels',
  refresh: 'Actualiser',
  search: 'Rechercher un logiciel',
  searchPlaceholder: 'Nom ou éditeur…',
  machineCount: '{count} poste(s)',
  columns: {
    name: 'Nom',
    version: 'Version',
    publisher: 'Éditeur',
    machines: 'Postes',
    firstSeen: 'Vu depuis',
  },
  empty: {
    loadFailed: 'Le catalogue n’a pas pu être chargé.',
    noMatch: 'Aucun logiciel ne correspond à « {search} ».',
    none: "Aucun logiciel inventorié pour l'instant.",
  },
};

const en: Translation<typeof fr> = {
  title: 'Fleet software',
  export: 'Export',
  exportExcel: 'Excel (.xlsx)',
  exportCsv: 'CSV',
  exportHint: 'Download the filtered catalogue (Excel or CSV)',
  exportFailed: 'Export failed',
  exportFileName: 'software',
  refresh: 'Refresh',
  search: 'Search software',
  searchPlaceholder: 'Name or publisher…',
  machineCount: '{count} computer | {count} computers',
  columns: {
    name: 'Name',
    version: 'Version',
    publisher: 'Publisher',
    machines: 'Computers',
    firstSeen: 'Seen since',
  },
  empty: {
    loadFailed: 'The catalogue could not be loaded.',
    noMatch: 'No software matches “{search}”.',
    none: 'No software inventoried yet.',
  },
};

export default { fr, en };
