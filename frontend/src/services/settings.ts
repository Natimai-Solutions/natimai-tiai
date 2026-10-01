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

export type EmailProvider = 'mailgun' | 'smtp';
export type SmtpSecurity = 'starttls' | 'tls' | 'none';

/** What the server's environment says for each mail field: the value a field
 * left empty in the console falls back to. Never a secret, nor the SMTP
 * account name — only whether one is set. */
export interface EmailEnv {
  provider: EmailProvider;
  from_email: string | null;
  from_name: string;
  smtp_host: string | null;
  smtp_port: number;
  smtp_security: SmtpSecurity;
  smtp_user_set: boolean;
  smtp_password_set: boolean;
  smtp_verify_tls: boolean;
  smtp_timeout_seconds: number;
  mailgun_domain: string | null;
  mailgun_api_key_set: boolean;
  mailgun_base_url: string;
  /** Whether the environment alone would send mail. */
  configured: boolean;
}

/** The card « Envoi des e-mails ». Each field is what the console stored;
 * `null` = nothing stored, the environment's value applies. */
export interface EmailSettings {
  provider: EmailProvider | null;
  from_email: string | null;
  from_name: string | null;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_security: SmtpSecurity | null;
  smtp_user: string | null;
  smtp_verify_tls: boolean | null;
  smtp_timeout_seconds: number | null;
  mailgun_domain: string | null;
  mailgun_base_url: string | null;
  /** The secrets are never sent back: only whether one is stored, and
   * whether it is stored but sealed under a key the server no longer has. */
  smtp_password_set: boolean;
  smtp_password_unreadable: boolean;
  mailgun_api_key_set: boolean;
  mailgun_api_key_unreadable: boolean;
  /** The policy as it resolves now. */
  effective_provider: EmailProvider;
  configured: boolean;
  /** What the chosen provider still lacks, in words. */
  missing: string[];
  env: EmailEnv;
}

/** Absent = unchanged; `null` = forget the console's value (the
 * environment's applies again); a secret is replaced by any non-empty string. */
export interface EmailSettingsPayload {
  provider?: EmailProvider | null;
  from_email?: string | null;
  from_name?: string | null;
  smtp_host?: string | null;
  smtp_port?: number | null;
  smtp_security?: SmtpSecurity | null;
  smtp_user?: string | null;
  smtp_password?: string | null;
  smtp_verify_tls?: boolean | null;
  smtp_timeout_seconds?: number | null;
  mailgun_domain?: string | null;
  mailgun_api_key?: string | null;
  mailgun_base_url?: string | null;
}

export interface EmailTestRequest {
  /** Defaults, server-side, to the caller's own address. */
  to?: string;
  /** The card's unsaved values, tried without being saved. */
  email?: EmailSettingsPayload;
}

export interface EmailTestResult {
  ok: boolean;
  /** Readable as is: what went out, or what to fix. */
  message: string;
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
  /** How mail leaves the console. */
  email: EmailSettings;
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
  email?: EmailSettingsPayload;
}

export async function getSettings(): Promise<ConsoleSettings> {
  const { data } = await api.get<ConsoleSettings>('/settings');
  return data;
}

export async function updateSettings(payload: SettingsPayload): Promise<ConsoleSettings> {
  const { data } = await api.patch<ConsoleSettings>('/settings', payload);
  return data;
}

/** Send one test mail now, outside the outbox. A failed send is still a
 * resolved promise, with `ok: false` and the reason in `message`. */
export async function sendTestEmail(request: EmailTestRequest): Promise<EmailTestResult> {
  const { data } = await api.post<EmailTestResult>('/settings/email/test', request);
  return data;
}
