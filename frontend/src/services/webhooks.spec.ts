import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { api } from 'boot/axios';
import { createApiToken, listApiTokens, revokeApiToken } from './auth';
import {
  createWebhook,
  deleteWebhook,
  listWebhookDeliveries,
  listWebhooks,
  renewWebhookSecret,
  testWebhook,
  updateWebhook,
} from './webhooks';

const fields = {
  name: 'Canal',
  url: 'https://hooks.example/in',
  format: 'json' as const,
  language: 'fr' as const,
  events: ['check.created' as const],
  enabled: true,
};

describe('webhooks and API tokens services', () => {
  beforeEach(() => {
    for (const m of ['get', 'post', 'patch', 'delete'] as const) {
      vi.mocked(api[m])
        .mockReset()
        .mockResolvedValue({ data: { ok: true } });
    }
  });

  it('call the webhook routes', async () => {
    await listWebhooks();
    await createWebhook(fields);
    await updateWebhook('h1', { enabled: false });
    await deleteWebhook('h1');
    await renewWebhookSecret('h1');
    expect(await testWebhook('h1')).toEqual({ ok: true });
    await listWebhookDeliveries('h1');
    expect(vi.mocked(api.get).mock.calls.map((c) => c[0])).toEqual([
      '/webhooks',
      '/webhooks/h1/deliveries',
    ]);
    expect(vi.mocked(api.post).mock.calls).toEqual([
      ['/webhooks', fields],
      ['/webhooks/h1/secret'],
      ['/webhooks/h1/test'],
    ]);
    expect(api.patch).toHaveBeenCalledWith('/webhooks/h1', { enabled: false });
    expect(api.delete).toHaveBeenCalledWith('/webhooks/h1');
  });

  it('call the token routes', async () => {
    await listApiTokens();
    await createApiToken({ name: 'Script', can_write: false, days: 30 });
    await revokeApiToken('t1');
    expect(api.get).toHaveBeenCalledWith('/auth/api-tokens');
    expect(api.post).toHaveBeenCalledWith('/auth/api-tokens', {
      name: 'Script',
      can_write: false,
      days: 30,
    });
    expect(api.delete).toHaveBeenCalledWith('/auth/api-tokens/t1');
  });
});
