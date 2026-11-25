import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput, QToggle } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/utils/liveDialog', () => ({
  liveDialog: () => ({ onOk: (ok: () => void) => ok() }),
}));

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  listApiTokens: vi.fn(),
  createApiToken: vi.fn(),
  revokeApiToken: vi.fn(),
}));

import {
  createApiToken,
  listApiTokens,
  revokeApiToken,
  type ApiToken,
  type User,
} from 'src/services/auth';
import { nextTick } from 'vue';
import { useAuthStore } from 'src/stores/auth';
import ApiTokensCard from './ApiTokensCard.vue';

const later = new Date(Date.now() + 86_400_000 * 30).toISOString();

function token(fields: Partial<ApiToken> = {}): ApiToken {
  return {
    id: 't1',
    name: 'Export',
    prefix: 'tiai_pat_abcd',
    can_write: false,
    created_at: '2026-11-01T10:00:00Z',
    expires_at: later,
    last_used_at: null,
    last_used_ip: null,
    revoked_at: null,
    ...fields,
  };
}

async function mountCard(permissions: string[], user: Partial<User> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().$patch({ user: { permissions, ...user } as never });
  const w = mount(ApiTokensCard, { global: { plugins: [pinia] }, attachTo: document.body });
  await flushPromises();
  return w;
}

describe('ApiTokensCard', () => {
  beforeEach(() => {
    vi.mocked(listApiTokens).mockReset().mockResolvedValue([token()]);
    vi.mocked(createApiToken).mockReset();
  });

  it('lists the tokens without their value', async () => {
    const w = await mountCard(['api_token:write']);
    expect(w.text()).toContain('Export');
    expect(w.text()).toContain('tiai_pat_abcd…');
    expect(w.text()).toContain('Lecture seule');
    expect(w.text()).toContain('Jamais utilisé');
    expect(w.find('[data-test="token-revoke"]').exists()).toBe(true);
  });

  it('shows the new token once, then forgets it', async () => {
    vi.mocked(createApiToken).mockResolvedValue({
      ...token({ id: 't2', can_write: true }),
      token: 'tiai_pat_secretvalue',
    });
    const w = await mountCard(['api_token:write']);
    await w.find('[data-test="token-add"]').trigger('click');
    await flushPromises();
    w.findAllComponents(QInput)
      .find((i) => i.props('label') === 'Nom')!
      .vm.$emit('update:modelValue', ' Sauvegarde ');
    w.findAllComponents(QToggle)
      .find((i) => i.props('label') === 'Autoriser l’écriture')!
      .vm.$emit('update:modelValue', true);
    w.findAllComponents(QInput)
      .find((i) => i.props('label') === 'Mot de passe actuel')!
      .vm.$emit('update:modelValue', 'secret');
    await flushPromises();
    await w.findComponent(QForm).trigger('submit');
    await flushPromises();
    expect(createApiToken).toHaveBeenCalledWith({
      name: 'Sauvegarde',
      can_write: true,
      days: 90,
      current_password: 'secret',
    });
    expect(document.body.textContent).toContain('tiai_pat_secretvalue');
    w.unmount();
  });

  it('is absent without the right and without tokens, or for an account still enrolling', async () => {
    vi.mocked(listApiTokens).mockResolvedValue([]);
    let w = await mountCard(['machine:read']);
    expect(w.find('[data-test="api-tokens-card"]').exists()).toBe(false);
    vi.mocked(listApiTokens).mockClear();
    w = await mountCard(['api_token:write'], { enrolment_only: true });
    expect(w.find('[data-test="api-tokens-card"]').exists()).toBe(false);
    expect(listApiTokens).not.toHaveBeenCalled();
  });

  it('keeps the tokens of an account that lost the right, to revoke them', async () => {
    const w = await mountCard(['machine:read']);
    expect(w.find('[data-test="api-tokens-card"]').exists()).toBe(true);
    expect(w.find('[data-test="token-add"]').exists()).toBe(false);
    expect(w.find('[data-test="token-revoke"]').exists()).toBe(true);
  });

  it('marks revoked and expired tokens without a revoke button', async () => {
    vi.mocked(listApiTokens).mockResolvedValue([
      token({ revoked_at: '2026-11-02T10:00:00Z' }),
      token({ id: 't3', expires_at: '2020-01-01T00:00:00Z' }),
    ]);
    const w = await mountCard(['api_token:write']);
    expect(w.text()).toContain('Révoqué');
    expect(w.text()).toContain('Expiré');
    expect(w.find('[data-test="token-revoke"]').exists()).toBe(false);
  });

  it('asks for a code too with a second factor, and nothing for the directory', async () => {
    vi.mocked(createApiToken).mockResolvedValue({ ...token({ id: 't2' }), token: 'tiai_pat_x' });
    let w = await mountCard(['api_token:write'], { second_factor_enabled: true });
    await w.find('[data-test="token-add"]').trigger('click');
    await flushPromises();
    const input = (label: string) =>
      w.findAllComponents(QInput).find((i) => i.props('label') === label)!;
    input('Nom').vm.$emit('update:modelValue', 'Export');
    input('Mot de passe actuel').vm.$emit('update:modelValue', 'secret');
    input('Code de double authentification').vm.$emit('update:modelValue', ' 123456 ');
    await flushPromises();
    await w.findComponent(QForm).trigger('submit');
    await flushPromises();
    expect(createApiToken).toHaveBeenLastCalledWith({
      name: 'Export',
      can_write: false,
      days: 90,
      current_password: 'secret',
      code: '123456',
    });
    w.unmount();

    w = await mountCard(['api_token:write'], { auth_source: 'oidc' });
    await w.find('[data-test="token-add"]').trigger('click');
    await flushPromises();
    expect(document.body.querySelector('[data-test="token-password"]')).toBeNull();
    expect(document.body.textContent).toContain('moins de dix minutes');
    w.findAllComponents(QInput)
      .find((i) => i.props('label') === 'Nom')!
      .vm.$emit('update:modelValue', 'Annuaire');
    await flushPromises();
    await w.findComponent(QForm).trigger('submit');
    await flushPromises();
    expect(createApiToken).toHaveBeenLastCalledWith({
      name: 'Annuaire',
      can_write: false,
      days: 90,
    });
    w.unmount();
  });

  it('revokes a token after confirmation', async () => {
    vi.mocked(revokeApiToken).mockReset().mockResolvedValue();
    const w = await mountCard(['api_token:write']);
    vi.mocked(listApiTokens).mockResolvedValue([token({ revoked_at: '2026-11-25T10:00:00Z' })]);
    await w.find('[data-test="token-revoke"]').trigger('click');
    await flushPromises();
    expect(revokeApiToken).toHaveBeenCalledWith('t1');
    expect(w.text()).toContain('Révoqué');
  });

  it('loads once an enrolment-only session has set up its second factor', async () => {
    const w = await mountCard(['api_token:write'], { enrolment_only: true });
    expect(listApiTokens).not.toHaveBeenCalled();
    useAuthStore().$patch({ user: { enrolment_only: false } as never });
    await nextTick();
    await flushPromises();
    expect(listApiTokens).toHaveBeenCalled();
    expect(w.find('[data-test="api-tokens-card"]').exists()).toBe(true);
  });
});
