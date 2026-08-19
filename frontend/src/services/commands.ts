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
  // Windows Update (phase 2) + the restart it eventually needs.
  | 'wu_scan'
  | 'wu_install'
  | 'wu_install_full'
  | 'wu_reset'
  | 'reboot'
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

export type CommandGroup = 'defender' | 'windows_update' | 'maintenance' | 'diagnostic';

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
  // The restart lives in this section rather than in Maintenance: what makes an
  // admin reach for it is the « redémarrage requis » an update just raised, and
  // the two belong next to each other in the menu.
  windows_update: 'Windows Update',
  maintenance: 'Maintenance',
  diagnostic: 'Diagnostic',
};

/**
 * The single source of the console's command catalogue.
 *
 * Both the machine detail page and the bulk-action menu read this list: they
 * used to carry a hand-kept array each, which was already drifting at three
 * Defender entries and would not have survived eighteen.
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
    type: 'wu_scan',
    label: 'Rechercher les mises à jour',
    icon: 'search',
    group: 'windows_update',
    confirm: false,
    bulk: true,
  },
  {
    type: 'wu_install',
    label: 'Installer les mises à jour (hors pilotes)',
    icon: 'system_update',
    group: 'windows_update',
    confirm: true,
    bulk: true,
    hint: 'Le poste télécharge et installe ses mises à jour logicielles ; compter plusieurs dizaines de minutes. Aucun redémarrage automatique : le poste signalera s’il en attend un.',
  },
  {
    type: 'wu_install_full',
    label: 'Installer les mises à jour (pilotes compris)',
    icon: 'browser_updated',
    group: 'windows_update',
    confirm: true,
    bulk: true,
    hint: 'Comme ci-dessus, mais les pilotes proposés par Windows Update sont installés eux aussi — à réserver aux postes où c’est souhaité. Aucun redémarrage automatique.',
  },
  {
    // Last in the section, after the two installs: it is what an admin reaches
    // for once those have failed on a poste, not something to try first.
    type: 'wu_reset',
    label: 'Réinitialiser Windows Update',
    icon: 'settings_backup_restore',
    group: 'windows_update',
    confirm: true,
    bulk: true,
    hint: 'Procédure Microsoft : les services Windows Update sont arrêtés, le magasin de mises à jour et le cache de signatures sont renommés, puis les services repartent. Windows les reconstruit à la recherche suivante — l’historique des mises à jour du poste est perdu et les correctifs déjà téléchargés le seront à nouveau. Rien n’est installé ni redémarré.',
  },
  {
    // Never automatic, whatever a poste reports as needing one: restarting a
    // machine somebody is working on is an explicit decision.
    type: 'reboot',
    label: 'Redémarrer le poste',
    icon: 'restart_alt',
    group: 'windows_update',
    confirm: true,
    bulk: true,
    hint: 'Le redémarrage a lieu dans 60 secondes ; l’utilisateur connecté voit un avertissement et peut enregistrer son travail. Les documents non enregistrés seront perdus.',
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

const groupOrder: CommandGroup[] = ['defender', 'windows_update', 'maintenance', 'diagnostic'];

/**
 * The catalogue split into menu sections. Eighteen entries in one flat dropdown
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
  /**
   * Targets left alone because they already carried an unfinished command of
   * the same type. Not an error — re-pressing a button on a poste that has not
   * answered yet is the normal way this happens — but the console has to say
   * so instead of claiming it sent something.
   *
   * Optional so an older server, which does not send the field, reads as zero
   * rather than as NaN in the notification.
   */
  skipped?: number;
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

/**
 * What a bulk send actually did, as a notification.
 *
 * The skipped count is the point. Fire a scan on 340 postes, press it again
 * before any of them has answered, and the server legitimately creates nothing
 * — « 0 commande(s) envoyée(s) » alone would read as a failure rather than as
 * "they all already have it".
 */
export function bulkSendNotification(res: CreateCommandsResponse): {
  type: 'positive' | 'warning';
  message: string;
} {
  // ?? 0 and not a required field: an older server does not send it, and NaN
  // in a notification is worse than an undercount.
  const skipped = res.skipped ?? 0;
  if (res.count === 0 && skipped > 0) {
    return {
      type: 'warning',
      message: `Rien à envoyer : cette commande est déjà en attente sur ${skipped} poste(s).`,
    };
  }
  const sent = `${res.count} commande(s) envoyée(s)`;
  return {
    type: 'positive',
    message: skipped > 0 ? `${sent} — ${skipped} déjà en attente, ignoré(s)` : sent,
  };
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
