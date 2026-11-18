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

import { t } from 'src/i18n';
import type {
  EmailProvider,
  EmailSettings,
  EmailSettingsPayload,
  EmailTestResult,
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
  if (from !== null && !EMAIL.test(from)) return t('settings.email.errors.fromEmail');
  if (form.provider === 'smtp') {
    const host = text(form.smtpHost);
    if (host !== null && !HOST.test(host)) return t('settings.email.errors.smtpHost');
    if (intOutside(form.smtpPort, 1, 65535)) return t('settings.email.errors.port');
    if (intOutside(form.smtpTimeout, 1, 120)) return t('settings.email.errors.timeout');
  } else {
    const domain = text(form.mailgunDomain);
    if (domain !== null && !HOST.test(domain)) return t('settings.email.errors.mailgunDomain');
    const base = text(form.mailgunBaseUrl);
    if (base !== null && !API_URL.test(base)) return t('settings.email.errors.mailgunBaseUrl');
  }
  return null;
}

/** An optional recipient for the test mail: empty (the caller's own address) or an address. */
export function testRecipientError(to: string): string | null {
  const value = to.trim();
  return value === '' || EMAIL.test(value) ? null : t('settings.email.errors.recipient');
}

export interface SecretState {
  label: string;
  color: 'positive' | 'warning' | 'grey';
}

/** The four cases of a secret the page cannot show. */
export type SecretKind = 'unreadable' | 'stored' | 'env' | 'unset';

/**
 * Which case a secret is in: stored in the console, stored but unreadable
 * since a change of SECRET_KEY, or taken from the environment — the three
 * cases an administrator must tell apart —, or none.
 */
export function secretKind(stored: boolean, unreadable: boolean, envSet: boolean): SecretKind {
  if (unreadable) return 'unreadable';
  if (stored) return 'stored';
  if (envSet) return 'env';
  return 'unset';
}

const SECRET_COLORS: Record<SecretKind, SecretState['color']> = {
  unreadable: 'warning',
  stored: 'positive',
  env: 'grey',
  unset: 'grey',
};

/** What the page says about a secret it cannot show: its badge. */
export function secretState(stored: boolean, unreadable: boolean, envSet: boolean): SecretState {
  const kind = secretKind(stored, unreadable, envSet);
  return { label: t(`settings.email.secret.${kind}`), color: SECRET_COLORS[kind] };
}

/** The line under a secret box: what saving will do with it. */
export function secretHint(kind: SecretKind, clearing: boolean): string {
  if (clearing) return t('settings.email.secretHint.clearing');
  if (kind === 'unreadable') return t('settings.email.secretHint.unreadable');
  if (kind === 'stored') return t('settings.email.secretHint.stored');
  return t('settings.email.secretHint.other');
}

const SECURITY_MODES: SmtpSecurity[] = ['starttls', 'tls', 'none'];

/** A security mode as the select shows it, in the reader's language. */
export function securityLabel(security: SmtpSecurity): string {
  return SECURITY_MODES.includes(security)
    ? t(`settings.email.securityOptions.${security}`)
    : security;
}

/** The select's options; each label is read when shown, in the reader's language. */
export const SECURITY_OPTIONS = SECURITY_MODES.map((value) => ({
  value,
  get label(): string {
    return securityLabel(value);
  },
}));

/** A provider inside a sentence: « valeur du serveur : serveur SMTP ». */
export function providerLabel(provider: EmailProvider): string {
  return t(`settings.email.providerInline.${provider === 'smtp' ? 'smtp' : 'mailgun'}`);
}

/** `key` translated with `named`, or null when the catalogue has no such key. */
function translated(key: string, named: Record<string, unknown> = {}): string | null {
  const text = t(key, named);
  return text === key ? null : text;
}

/**
 * What the chosen provider lacks, in the reader's language: from the codes of
 * the server (`missing_codes`), each one falling back to the server's own
 * French when the console does not know it — or when the server is older and
 * sends no codes.
 */
export function missingTexts(s: Pick<EmailSettings, 'missing' | 'missing_codes'>): string[] {
  const codes = s.missing_codes;
  if (!codes || codes.length !== s.missing.length) return s.missing;
  return codes.map((code, i) => translated(`settings.email.missing.${code}`) ?? s.missing[i]!);
}

/** The one-line state of the card: does mail leave, and if not, why. */
export function emailStatus(s: EmailSettings): { ok: boolean; text: string } {
  if (s.configured) {
    const key = s.effective_provider === 'smtp' ? 'viaSmtp' : 'viaMailgun';
    return { ok: true, text: t(`settings.email.status.${key}`) };
  }
  const missing = missingTexts(s);
  if (!missing.length) return { ok: false, text: t('settings.email.status.none') };
  return {
    ok: false,
    text: t('settings.email.status.missing', {
      missing: missing.join(t('settings.email.listSeparator')),
    }),
  };
}

// The server cuts its sentence to this many characters (``probe._MAX_MESSAGE``).
const MAX_RESULT = 400;

/** A parameter as the server's f-string writes it (`None` for nothing). */
function str(value: unknown): string {
  if (value === null || value === undefined) return 'None';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** The sentence of a test send's outcome, from its code; null for an unknown code. */
function resultSentence(code: string, params: Record<string, unknown>): string | null {
  const key = `settings.test.results.${code}`;
  const named = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, str(v)]));
  switch (code) {
    case 'sent':
      return translated(`${key}_${params.provider === 'smtp' ? 'smtp' : 'mailgun'}`, named);
    case 'incomplete': {
      const codes = Array.isArray(params.missing) ? params.missing.map(String) : [];
      const texts = codes.map((c) => translated(`settings.email.missing.${c}`));
      if (texts.some((x) => x === null)) return null;
      return translated(key, { missing: texts.join(t('settings.email.listSeparator')) });
    }
    case 'smtp_auth_required':
      return translated(params.has_user === true ? `${key}_user` : key, named);
    case 'smtp_recipients_refused': {
      const refused = Array.isArray(params.recipients) ? params.recipients : [];
      const details = refused
        .map((r: Record<string, unknown>) =>
          t('settings.test.refusedRecipient', {
            address: str(r.address),
            code: str(r.code),
            text: str(r.text),
          }),
        )
        .join(t('settings.test.refusedRecipientSeparator'));
      return translated(key, { details });
    }
    case 'mailgun_status':
      return translated(params.body ? `${key}_body` : key, named);
    default:
      return translated(key, named);
  }
}

/**
 * What the page says under « Envoyer un e-mail de test », in the reader's
 * language: the server's outcome worded from its code and parameters — the
 * server's own words (an SMTP reply, a system error) kept as they came. A code
 * the console does not know, or a server older than the codes, shows the
 * server's French sentence.
 */
export function testResultText(result: EmailTestResult): string {
  if (!result.code || !result.params) return result.message;
  const sentence = resultSentence(result.code, result.params);
  return sentence === null ? result.message : sentence.slice(0, MAX_RESULT);
}
