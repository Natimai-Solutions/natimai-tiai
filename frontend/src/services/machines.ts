import { api } from 'boot/axios';

export type MachineStatus = 'up_to_date' | 'outdated' | 'needs_verification' | 'inactive';

/**
 * Windows Update facet of the machine list. A separate axis from
 * `MachineStatus` (an antivirus axis): the two filters combine.
 */
export type WindowsUpdateFilter = 'pending' | 'reboot_required';

/**
 * Scan-freshness facet of the machine list: which Defender scan is overdue.
 * A third axis next to the antivirus and Windows Update ones — the filters
 * combine. 'both' selects postes where quick *and* full scans are overdue.
 */
export type ScanFilter = 'quick' | 'full' | 'both';

export interface Machine {
  id: string;
  machine_uuid: string;
  hostname: string | null;
  domain: string | null;
  /**
   * The site, as the agent's configuration names it ("Lycée de Taravao").
   * null = the agent reports none, which is the default. What a multi-site
   * parc filters by — and what the Wake-on-LAN relay picks a neighbour with.
   */
  location: string | null;
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
  /**
   * Three inventory fields in the list and not the twenty-five the fiche shows:
   * this payload serves a thousand rows, and what a list is scanned for is
   * "quel modèle" and "lequel n'a plus de place".
   */
  hw_model: string | null;
  ram_total_mb: number | null;
  system_volume_total_mb: number | null;
  system_volume_free_mb: number | null;
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

/** One physical memory stick. */
export interface MemoryModule {
  id: number;
  /** The bank/slot label ("DIMM A1") — the server's key for this row. */
  slot: string;
  capacity_mb: number | null;
  type: string | null;
  speed_mhz: number | null;
  manufacturer: string | null;
  serial: string | null;
  form_factor: string | null;
}

/** One physical drive. */
export interface Disk {
  id: number;
  device_id: string;
  model: string | null;
  serial: string | null;
  firmware: string | null;
  /**
   * SSD / HDD / NVMe / unknown. 'unknown' is a real answer: the WMI class that
   * always responds cannot tell the two apart, and a host without the Storage
   * namespace falls back to it.
   */
  media_type: string | null;
  bus_type: string | null;
  size_mb: number | null;
  health_status: string | null;
  is_removable: boolean;
}

/** One fixed logical volume. No `used_mb`: it is `total - free`, and two figures
 * that can contradict each other about one number is what deriving avoids. */
export interface Volume {
  id: number;
  letter: string;
  label: string | null;
  filesystem: string | null;
  total_mb: number | null;
  free_mb: number | null;
  is_system: boolean;
  /** BitLocker. null = not read, which is *not* "not encrypted". */
  encryption_status: string | null;
}

/** One network adapter. The elected address lives on the machine itself
 * (`ip_address`, `mac_address`) and is re-read every heartbeat; this list is a
 * day old. */
export interface Nic {
  id: number;
  name: string | null;
  mac: string | null;
  type: string | null;
  speed_mbps: number | null;
  is_up: boolean;
  is_virtual: boolean;
  ip_address: string | null;
  ip_prefix_length: number | null;
  is_dhcp: boolean | null;
  gateway: string | null;
  driver_version: string | null;
}

/** One display adapter. Two is the common case: an iGPU and a card. */
export interface Gpu {
  id: number;
  name: string;
  chipset: string | null;
  memory_mb: number | null;
  driver_version: string | null;
  driver_date: string | null;
  resolution: string | null;
}

/** One program installed on a machine, with its catalogue identity. */
export interface InstalledSoftware {
  /** The parc-wide handle: what "qui d'autre a ce logiciel" is asked with. */
  software_id: number;
  name: string;
  version: string;
  publisher: string;
  install_date: string | null;
  arch: string | null;
  source: string | null;
  install_location: string | null;
  first_seen: string;
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
  /**
   * The kill-switch state. A revoked poste is cut off for good — even the
   * fleet-wide secret cannot re-enroll it — until an admin allows it back.
   */
  token_revoked: boolean;
  first_seen: string;
  created_at: string;
  updated_at: string;

  // --- Inventory. Cardinality-one facts as fields, the rest as lists.
  hw_manufacturer: string | null;
  hw_serial: string | null;
  hw_chassis_type: string | null;
  hw_is_virtual: boolean;
  hw_hypervisor: string | null;
  mb_manufacturer: string | null;
  mb_model: string | null;
  mb_serial: string | null;
  bios_vendor: string | null;
  bios_version: string | null;
  bios_date: string | null;
  secure_boot: boolean | null;
  tpm_version: string | null;
  cpu_model: string | null;
  cpu_manufacturer: string | null;
  cpu_cores: number | null;
  cpu_threads: number | null;
  cpu_speed_mhz: number | null;
  cpu_count: number | null;
  ram_slots_total: number | null;
  ram_slots_used: number | null;
  os_architecture: string | null;
  os_install_date: string | null;
  last_boot_time: string | null;
  /**
   * When the inventory was taken — deliberately not `last_seen`. A poste seen a
   * minute ago whose inventory is three weeks old is an anomaly to show.
   */
  inventory_last_seen: string | null;
  memory_modules: MemoryModule[];
  disks: Disk[];
  volumes: Volume[];
  nics: Nic[];
  gpus: Gpu[];
  software: InstalledSoftware[];
  /**
   * The agent version this poste is measured against: the highest one on the
   * parc, or the one pinned server-side. null on an empty parc. What turns
   * "0.4.1" into "behind 0.5.0" (see utils/agentVersion).
   */
  agent_latest_version: string | null;
}

export interface MachineList {
  items: Machine[];
  total: number;
  page: number;
  page_size: number;
  /** Same reference as on the fiche, once per page: the list flags the rows below it. */
  agent_latest_version: string | null;
}

/** Sortable columns of the machine list, named after the API's own fields. */
export type MachineSortField =
  | 'hostname'
  | 'domain'
  | 'location'
  | 'av_product_name'
  | 'wu_pending_count'
  | 'session_user_present'
  | 'last_seen'
  | 'hw_model'
  | 'ram_total_mb'
  /** Free space as a *percentage*: 40 Go left on a 4 To disk and on a 128 Go SSD
   * are not the same news. Derived server-side from two columns. */
  | 'disk_free_percent';

export interface ListMachinesParams {
  /** Free search: hostname, UUID, IP, antivirus name — and MAC in any notation. */
  search?: string;
  domain?: string;
  /** Site, matched exactly (the dropdown feeds fleet values). */
  location?: string;
  /** Antivirus name, matched as a substring server-side. */
  antivirus?: string;
  /** OS version, matched as a substring server-side ("Windows 10" = every build). */
  os_version?: string;
  status?: MachineStatus;
  /** true = only postes on right now (heartbeat within the online window). */
  online?: boolean;
  wu_status?: WindowsUpdateFilter;
  /** Only machines whose scan(s) of `scan_type` predate `scan_older_than_days`. */
  scan_type?: ScanFilter;
  /** Age threshold for `scan_type`, in days; the server defaults to 7. */
  scan_older_than_days?: number;
  /** true = only machines with at least one active threat. */
  with_active_threats?: boolean;
  /** Hardware model, matched as a substring ("OptiPlex" gathers 7010 and 7020). */
  hw_model?: string;
  hw_manufacturer?: string;
  /** Processor model, matched as a substring ("i5-8" gathers a generation). */
  cpu_model?: string;
  /** Chassis kind as the agent normalises it: desktop, laptop, tablet… (exact). */
  hw_chassis_type?: string;
  /**
   * Memory bounds in whole GiB, inclusive — the *nominal* size (16 for a poste
   * Windows reports as 16 289 Mio), rounded up server-side.
   */
  ram_min_gb?: number;
  ram_max_gb?: number;
  /** Only machines whose system volume is below this percentage of free space. */
  disk_free_below?: number;
  /** Only machines carrying this catalogue entry — the software drill-down. */
  software_id?: number;
  /** Exact agent version, as the fleet listing names it. */
  agent_version?: string;
  /** true = only postes whose agent is below the reference — the ones a deployment missed. */
  agent_outdated?: boolean;
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

/** One OS version present in the fleet, with how many machines report it. */
export interface OsVersion {
  name: string;
  count: number;
}

/**
 * OS versions found across the fleet, most widespread first. Feeds the machine
 * list's OS filter dropdown, and the counts double as a migration progress bar
 * ("how many postes are still on Windows 10").
 */
export async function listOsVersions(): Promise<OsVersion[]> {
  const { data } = await api.get<OsVersion[]>('/machines/os-versions');
  return data;
}

/** One agent version present in the fleet, with how many postes run it. */
export interface AgentVersion {
  name: string;
  count: number;
  /** Below the reference — what makes the dropdown a deployment progress bar. */
  outdated: boolean;
}

export interface AgentVersions {
  /** The reference: the highest version on the parc, or the pinned one. */
  latest: string | null;
  /** Pinned in the server's configuration rather than derived from the fleet. */
  pinned: boolean;
  /** Newest first. */
  versions: AgentVersion[];
}

/**
 * Agent versions across the fleet, each flagged against the reference. Feeds
 * the agent filter, and the counts are the deployment's progress bar
 * ("combien restent sur 0.4.1").
 */
export async function listAgentVersions(): Promise<AgentVersions> {
  const { data } = await api.get<AgentVersions>('/machines/agent-versions');
  return data;
}

/** One distinct inventory value present in the fleet, with its count. */
export interface FleetValue {
  name: string;
  count: number;
}

/**
 * Hardware models present in the fleet, most widespread first. Feeds the model
 * filter, and the renewal plan is read off it top-down.
 */
export async function listModels(): Promise<FleetValue[]> {
  const { data } = await api.get<FleetValue[]>('/machines/models');
  return data;
}

/** Hardware manufacturers present in the fleet, most widespread first. */
export async function listManufacturers(): Promise<FleetValue[]> {
  const { data } = await api.get<FleetValue[]>('/machines/manufacturers');
  return data;
}

/** Processor models present in the fleet, most widespread first. */
export async function listProcessors(): Promise<FleetValue[]> {
  const { data } = await api.get<FleetValue[]>('/machines/processors');
  return data;
}

/** Chassis kinds present in the fleet (desktop, laptop…), most common first. */
export async function listChassisTypes(): Promise<FleetValue[]> {
  const { data } = await api.get<FleetValue[]>('/machines/chassis-types');
  return data;
}

/**
 * Sites the agents report, most populated first. Feeds the location filter;
 * postes whose agent names no site are not listed — they are reached by
 * clearing the filter.
 */
export async function listLocations(): Promise<FleetValue[]> {
  const { data } = await api.get<FleetValue[]>('/machines/locations');
  return data;
}

/** One column the fleet export can produce, as the server's catalogue lists it. */
export interface ExportColumn {
  key: string;
  label: string;
  /** identity / antivirus / windows_update / hardware — the picker's sections. */
  group: string;
  group_label: string;
  kind: string;
  /** Part of the set exported when the reader picks nothing. */
  default: boolean;
}

/**
 * The export's column catalogue, in the order the picker shows it. Served
 * rather than hardcoded: the catalogue is what the export reads, and a picker
 * offering a column the server does not know would fail at the click.
 */
export async function listExportColumns(): Promise<ExportColumn[]> {
  const { data } = await api.get<ExportColumn[]>('/machines/export-columns');
  return data;
}

export type ExportFormat = 'xlsx' | 'csv';

export interface ExportOptions {
  format: ExportFormat;
  /** Catalogue keys, in the order the columns should appear; empty = defaults. */
  columns?: string[];
  /** IANA zone the timestamps are written in; omitted = UTC. */
  tz?: string;
}

/**
 * The filtered fleet as a spreadsheet — Excel or CSV, with chosen columns.
 *
 * Fetched as a blob and handed to the browser rather than linked to: the API
 * needs the Authorization header, which a plain `<a href>` would not carry.
 */
export async function exportMachines(
  params: ListMachinesParams,
  options: ExportOptions,
): Promise<Blob> {
  const query: Record<string, unknown> = { ...params };
  if (options.columns?.length) query.columns = options.columns.join(',');
  if (options.tz) query.tz = options.tz;
  const { data } = await api.get<Blob>(`/machines/export.${options.format}`, {
    params: query,
    responseType: 'blob',
  });
  return data;
}

export async function getMachine(id: string): Promise<MachineDetail> {
  const { data } = await api.get<MachineDetail>(`/machines/${id}`);
  return data;
}

export async function revokeToken(id: string): Promise<void> {
  await api.post(`/machines/${id}/revoke-token`);
}

/**
 * Lift a revocation: the old token stays dead, the poste comes back on its
 * next enrollment attempt (its agent retries by itself, within its back-off).
 */
export async function allowReenroll(id: string): Promise<void> {
  await api.post(`/machines/${id}/allow-reenroll`);
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
  /**
   * The server handed the wake to a poste of the target's site to emit,
   * rather than emitting itself (WOL_RELAY_ENABLED). Nothing has left any
   * wire yet when this answer arrives; the notification says so. Optional so
   * an older server reads as the emitting one.
   */
  relayed?: boolean;
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
  // In relay mode the packet has not left anywhere yet: a poste of the site
  // will emit it on its next contact with the server, and the sentence must
  // not claim more than that.
  const sent = res.relayed
    ? `Réveil confié aux postes voisins de ${res.woken} poste(s)`
    : `Paquet de réveil émis vers ${res.woken} poste(s)`;
  if (res.failed > 0) {
    const left = res.relayed ? 'sans cible ni relais' : 'sans cible connue';
    return { type: 'warning', message: `${sent} — ${res.failed} ${left}` };
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
