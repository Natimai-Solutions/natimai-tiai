import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { RouterView, createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/settings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/settings')>()),
  getSettings: vi.fn(),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  listAssignableOwners: vi.fn(() => Promise.resolve([])),
}));

import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { listAssignableOwners } from 'src/services/maintenance';
import { getSettings, type ConsoleSettings } from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';
import SettingsPage from './SettingsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

function consoleSettings(): ConsoleSettings {
  const value: ConsoleSettings = {
    maintenance_default_cycle_days: 90,
    maintenance_default_owner: null,
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
    env_maintenance_reminder_weekday: 0,
    room_source: 'manual',
    email: {
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
      missing: [],
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
    },
    environment: [],
    updated_at: null,
  };
  return value;
}

// Rendered by a router-view, as in the app: the guard on leaving the page is
// only registered for a component the router itself rendered.
const App = defineComponent({ render: () => h(RouterView) });

async function mountPage(permissions: string[]) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'me', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/settings', name: 'settings', component: SettingsPage },
      { path: '/', name: 'dashboard', component: Stub },
    ],
  });
  await router.push('/settings');
  const app = mount(App, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return { wrapper: app.findComponent(SettingsPage), router, app };
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.mocked(getSettings).mockReset();
    vi.mocked(listAssignableOwners).mockClear();
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  // Item 2.
  it('says the settings could not be read, with « Réessayer »', async () => {
    vi.mocked(getSettings).mockRejectedValueOnce({ response: { status: 500, data: {} } });
    const { wrapper, app } = await mountPage(['settings:read']);
    expect(wrapper.findComponent(LoadErrorBanner).exists()).toBe(true);

    vi.mocked(getSettings).mockResolvedValueOnce(consoleSettings());
    wrapper.findComponent(LoadErrorBanner).vm.$emit('retry');
    await flushPromises();
    expect(wrapper.findComponent(LoadErrorBanner).exists()).toBe(false);
    app.unmount();
  });

  // Item 4: a read-only account does not ask for the owners it cannot set.
  it('does not ask a read-only account for the assignable owners', async () => {
    vi.mocked(getSettings).mockResolvedValue(consoleSettings());
    const { app } = await mountPage(['settings:read']);
    expect(listAssignableOwners).not.toHaveBeenCalled();
    app.unmount();
  });

  // Item 12: leaving with a card changed and not saved asks first.
  it('asks before leaving with unsaved changes, and stays when told to', async () => {
    vi.mocked(getSettings).mockResolvedValue(consoleSettings());
    const { wrapper, router, app } = await mountPage(['settings:read', 'settings:write']);
    (wrapper.vm as unknown as { usageForm: { lowHours: number } }).usageForm.lowHours = 12;
    await flushPromises();

    const leaving = router.push('/');
    await flushPromises();
    expect(document.body.textContent).toContain('Modifications non enregistrées');
    [...document.querySelectorAll<HTMLElement>('.q-dialog-plugin button')]
      .find((b) => b.textContent?.includes('Rester sur la page'))!
      .click();
    await leaving;
    expect(router.currentRoute.value.name).toBe('settings');
    app.unmount();
  });

  it('leaves without asking when nothing was changed', async () => {
    vi.mocked(getSettings).mockResolvedValue(consoleSettings());
    const { router, app } = await mountPage(['settings:read', 'settings:write']);
    await router.push('/');
    expect(router.currentRoute.value.name).toBe('dashboard');
    app.unmount();
  });
});
