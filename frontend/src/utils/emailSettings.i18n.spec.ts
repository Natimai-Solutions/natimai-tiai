import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import type { EmailSettings, EmailTestResult } from 'src/services/settings';
import {
  SECURITY_OPTIONS,
  emailFormError,
  emailStatus,
  missingTexts,
  providerLabel,
  secretHint,
  secretState,
  testRecipientError,
  testResultText,
  type EmailForm,
} from './emailSettings';

/**
 * The server's own French for the e-mail card — what a provider lacks, and
 * the outcome of a test send — with the codes and parameters it sends beside
 * it (backend/tests/test_settings_texts.py writes and checks them). The
 * console must write the same from the codes.
 */
interface Fixture {
  email_test: (EmailTestResult & { code: string; params: Record<string, unknown> })[];
  email_missing: { code: string; label: string }[];
}
const FIXTURE = JSON.parse(
  readFileSync(
    new URL('../../../backend/tests/data/settings_texts_fr.json', import.meta.url),
    'utf-8',
  ),
) as Fixture;

afterEach(() => setLocale('fr'));

function settings(overrides: Partial<EmailSettings> = {}): EmailSettings {
  return {
    provider: null,
    from_email: null,
    from_name: null,
    smtp_host: null,
    smtp_port: null,
    smtp_security: null,
    smtp_user: null,
    smtp_verify_tls: null,
    smtp_timeout_seconds: null,
    mailgun_domain: null,
    mailgun_base_url: null,
    smtp_password_set: false,
    smtp_password_unreadable: false,
    mailgun_api_key_set: false,
    mailgun_api_key_unreadable: false,
    effective_provider: 'mailgun',
    configured: false,
    missing: ['le domaine Mailgun', 'la clé API Mailgun'],
    missing_codes: ['mailgun_domain', 'mailgun_api_key'],
    env: {
      provider: 'mailgun',
      from_email: null,
      from_name: 'Tiai',
      smtp_host: null,
      smtp_port: 587,
      smtp_security: 'starttls',
      smtp_user_set: false,
      smtp_password_set: false,
      smtp_verify_tls: true,
      smtp_timeout_seconds: 10,
      mailgun_domain: null,
      mailgun_api_key_set: false,
      mailgun_base_url: 'https://api.mailgun.net/v3',
      configured: false,
    },
    ...overrides,
  };
}

describe('the test send in French', () => {
  it.each(FIXTURE.email_test.map((c) => [c.code, c.message.slice(0, 60), c] as const))(
    'words %s as the server does (%s…)',
    (_code, _start, result) => {
      expect(testResultText(result)).toBe(result.message);
    },
  );

  it('words every missing field as the server does', () => {
    for (const { code, label } of FIXTURE.email_missing) {
      expect(missingTexts({ missing: ['?'], missing_codes: [code] })).toEqual([label]);
    }
  });
});

describe('the test send in English', () => {
  const find = (code: string, pick: (c: Fixture['email_test'][number]) => boolean = () => true) =>
    FIXTURE.email_test.find((c) => c.code === code && pick(c))!;

  it('words the outcome, keeping the server’s own words', () => {
    setLocale('en');
    expect(testResultText(find('sent', (c) => c.params.provider === 'smtp'))).toBe(
      'Test e-mail sent to admin@lycee.pf through the SMTP server smtp.x.fr:587.',
    );
    expect(testResultText(find('sent', (c) => c.params.provider === 'mailgun'))).toBe(
      'Test e-mail sent to admin@lycee.pf through Mailgun (domain mg.x.fr).',
    );
    expect(testResultText(find('incomplete'))).toBe(
      'Incomplete settings: missing the SMTP server, the sender address.',
    );
    expect(testResultText(find('smtp_auth_failed'))).toBe(
      'Credentials refused by the SMTP server — check the user name and password (answer: 535 5.7.8 bad credentials ••••)',
    );
    expect(testResultText(find('smtp_auth_required', (c) => c.params.has_user === true))).toMatch(
      /the configured account was not enough/,
    );
    expect(testResultText(find('smtp_recipients_refused'))).toBe(
      'Recipient refused by the SMTP server (a@x.fr: 550 no such user; b@x.fr: 551 gone)',
    );
    expect(testResultText(find('mailgun_status', (c) => c.params.body !== ''))).toBe(
      'Mailgun answered 500: Internal failure',
    );
    expect(testResultText(find('mailgun_status', (c) => c.params.body === ''))).toBe(
      'Mailgun answered 502',
    );
    for (const c of FIXTURE.email_test) {
      expect(testResultText(c), c.code).not.toMatch(/[éèàùç«»]|serveur|Le |Impossible/);
    }
  });

  it('shows the server’s sentence for what it does not know', () => {
    setLocale('en');
    // An older server: no code.
    expect(testResultText({ ok: false, message: 'Échec ancien' })).toBe('Échec ancien');
    // A newer one: an unknown code, or an unknown missing field.
    expect(testResultText({ ok: false, message: 'Nouveau', code: 'later', params: {} })).toBe(
      'Nouveau',
    );
    expect(
      testResultText({
        ok: false,
        message: 'Configuration incomplète : il manque autre chose.',
        code: 'incomplete',
        params: { missing: ['later'] },
      }),
    ).toBe('Configuration incomplète : il manque autre chose.');
  });
});

describe('the e-mail card in English', () => {
  it('says whether mail leaves, from the codes', () => {
    setLocale('en');
    expect(emailStatus(settings()).text).toBe(
      'No e-mail goes out: missing the Mailgun domain, the Mailgun API key.',
    );
    expect(emailStatus(settings({ configured: true, effective_provider: 'smtp' })).text).toBe(
      'E-mails go out through an SMTP server.',
    );
    expect(emailStatus(settings({ missing: [], missing_codes: [] })).text).toBe(
      'No e-mail goes out.',
    );
    // An older server: its French list, inside the English sentence.
    const older = settings();
    delete older.missing_codes;
    expect(emailStatus(older).text).toBe(
      'No e-mail goes out: missing le domaine Mailgun, la clé API Mailgun.',
    );
  });

  it('words the form’s refusals, the secrets and the security modes', () => {
    setLocale('en');
    const form = {
      provider: 'smtp',
      fromEmail: 'nope',
      smtpPort: '',
      smtpTimeout: '',
    } as EmailForm;
    expect(emailFormError(form)).toBe('The sender address is not an e-mail address.');
    expect(emailFormError({ ...form, fromEmail: '', smtpHost: '', smtpPort: 0 })).toBe(
      'The port is a whole number between 1 and 65535.',
    );
    expect(testRecipientError('moi')).toBe('This is not an e-mail address.');
    expect(secretState(false, true, true)).toEqual({ label: 'to type again', color: 'warning' });
    expect(secretState(true, false, false).label).toBe('saved');
    expect(secretHint('stored', false)).toBe('Leave empty to keep the saved value.');
    expect(secretHint('stored', true)).toBe(
      'Will be deleted on save: the server’s value will apply.',
    );
    expect(SECURITY_OPTIONS.map((o) => o.label)).toEqual([
      'STARTTLS (port 587)',
      'Implicit TLS (port 465)',
      'None (internal relay, port 25)',
    ]);
    expect(providerLabel('smtp')).toBe('SMTP server');
  });

  it('follows the language of the moment', () => {
    expect(SECURITY_OPTIONS[1]!.label).toBe('TLS implicite (port 465)');
    setLocale('en');
    expect(SECURITY_OPTIONS[1]!.label).toBe('Implicit TLS (port 465)');
  });
});
