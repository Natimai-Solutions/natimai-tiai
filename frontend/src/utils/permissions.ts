/**
 * The permission catalogue, mirrored from the backend
 * (`app/features/user/permissions.py`, `PERMISSION_CATALOGUE`). Keys are
 * `resource:action`; the labels are the console's, and the order is the
 * order of the grid on the groups page.
 */

export type Resource =
  'machine' | 'threat' | 'command' | 'risky_command' | 'room' | 'intervention' | 'user' | 'audit';

export type Action = 'read' | 'write' | 'execute';

export interface PermissionEntry {
  key: string;
  resource: Resource;
  action: Action;
  /** What the resource is, as a row header. */
  resourceLabel: string;
  /** What granting this lets someone do, as the checkbox's label. */
  label: string;
  /** A sentence for the cases where the label alone would be read two ways. */
  hint?: string;
}

export function permissionKey(resource: Resource, action: Action): string {
  return `${resource}:${action}`;
}

export const PERMISSION_CATALOGUE: PermissionEntry[] = [
  {
    key: 'machine:read',
    resource: 'machine',
    action: 'read',
    resourceLabel: 'Postes',
    label: 'Consulter',
    hint: 'Le tableau de bord, la liste et la fiche des postes, les logiciels, les exports.',
  },
  {
    key: 'machine:write',
    resource: 'machine',
    action: 'write',
    resourceLabel: 'Postes',
    label: 'Gérer',
    hint: 'Révoquer un token, autoriser un ré-enrôlement, fusionner des doublons.',
  },
  {
    key: 'threat:read',
    resource: 'threat',
    action: 'read',
    resourceLabel: 'Menaces',
    label: 'Consulter',
  },
  {
    key: 'command:read',
    resource: 'command',
    action: 'read',
    resourceLabel: 'Commandes',
    label: "Consulter l'historique",
  },
  {
    key: 'command:execute',
    resource: 'command',
    action: 'execute',
    resourceLabel: 'Commandes',
    label: 'Exécuter les commandes courantes',
    hint: 'Scans, mise à jour des signatures, recherche de mises à jour, cache DNS, stratégies, diagnostics, réveil Wake-on-LAN…',
  },
  {
    key: 'risky_command:execute',
    resource: 'risky_command',
    action: 'execute',
    resourceLabel: 'Commandes à risque',
    label: 'Exécuter les commandes à risque',
    hint: 'Redémarrage, arrêt, installation des mises à jour, réinitialisation de Windows Update, réparations DISM, réinitialisation du spouleur. Requiert aussi les commandes courantes.',
  },
  {
    key: 'room:read',
    resource: 'room',
    action: 'read',
    resourceLabel: 'Salles et bâtiments',
    label: 'Consulter',
  },
  {
    key: 'room:write',
    resource: 'room',
    action: 'write',
    resourceLabel: 'Salles et bâtiments',
    label: 'Gérer',
    hint: 'Créer et modifier les salles et les bâtiments, y affecter des postes.',
  },
  {
    key: 'intervention:read',
    resource: 'intervention',
    action: 'read',
    resourceLabel: 'Historique des interventions',
    label: 'Consulter',
  },
  {
    key: 'intervention:write',
    resource: 'intervention',
    action: 'write',
    resourceLabel: 'Historique des interventions',
    label: 'Saisir',
    hint: 'Ajouter, modifier et supprimer des interventions sur tout poste ; les suppressions sont tracées.',
  },
  {
    key: 'user:read',
    resource: 'user',
    action: 'read',
    resourceLabel: 'Comptes et groupes',
    label: 'Consulter',
  },
  {
    key: 'user:write',
    resource: 'user',
    action: 'write',
    resourceLabel: 'Comptes et groupes',
    label: 'Gérer',
    hint: 'Créer, modifier et supprimer des comptes et des groupes, réinitialiser des mots de passe.',
  },
  {
    key: 'audit:read',
    resource: 'audit',
    action: 'read',
    resourceLabel: "Journal d'audit",
    label: 'Consulter',
  },
];

/** The catalogue as the grid shows it: one row per resource, in order. */
export interface PermissionRow {
  resource: Resource;
  resourceLabel: string;
  entries: PermissionEntry[];
}

export function permissionRows(): PermissionRow[] {
  const rows: PermissionRow[] = [];
  for (const entry of PERMISSION_CATALOGUE) {
    const row = rows.find((r) => r.resource === entry.resource);
    if (row) row.entries.push(entry);
    else
      rows.push({ resource: entry.resource, resourceLabel: entry.resourceLabel, entries: [entry] });
  }
  return rows;
}

/** A readable name for a key, for lists that show what a group grants. */
export function permissionLabel(key: string): string {
  const entry = PERMISSION_CATALOGUE.find((e) => e.key === key);
  return entry ? `${entry.resourceLabel} — ${entry.label.toLowerCase()}` : key;
}
