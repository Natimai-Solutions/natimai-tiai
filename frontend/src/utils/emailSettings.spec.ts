import { describe, expect, it } from 'vitest';
import type { EmailSettings } from 'src/services/settings';
import {
  emailFormError,
  emailFormFrom,
  emailPayload,
  emailStatus,
  SECURITY_OPTIONS,
  secretState,
  testRecipientError,
} from './emailSettings';

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
    env: {
      provider: 'mailgun',
      from_email: 'tiai@env.fr',
      from_name: 'Tia’i',
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

describe('emailFormFrom', () => {
  it('shows stored text, and the choice in force where nothing is stored', () => {
    const form = emailFormFrom(settings());
    expect(form.provider).toBe('mailgun');
    expect(form.smtpSecurity).toBe('starttls');
    expect(form.smtpVerifyTls).toBe(true);
    expect(form.smtpHost).toBe('');
    expect(form.smtpPort).toBe('');
  });

  it('never fills a secret box, whatever is stored', () => {
    const form = emailFormFrom(
      settings({
        provider: 'smtp',
        smtp_host: 'smtp.x.fr',
        smtp_port: 465,
        smtp_password_set: true,
      }),
    );
    expect(form).toMatchObject({ provider: 'smtp', smtpHost: 'smtp.x.fr', smtpPort: 465 });
    expect(form.smtpPassword).toBe('');
    expect(form.clearSmtpPassword).toBe(false);
  });
});

describe('emailPayload', () => {
  it('sends empty boxes and the environment’s own choices as null', () => {
    const s = settings();
    expect(emailPayload(emailFormFrom(s), s)).toEqual({
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
    });
  });

  it('sends typed values, trimmed, and choices that differ from the environment', () => {
    const s = settings();
    const form = {
      ...emailFormFrom(s),
      provider: 'smtp' as const,
      smtpHost: '  smtp.x.fr ',
      smtpPort: '465',
      smtpSecurity: 'tls' as const,
      smtpVerifyTls: false,
      smtpTimeout: 30,
      fromEmail: 'tiai@x.fr',
    };
    expect(emailPayload(form, s)).toMatchObject({
      provider: 'smtp',
      smtp_host: 'smtp.x.fr',
      smtp_port: 465,
      smtp_security: 'tls',
      smtp_verify_tls: false,
      smtp_timeout_seconds: 30,
      from_email: 'tiai@x.fr',
    });
  });

  it('sends a secret only when typed or explicitly cleared', () => {
    const s = settings({ smtp_password_set: true, mailgun_api_key_set: true });
    const untouched = emailPayload(emailFormFrom(s), s);
    expect('smtp_password' in untouched).toBe(false);
    expect('mailgun_api_key' in untouched).toBe(false);

    const typed = emailPayload(
      { ...emailFormFrom(s), smtpPassword: 'n0uveau', clearMailgunApiKey: true },
      s,
    );
    expect(typed.smtp_password).toBe('n0uveau');
    expect(typed.mailgun_api_key).toBeNull();

    // Typing wins over a pending « effacer ».
    const both = emailPayload(
      { ...emailFormFrom(s), smtpPassword: 'x', clearSmtpPassword: true },
      s,
    );
    expect(both.smtp_password).toBe('x');
  });
});

describe('emailFormError', () => {
  const base = emailFormFrom(settings());

  it('accepts an empty form: everything follows the environment', () => {
    expect(emailFormError(base)).toBeNull();
    expect(emailFormError({ ...base, provider: 'smtp' })).toBeNull();
  });

  it('refuses what the server would refuse, provider by provider', () => {
    expect(emailFormError({ ...base, fromEmail: 'pas-une-adresse' })).toMatch(/expéditeur/);
    const smtp = { ...base, provider: 'smtp' as const };
    expect(emailFormError({ ...smtp, smtpHost: 'smtp://x.fr' })).toMatch(/serveur SMTP/);
    expect(emailFormError({ ...smtp, smtpPort: 0 })).toMatch(/port/);
    expect(emailFormError({ ...smtp, smtpPort: '70000' })).toMatch(/port/);
    expect(emailFormError({ ...smtp, smtpPort: 25.5 })).toMatch(/port/);
    expect(emailFormError({ ...smtp, smtpTimeout: 500 })).toMatch(/délai/);
    expect(emailFormError({ ...smtp, smtpHost: 'smtp.x.fr', smtpPort: 587 })).toBeNull();
    expect(emailFormError({ ...base, mailgunDomain: 'mg.x.fr/v3' })).toMatch(/domaine/);
    expect(emailFormError({ ...base, mailgunBaseUrl: 'api.mailgun.net' })).toMatch(/https/);
    expect(emailFormError({ ...base, mailgunBaseUrl: 'https://api.eu.mailgun.net/v3' })).toBeNull();
  });

  it('ignores the hidden provider’s fields', () => {
    expect(emailFormError({ ...base, smtpPort: 0 })).toBeNull();
    expect(emailFormError({ ...base, provider: 'smtp', mailgunDomain: 'a b' })).toBeNull();
  });
});

describe('testRecipientError', () => {
  it('accepts nothing (one’s own address) or an address', () => {
    expect(testRecipientError('')).toBeNull();
    expect(testRecipientError(' moi@lycee.local ')).toBeNull();
    expect(testRecipientError('moi')).toMatch(/adresse/);
  });
});

describe('secretState', () => {
  it('tells the four cases apart, unreadable first', () => {
    expect(secretState(false, true, true)).toEqual({ label: 'à ressaisir', color: 'warning' });
    expect(secretState(true, false, true).label).toBe('enregistré');
    expect(secretState(false, false, true).label).toBe('valeur du serveur');
    expect(secretState(false, false, false).label).toBe('non défini');
  });
});

describe('emailStatus', () => {
  it('says whether mail leaves, and what is missing when it does not', () => {
    expect(emailStatus(settings())).toEqual({
      ok: false,
      text: 'Aucun e-mail ne part : il manque le domaine Mailgun, la clé API Mailgun.',
    });
    expect(
      emailStatus(settings({ configured: true, effective_provider: 'smtp', missing: [] })),
    ).toEqual({
      ok: true,
      text: 'Les e-mails partent par un serveur SMTP.',
    });
    expect(emailStatus(settings({ configured: true, missing: [] })).text).toMatch(/Mailgun/);
    expect(emailStatus(settings({ missing: [] })).text).toBe('Aucun e-mail ne part.');
  });

  it('offers the three security modes', () => {
    expect(SECURITY_OPTIONS.map((o) => o.value)).toEqual(['starttls', 'tls', 'none']);
  });
});
