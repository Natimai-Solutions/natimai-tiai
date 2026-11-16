import type { AxiosAdapter } from 'axios';
import { describe, expect, it, vi } from 'vitest';
import { onForbidden, setAccessToken } from 'src/services/session';
import boot, { api } from './axios';

/** Answer every request with `status`, as a server would. */
function serverAnswers(status: number): AxiosAdapter {
  return (config) =>
    Promise.reject(
      Object.assign(new Error(`HTTP ${status}`), {
        isAxiosError: true,
        config,
        response: { status, data: {}, headers: {}, config, statusText: '' },
      }),
    );
}

describe('boot/axios', () => {
  const push = vi.fn(() => Promise.resolve());
  const router = { currentRoute: { value: { name: 'machines', fullPath: '/machines?x=1' } }, push };
  (boot as unknown as (ctx: unknown) => void)({
    app: { config: { globalProperties: {} } },
    router,
  });

  // Item 7: the login page is told the session ended, and says so.
  it('sends the reader to the login page saying the session ended', async () => {
    setAccessToken('expired');
    api.defaults.adapter = serverAnswers(401);
    await expect(api.get('/machines')).rejects.toBeTruthy();
    expect(push).toHaveBeenCalledWith({
      name: 'login',
      query: { redirect: '/machines?x=1', ended: '1' },
    });
  });

  // Item 4: a 403 is how a change of rights is noticed during the session.
  it('tells the profile a 403 was answered', async () => {
    setAccessToken('token');
    const heard = vi.fn();
    const stop = onForbidden(heard);
    api.defaults.adapter = serverAnswers(403);
    await expect(api.get('/rooms')).rejects.toBeTruthy();
    expect(heard).toHaveBeenCalledTimes(1);
    stop();
  });
});
