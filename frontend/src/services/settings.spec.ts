import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { api } from 'boot/axios';
import { getSettings, sendTestEmail, updateSettings } from './settings';

describe('settings service', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.patch).mockReset();
  });

  it('reads and patches the settings', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { room_source: 'manual' } });
    vi.mocked(api.patch).mockResolvedValue({ data: { room_source: 'manual' } });

    expect(await getSettings()).toEqual({ room_source: 'manual' });
    expect(api.get).toHaveBeenCalledWith('/settings');

    await updateSettings({ email: { smtp_host: 'smtp.x.fr', smtp_password: null } });
    expect(api.patch).toHaveBeenCalledWith('/settings', {
      email: { smtp_host: 'smtp.x.fr', smtp_password: null },
    });
  });

  it('sends a test mail and hands back the outcome, failure included', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { ok: false, message: 'Identifiants refusés par le serveur SMTP' },
    });

    const result = await sendTestEmail({ to: 'moi@x.fr', email: { smtp_port: 2525 } });

    expect(api.post).toHaveBeenCalledWith('/settings/email/test', {
      to: 'moi@x.fr',
      email: { smtp_port: 2525 },
    });
    expect(result).toEqual({ ok: false, message: 'Identifiants refusés par le serveur SMTP' });
  });
});
