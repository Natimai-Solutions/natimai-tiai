import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  getMe: vi.fn(),
  totpSetup: vi.fn(),
  totpConfirm: vi.fn(),
  totpDisable: vi.fn(),
  regenerateBackupCodes: vi.fn(),
}));

import {
  getMe,
  regenerateBackupCodes,
  totpConfirm,
  totpDisable,
  totpSetup,
  type User,
} from 'src/services/auth';
import { setAccessToken } from 'src/services/session';
import { useAuthStore } from 'src/stores/auth';
import SecondFactorCard from './SecondFactorCard.vue';

function me(fields: Partial<User> = {}): User {
  return {
    id: 'u',
    email: 'a@b.c',
    full_name: null,
    email_preference: 'digest_daily',
    preferences: {},
    groups: [],
    permissions: [],
    second_factor_enabled: false,
    second_factor_required: false,
    backup_codes_left: 0,
    ...fields,
  };
}

async function mountCard(user: User) {
  const pinia = createPinia();
  setActivePinia(pinia);
  setAccessToken('t');
  useAuthStore().user = user;
  const w = mount(SecondFactorCard, { global: { plugins: [pinia] }, attachTo: document.body });
  await flushPromises();
  return w;
}

const CODES = Array.from({ length: 10 }, (_, i) => `AAAA${i}-BBBBB`);

describe('SecondFactorCard', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.mocked(totpSetup).mockReset();
    vi.mocked(totpConfirm).mockReset();
    vi.mocked(totpDisable).mockReset();
    vi.mocked(regenerateBackupCodes).mockReset();
    vi.mocked(getMe).mockReset();
  });

  it('enrols: QR code and key, a first code, then the backup codes once', async () => {
    vi.mocked(totpSetup).mockResolvedValue({
      secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
      otpauth_uri: 'otpauth://totp/x?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
    });
    vi.mocked(totpConfirm).mockResolvedValue(CODES);
    vi.mocked(getMe).mockResolvedValue(me({ second_factor_enabled: true, backup_codes_left: 10 }));
    const w = await mountCard(me());
    expect(w.find('[data-test="second-factor-state"]').text()).toBe('Désactivée');

    await w.find('[data-test="second-factor-enable"]').trigger('click');
    await flushPromises();
    // The password again first.
    w.findAllComponents(QInput)
      .find((i) => i.props('label') === 'Mot de passe actuel')!
      .vm.$emit('update:modelValue', 'secret');
    await flushPromises();
    await w.findAllComponents(QForm).at(-1)!.trigger('submit');
    await flushPromises();
    expect(totpSetup).toHaveBeenCalledWith('secret');
    expect(w.find('svg[role="img"] path').attributes('d')).toMatch(/^M\d/);
    expect(w.find('[data-test="second-factor-secret"]').text()).toBe(
      'JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP',
    );

    w.findAllComponents(QInput)
      .find((i) => i.props('label') === 'Code affiché par l’application')!
      .vm.$emit('update:modelValue', '123 456');
    await flushPromises();
    await w.find('[data-test="second-factor-setup"]').findComponent(QForm).trigger('submit');
    await flushPromises();
    expect(totpConfirm).toHaveBeenCalledWith('123456');
    expect(document.body.textContent).toContain('Vos codes de secours');
    expect(document.body.textContent).toContain('AAAA9-BBBBB');
    expect(w.find('[data-test="second-factor-state"]').text()).toBe('Activée');
    w.unmount();
  });

  it('does not offer to turn it off when a group requires it', async () => {
    const w = await mountCard(
      me({ second_factor_enabled: true, second_factor_required: true, backup_codes_left: 3 }),
    );
    expect(w.text()).toContain('Un de vos groupes l’impose.');
    expect(w.text()).toContain('Codes de secours restants : 3');
    const labels = w.findAll('button').map((b) => b.text());
    expect(labels).toContain('Nouveaux codes de secours');
    expect(labels).not.toContain('Désactiver');
    w.unmount();
  });

  it('turns it off with the password and a code', async () => {
    vi.mocked(totpDisable).mockResolvedValue();
    vi.mocked(getMe).mockResolvedValue(me());
    const w = await mountCard(me({ second_factor_enabled: true, backup_codes_left: 10 }));
    const off = w.findAll('button').find((b) => b.text() === 'Désactiver');
    await off!.trigger('click');
    await flushPromises();
    const inputs = w.findAllComponents(QInput);
    inputs
      .find((i) => i.props('label') === 'Mot de passe actuel')!
      .vm.$emit('update:modelValue', 'secret');
    inputs
      .find((i) => i.props('label') === 'Code de l’application ou code de secours')!
      .vm.$emit('update:modelValue', ' ABCDE-FGHJK ');
    await flushPromises();
    await w.findAllComponents(QForm).at(-1)!.trigger('submit');
    await flushPromises();
    expect(totpDisable).toHaveBeenCalledWith('secret', 'ABCDE-FGHJK');
    expect(w.find('[data-test="second-factor-state"]').text()).toBe('Désactivée');
    w.unmount();
  });
});
