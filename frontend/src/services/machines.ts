import { api } from 'boot/axios';

export type MachineStatus = 'up_to_date' | 'outdated' | 'needs_verification' | 'inactive';

/**
 * Windows Update facet of the machine list. A separate axis from
 * `MachineStatus` (an antivirus axis): the two filters combine.
 */
export type WindowsUpdateFilter = 'pending' | 'reboot_required';

export interface Machine {
  id: string;
  machine_uuid: string;
  hostname: string | null;
  domain: string | null;
  /** Primary address elected by the agent; null = never reported. */
  ip_address: string | null;
  os_version: string | null;
  agent_version: string | null;
  is_up_to_date: boolean | null;
  needs_verification: boolean;
  signature_version: string | null;
  /**
   * Antivirus registered with the Windows Security Center — the only source that
   * sees a third-party product. null = never reported (agent too old, or a host
   * with no Security Center); '' = read and empty, i.e. no antivirus at all.
   */
  av_product_name: string | null;
  av_product_enabled: boolean | null;
  av_product_signatures_up_to_date: boolean | null;
  /** Whether the product above is Defender itself (decided by the agent). */
  av_product_is_defender: boolean | null;
  /** null = never reported (agent older than the feature, or a failed read). */
  session_user_present: boolean | null;
  /** null while present = the agent reports presence only (privacy setting). */
  session_username: string | null;
  /**
   * Pending Windows updates. null = never reported — an agent older than the
   * feature, or one whose Windows Update search failed — which the console
   * shows as unknown rather than as "nothing to install".
   */
  wu_pending_count: number | null;
  /** Never null: a machine that has not reported is not awaiting a restart. */
  wu_reboot_required: boolean;
  last_seen: string;
  /**
   * Powered on with its agent reaching the server, i.e. `last_seen` is younger
   * than the server's online window (a few agent poll intervals). Computed
   * server-side on each read — a snapshot, like every other field here, that
   * goes stale until the next refresh.
   */
  is_online: boolean;
}

/** An update Windows Update reports as applicable and not yet installed. */
export interface PendingUpdate {
  id: number;
  /** WUA's UpdateID and revision — the server's dedup key, not for display. */
  update_id: string;
  kb: string | null;
  title: string;
  /** MSRC rating, lowercased server-side: critical / important / moderate / low. */
  severity: string | null;
  type: 'software' | 'driver' | string;
  categories: string | null;
  is_downloaded: boolean;
  size_mb: number | null;
  /** When this machine first reported the update — how long it has been behind. */
  first_seen: string;
  last_seen: string;
}

export interface MachineDetail extends Machine {
  /**
   * Hardware address of the adapter holding `ip_address`, canonicalised
   * server-side. null = never reported, and a poste without one cannot be woken:
   * the magic packet has nothing to name.
   */
  mac_address: string | null;
  /**
   * Mask reported for `ip_address` by the poste's own adapter — 16 for a machine
   * in 10.4.0.0/16. It is what the wake broadcasts to. null = never reported (an
   * agent older than the feature), and the server then falls back on its
   * configured default.
   */
  ip_prefix_length: number | null;
  rtp_enabled: boolean | null;
  av_enabled: boolean | null;
  signature_last_updated: string | null;
  signature_age_days: number | null;
  last_quick_scan: string | null;
  last_full_scan: string | null;
  /** Defender's AMRunningMode: Normal / Passive / SxS Passive Mode / EDR Block Mode. */
  running_mode: string | null;
  session_state: string | null;
  session_is_remote: boolean | null;
  wu_last_search: string | null;
  wu_last_install: string | null;
  /** Sorted critical-first by the server; empty when nothing is pending. */
  pending_updates: PendingUpdate[];
  machine_guid: string | null;
  smbios_uuid: string | null;
  tpm_ek_hash: string | null;
  first_seen: string;
  created_at: string;
  updated_at: string;
}

export interface MachineList {
  items: Machine[];
  total: number;
  page: number;
  page_size: number;
}

/** Sortable columns of the machine list, named after the API's own fields. */
export type MachineSortField =
  | 'hostname'
  | 'domain'
  | 'av_product_name'
  | 'wu_pending_count'
  | 'session_user_present'
  | 'last_seen';

export interface ListMachinesParams {
  search?: string;
  domain?: string;
  /** Antivirus name, matched as a substring server-side. */
  antivirus?: string;
  status?: MachineStatus;
  wu_status?: WindowsUpdateFilter;
  /** true = only machines with at least one active threat. */
  with_active_threats?: boolean;
  /** Server-side sort; omitted = freshest contact first. */
  sort_by?: MachineSortField;
  sort_desc?: boolean;
  page?: number;
  page_size?: number;
}

export async function listMachines(params: ListMachinesParams = {}): Promise<MachineList> {
  const { data } = await api.get<MachineList>('/machines', { params });
  return data;
}

/** One antivirus present in the fleet, with how many machines report it. */
export interface AntivirusProduct {
  name: string;
  count: number;
}

/**
 * Antivirus products found across the fleet, most widespread first. Feeds the
 * machine list's filter dropdown: which products are installed is fleet data, not
 * something the console can hardcode.
 */
export async function listAntivirusProducts(): Promise<AntivirusProduct[]> {
  const { data } = await api.get<AntivirusProduct[]>('/machines/antivirus-products');
  return data;
}

export async function getMachine(id: string): Promise<MachineDetail> {
  const { data } = await api.get<MachineDetail>(`/machines/${id}`);
  return data;
}

export async function revokeToken(id: string): Promise<void> {
  await api.post(`/machines/${id}/revoke-token`);
}

/** What makes a record a candidate duplicate, strongest evidence first. */
export type MatchReason = 'smbios_uuid' | 'tpm_ek_hash' | 'hostname';

export interface DuplicateCandidate extends Machine {
  /** When this record was first enrolled — what tells two records of the same
   * poste apart, since they share its hostname. */
  first_seen: string;
  match_reason: MatchReason;
}

/**
 * Candidate duplicates of a machine: other records that may be the same
 * physical poste, matched on its SMBIOS anchor, its TPM key, or — as a lead and
 * not as proof — its hostname. Sorted with the hardware evidence first.
 */
export async function getDuplicates(id: string): Promise<DuplicateCandidate[]> {
  const { data } = await api.get<DuplicateCandidate[]>(`/machines/${id}/duplicates`);
  return data;
}

/** What the server did about one machine when asked to wake it. */
export interface WakeResult {
  machine_id: string;
  hostname: string | null;
  ok: boolean;
  /**
   * The server's own sentence, in French: the destination the packet went to,
   * or why none could be found. Shown as-is — it is the only thing that
   * explains a poste that did not come back.
   */
  detail: string;
}

export interface WakeResponse {
  results: WakeResult[];
  woken: number;
  failed: number;
}

/**
 * Wake machines with a Wake-on-LAN magic packet emitted by the *server*.
 *
 * The one action in this console that does not go through the poste's agent,
 * and it could not: the machine is off. It therefore has no command to queue and
 * no result to wait for — the server emits, records the attempt in the machine's
 * command history, and answers here with what it did.
 *
 * Never partially fails as a request: a poste with no known MAC comes back as a
 * failed entry among the others, not as an HTTP error.
 */
export async function wakeMachines(ids: string[]): Promise<WakeResponse> {
  const { data } = await api.post<WakeResponse>('/machines/wake', { machine_ids: ids });
  return data;
}

/**
 * What a wake actually did, as a notification.
 *
 * Three outcomes rather than two, because "rien n'a été émis" and "tout est
 * parti" are not the same news, and neither is the mixed case an admin has to
 * act on. Nothing here promises a poste came back: Wake-on-LAN is
 * unacknowledged, and the console learns of a wake only when the agent reports.
 */
export function wakeNotification(res: WakeResponse): {
  type: 'positive' | 'warning' | 'negative';
  message: string;
} {
  if (res.woken === 0) {
    // One poste failing has a reason worth quoting; thirty have thirty, and the
    // detail of each is in its own line of the machine's command history.
    const only = res.failed === 1 ? res.results.find((r) => !r.ok) : undefined;
    return {
      type: 'negative',
      message: only
        ? `Réveil impossible : ${only.detail}`
        : `Réveil impossible sur ${res.failed} poste(s) : aucun paquet émis.`,
    };
  }
  const sent = `Paquet de réveil émis vers ${res.woken} poste(s)`;
  if (res.failed > 0) {
    return { type: 'warning', message: `${sent} — ${res.failed} sans cible connue` };
  }
  return { type: 'positive', message: `${sent} — le poste remontera à son prochain démarrage` };
}

/** Merge `sourceId` into `targetId` (kept); returns the updated target. */
export async function mergeMachines(targetId: string, sourceId: string): Promise<MachineDetail> {
  const { data } = await api.post<MachineDetail>(`/machines/${targetId}/merge`, {
    source_id: sourceId,
  });
  return data;
}
