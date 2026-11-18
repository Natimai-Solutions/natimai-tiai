import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { RouterView, createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/settings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/settings')>()),
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}));
vi.mock('src/services/stats', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/stats')>()),
  getOverview: vi.fn(() => Promise.reject(new Error('not asked in this spec'))),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  listAssignableOwners: vi.fn(() => Promise.resolve([])),
}));

import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { listAssignableOwners } from 'src/services/maintenance';
import { QInput } from 'quasar';
import { resetFleetThresholds, useFleetThresholds } from 'src/composables/useFleetThresholds';
import { getSettings, updateSettings, type ConsoleSettings } from 'src/services/settings';
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

  type Page = Awaited<ReturnType<typeof mountPage>>;
  const field = (page: Page, label: string) =>
    page.wrapper.findAllComponents(QInput).find((i) => i.props('label') === label)!;
  /** « Enregistrer » of the card whose title is `title`. */
  async function saveCard(page: Page, title: string) {
    const card = page.wrapper.findAll('.q-card').find((c) => c.text().startsWith(title))!;
    await card
      .findAll('button')
      .find((b) => b.text() === 'Enregistrer')!
      .trigger('click');
    await flushPromises();
  }
  /** Try to leave; true when the page asked first (and the reader stays). */
  async function asksBeforeLeaving(page: Page): Promise<string | null> {
    const leaving = page.router.push('/');
    await flushPromises();
    const dialog = document.querySelector<HTMLElement>('.q-dialog-plugin');
    if (!dialog) {
      await leaving;
      return null;
    }
    const text = dialog.textContent ?? '';
    [...dialog.querySelectorAll<HTMLElement>('button')]
      .find((b) => b.textContent?.includes('Rester sur la page'))!
      .click();
    await leaving;
    return text;
  }
  /** What the browser is told on a reload or a closed tab. */
  function blocksUnload(): boolean {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  }

  // Review finding 3: the maintenance card is a card like the four others.
  describe('the maintenance card and the unsaved-changes guard', () => {
    beforeEach(() => {
      vi.mocked(getSettings).mockResolvedValue(consoleSettings());
      vi.mocked(updateSettings).mockReset();
    });

    it('asks before leaving with its cycle changed, and names the card', async () => {
      const page = await mountPage(['settings:read', 'settings:write']);
      expect(blocksUnload()).toBe(false);
      field(page, 'Cycle par défaut').vm.$emit('update:modelValue', 123);
      await flushPromises();

      expect(blocksUnload()).toBe(true);
      expect(await asksBeforeLeaving(page)).toContain('« Maintenance »');
      expect(page.router.currentRoute.value.name).toBe('settings');
      page.app.unmount();
    });

    it('asks for the « à échéance » window and for the default owner too', async () => {
      const page = await mountPage(['settings:read', 'settings:write']);
      field(page, 'Fenêtre « à échéance »').vm.$emit('update:modelValue', 20);
      await flushPromises();
      expect(await asksBeforeLeaving(page)).toContain('« Maintenance »');
      field(page, 'Fenêtre « à échéance »').vm.$emit('update:modelValue', 14);
      (page.wrapper.vm as unknown as { form: { ownerId: string | null } }).form.ownerId = 'u-1';
      await flushPromises();
      expect(await asksBeforeLeaving(page)).toContain('« Maintenance »');
      page.app.unmount();
    });

    it('is silent once the value is put back as it was', async () => {
      const page = await mountPage(['settings:read', 'settings:write']);
      field(page, 'Cycle par défaut').vm.$emit('update:modelValue', 123);
      await flushPromises();
      field(page, 'Cycle par défaut').vm.$emit('update:modelValue', 90);
      await flushPromises();
      expect(blocksUnload()).toBe(false);
      expect(await asksBeforeLeaving(page)).toBeNull();
      page.app.unmount();
    });

    it('is silent once the card is saved', async () => {
      vi.mocked(updateSettings).mockResolvedValue({
        ...consoleSettings(),
        maintenance_default_cycle_days: 123,
      });
      const page = await mountPage(['settings:read', 'settings:write']);
      field(page, 'Cycle par défaut').vm.$emit('update:modelValue', 123);
      await flushPromises();
      await saveCard(page, 'Maintenance');
      expect(updateSettings).toHaveBeenCalledTimes(1);
      expect(blocksUnload()).toBe(false);
      expect(await asksBeforeLeaving(page)).toBeNull();
      page.app.unmount();
    });

    it('still asks when the save was refused', async () => {
      vi.mocked(updateSettings).mockRejectedValue({ response: { status: 500, data: {} } });
      const page = await mountPage(['settings:read', 'settings:write']);
      field(page, 'Cycle par défaut').vm.$emit('update:modelValue', 123);
      await flushPromises();
      await saveCard(page, 'Maintenance');
      expect(await asksBeforeLeaving(page)).toContain('« Maintenance »');
      page.app.unmount();
    });

    it('never asks a read-only account', async () => {
      const page = await mountPage(['settings:read']);
      (page.wrapper.vm as unknown as { form: { cycle: number } }).form.cycle = 123;
      await flushPromises();
      expect(blocksUnload()).toBe(false);
      expect(await asksBeforeLeaving(page)).toBeNull();
      page.app.unmount();
    });
  });

  // Surviving mutation: nothing told a card saved from a card still to save.
  it('is silent after the usage card was saved', async () => {
    vi.mocked(getSettings).mockResolvedValue(consoleSettings());
    vi.mocked(updateSettings).mockReset();
    vi.mocked(updateSettings).mockResolvedValue({ ...consoleSettings(), usage_low_hours: 12 });
    const page = await mountPage(['settings:read', 'settings:write']);
    field(page, 'Poste peu utilisé en dessous de').vm.$emit('update:modelValue', 12);
    await flushPromises();
    expect(blocksUnload()).toBe(true);

    await saveCard(page, 'Utilisation des postes');
    expect(updateSettings).toHaveBeenCalledWith(expect.objectContaining({ usage_low_hours: 12 }));
    expect(blocksUnload()).toBe(false);
    expect(await asksBeforeLeaving(page)).toBeNull();
    page.app.unmount();
  });

  // Surviving mutation: the disk threshold saved here is the one the list and
  // the fiche colour their disks by, without waiting for their next read.
  it('hands the disk threshold to the list and the fiche, at load and on save', async () => {
    resetFleetThresholds();
    vi.mocked(getSettings).mockResolvedValue({ ...consoleSettings(), low_disk_free_percent: 15 });
    vi.mocked(updateSettings).mockReset();
    vi.mocked(updateSettings).mockResolvedValue({
      ...consoleSettings(),
      low_disk_free_percent: 30,
    });
    const page = await mountPage(['settings:read', 'settings:write']);
    const { lowDiskPercent } = useFleetThresholds();
    expect(lowDiskPercent.value).toBe(15);

    field(page, 'Disque presque plein en dessous de').vm.$emit('update:modelValue', 30);
    await flushPromises();
    await saveCard(page, 'Supervision du parc');
    expect(updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ low_disk_free_percent: 30 }),
    );
    expect(lowDiskPercent.value).toBe(30);
    resetFleetThresholds();
    page.app.unmount();
  });
});
