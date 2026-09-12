import { api } from 'boot/axios';

/** The console's parc-wide settings (page Paramètres), editable without a restart. */
export interface ConsoleSettings {
  maintenance_default_cycle_days: number;
  maintenance_default_owner: { id: string; name: string } | null;
  maintenance_due_soon_days: number;
  /** What the environment says, for the page to show where a value came from. */
  env_default_cycle_days: number;
  env_due_soon_days: number;
  room_source: string;
  updated_at: string | null;
}

export interface SettingsPayload {
  maintenance_default_cycle_days?: number;
  maintenance_default_owner_id?: string | null;
  maintenance_due_soon_days?: number;
}

export async function getSettings(): Promise<ConsoleSettings> {
  const { data } = await api.get<ConsoleSettings>('/settings');
  return data;
}

export async function updateSettings(payload: SettingsPayload): Promise<ConsoleSettings> {
  const { data } = await api.patch<ConsoleSettings>('/settings', payload);
  return data;
}
