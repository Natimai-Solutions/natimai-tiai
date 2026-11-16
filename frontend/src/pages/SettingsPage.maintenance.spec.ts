import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/settings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/settings')>()),
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  listAssignableOwners: vi.fn(),
}));

import { listAssignableOwners } from 'src/services/maintenance';
import { getSettings, updateSettings, type ConsoleSettings } from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';
import SettingsPage from './SettingsPage.vue';

/** Enough of the page's settings for every card to render. */
function settings(over: Partial<ConsoleSettings> = {}): ConsoleSettings {
  const env = {
    provider: 'smtp',
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
    mailgun_base_url: 'https://api.eu.mailgun.net',
    configured: false,
  };
  return {
    maintenance_default_cycle_days: 90,
    maintenance_default_owner: null,
    maintenance_default_owner_unavailable: null,
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
      effective_provider: 'smtp',
      configured: false,
      missing: [],
      env,
    },
    environment: [],
    updated_at: null,
    ...over,
  } as ConsoleSettings;
}

async function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'me',
    email: 'a@b.c',
    permissions: ['settings:read', 'settings:write'],
  } as never;
  const wrapper = mount(SettingsPage, {
    shallow: true,
    global: { plugins: [pinia], renderStubDefaultSlot: true },
  });
  await flushPromises();
  return wrapper;
}

const ownerPicker = (wrapper: Awaited<ReturnType<typeof mountPage>>) =>
  wrapper
    .findAllComponents({ name: 'QSelect' })
    .find((s) => s.props('label') === 'Responsable par défaut')!;

async function saveMaintenanceCard(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  // The maintenance card's « Enregistrer » is the first of the page.
  await wrapper.find('[label="Enregistrer"]').trigger('click');
  await flushPromises();
}

describe('SettingsPage — the default owner deactivated since (item 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAssignableOwners).mockResolvedValue([{ id: 'u-1', name: 'Alice' }]);
    vi.mocked(updateSettings).mockImplementation(() => Promise.resolve(settings()));
  });

  it('names it instead of an empty field, and does not erase it on save', async () => {
    vi.mocked(getSettings).mockResolvedValue(
      settings({ maintenance_default_owner_unavailable: { id: 'u-gone', name: 'Marie' } }),
    );
    const wrapper = await mountPage();

    const picker = ownerPicker(wrapper);
    expect(picker.props('modelValue')).toBe('u-gone');
    expect(picker.props('options')).toEqual([
      { label: 'Compte désactivé : Marie', value: 'u-gone' },
      { label: 'Alice', value: 'u-1' },
    ]);

    await saveMaintenanceCard(wrapper);

    expect(updateSettings).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(updateSettings).mock.calls[0]![0];
    expect(payload).not.toHaveProperty('maintenance_default_owner_id');
    expect(payload.maintenance_default_cycle_days).toBe(90);
  });

  it('sends the owner when the operator picks another — or clears it', async () => {
    vi.mocked(getSettings).mockResolvedValue(
      settings({ maintenance_default_owner_unavailable: { id: 'u-gone', name: 'Marie' } }),
    );
    const wrapper = await mountPage();

    ownerPicker(wrapper).vm.$emit('update:modelValue', 'u-1');
    await saveMaintenanceCard(wrapper);
    expect(vi.mocked(updateSettings).mock.calls[0]![0].maintenance_default_owner_id).toBe('u-1');

    ownerPicker(wrapper).vm.$emit('update:modelValue', null);
    await saveMaintenanceCard(wrapper);
    expect(vi.mocked(updateSettings).mock.calls[1]![0]).toHaveProperty(
      'maintenance_default_owner_id',
      null,
    );
  });
});
