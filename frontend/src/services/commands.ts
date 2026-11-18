import { api } from 'boot/axios';
import { t } from 'src/i18n';
import catalogue from 'src/i18n/messages/commands';

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
  // Windows Update (phase 2).
  | 'wu_scan'
  | 'wu_install'
  | 'wu_install_full'
  | 'wu_reset'
  // Inventory (phase 3).
  | 'inventory_scan'
  // Power: taking the poste down, and bringing it back.
  | 'reboot'
  | 'shutdown'
  | 'wake_on_lan'
  // Diagnostics: read-only, the value is in reading the result.
  | 'gpo_report'
  | 'net_config'
  // Software deployment: the two types that carry a package. Not in the
  // generic menu — they need a package chosen — but listed in histories.
  | 'package_install'
  | 'package_uninstall';

export type CommandStatus =
  'pending' | 'delivered' | 'running' | 'succeeded' | 'failed' | 'expired';

export type CommandGroup =
  'defender' | 'windows_update' | 'inventory' | 'power' | 'maintenance' | 'diagnostic';

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
  /**
   * Needs `risky_command:execute` on top of `command:execute`: the action can
   * cost somebody their work or change the poste for good. Mirrors the
   * backend's `RISKY_COMMAND_TYPES`, which is what actually refuses it.
   */
  risky?: boolean;
  /**
   * Executed by the *server*, not queued for the poste's agent.
   *
   * True of exactly one action, and it could not be otherwise: a Wake-on-LAN
   * targets a machine that is off, so there is no agent to hand it to. The
   * pages read this to pick the call to make — `wakeMachines` instead of
   * `createCommands` — while the menu, the confirmation and the history label
   * stay the same for both kinds.
   */
  serverSide?: boolean;
}

/** A group's name in the language shown, read when it is shown. */
export function commandGroupLabel(group: CommandGroup): string {
  return t(`commands.groups.${group}`);
}

// The restart used to sit in the Windows Update section, on the grounds that
// what makes an admin reach for it is the « redémarrage requis » an update
// just raised. With a shutdown and a wake beside it that no longer holds: the
// three actions that change a poste's power state are one decision family and
// belong in one section. The « Redémarrage requis » badge on the Windows
// Update card still says when to reach for it.
const GROUPS: CommandGroup[] = [
  'defender',
  'windows_update',
  'inventory',
  'power',
  'maintenance',
  'diagnostic',
];

/**
 * The groups' names, each read in the language shown at the moment it is
 * read (a getter per group): a table kept across a change of language
 * still says the right thing.
 */
export const commandGroupLabels = Object.defineProperties(
  {} as Record<CommandGroup, string>,
  Object.fromEntries(
    GROUPS.map((group) => [group, { get: () => commandGroupLabel(group), enumerable: true }]),
  ),
);

type CommandSpec = Omit<CommandAction, 'label' | 'hint'>;

/**
 * A catalogue entry whose `label` (and `hint`, with `withHint`) are read
 * from `commands.actions.<type>` each time they are read: in the language
 * shown at that moment, never the one of the page's first render.
 */
function entry(spec: CommandSpec & { withHint?: boolean }): CommandAction {
  const { withHint, ...rest } = spec;
  const action = { ...rest } as CommandAction;
  Object.defineProperty(action, 'label', {
    get: () => t(`commands.actions.${spec.type}.label`),
    enumerable: true,
  });
  if (withHint) {
    Object.defineProperty(action, 'hint', {
      get: () => t(`commands.actions.${spec.type}.hint`),
      enumerable: true,
    });
  }
  return action;
}

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
  entry({
    type: 'quick_scan',
    icon: 'bolt',
    group: 'defender',
    confirm: false,
    bulk: true,
  }),
  entry({
    type: 'full_scan',
    icon: 'travel_explore',
    group: 'defender',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    type: 'update_signatures',
    icon: 'sync',
    group: 'defender',
    confirm: false,
    bulk: true,
  }),
  entry({
    type: 'wu_scan',
    icon: 'search',
    group: 'windows_update',
    confirm: false,
    bulk: true,
  }),
  entry({
    type: 'wu_install',
    risky: true,
    icon: 'system_update',
    group: 'windows_update',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    type: 'wu_install_full',
    risky: true,
    icon: 'browser_updated',
    group: 'windows_update',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    // Last in the section, after the two installs: it is what an admin reaches
    // for once those have failed on a poste, not something to try first.
    type: 'wu_reset',
    risky: true,
    icon: 'settings_backup_restore',
    group: 'windows_update',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    type: 'inventory_scan',
    icon: 'inventory_2',
    group: 'inventory',
    // A read, and a fast one: a dozen WMI queries and two registry walks. There
    // is nothing to warn about and nothing to undo, so no confirmation.
    confirm: false,
    bulk: true,
  }),
  entry({
    // Never automatic, whatever a poste reports as needing one: restarting a
    // machine somebody is working on is an explicit decision.
    type: 'reboot',
    risky: true,
    icon: 'restart_alt',
    group: 'power',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    // The counterpart of the wake below, and the reason that one exists: a parc
    // somebody switches off in the evening is a parc somebody has to switch
    // back on in the morning.
    type: 'shutdown',
    risky: true,
    icon: 'power_settings_new',
    group: 'power',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    // The one action the server performs itself: the poste is off, there is no
    // agent to ask. No confirmation — a wake costs three datagrams and wakes a
    // machine at worst, where the two above can cost somebody their work.
    // Or, on a server hosted off-site, relayed: the server hands the wake to
    // a poste of the same site, which emits it on its next contact. Same menu
    // entry either way — the notification says which happened.
    type: 'wake_on_lan',
    icon: 'wifi_tethering',
    group: 'power',
    confirm: false,
    bulk: true,
    serverSide: true,
  }),
  entry({
    // /target:computer: l'agent tourne en LocalSystem, il n'y a pas de ruche
    // utilisateur à rafraîchir — le libellé l'assume plutôt que de laisser
    // croire que les stratégies utilisateur suivront.
    type: 'gpo_update',
    icon: 'policy',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  }),
  entry({
    type: 'flush_dns',
    icon: 'dns',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  }),
  entry({
    type: 'time_resync',
    icon: 'schedule',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  }),
  entry({
    type: 'cert_pulse',
    icon: 'verified_user',
    group: 'maintenance',
    confirm: false,
    bulk: true,
  }),
  entry({
    type: 'spooler_reset',
    risky: true,
    icon: 'print',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    type: 'sfc_scan',
    icon: 'health_and_safety',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    type: 'dism_restore_health',
    risky: true,
    icon: 'build',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    type: 'dism_component_cleanup',
    risky: true,
    icon: 'cleaning_services',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    type: 'chkdsk_scan',
    icon: 'storage',
    group: 'maintenance',
    confirm: true,
    bulk: true,
    withHint: true,
  }),
  entry({
    // Diagnostics: bulk: false on purpose. Their value is reading one machine's
    // output; fired on the whole fleet they produce a hundred reports nobody
    // opens, at the price of a hundred commands.
    type: 'gpo_report',
    icon: 'fact_check',
    group: 'diagnostic',
    confirm: false,
    bulk: false,
  }),
  entry({
    type: 'net_config',
    icon: 'lan',
    group: 'diagnostic',
    confirm: false,
    bulk: false,
  }),
];

export interface CommandActionGroup {
  group: CommandGroup;
  label: string;
  actions: CommandAction[];
}

// Every group of the catalogue must be here: a group left out vanishes from
// every menu, its actions with it (audit B12, « Rafraîchir l'inventaire »).
const groupOrder: CommandGroup[] = GROUPS;

/**
 * Whether a permission set lets someone trigger `action`: the everyday grant
 * for everything, the risky one on top for the actions flagged so.
 */
export function canRunCommand(permissions: Set<string>, action: CommandAction): boolean {
  if (!permissions.has('command:execute')) return false;
  return !action.risky || permissions.has('risky_command:execute');
}

/**
 * The catalogue split into menu sections. Twenty entries in one flat dropdown
 * is unusable; grouped, an admin finds "Maintenance" without reading the list.
 *
 * `bulkOnly` keeps the diagnostics out of the mass-action menu; `permissions`
 * drops what the caller may not run, so a menu never offers a 403.
 */
export function commandActionGroups(
  options: { bulkOnly?: boolean; permissions?: Set<string> } = {},
): CommandActionGroup[] {
  const allowed = (a: CommandAction) =>
    options.permissions === undefined || canRunCommand(options.permissions, a);
  return groupOrder
    .map((group) => {
      const section = {
        group,
        actions: commandActions.filter(
          (a) => a.group === group && (!options.bulkOnly || a.bulk) && allowed(a),
        ),
      } as CommandActionGroup;
      // Read when shown, like the actions' labels.
      Object.defineProperty(section, 'label', {
        get: () => commandGroupLabel(group),
        enumerable: true,
      });
      return section;
    })
    .filter((section) => section.actions.length > 0);
}

/**
 * Human label for a command type, for the history table. Falls back to the raw
 * value: a type this build does not know (an older console against a newer
 * server) must still be readable, not blank.
 */
export function commandTypeLabel(type: string): string {
  return Object.prototype.hasOwnProperty.call(catalogue.fr.actions, type)
    ? t(`commands.actions.${type}.label`)
    : type;
}

/** A history row's label: the type, and for a deployment the package it carried. */
export function commandRowLabel(cmd: Pick<Command, 'type' | 'package_name'>): string {
  const label = commandTypeLabel(cmd.type);
  return cmd.package_name ? t('commands.rowLabel', { label, package: cmd.package_name }) : label;
}

const ALREADY_THERE = ['pending', 'delivered', 'running'];

/** A command's status in the language shown; the raw value for one unknown. */
export function commandStatusLabel(status: string): string {
  return Object.prototype.hasOwnProperty.call(catalogue.fr.status, status)
    ? t(`commands.status.${status}`)
    : status;
}

/**
 * What a single-poste send did, as a notification. The server creates nothing
 * when the same command is still standing on the poste, and says where it
 * stands (`reason`): « déjà en cours sur ce poste » is not the same news as
 * « déjà en attente ».
 */
export function singleSendNotification(
  action: Pick<CommandAction, 'label'>,
  res: CreateCommandsResponse,
): { type: 'positive' | 'warning' | 'negative'; message: string } {
  if (res.count > 0) return { type: 'positive', message: t('commands.send.sent') };
  if ((res.revoked ?? 0) > 0) {
    return { type: 'negative', message: t('commands.send.revoked', { label: action.label }) };
  }
  const reason = ALREADY_THERE.includes(res.reason ?? '') ? res.reason! : 'pending';
  const where = t(`commands.send.where.${reason}`);
  return { type: 'warning', message: t('commands.send.already', { label: action.label, where }) };
}

export interface CreateCommandsPayload {
  type: CommandType;
  ttl_minutes?: number;
  // Exactly one target must be provided.
  machine_ids?: string[];
  target_all?: boolean;
  target_domain?: string;
  /** Every poste of a site, as the agents report it (exact). */
  target_location?: string;
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
  /**
   * Targets left alone because their token is revoked: no agent will ever
   * fetch the command. Optional: an older server does not send it.
   */
  revoked?: number;
  /**
   * On a single target left alone: where the command already standing on it
   * is (`pending`, `delivered`, `running`). Optional: an older server does not
   * send it, and the console then says « déjà en attente ».
   */
  reason?: 'pending' | 'delivered' | 'running' | null;
}

export interface Command {
  id: string;
  machine_id: string;
  type: string;
  status: string;
  /**
   * The poste that emitted a relayed wake on behalf of `machine_id`; null on
   * every other row. Optional: an older server does not send it.
   */
  relay_machine_id?: string | null;
  /** The package of a deployment command. Optional: an older server does not send it. */
  package_id?: string | null;
  /** That package's name and version (« 7-Zip 23.01 »). Optional likewise. */
  package_name?: string | null;
  /** The poste's name, sent by the list endpoint. */
  machine_hostname?: string | null;
  created_by: string | null;
  created_at: string;
  expires_at: string;
  delivered_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  result_output: string | null;
  error: string | null;
  /**
   * What the console words the verdict from (`commandResultText`): the
   * `error` of a failed command, the `result_output` of a succeeded one —
   * written by the server, or by the agent. Optional: an older server sends
   * neither, and a row stored before, or a tool's own output, has none.
   */
  result_code?: string | null;
  result_params?: Record<string, unknown> | null;
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

/** The two actions that can cost somebody their unsaved work. */
export function isDisruptive(action: CommandAction): boolean {
  return action.type === 'reboot' || action.type === 'shutdown';
}

/** What the confirmation dialog of an action shows — plain options for `$q.dialog`. */
export interface CommandConfirm {
  title: string;
  message: string;
  ok: { label: string; color: string; unelevated: true; noCaps: true };
  cancel: { label: string; flat: true; noCaps: true };
  persistent: true;
}

/**
 * The confirmation of an action on `count` postes, `withSession` of which had a
 * user logged on at their last contact.
 *
 * The OK button says what it does — « Redémarrer 12 postes », not « OK » — and
 * turns red for the two actions that can lose somebody's work. For those, the
 * logged-on users are counted: « dont 3 avec une session ouverte » is the
 * sentence that makes an operator wait for lunch.
 */
export function commandConfirm(
  action: CommandAction,
  count: number,
  withSession = 0,
): CommandConfirm {
  const plural = count > 1;
  const disruptive = isDisruptive(action);
  const label = action.label;
  const lines = [
    plural
      ? t('commands.confirm.questionMany', { label, count })
      : t('commands.confirm.questionOne', { label }),
  ];
  if (disruptive && withSession > 0) {
    lines.push(
      plural
        ? t('commands.confirm.withSessions', { count: withSession })
        : t('commands.confirm.withSessionOne'),
    );
  }
  const hint = action.hint;
  if (hint) lines.push(hint);
  const okLabel = disruptive
    ? plural
      ? t(`commands.actions.${action.type}.okMany`, { count })
      : label
    : plural
      ? t('commands.confirm.runMany', { count })
      : t('commands.confirm.runOne');
  return {
    title: label,
    message: lines.join(' '),
    ok: {
      label: okLabel,
      color: disruptive ? 'negative' : 'primary',
      unelevated: true,
      noCaps: true,
    },
    cancel: { label: t('commands.confirm.cancel'), flat: true, noCaps: true },
    persistent: true,
  };
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
  const revoked = res.revoked ?? 0;
  if (res.count === 0 && (skipped > 0 || revoked > 0)) {
    const parts = [
      skipped > 0 ? t('commands.bulk.alreadyEverywhere', { count: skipped }, skipped) : '',
      revoked > 0 ? t('commands.bulk.revokedPostes', { count: revoked }, revoked) : '',
    ].filter(Boolean);
    return {
      type: 'warning',
      message: t('commands.bulk.nothing', {
        parts: parts.join(t('commands.bulk.partsSeparator')),
      }),
    };
  }
  const sent = t('commands.bulk.sent', { count: res.count }, res.count);
  const left = [
    skipped > 0 ? t('commands.bulk.alreadyPending', { count: skipped }) : '',
    revoked > 0 ? t('commands.bulk.revoked', { count: revoked }) : '',
  ].filter(Boolean);
  return {
    // Skipped ones are routine (pressed twice); a revoked poste is not.
    type: revoked > 0 ? 'warning' : 'positive',
    message: left.length
      ? t('commands.bulk.sentAndLeft', {
          sent,
          left: left.join(t('commands.bulk.leftSeparator')),
        })
      : sent,
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

// --- Verdicts, worded from their codes ---------------------------------------

type Params = Record<string, unknown>;

/** Whether `code` names a sentence of the catalogue (`commands.results`). */
function knownCode(code: string): boolean {
  let node: unknown = catalogue.fr.results;
  for (const part of code.split('.')) {
    if (typeof node !== 'object' || node === null) return false;
    if (!Object.prototype.hasOwnProperty.call(node, part)) return false;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === 'string';
}

/** A parameter as the sentence shows it: the server's are flat values. */
function text(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function word(key: string, named: Params = {}, plural?: number): string {
  return plural === undefined ? t(key, named) : t(key, named, plural);
}

/** « 12 min », « 1 h 05 », « moins d'une minute » — as the server writes it. */
function elapsed(minutes: number): string {
  if (minutes < 1) return word('commands.words.elapsed.lessThanMinute');
  if (minutes < 60) return word('commands.words.elapsed.minutes', { minutes });
  return word('commands.words.elapsed.hours', {
    hours: Math.floor(minutes / 60),
    minutes: String(minutes % 60).padStart(2, '0'),
  });
}

function site(p: Params): string {
  const kind = p.site_kind === 'location' ? 'location' : 'domain';
  return word(`commands.words.site.${kind}`, { site: text(p.site) });
}

function powerWord(form: 'noun' | 'label', p: Params): string {
  return word(`commands.words.power.${form}.${p.action === 'shutdown' ? 'shutdown' : 'reboot'}`);
}

/** What let a package run (the agent's trust note), or ''. */
function trustNote(p: Params): string {
  if (p.trust === 'signer') return word('commands.words.trustSigner', { by: text(p.by) });
  if (p.trust !== 'publisher') return '';
  const note = word('commands.words.trustPublisher', { by: text(p.by) });
  return p.revocation_offline === true ? note + word('commands.words.revocationOffline') : note;
}

function wordFrom(table: object, prefix: string, key: unknown): string {
  return typeof key === 'string' && Object.prototype.hasOwnProperty.call(table, key)
    ? word(`${prefix}.${key}`)
    : '';
}

/**
 * The parameters a code's sentence is filled with — its own, and the pieces
 * built from them — and the number its plural follows, if any.
 */
function filled(code: string, p: Params): { named: Params; plural?: number } {
  const named: Params = Object.fromEntries(Object.entries(p).map(([k, v]) => [k, text(v)]));
  const words = catalogue.fr.words;
  switch (code) {
    case 'wol.address_not_allowed':
    case 'wol.subnet_not_allowed': {
      named.allowed =
        p.allowed === null || p.allowed === undefined
          ? word('commands.words.privateRanges')
          : text(p.allowed);
      const fallback = word('commands.words.defaultMask', {
        prefix: text(p.default_prefix_length),
      });
      named.masks =
        p.prefix_length === null || p.prefix_length === undefined
          ? word('commands.words.masksDefault', { fallback })
          : word('commands.words.masksReported', { prefix: text(p.prefix_length), fallback });
      return { named };
    }
    case 'wol.sent':
    case 'wol.relay.sent':
      return { named, plural: count(p.copies) };
    case 'wol.no_relay':
      named.site = site(p);
      return { named };
    case 'wol.relay_queued':
      named.site = site(p);
      return { named, plural: count(p.peers) };
    case 'wol.relay_already':
      named.state = word(
        `commands.words.relayState.${p.state === 'delivered' ? 'delivered' : 'pending'}`,
      );
      named.elapsed = elapsed(count(p.minutes));
      return { named };
    case 'agent.power_pending':
    case 'power.too_soon':
      named.noun = powerWord('noun', p);
      return { named };
    case 'power.scheduled':
    case 'power.schedule_failed':
      named.label = powerWord('label', p);
      return { named };
    case 'wu.scan':
      return { named, plural: count(p.count) };
    case 'wu.install_incomplete':
      return { named, plural: count(p.failed) };
    case 'wu.known_error':
      named.hint = wordFrom(words.wuHints, 'commands.words.wuHints', `h${text(p.hresult)}`);
      return { named };
    case 'wu.install_result':
      named.result = wordFrom(words.wuResult, 'commands.words.wuResult', p.result);
      return { named };
    case 'inventory.scan':
    case 'inventory.scan_without_software':
      for (const key of ['disks', 'volumes', 'nics', 'software'] as const) {
        const n = count(p[key]);
        named[key] = word(`commands.words.inventory.${key}`, { count: n }, n);
      }
      return { named };
    case 'chkdsk.offline_repair':
      named.meaning = wordFrom(words.chkdsk, 'commands.words.chkdsk', p.meaning);
      return { named };
    case 'spooler.reset':
      return { named, plural: count(p.removed) };
    case 'deploy.no_step':
      named.step = wordFrom(words.deployStep, 'commands.words.deployStep', p.action);
      return { named };
    case 'deploy.exit_code': {
      const note = trustNote(p);
      named.trust = note ? word('commands.words.trustInParentheses', { note }) : '';
      return { named };
    }
    case 'deploy.done': {
      named.verb = wordFrom(words.deployVerb, 'commands.words.deployVerb', p.action);
      named.what = text(p.name) || word('commands.words.packageId', { id: text(p.package_id) });
      named.how = [word('commands.words.method', { method: text(p.method) }), trustNote(p)]
        .map((part) => part.trim())
        .filter(Boolean)
        .join(word('commands.words.howSeparator'));
      named.reboot = p.reboot === true ? word('commands.words.rebootToFinish') : '';
      return { named };
    }
    case 'deploy.winget_done':
      named.already = p.already === true ? word('commands.words.wingetAlready') : '';
      return { named };
  }
  return { named };
}

/**
 * The sentence of a verdict's code in the language shown, or null for a
 * code this console does not know (a newer server or agent): the caller
 * then shows the stored text. A verdict a relay emitted (`params.relay`) is
 * signed with the relay's name, as the server signs its text.
 */
export function commandMessage(
  code: string | null | undefined,
  params?: Record<string, unknown> | null,
): string | null {
  if (!code || !knownCode(code)) return null;
  const p = params ?? {};
  const { named, plural } = filled(code, p);
  // A detail that is itself one of the agent's coded messages (detail_code,
  // its parameters as detail_<name>): worded too, not quoted in French.
  if (typeof p.detail_code === 'string') {
    const inner = Object.fromEntries(
      Object.entries(p)
        .filter(([k]) => k.startsWith('detail_') && k !== 'detail_code')
        .map(([k, v]) => [k.slice('detail_'.length), v]),
    );
    const detail = commandMessage(p.detail_code, inner);
    if (detail !== null) named.detail = detail;
  }
  const sentence = word(`commands.results.${code}`, named, plural);
  const relay = typeof p.relay === 'string' ? p.relay : '';
  return relay ? word('commands.relayed', { relay, text: sentence }) : sentence;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * A stored text with the note that ends a text cut short — the server's or
 * the agent's, always written in French — in the language shown.
 */
function withTruncationWorded(stored: string): string {
  const server = catalogue.fr.truncated.server;
  if (stored.endsWith(server)) {
    return stored.slice(0, -server.length) + word('commands.truncated.server');
  }
  const [before = '', after = ''] = catalogue.fr.truncated.agent.split('{kib}');
  const agent = new RegExp(`${escapeRegExp(before)}(\\d+)${escapeRegExp(after)}$`);
  const cut = agent.exec(stored);
  if (cut) {
    return stored.slice(0, cut.index) + word('commands.truncated.agent', { kib: cut[1] });
  }
  return stored;
}

type Verdict = Pick<
  Command,
  'status' | 'result_output' | 'error' | 'result_code' | 'result_params'
>;

/**
 * A command's output or error as the console shows it: worded from its code
 * in the language shown when the code words that text — the error of a
 * failed command, the output of a succeeded one — and this console knows
 * it; else the stored text as the server or the agent wrote it (a tool's
 * output, a row stored before codes, an older agent), its truncation note
 * worded.
 */
export function commandResultText(cmd: Verdict, kind: 'output' | 'error'): string {
  const stored = (kind === 'error' ? cmd.error : cmd.result_output) ?? '';
  if (!stored) return '';
  const worded = cmd.status === 'failed' ? 'error' : 'output';
  if (kind === worded) {
    const sentence = commandMessage(cmd.result_code, cmd.result_params);
    if (sentence !== null) return sentence;
  }
  return withTruncationWorded(stored);
}

/** A row's verdict in one line of text: its error, else its output. */
export function commandVerdictText(cmd: Verdict): string {
  return commandResultText(cmd, 'error') || commandResultText(cmd, 'output');
}

/**
 * What the server did about one poste asked to wake (`WakeResult.detail`),
 * in the language shown: worded from `detail_code` and `detail_params` when
 * this console knows the code, else the server's own sentence; null when
 * there is none.
 */
export function wakeDetailText(
  detail: string | null,
  code?: string | null,
  params?: Record<string, unknown> | null,
): string | null {
  return commandMessage(code, params) ?? detail;
}
