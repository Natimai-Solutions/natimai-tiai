import { api } from 'boot/axios';

export type MachineStatus = 'up_to_date' | 'outdated' | 'needs_verification' | 'inactive';

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
  /** null = never reported (agent older than the feature, or a failed read). */
  session_user_present: boolean | null;
  /** null while present = the agent reports presence only (privacy setting). */
  session_username: string | null;
  last_seen: string;
}

export interface MachineDetail extends Machine {
  rtp_enabled: boolean | null;
  av_enabled: boolean | null;
  signature_last_updated: string | null;
  signature_age_days: number | null;
  last_quick_scan: string | null;
  last_full_scan: string | null;
  session_state: string | null;
  session_is_remote: boolean | null;
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
  status?: MachineStatus;
  page?: number;
  page_size?: number;
}

export async function listMachines(params: ListMachinesParams = {}): Promise<MachineList> {
  const { data } = await api.get<MachineList>('/machines', { params });
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
