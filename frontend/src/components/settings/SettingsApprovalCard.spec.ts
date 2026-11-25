import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn, QInput, QToggle } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/settings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/settings')>()),
  updateSettings: vi.fn(),
}));

import { approvalsVersion } from 'src/composables/useApprovalsBadge';
import { updateSettings, type ConsoleSettings } from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';
import SettingsApprovalCard from './SettingsApprovalCard.vue';

function settings(fields: Partial<ConsoleSettings> = {}): ConsoleSettings {
  return {
    approval_enabled: false,
    approval_threshold: 40,
    approval_ttl_hours: 24,
    approval_eligible: 3,
    env_approval_enabled: false,
    env_approval_threshold: 40,
    env_approval_ttl_hours: 24,
    ...fields,
  } as ConsoleSettings;
}

async function mountCard(
  value: ConsoleSettings,
  permissions = ['settings:read', 'settings:write'],
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().$patch({ user: { permissions } as never });
  const w = mount(SettingsApprovalCard, {
    props: { settings: value },
    global: { plugins: [pinia] },
    attachTo: document.body,
  });
  await flushPromises();
  return w;
}

function refused(code: string, details?: Record<string, unknown>) {
  return Object.assign(new Error('x'), {
    response: { status: 422, data: { error: { code, details } } },
  });
}

describe('SettingsApprovalCard (C10)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.mocked(updateSettings).mockReset();
  });

  it('greys the switch with fewer than two accounts able to approve, and says why', async () => {
    const w = await mountCard(settings({ approval_eligible: 1 }));
    expect(w.findComponent(QToggle).props('disable')).toBe(true);
    expect(w.find('[data-test="approval-eligible"]').text()).toBe(
      '1 compte peut approuver (sans tenir compte des lieux).',
    );
    expect(w.find('[data-test="approval-not-enough"]').exists()).toBe(true);
  });

  it('leaves it free with two, and lets an approval on already be turned off', async () => {
    let w = await mountCard(settings({ approval_eligible: 2 }));
    expect(w.findComponent(QToggle).props('disable')).toBe(false);
    expect(w.find('[data-test="approval-eligible"]').text()).toContain(
      '2 comptes peuvent approuver',
    );
    w = await mountCard(settings({ approval_enabled: true, approval_eligible: 1 }));
    expect(w.findComponent(QToggle).props('disable')).toBe(false);
  });

  it('saves the three fields and tells the menu', async () => {
    vi.mocked(updateSettings).mockResolvedValue(
      settings({ approval_enabled: true, approval_threshold: 60 }),
    );
    const w = await mountCard(settings());
    w.findComponent(QToggle).vm.$emit('update:modelValue', true);
    w.findAllComponents(QInput)[0]!.vm.$emit('update:modelValue', 60);
    const before = approvalsVersion.value;
    await w.find('[data-test="approval-save"]').trigger('click');
    await flushPromises();
    expect(updateSettings).toHaveBeenCalledWith({
      approval_enabled: true,
      approval_threshold: 60,
      approval_ttl_hours: 24,
    });
    expect(w.emitted('saved')).toHaveLength(1);
    expect(approvalsVersion.value).toBe(before + 1);
  });

  it('shows the refusal under two approvers in the card', async () => {
    vi.mocked(updateSettings).mockRejectedValue(
      refused('approval.not_enough_approvers', { eligible: 1 }),
    );
    const w = await mountCard(settings({ approval_eligible: 2 }));
    w.findComponent(QToggle).vm.$emit('update:modelValue', true);
    await w.find('[data-test="approval-save"]').trigger('click');
    await flushPromises();
    expect(w.find('[data-test="approval-error"]').text()).toContain('deux comptes');
    expect(w.emitted('saved')).toBeUndefined();
  });

  it('refuses a threshold out of bounds before sending', async () => {
    const w = await mountCard(settings());
    w.findAllComponents(QInput)[0]!.vm.$emit('update:modelValue', 1);
    await flushPromises();
    expect(w.findAllComponents(QInput)[0]!.props('errorMessage')).toContain('2');
    const save = w
      .findAllComponents(QBtn)
      .find((b) => b.attributes('data-test') === 'approval-save')!;
    expect(save.props('disable')).toBe(true);
  });

  it('is read-only without settings:write', async () => {
    const w = await mountCard(settings(), ['settings:read']);
    expect(w.find('[data-test="approval-save"]').exists()).toBe(false);
    expect(w.findComponent(QToggle).props('disable')).toBe(true);
  });
});
