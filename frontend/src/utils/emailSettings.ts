/**
 * The card « Envoi des e-mails », as pure functions: from what the server
 * serves to the form, from the form to the payload, and what to say about a
 * secret the page never sees.
 *
 * Two conventions, one per kind of control:
 * - a text or number box shows only what the console stored; empty means
 *   « la valeur du serveur », which the box shows as its placeholder;
 * - a choice (provider, security, certificate check) always has a value, so it
 *   shows the one in force — and saving the environment's own value stores
 *   nothing, so the field keeps following the environment.
 *
 * Secrets are write-only: the box starts empty whatever is stored, a typed
 * value replaces the stored one, and only an explicit « effacer » removes it.
 */

import type {
  EmailProvider,
  EmailSettings,
  EmailSettingsPayload,
  SmtpSecurity,
} from 'src/services/settings';

export interface EmailForm {
  provider: EmailProvider;
  fromEmail: string;
  fromName: string;
  smtpHost: string;
  /** `number | string`: an emptied number box hands back ''. */
  smtpPort: number | string;
  smtpSecurity: SmtpSecurity;
  smtpUser: string;
  /** A new password, typed now; empty = keep the stored one. */
  smtpPassword: string;
  /** Remove the stored password on save (the environment's applies again). */
  clearSmtpPassword: boolean;
  smtpVerifyTls: boolean;
  smtpTimeout: number | string;
  mailgunDomain: string;
  mailgunApiKey: string;
  clearMailgunApiKey: boolean;
  mailgunBaseUrl: string;
}

/** The form as the stored settings fill it. */
export function emailFormFrom(s: EmailSettings): EmailForm {
  return {
    provider: s.provider ?? s.env.provider,
    fromEmail: s.from_email ?? '',
    fromName: s.from_name ?? '',
    smtpHost: s.smtp_host ?? '',
    smtpPort: s.smtp_port ?? '',
    smtpSecurity: s.smtp_security ?? s.env.smtp_security,
    smtpUser: s.smtp_user ?? '',
    smtpPassword: '',
    clearSmtpPassword: false,
    smtpVerifyTls: s.smtp_verify_tls ?? s.env.smtp_verify_tls,
    smtpTimeout: s.smtp_timeout_seconds ?? '',
    mailgunDomain: s.mailgun_domain ?? '',
    mailgunApiKey: '',
    clearMailgunApiKey: false,
    mailgunBaseUrl: s.mailgun_base_url ?? '',
  };
}

function text(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

function int(value: number | string): number | null {
  if (value === '' || value === null || value === undefined) return null;
  return Number(value);
}

/** A choice equal to the environment's is not pinned: it keeps following it. */
function choice<T>(value: T, env: T): T | null {
  return value === env ? null : value;
}

/** A typed secret replaces; an explicit « effacer » clears; otherwise not sent. */
function secret(typed: string, clear: boolean): string | null | undefined {
  if (typed !== '') return typed;
  return clear ? null : undefined;
}

/**
 * The payload the card sends — to PATCH /settings on « Enregistrer », and to
 * the test send as the unsaved values to try. Every plain field is sent (an
 * unchanged one rewrites what is stored); a secret only when typed or cleared.
 */
export function emailPayload(form: EmailForm, s: EmailSettings): EmailSettingsPayload {
  const payload: EmailSettingsPayload = {
    provider: choice(form.provider, s.env.provider),
    from_email: text(form.fromEmail),
    from_name: text(form.fromName),
    smtp_host: text(form.smtpHost),
    smtp_port: int(form.smtpPort),
    smtp_security: choice(form.smtpSecurity, s.env.smtp_security),
    smtp_user: text(form.smtpUser),
    smtp_verify_tls: choice(form.smtpVerifyTls, s.env.smtp_verify_tls),
    smtp_timeout_seconds: int(form.smtpTimeout),
    mailgun_domain: text(form.mailgunDomain),
    mailgun_base_url: text(form.mailgunBaseUrl),
  };
  const password = secret(form.smtpPassword, form.clearSmtpPassword);
  if (password !== undefined) payload.smtp_password = password;
  const key = secret(form.mailgunApiKey, form.clearMailgunApiKey);
  if (key !== undefined) payload.mailgun_api_key = key;
  return payload;
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const HOST = /^[A-Za-z0-9.\-[\]:]+$/;
const API_URL = /^https?:\/\/[^\s/]+(\/\S*)?$/;

function intOutside(value: number | string, low: number, high: number): boolean {
  const n = int(value);
  return n !== null && (!Number.isInteger(n) || n < low || n > high);
}

/** What stops the form from being saved or tried, in the page's words; null when nothing. */
export function emailFormError(form: EmailForm): string | null {
  const from = text(form.fromEmail);
  if (from !== null && !EMAIL.test(from))
    return "L'adresse d'expéditeur n'est pas une adresse e-mail.";
  if (form.provider === 'smtp') {
    const host = text(form.smtpHost);
    if (host !== null && !HOST.test(host))
      return 'Le serveur SMTP est un nom ou une adresse, sans « smtp:// » ni chemin.';
    if (intOutside(form.smtpPort, 1, 65535)) return 'Le port est un entier entre 1 et 65535.';
    if (intOutside(form.smtpTimeout, 1, 120))
      return 'Le délai est un entier entre 1 et 120 secondes.';
  } else {
    const domain = text(form.mailgunDomain);
    if (domain !== null && !HOST.test(domain))
      return 'Le domaine Mailgun est un nom de domaine, sans chemin.';
    const base = text(form.mailgunBaseUrl);
    if (base !== null && !API_URL.test(base))
      return "L'adresse de l'API Mailgun commence par https://.";
  }
  return null;
}

/** An optional recipient for the test mail: empty (the caller's own address) or an address. */
export function testRecipientError(to: string): string | null {
  const value = to.trim();
  return value === '' || EMAIL.test(value) ? null : "Ce n'est pas une adresse e-mail.";
}

export interface SecretState {
  label: string;
  color: 'positive' | 'warning' | 'grey';
}

/**
 * What the page says about a secret it cannot show: stored in the console,
 * stored but unreadable since a change of SECRET_KEY, or taken from the
 * environment — the three cases an administrator must tell apart.
 */
export function secretState(stored: boolean, unreadable: boolean, envSet: boolean): SecretState {
  if (unreadable) return { label: 'à ressaisir', color: 'warning' };
  if (stored) return { label: 'enregistré', color: 'positive' };
  if (envSet) return { label: 'valeur du serveur', color: 'grey' };
  return { label: 'non défini', color: 'grey' };
}

const SECURITY_LABELS: Record<SmtpSecurity, string> = {
  starttls: 'STARTTLS (port 587)',
  tls: 'TLS implicite (port 465)',
  none: 'Aucune (relais interne, port 25)',
};

export const SECURITY_OPTIONS = (Object.keys(SECURITY_LABELS) as SmtpSecurity[]).map((value) => ({
  value,
  label: SECURITY_LABELS[value],
}));

/** The one-line state of the card: does mail leave, and if not, why. */
export function emailStatus(s: EmailSettings): { ok: boolean; text: string } {
  if (s.configured) {
    const via = s.effective_provider === 'smtp' ? 'un serveur SMTP' : 'Mailgun';
    return { ok: true, text: `Les e-mails partent par ${via}.` };
  }
  const missing = s.missing.length ? ` : il manque ${s.missing.join(', ')}` : '';
  return { ok: false, text: `Aucun e-mail ne part${missing}.` };
}
