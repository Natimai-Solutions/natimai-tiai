import { readFileSync } from 'node:fs';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { RouterView, createMemoryHistory, createRouter } from 'vue-router';
import { QSelect } from 'quasar';

vi.mock('src/services/settings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/settings')>()),
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  sendTestEmail: vi.fn(),
}));
vi.mock('src/services/stats', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/stats')>()),
  getOverview: vi.fn(() => Promise.reject(new Error('not asked in this spec'))),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  listAssignableOwners: vi.fn(() => Promise.resolve([{ id: 'u-1', name: 'Alice' }])),
}));

import { setLocale } from 'src/i18n';
import {
  getSettings,
  sendTestEmail,
  type ConsoleSettings,
  type EnvGroup,
} from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';
import SettingsPage from './SettingsPage.vue';

// The server's environment with its default settings, as it sends it
// (backend/tests/data/settings_texts_fr.json): French values and descriptions,
// with the codes and raw values the console words them from.
const DEFAULT_ENVIRONMENT = (
  JSON.parse(
    readFileSync(`${process.cwd()}/../backend/tests/data/settings_texts_fr.json`, 'utf-8'),
  ) as { environment: { name: string; groups: EnvGroup[] }[] }
).environment.find((s) => s.name === 'defaults')!.groups;

function consoleSettings(): ConsoleSettings {
  return {
    maintenance_default_cycle_days: 90,
    maintenance_default_owner: null,
    maintenance_default_owner_unavailable: { id: 'u-gone', name: 'Marie' },
    maintenance_due_soon_days: 14,
    env_default_cycle_days: 90,
    env_due_soon_days: 14,
    usage_window_days: 7,
    usage_low_hours: 10,
    usage_high_hours: 30,
    env_usage_window_days: 7,
    env_usage_low_hours: 10,
    env_usage_high_hours: 30,
    signature_max_age_days: 3,
    inactive_after_days: 30,
    low_disk_free_percent: 10,
    hardware_aging_years: 5,
    agent_expected_version: null,
    command_default_ttl_minutes: 60,
    env_signature_max_age_days: 3,
    env_inactive_after_days: 30,
    env_low_disk_free_percent: 10,
    env_hardware_aging_years: 5,
    env_agent_expected_version: null,
    env_command_default_ttl_minutes: 60,
    digest_hour_utc: 18,
    maintenance_reminder_weekday: 0,
    env_digest_hour_utc: 18,
    env_maintenance_reminder_weekday: 4,
    room_source: 'manual',
    email: {
      provider: 'smtp',
      from_email: null,
      from_name: null,
      smtp_host: null,
      smtp_port: null,
      smtp_security: null,
      smtp_user: 'relay@school.example',
      smtp_verify_tls: null,
      smtp_timeout_seconds: null,
      mailgun_domain: null,
      mailgun_base_url: null,
      smtp_password_set: false,
      smtp_password_unreadable: true,
      mailgun_api_key_set: false,
      mailgun_api_key_unreadable: false,
      effective_provider: 'smtp',
      configured: false,
      missing: ['le serveur SMTP', "l'adresse d'expéditeur"],
      missing_codes: ['smtp_host', 'from_email'],
      env: {
        provider: 'mailgun',
        from_email: null,
        from_name: 'Tiai',
        smtp_host: null,
        smtp_port: 587,
        smtp_security: 'tls',
        smtp_user_set: true,
        smtp_password_set: false,
        smtp_verify_tls: false,
        smtp_timeout_seconds: 10,
        mailgun_domain: null,
        mailgun_api_key_set: false,
        mailgun_base_url: 'https://api.mailgun.net/v3',
        configured: false,
      },
    },
    environment: DEFAULT_ENVIRONMENT,
    updated_at: null,
  };
}

const App = defineComponent({ render: () => h(RouterView) });
const Stub = defineComponent({ render: () => h('div') });

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'me@school.example',
    permissions: ['settings:read', 'settings:write'],
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/settings', component: SettingsPage },
      { path: '/', component: Stub },
    ],
  });
  await router.push('/settings');
  const app = mount(App, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return { app, router, page: app.findComponent(SettingsPage) };
}

/** The labels of the select whose label is `label`. */
function optionLabels(app: Awaited<ReturnType<typeof mountPage>>['app'], label: string) {
  const select = app.findAllComponents(QSelect).find((s) => s.props('label') === label)!;
  return (select.props('options') as { label: string }[]).map((o) => o.label);
}

describe('SettingsPage in English', () => {
  beforeEach(() => {
    vi.mocked(getSettings).mockResolvedValue(consoleSettings());
  });
  afterEach(() => {
    setLocale('fr');
    document.body.innerHTML = '';
  });

  it('reads in English, the server’s environment included', async () => {
    setLocale('en');
    const { app, page } = await mountPage();
    (page.vm as unknown as { testResult: unknown }).testResult = {
      ok: true,
      message: 'E-mail de test envoyé à me@school.example par le serveur SMTP smtp.x:25.',
      code: 'sent',
      params: { to: 'me@school.example', provider: 'smtp', host: 'smtp.x', port: 25 },
    };
    await flushPromises();
    const text = app.text();

    expect(text).toContain('Settings');
    expect(text).toContain('0 = no maintenance by default · environment variable: 90 days');
    expect(text).toContain('Fleet monitoring');
    expect(text).toContain('environment variable: Friday');
    expect(text).toContain('No e-mail goes out: missing the SMTP server, the sender address.');
    expect(text).toContain('server value: Implicit TLS (port 465)');
    expect(text).toContain('to type again');
    expect(text).toContain(
      'Saved under another SECRET_KEY of the server, unreadable: type it again.',
    );
    expect(text).toContain('server value: no');
    expect(text).toContain(
      'Test e-mail sent to me@school.example through the SMTP server smtp.x:25.',
    );
    // The server's environment, worded by the console.
    expect(text).toContain('Server settings');
    expect(text).toContain('Computers and thresholds');
    expect(text).toContain('Waking computers (Wake-on-LAN)');
    expect(text).toContain('UDP port of the magic packet');
    expect(text).toContain('2147483648 (2 GiB)');
    expect(text).toContain('0 (Monday)');
    expect(text).toContain('manual (by hand, from the console)');
    expect(text).toContain(
      'mailgun (incomplete in the environment: no e-mail goes out without settings in the console)',
    );
    expect(text).toContain('— not set');
    // Nothing left in French.
    expect(text).not.toMatch(/[éèàùç«»]/);
    expect(text).not.toMatch(/\b(jours|heures|valeur|serveur|Enregistrer|oui|non)\b/);

    expect(optionLabels(app, 'Day of the maintenance reminder (UTC)')[0]).toBe('Monday');
    expect(optionLabels(app, 'Time of the daily digest (UTC)')[8]).toBe('8:00 UTC');
    expect(optionLabels(app, 'Security')).toEqual([
      'STARTTLS (port 587)',
      'Implicit TLS (port 465)',
      'None (internal relay, port 25)',
    ]);
    expect(optionLabels(app, 'Default owner')[0]).toBe('Deactivated account: Marie');
    expect(app.find('input[aria-label="Search the settings"]').exists()).toBe(true);
    app.unmount();
  });

  it('searches what it shows, in English', async () => {
    setLocale('en');
    const { app, page } = await mountPage();
    (page.vm as unknown as { envFilter: string }).envFilter = 'packet';
    await flushPromises();
    const rows = app.findAll('.env-table tr').map((r) => r.find('code').text());
    expect(rows).toEqual(['WOL_PORT', 'WOL_PACKET_COUNT']);
    (page.vm as unknown as { envFilter: string }).envFilter = 'zzz';
    await flushPromises();
    expect(app.text()).toContain('No setting matches.');
    app.unmount();
  });

  it('asks before leaving with unsaved changes, in English', async () => {
    setLocale('en');
    const { page, router, app } = await mountPage();
    (page.vm as unknown as { usageForm: { lowHours: number } }).usageForm.lowHours = 12;
    await flushPromises();
    const leaving = router.push('/');
    await flushPromises();
    const dialog = document.querySelector<HTMLElement>('.q-dialog-plugin')!;
    expect(dialog.textContent).toContain('Unsaved changes');
    expect(dialog.textContent).toContain('The changes to “Usage” have not been saved.');
    [...dialog.querySelectorAll<HTMLElement>('button')]
      .find((b) => b.textContent?.includes('Stay on the page'))!
      .click();
    await leaving;
    app.unmount();
  });

  it('switches language live', async () => {
    const { app } = await mountPage();
    expect(app.text()).toContain('Paramètres');
    expect(app.text()).toContain('Port UDP du paquet magique');
    expect(app.text()).toContain('2147483648 (2 Gio)');
    expect(optionLabels(app, 'Jour du rappel des maintenances (UTC)')[0]).toBe('Lundi');

    setLocale('en');
    await nextTick();
    expect(app.text()).toContain('Settings');
    expect(app.text()).toContain('UDP port of the magic packet');
    expect(app.text()).toContain('2147483648 (2 GiB)');
    expect(app.text()).not.toContain('Paramètres');
    expect(optionLabels(app, 'Day of the maintenance reminder (UTC)')[0]).toBe('Monday');
    app.unmount();
  });

  it('rewords a failed e-mail test after a live switch (gap2-3-3)', async () => {
    vi.mocked(sendTestEmail).mockRejectedValueOnce(new Error('network'));
    const { app } = await mountPage();
    const send = app.findAll('button').find((b) => b.text().includes('Envoyer un e-mail de test'))!;
    await send.trigger('click');
    await flushPromises();
    expect(sendTestEmail).toHaveBeenCalled();
    expect(app.text()).toContain('Envoi du test impossible');

    setLocale('en');
    await nextTick();
    expect(app.text()).toContain('Could not send the test');
    expect(app.text()).not.toContain('Envoi du test impossible');
    app.unmount();
  });
});
