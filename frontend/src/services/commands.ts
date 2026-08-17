import { api } from 'boot/axios';

export type CommandType =
  // Defender (phase 1).
  | 'quick_scan'
  | 'full_scan'
  | 'update_signatures'
  // Maintenance: acts on the machine.
  | 'gpo_update'
  | 'flush_dns'
  | 'time_resync'
  | 'cert_pulse'
  | 'spooler_reset'
  | 'sfc_scan'
  | 'dism_restore_health'
  | 'dism_component_cleanup'
  | 'chkdsk_scan'
  // Diagnostics: read-only, the value is in reading the result.
  | 'gpo_report'
  | 'net_config';

export type CommandStatus =
  | 'pending'
  | 'delivered'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'expired';

export type CommandGroup = 'defender' | 'maintenance' | 'diagnostic';

/** A command as the console offers it: label, icon, and how it may be triggered. */
export interface CommandAction {
  type: CommandType;
  label: string;
  icon: string;
  group: CommandGroup;
  /** Ask before sending — everything that changes the machine or ties it up for a while. */
  confirm: boolean;
  /** Offered as a bulk action. Diagnostics are not: in bulk they only produce noise. */
  bulk: boolean;
  /** Extra sentence for the confirmation dialog, when the cost is not obvious. */
  hint?: string;
}

export const commandGroupLabels: Record<CommandGroup, string> = {
  defender: 'Defender',
  maintenance: 'Maintenance',
  diagnostic: 'Diagnostic',
};

/**
 * The single source of the console's command catalogue.
 *
 * Both the machine detail page and the bulk-action menu read this list: they
 * used to carry a hand-kept array each, which was already drifting at three
 * Defender entries and would not have survived fourteen.
 *
 * Order matters — it is the order of the menu — and mirrors the agent's own
 * catalogue (`agent/internal/collector/maintenance.go`) and the backend enum.
 */
export const commandActions: CommandAction[] = [
  {
    type: 'quick_scan',
    label: 'Scan rapide',
    icon: 'bolt',
    group: 'defender',
    confirm: false,
    bulk: true,
  },
  {
    type: 'full_scan',
    label: 'Scan complet',
    icon: 'travel_explore',
    group: 'defender',
    confirm: true,
    bulk: true,
    hint: 'Un scan complet mobilise le poste pendant plusieurs dizaines de minutes.',
  },
  {
    type: 'update_signatures',
    label: 'Mise à jour des signatures',
    icon: 'sync',
    group: 'defender',
    confirm: false,
    bulk: true,
  },
  {
    // /target:computer: l'agent tourne en LocalSystem, il n'y a pas de ruche
    // utilisateur à rafraîchir — le libellé l'assume plutôt que de laisser
    // croire que les stratégies utilisateur suivront.
    type: 'gpo_update',
    label: 'Appliquer les stratégies (ordinateur)',
    icon: 'policy',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  },
  {
    type: 'flush_dns',
    label: 'Vider le cache DNS',
    icon: 'dns',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  },
  {
    type: 'time_resync',
    label: "Resynchroniser l'horloge",
    icon: 'schedule',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  },
  {
    type: 'cert_pulse',
    label: 'Relancer l’inscription des certificats',
    icon: 'verified_user',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  },
  {
    type: 'spooler_reset',
    label: 'Réinitialiser le spouleur d’impression',
    icon: 'print',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    hint: 'Le service est arrêté, la file d’impression est vidée, puis le service redémarre : les travaux en attente sont perdus.',
  },
  {
    type: 'sfc_scan',
    label: 'Vérifier l’intégrité système (sfc)',
    icon: 'health_and_safety',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    hint: 'Compter 10 à 20 minutes, pendant lesquelles le poste est sollicité.',
  },
  {
    type: 'dism_restore_health',
    label: 'Réparer l’image système (DISM)',
    icon: 'build',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    hint: 'Jusqu’à une heure. Les correctifs sont téléchargés depuis Windows Update ou le serveur WSUS du poste.',
  },
  {
    type: 'dism_component_cleanup',
    label: 'Nettoyer le magasin de composants (DISM)',
    icon: 'cleaning_services',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    hint: 'Libère de l’espace disque ; compter plusieurs dizaines de minutes.',
  },
  {
    type: 'chkdsk_scan',
    label: 'Analyser le disque (chkdsk)',
    icon: 'storage',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    hint: 'Analyse en ligne : elle signale les erreurs sans les corriger, le poste reste utilisable.',
  },
  {
    // Diagnostics: bulk: false on purpose. Their value is reading one machine's
    // output; fired on the whole fleet they produce a hundred reports nobody
    // opens, at the price of a hundred commands.
    type: 'gpo_report',
    label: 'Rapport de stratégies (gpresult)',
    icon: 'fact_check',
    group: 'diagnostic',
    confirm: false,
    bulk: false,
  },
  {
    type: 'net_config',
    label: 'Configuration réseau (ipconfig)',
    icon: 'lan',
    group: 'diagnostic',
    confirm: false,
    bulk: false,
  },
];

export interface CommandActionGroup {
  group: CommandGroup;
  label: string;
  actions: CommandAction[];
}

const groupOrder: CommandGroup[] = ['defender', 'maintenance', 'diagnostic'];

/**
 * The catalogue split into menu sections. Fourteen entries in one flat dropdown
 * is unusable; grouped, an admin finds "Maintenance" without reading the list.
 *
 * `bulkOnly` keeps the diagnostics out of the mass-action menu.
 */
export function commandActionGroups(options: { bulkOnly?: boolean } = {}): CommandActionGroup[] {
  return groupOrder
    .map((group) => ({
      group,
      label: commandGroupLabels[group],
      actions: commandActions.filter((a) => a.group === group && (!options.bulkOnly || a.bulk)),
    }))
    .filter((section) => section.actions.length > 0);
}

/**
 * Human label for a command type, for the history table. Falls back to the raw
 * value: a type this build does not know (an older console against a newer
 * server) must still be readable, not blank.
 */
export function commandTypeLabel(type: string): string {
  return commandActions.find((a) => a.type === type)?.label ?? type;
}

export interface CreateCommandsPayload {
  type: CommandType;
  ttl_minutes?: number;
  // Exactly one target must be provided.
  machine_ids?: string[];
  target_all?: boolean;
  target_domain?: string;
  target_status?: string;
}

export interface CreateCommandsResponse {
  created: string[];
  count: number;
}

export interface Command {
  id: string;
  machine_id: string;
  type: string;
  status: string;
  created_by: string | null;
  created_at: string;
  expires_at: string;
  delivered_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  result_output: string | null;
  error: string | null;
}

export interface CommandList {
  items: Command[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListCommandsParams {
  status?: CommandStatus;
  machine_id?: string;
  page?: number;
  page_size?: number;
}

export async function createCommands(
  payload: CreateCommandsPayload,
): Promise<CreateCommandsResponse> {
  const { data } = await api.post<CreateCommandsResponse>('/commands', payload);
  return data;
}

export async function listCommands(params: ListCommandsParams = {}): Promise<CommandList> {
  const { data } = await api.get<CommandList>('/commands', { params });
  return data;
}
