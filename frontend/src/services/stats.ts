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
  /**
   * Inventory. Each one is a list an administrator can open and act on, which is
   * why "how much RAM in total" is not among them.
   */
  machines_low_disk: number;
  machines_unencrypted: number;
  machines_aging: number;
  /** Distinct programs installed somewhere — the size of the catalogue page. */
  software_count: number;
  /**
   * The thresholds the two counts above were computed with. Served rather than
   * hardcoded here: they are server settings, and a card reading "moins de 10 %"
   * while the server counted at 15 would be a lie nobody could see.
   */
  low_disk_free_percent: number;
  hardware_aging_years: number;
  /** Postes whose agent is below the reference — the ones a deployment missed. */
  machines_agent_outdated: number;
  /** Verification requests waiting on somebody. */
  open_checks: number;
  /** The reference itself, for the card's caption. null on an empty parc. */
  agent_latest_version: string | null;
}

export async function getOverview(): Promise<StatsOverview> {
  const { data } = await api.get<StatsOverview>('/stats/overview');
  return data;
}
