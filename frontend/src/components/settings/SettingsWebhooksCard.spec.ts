import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/webhooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/webhooks')>()),
  listWebhooks: vi.fn(),
  createWebhook: vi.fn(),
  updateWebhook: vi.fn(),
  listWebhookDeliveries: vi.fn(),
  testWebhook: vi.fn(),
}));

import { createWebhook, listWebhooks, testWebhook, type Webhook } from 'src/services/webhooks';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import SettingsWebhooksCard from './SettingsWebhooksCard.vue';

function hook(fields: Partial<Webhook> = {}): Webhook {
  return {
    id: 'h1',
    name: 'Canal Teams',
    url: 'https://hooks.example/in',
    format: 'teams',
    language: 'fr',
    events: ['threat.detected', 'check.created'],
    enabled: true,
    created_by: 'u',
    created_at: '2026-11-01T10:00:00Z',
    updated_at: '2026-11-01T10:00:00Z',
    last_success_at: null,
    last_failure_at: null,
    last_error: null,
    consecutive_failures: 0,
    pending: 0,
    ...fields,
  };
}

async function mountCard(permissions: string[]) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().$patch({ user: { permissions } as never });
  const w = mount(SettingsWebhooksCard, { global: { plugins: [pinia] }, attachTo: document.body });
  await flushPromises();
  return w;
}

function refused(code: string, details?: Record<string, unknown>) {
  return Object.assign(new Error('x'), {
    response: { status: 422, data: { error: { code, details } } },
  });
}

describe('SettingsWebhooksCard', () => {
  beforeEach(() => {
    vi.mocked(listWebhooks).mockReset().mockResolvedValue([hook()]);
    vi.mocked(createWebhook).mockReset();
    vi.mocked(testWebhook).mockReset();
  });

  it('lists the webhooks with their events and last failure', async () => {
    vi.mocked(listWebhooks).mockResolvedValue([
      hook({
        last_failure_at: '2026-11-02T10:00:00Z',
        last_error: 'HTTP 500',
        consecutive_failures: 2,
      }),
    ]);
    const w = await mountCard(['webhook:read', 'webhook:write']);
    expect(w.text()).toContain('Canal Teams');
    expect(w.text()).toContain('Microsoft Teams');
    expect(w.text()).toContain('Menace détectée, Vérification demandée');
    expect(w.text()).toContain('HTTP 500');
    expect(w.find('[data-test="webhook-add"]').exists()).toBe(true);
  });

  it('read-only without the right to write, absent without the right to read', async () => {
    let w = await mountCard(['webhook:read']);
    expect(w.find('[data-test="webhook-add"]').exists()).toBe(false);
    w = await mountCard(['machine:read']);
    expect(w.find('[data-test="webhooks-card"]').exists()).toBe(false);
  });

  it('says why an account confined to some places sees none', async () => {
    vi.mocked(listWebhooks).mockRejectedValue(refused('auth.scope.restricted'));
    const w = await mountCard(['webhook:read', 'webhook:write']);
    expect(w.text()).toContain('réservés aux comptes sans limite de lieux');
    expect(w.find('[data-test="webhook-add"]').exists()).toBe(false);
  });

  it('creates one and shows its secret once', async () => {
    vi.mocked(listWebhooks).mockResolvedValue([]);
    vi.mocked(createWebhook).mockResolvedValue({ ...hook(), secret: 's3cr3t-value' });
    const w = await mountCard(['webhook:read', 'webhook:write']);
    await w.find('[data-test="webhook-add"]').trigger('click');
    await flushPromises();
    const input = (label: string) =>
      w.findAllComponents(QInput).find((i) => i.props('label') === label)!;
    input('Nom').vm.$emit('update:modelValue', 'Script');
    input('Adresse').vm.$emit('update:modelValue', ' https://hooks.example/in ');
    await flushPromises();
    await w.findComponent(QForm).trigger('submit');
    await flushPromises();
    expect(createWebhook).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Script',
        url: 'https://hooks.example/in',
        format: 'json',
        events: ['threat.detected'],
      }),
    );
    expect(document.body.textContent).toContain('s3cr3t-value');
    w.unmount();
  });

  it('words a refused destination', () => {
    expect(
      apiErrorMessage(
        refused('webhook.destination_refused', { reason: 'webhook.url.credentials' }),
      ),
    ).toContain('identifiant');
  });
});
