import { api } from 'boot/axios';

/** One variable of the server's environment, as the page prints it. */
export interface EnvItem {
  key: string;
  /** Already rendered server-side; `null` = not set. */
  value: string | null;
  description: string;
}

export interface EnvGroup {
  label: string;
  items: EnvItem[];
}

/** The console's parc-wide settings (page Paramètres), editable without a restart. */
export interface ConsoleSettings {
  maintenance_default_cycle_days: number;
  maintenance_default_owner: { id: string; name: string } | null;
  maintenance_due_soon_days: number;
  /** What the environment says, for the page to show where a value came from. */
  env_default_cycle_days: number;
  env_due_soon_days: number;
  /** Usage statistics: the window and the two thresholds, as resolved. */
  usage_window_days: number;
  usage_low_hours: number;
  usage_high_hours: number;
  /** What the environment says for each — the value before the console wrote one. */
  env_usage_window_days: number;
  env_usage_low_hours: number;
  env_usage_high_hours: number;
  /** Parc thresholds, as resolved (the console's value, else the environment's). */
  signature_max_age_days: number;
  inactive_after_days: number;
  low_disk_free_percent: number;
  hardware_aging_years: number;
  /** `null` = automatic: the highest version the parc reports. */
  agent_expected_version: string | null;
  command_default_ttl_minutes: number;
  env_signature_max_age_days: number;
  env_inactive_after_days: number;
  env_low_disk_free_percent: number;
  env_hardware_aging_years: number;
  env_agent_expected_version: string | null;
  env_command_default_ttl_minutes: number;
  /** The mail schedule: the digest hour in UTC, the reminder weekday (0 = lundi). */
  digest_hour_utc: number;
  maintenance_reminder_weekday: number;
  env_digest_hour_utc: number;
  env_maintenance_reminder_weekday: number;
  room_source: string;
  /** The rest of the environment, read-only and never a secret: what an
   * administrator checks without a shell on the server. */
  environment: EnvGroup[];
  updated_at: string | null;
}

export interface SettingsPayload {
  maintenance_default_cycle_days?: number;
  maintenance_default_owner_id?: string | null;
  maintenance_due_soon_days?: number;
  usage_window_days?: number;
  usage_low_hours?: number;
  usage_high_hours?: number;
  signature_max_age_days?: number;
  inactive_after_days?: number;
  low_disk_free_percent?: number;
  hardware_aging_years?: number;
  /** `''` = automatic, even over a version pinned in the environment. */
  agent_expected_version?: string;
  command_default_ttl_minutes?: number;
  digest_hour_utc?: number;
  maintenance_reminder_weekday?: number;
}

export async function getSettings(): Promise<ConsoleSettings> {
  const { data } = await api.get<ConsoleSettings>('/settings');
  return data;
}

export async function updateSettings(payload: SettingsPayload): Promise<ConsoleSettings> {
  const { data } = await api.patch<ConsoleSettings>('/settings', payload);
  return data;
}
