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
import { QInput, QToggle } from 'quasar';
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
    alert_rules: ['disk_low', 'disk_unhealthy', 'inactive'],
    alert_enabled_rules: ['disk_low', 'disk_unhealthy', 'inactive'],
    alert_auto_check_rules: ['disk_low', 'inactive'],
    alert_reboot_pending_days: 7,
    alert_warranty_days: 30,
    alert_unencrypted_scope: 'laptops',
    alert_forbidden_software: [],
    console_timezone: 'Pacific/Tahiti',
    env_console_timezone: 'Pacific/Tahiti',
    forbidden_windows: [{ days: [0, 1, 2, 3, 4], start: '07:30', end: '12:00' }],
    reports_enabled: false,
    env_reports_enabled: false,
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

    // C10: the two-person approval card sits after the schedules' and counts
    // among the cards the page asks about.
    it('shows the approval card after the schedules, and asks for it too', async () => {
      vi.mocked(getSettings).mockResolvedValue({
        ...consoleSettings(),
        approval_enabled: false,
        approval_threshold: 40,
        approval_ttl_hours: 24,
        approval_eligible: 2,
      });
      const page = await mountPage(['settings:read', 'settings:write']);
      const titles = page.wrapper.findAll('.q-card').map((c) => c.text());
      const at = (title: string) => titles.findIndex((t) => t.startsWith(title));
      expect(at('Approbation à deux')).toBe(at('Planifications') + 1);
      field(page, 'Au-delà de (postes)').vm.$emit('update:modelValue', 60);
      await flushPromises();
      expect(await asksBeforeLeaving(page)).toContain('« Approbation à deux »');
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

  describe('the compliance card (C5)', () => {
    beforeEach(() => {
      vi.mocked(getSettings).mockResolvedValue({
        ...consoleSettings(),
        compliance_patch_grace_days: 14,
        env_compliance_patch_grace_days: 14,
        compliance_admins_allowed: ['GG-Techs'],
      });
      vi.mocked(updateSettings).mockReset();
    });

    it('saves the grace and the accepted administrators, trimmed', async () => {
      vi.mocked(updateSettings).mockResolvedValue(consoleSettings());
      const page = await mountPage(['settings:read', 'settings:write']);
      const vm = page.wrapper.vm as unknown as {
        complianceForm: { patchGraceDays: number | string; admins: string[] };
      };
      vm.complianceForm.patchGraceDays = '21';
      vm.complianceForm.admins = ['GG-Techs', ' LYCEE\\Tech ', ' '];
      await flushPromises();
      expect(blocksUnload()).toBe(true);
      await saveCard(page, 'Conformité des postes');
      expect(updateSettings).toHaveBeenCalledWith({
        compliance_patch_grace_days: 21,
        compliance_admins_allowed: ['GG-Techs', 'LYCEE\\Tech'],
      });
      page.app.unmount();
    });

    it('does not save a delay out of range', async () => {
      const page = await mountPage(['settings:read', 'settings:write']);
      field(
        page,
        'Délai avant qu’un poste en retard d’un correctif critique ou important soit non conforme (jours)',
      ).vm.$emit('update:modelValue', 400);
      await flushPromises();
      await saveCard(page, 'Conformité des postes');
      expect(updateSettings).not.toHaveBeenCalled();
      page.app.unmount();
    });
  });

  describe('the licences card (C6)', () => {
    beforeEach(() => {
      vi.mocked(getSettings).mockResolvedValue({
        ...consoleSettings(),
        license_expiry_days: 60,
        env_license_expiry_days: 60,
      });
      vi.mocked(updateSettings).mockReset();
    });

    it('saves the days before the end, and refuses them out of range', async () => {
      vi.mocked(updateSettings).mockResolvedValue({
        ...consoleSettings(),
        license_expiry_days: 90,
      });
      const page = await mountPage(['settings:read', 'settings:write']);
      field(page, 'Jours avant l’échéance').vm.$emit('update:modelValue', 0);
      await flushPromises();
      await saveCard(page, 'Licences logicielles');
      expect(updateSettings).not.toHaveBeenCalled();

      field(page, 'Jours avant l’échéance').vm.$emit('update:modelValue', '90');
      await flushPromises();
      expect(blocksUnload()).toBe(true);
      await saveCard(page, 'Licences logicielles');
      expect(updateSettings).toHaveBeenCalledWith({ license_expiry_days: 90 });
      page.app.unmount();
    });
  });

  describe('the alerts card', () => {
    beforeEach(() => {
      vi.mocked(getSettings).mockResolvedValue(consoleSettings());
      vi.mocked(updateSettings).mockReset();
    });

    function toggle(page: Page, label: string) {
      return page.wrapper.findAllComponents(QToggle).find((c) => c.props('label') === label)!;
    }

    it('is silent after a rule is turned off and on again', async () => {
      const page = await mountPage(['settings:read', 'settings:write']);
      const disk = toggle(page, 'Disque système presque plein');
      await disk.trigger('click');
      await flushPromises();
      expect(blocksUnload()).toBe(true);
      await disk.trigger('click');
      await flushPromises();
      // Back on, last in the list now: the same rules all the same.
      expect(blocksUnload()).toBe(false);
      expect(await asksBeforeLeaving(page)).toBeNull();
      page.app.unmount();
    });

    it('saves only the auto-checks of rules turned on, and the patterns that read', async () => {
      vi.mocked(updateSettings).mockResolvedValue(consoleSettings());
      const page = await mountPage(['settings:read', 'settings:write']);
      await toggle(page, 'Sans contact').trigger('click');
      const vm = page.wrapper.vm as unknown as {
        alertForm: { forbidden: string[]; warrantyDays: number | string };
      };
      vm.alertForm.forbidden = [' x ', ' uTorrent '];
      vm.alertForm.warrantyDays = '45';
      await flushPromises();
      await saveCard(page, 'Alertes');
      expect(updateSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          alert_enabled_rules: ['disk_low', 'disk_unhealthy'],
          alert_auto_check_rules: ['disk_low'],
          alert_forbidden_software: ['uTorrent'],
          alert_warranty_days: 45,
          alert_reboot_pending_days: 7,
        }),
      );
      page.app.unmount();
    });

    it('does not save a number of days out of range', async () => {
      const page = await mountPage(['settings:read', 'settings:write']);
      field(page, 'Fin de garantie signalée').vm.$emit('update:modelValue', 0);
      await flushPromises();
      await saveCard(page, 'Alertes');
      expect(updateSettings).not.toHaveBeenCalled();
      page.app.unmount();
    });
  });

  it('opens the report form as it is switched (C4)', async () => {
    vi.mocked(getSettings).mockResolvedValue(consoleSettings());
    vi.mocked(updateSettings).mockReset();
    vi.mocked(updateSettings).mockResolvedValue({ ...consoleSettings(), reports_enabled: true });
    const page = await mountPage(['settings:read', 'settings:write']);
    const toggle = page.wrapper
      .findAllComponents(QToggle)
      .find((c) => c.props('label') === 'Ouvrir le formulaire de signalement')!;
    expect(toggle.props('modelValue')).toBe(false);
    toggle.vm.$emit('update:modelValue', true);
    await flushPromises();
    expect(updateSettings).toHaveBeenCalledWith({ reports_enabled: true });
    expect(toggle.props('modelValue')).toBe(true);
    page.app.unmount();
  });

  describe('the schedules card', () => {
    beforeEach(() => {
      vi.mocked(getSettings).mockResolvedValue(consoleSettings());
      vi.mocked(updateSettings).mockReset();
    });

    it('saves the zone and the windows, days in order', async () => {
      vi.mocked(updateSettings).mockResolvedValue(consoleSettings());
      const page = await mountPage(['settings:read', 'settings:write']);
      const vm = page.wrapper.vm as unknown as {
        planningForm: {
          timezone: string;
          windows: { days: number[]; start: string; end: string }[];
        };
      };
      expect(vm.planningForm.windows).toEqual([
        { days: [0, 1, 2, 3, 4], start: '07:30', end: '12:00' },
      ]);
      vm.planningForm.timezone = ' Europe/Paris ';
      vm.planningForm.windows.push({ days: [5, 3], start: '13:00', end: '17:00' });
      await flushPromises();
      expect(blocksUnload()).toBe(true);
      await saveCard(page, 'Planifications');
      expect(updateSettings).toHaveBeenCalledWith({
        console_timezone: 'Europe/Paris',
        forbidden_windows: [
          { days: [0, 1, 2, 3, 4], start: '07:30', end: '12:00' },
          { days: [3, 5], start: '13:00', end: '17:00' },
        ],
      });
      page.app.unmount();
    });

    it('does not save a window that ends before it starts', async () => {
      const page = await mountPage(['settings:read', 'settings:write']);
      const vm = page.wrapper.vm as unknown as {
        planningForm: { windows: { days: number[]; start: string; end: string }[] };
      };
      vm.planningForm.windows[0]!.end = '07:00';
      await flushPromises();
      expect(document.body.textContent).toContain('Des jours, et une fin après le début');
      await saveCard(page, 'Planifications');
      expect(updateSettings).not.toHaveBeenCalled();
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
