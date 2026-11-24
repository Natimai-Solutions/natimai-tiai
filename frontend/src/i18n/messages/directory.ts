import type { Translation } from './types';

/** La lecture de l'annuaire par des postes désignés (plan `dev/plan-lecture-annuaire.md`). */
const fr = {
  title: 'Annuaire',
  caption:
    'Des postes désignés lisent les objets ordinateurs de leur domaine avec leur compte machine. Le serveur range alors les salles d’après cette lecture et signale les postes dont la déclaration diffère.',
  mode: {
    off: 'Désactivée : l’emplacement, l’OU et le DN déclarés par les agents sont crus sur parole (DIRECTORY_VERIFY=off).',
    relay:
      'Lecture par des postes désignés (DIRECTORY_VERIFY=relay), toutes les {minutes} min. Une lecture non renouvelée depuis {hours} h ne vérifie plus rien.',
  },
  loadFailed: 'L’état de l’annuaire n’a pas pu être chargé.',
  noDomain: 'Aucun domaine lu pour l’instant.',
  domain: {
    lastRead: 'Lu le {date} par {reader} : {count} objet(s)',
    neverRead: 'Pas encore lu',
    readers: 'Lecteurs : {names}',
    noReader: 'Aucun lecteur désigné : ce domaine garde la déclaration des agents.',
    disagreement:
      'Les lecteurs ne lisent pas la même chose ({names}) : rien ne bouge tant qu’ils ne sont pas d’accord.',
    pending:
      'La dernière lecture déplacerait {count} poste(s), plus que le seuil de {limit} : à confirmer.',
    move: '{host} : {from} → {to}',
    noRoom: 'aucune salle',
    confirm: 'Appliquer les déplacements',
    discard: 'Laisser les postes en place',
    forget: 'Oublier ce domaine',
    forgetConfirm:
      'Oublier le domaine {name} ? Ses lectures sont effacées et ses postes seront rapprochés de nouveau à la prochaine lecture. À faire quand le domaine a été reconstruit sous un autre identifiant.',
    cancel: 'Annuler',
    done: 'Fait',
    failed: 'L’opération a échoué',
  },
  waiting: 'Lecteurs en attente de leur première lecture : {names}',
  withoutReader: 'Domaines déclarés par des postes sans lecteur : {names}',
  counts:
    'Postes vérifiés : {verified} · écarts : {mismatch} · inconnus : {unknown} · périmés : {stale} · contestés : {contested}',
  restricted:
    'L’état de l’annuaire porte sur tout le parc : il n’est pas affiché à un compte limité à certains lieux.',
  status: {
    verified: 'Vérifié',
    mismatch: 'Écart',
    unknown: 'Inconnu',
    stale: 'Périmé',
    contested: 'Contesté',
  },
  statusHint: {
    verified: 'Ce que l’agent déclare est ce que l’annuaire dit.',
    mismatch:
      'L’agent déclare autre chose que l’annuaire : poste déplacé dans AD et pas encore redémarré, ou déclaration à vérifier.',
    unknown: 'Aucun objet ordinateur de ce nom lu dans l’annuaire.',
    stale: 'Objet désactivé ou supprimé de l’annuaire, ou lecture trop ancienne.',
    contested:
      'Deux postes enrôlés portent ce nom dans ce domaine : aucun n’est rapproché de l’objet tant que l’un des deux n’est pas fusionné, supprimé ou révoqué.',
  },
  card: {
    title: 'Annuaire',
    caption: 'Ce que l’agent déclare, à côté de ce qu’un lecteur a lu dans l’annuaire.',
    declared: 'Déclaré par l’agent',
    read: 'Lu dans l’annuaire',
    dn: 'Nom distinctif',
    ou: 'OU',
    location: 'Emplacement',
    reader: 'Lecteur d’annuaire depuis le {date}',
    designate: 'Désigner comme lecteur d’annuaire',
    revoke: 'Retirer la désignation',
    designateHint:
      'Un serveur membre ou un poste d’administration toujours allumé, jamais un poste élève : il lira les objets ordinateurs de son domaine pour les autres.',
    designated: 'Poste désigné lecteur d’annuaire',
    revoked: 'Désignation retirée',
  },
  chip: 'Annuaire : {status}',
};

const en: Translation<typeof fr> = {
  title: 'Directory',
  caption:
    'Designated computers read the computer objects of their domain with their machine account. The server then files the rooms by that reading and flags the computers whose declaration differs.',
  mode: {
    off: 'Off: the location, OU and DN the agents declare are taken at their word (DIRECTORY_VERIFY=off).',
    relay:
      'Read by designated computers (DIRECTORY_VERIFY=relay), every {minutes} min. A reading not renewed for {hours} h verifies nothing.',
  },
  loadFailed: 'The directory state could not be loaded.',
  noDomain: 'No domain read yet.',
  domain: {
    lastRead: 'Read on {date} by {reader}: {count} object(s)',
    neverRead: 'Not read yet',
    readers: 'Readers: {names}',
    noReader: 'No designated reader: this domain keeps the agents’ declaration.',
    disagreement:
      'The readers do not read the same thing ({names}): nothing moves until they agree.',
    pending:
      'The last reading would move {count} computer(s), more than the limit of {limit}: to confirm.',
    move: '{host}: {from} → {to}',
    noRoom: 'no room',
    confirm: 'Apply the moves',
    discard: 'Leave the computers where they are',
    forget: 'Forget this domain',
    forgetConfirm:
      'Forget the domain {name}? Its readings are erased and its computers will be matched again at the next reading. For a domain rebuilt under another identifier.',
    cancel: 'Cancel',
    done: 'Done',
    failed: 'The operation failed',
  },
  waiting: 'Readers waiting for their first reading: {names}',
  withoutReader: 'Domains declared by computers without a reader: {names}',
  counts:
    'Computers verified: {verified} · mismatches: {mismatch} · unknown: {unknown} · stale: {stale} · contested: {contested}',
  restricted:
    'The directory state covers the whole fleet: it is not shown to an account confined to some places.',
  status: {
    verified: 'Verified',
    mismatch: 'Mismatch',
    unknown: 'Unknown',
    stale: 'Stale',
    contested: 'Contested',
  },
  statusHint: {
    verified: 'What the agent declares is what the directory says.',
    mismatch:
      'The agent declares something else than the directory: computer moved in AD and not restarted yet, or a declaration to check.',
    unknown: 'No computer object of that name read in the directory.',
    stale: 'Object disabled or deleted in the directory, or reading too old.',
    contested:
      'Two enrolled computers bear this name in this domain: neither is matched to the object until one of them is merged, deleted or revoked.',
  },
  card: {
    title: 'Directory',
    caption: 'What the agent declares, beside what a reader read in the directory.',
    declared: 'Declared by the agent',
    read: 'Read in the directory',
    dn: 'Distinguished name',
    ou: 'OU',
    location: 'Location',
    reader: 'Directory reader since {date}',
    designate: 'Designate as directory reader',
    revoke: 'Remove the designation',
    designateHint:
      'A member server or an administration computer always on, never a pupil’s computer: it will read the computer objects of its domain for the others.',
    designated: 'Computer designated as directory reader',
    revoked: 'Designation removed',
  },
  chip: 'Directory: {status}',
};

export default { fr, en };
