import { api } from 'boot/axios';

export interface Threat {
  id: number;
  machine_id: string;
  detection_id: string | null;
  threat_name: string | null;
  severity: string | null;
  category: string | null;
  status: string | null;
  action_taken: string | null;
  detected_at: string | null;
}

export interface ThreatList {
  items: Threat[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListThreatsParams {
  machine_id?: string;
  status?: string;
  severity?: string;
  /** true: the retired postes' threats left out (the dashboard's sample). */
  in_parc?: boolean;
  page?: number;
  page_size?: number;
}

export async function listThreats(params: ListThreatsParams = {}): Promise<ThreatList> {
  const { data } = await api.get<ThreatList>('/threats', { params });
  return data;
}
