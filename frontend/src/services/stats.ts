import { api } from 'boot/axios';

export interface StatsOverview {
  total: number;
  up_to_date: number;
  outdated: number;
  needs_verification: number;
  inactive: number;
  with_active_threats: number;
  /** Machines reporting at least one pending Windows update. */
  machines_wu_pending: number;
  /** Machines waiting on a restart — counted whether or not they are patched. */
  machines_reboot_required: number;
}

export async function getOverview(): Promise<StatsOverview> {
  const { data } = await api.get<StatsOverview>('/stats/overview');
  return data;
}
