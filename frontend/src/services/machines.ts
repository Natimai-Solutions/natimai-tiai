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

export interface ListMachinesParams {
  search?: string;
  domain?: string;
  /** Antivirus name, matched as a substring server-side. */
  antivirus?: string;
  status?: MachineStatus;
  wu_status?: WindowsUpdateFilter;
  /** true = only machines with at least one active threat. */
  with_active_threats?: boolean;
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

/** Candidate duplicates of a machine (others sharing its SMBIOS anchor). */
export async function getDuplicates(id: string): Promise<Machine[]> {
  const { data } = await api.get<Machine[]>(`/machines/${id}/duplicates`);
  return data;
}

/** Merge `sourceId` into `targetId` (kept); returns the updated target. */
export async function mergeMachines(targetId: string, sourceId: string): Promise<MachineDetail> {
  const { data } = await api.post<MachineDetail>(`/machines/${targetId}/merge`, {
    source_id: sourceId,
  });
  return data;
}
