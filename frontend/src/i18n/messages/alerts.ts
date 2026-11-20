import type { Translation } from './types';

/** Les alertes (plan `dev/plan-evolutions-itil.md`, chantier C1). */
const fr = {
  title: 'Alertes',
  subtitle:
    'Ce que les règles relèvent sur les postes, ouvert et résolu par le serveur toutes les cinq minutes.',
  refresh: 'Actualiser',
  all: 'Toutes',
  openSince: 'depuis le {date}',
  resolvedOn: 'résolue le {date}',
  check: 'Vérification demandée',
  columns: {
    machine: 'Poste',
    place: 'Emplacement',
    rule: 'Alerte',
    detail: 'Détail',
    opened: 'Ouverte le',
  },
  empty: {
    loadFailed: 'Les alertes n’ont pas pu être chargées.',
    none: 'Aucune alerte ouverte.',
    noneRule: 'Aucune alerte ouverte pour cette règle.',
  },
  card: {
    title: 'Alertes',
    caption: 'Relevées par le serveur sur ce que le poste remonte',
    what: 'les alertes',
    loading: 'Chargement…',
    none: 'Aucune alerte ouverte sur ce poste.',
    history: 'Historique ({count})',
    hideHistory: 'Masquer l’historique',
  },
  rules: {
    disk_low: 'Disque système presque plein',
    disk_unhealthy: 'Disque en mauvaise santé',
    volume_unencrypted: 'Volume système non chiffré',
    reboot_pending: 'Redémarrage en attente',
    os_unsupported: 'Windows hors support',
    forbidden_software: 'Logiciel interdit',
    inactive: 'Sans contact',
    warranty_ending: 'Garantie bientôt terminée',
  },
  detail: {
    disk_low: '{percent} % libres (seuil : {threshold} %)',
    disk_unhealthy: '{disks}',
    volume_unencrypted: 'Volume {letter} : {status}',
    reboot_pending: 'Demandé par Windows Update le {date}',
    os_unsupported: '{os}, plus mis à jour depuis le {date}',
    os_unsupportedNoDate: '{os}, plus mis à jour',
    forbidden_software: '{programs}',
    forbidden_softwareMore: '{programs} et {count} autre(s)',
    inactive: 'Dernier contact le {date}',
    warranty_ending: 'Garantie jusqu’au {date}',
  },
  /** The instructions of a verification the server opened for an alert. */
  instructions: 'Alerte : {rule} — {detail}',
};

const en: Translation<typeof fr> = {
  title: 'Alerts',
  subtitle:
    'What the rules find on the computers, opened and resolved by the server every five minutes.',
  refresh: 'Refresh',
  all: 'All',
  openSince: 'since {date}',
  resolvedOn: 'resolved on {date}',
  check: 'Check requested',
  columns: {
    machine: 'Computer',
    place: 'Location',
    rule: 'Alert',
    detail: 'Detail',
    opened: 'Opened on',
  },
  empty: {
    loadFailed: 'The alerts could not be loaded.',
    none: 'No open alert.',
    noneRule: 'No open alert for this rule.',
  },
  card: {
    title: 'Alerts',
    caption: 'Raised by the server from what the computer reports',
    what: 'the alerts',
    loading: 'Loading…',
    none: 'No open alert on this computer.',
    history: 'History ({count})',
    hideHistory: 'Hide history',
  },
  rules: {
    disk_low: 'System disk nearly full',
    disk_unhealthy: 'Unhealthy disk',
    volume_unencrypted: 'System volume not encrypted',
    reboot_pending: 'Restart pending',
    os_unsupported: 'Windows out of support',
    forbidden_software: 'Forbidden software',
    inactive: 'No contact',
    warranty_ending: 'Warranty ending soon',
  },
  detail: {
    disk_low: '{percent} % free (threshold: {threshold} %)',
    disk_unhealthy: '{disks}',
    volume_unencrypted: 'Volume {letter}: {status}',
    reboot_pending: 'Requested by Windows Update on {date}',
    os_unsupported: '{os}, no longer updated since {date}',
    os_unsupportedNoDate: '{os}, no longer updated',
    forbidden_software: '{programs}',
    forbidden_softwareMore: '{programs} and {count} more',
    inactive: 'Last contact on {date}',
    warranty_ending: 'Warranty until {date}',
  },
  instructions: 'Alert: {rule} — {detail}',
};

export default { fr, en };
