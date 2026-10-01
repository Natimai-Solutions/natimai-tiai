import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createUnauthorizedHandler,
  endSession,
  ensureSession,
  getAccessToken,
  onSessionEnd,
  setAccessToken,
  singleFlight,
  type ReplayableConfig,
} from './session';

afterEach(() => {
  setAccessToken(null);
});

/** A promise and the hands to settle it, to hold a refresh in flight. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function httpError(status: number, config: ReplayableConfig | undefined) {
  return { response: { status }, config };
}

describe('access token', () => {
  it('is held in memory and forgotten when the session ends', () => {
    setAccessToken('jwt-1');
    expect(getAccessToken()).toBe('jwt-1');
    endSession();
    expect(getAccessToken()).toBeNull();
  });

  it('tells the listeners when the session ends, until they unsubscribe', () => {
    const listener = vi.fn();
    const unsubscribe = onSessionEnd(listener);
    endSession();
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    endSession();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe('singleFlight', () => {
  it('shares one run between concurrent callers', async () => {
    const pending = deferred<string>();
    const task = vi.fn(() => pending.promise);
    const shared = singleFlight(task);

    const calls = [shared(), shared(), shared()];
    pending.resolve('jwt-2');

    expect(await Promise.all(calls)).toEqual(['jwt-2', 'jwt-2', 'jwt-2']);
    expect(task).toHaveBeenCalledTimes(1);
  });

  it('starts a new run once the previous one has settled, failed or not', async () => {
    const task = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error('expired'))
      .mockResolvedValueOnce('jwt-3');
    const shared = singleFlight(task);

    await expect(shared()).rejects.toThrow('expired');
    await expect(shared()).resolves.toBe('jwt-3');
    expect(task).toHaveBeenCalledTimes(2);
  });
});

describe('createUnauthorizedHandler', () => {
  function setup(refresh: () => Promise<string>) {
    const replay = vi.fn(async (config: ReplayableConfig) => ({ replayed: config.url }));
    const onSessionLost = vi.fn();
    const handler = createUnauthorizedHandler<ReplayableConfig>({
      refresh,
      replay,
      onSessionLost,
    });
    return { handler, replay, onSessionLost };
  }

  it('refreshes once and replays the request on a 401', async () => {
    const refresh = vi.fn(async () => 'jwt-new');
    const { handler, replay, onSessionLost } = setup(refresh);
    const config: ReplayableConfig = { url: '/machines' };

    await expect(handler(httpError(401, config))).resolves.toEqual({ replayed: '/machines' });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(replay).toHaveBeenCalledWith(config);
    expect(config._retriedAfterRefresh).toBe(true);
    expect(onSessionLost).not.toHaveBeenCalled();
  });

  it('refreshes for a request config without a url too', async () => {
    const refresh = vi.fn(async () => 'jwt-new');
    const { handler, replay } = setup(refresh);

    await handler(httpError(401, {}));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(replay).toHaveBeenCalledTimes(1);
  });

  it('serves concurrent 401s with a single refresh', async () => {
    const pending = deferred<string>();
    const task = vi.fn(() => pending.promise);
    const { handler, replay } = setup(singleFlight(task));

    const results = ['/a', '/b', '/c'].map((url) => handler(httpError(401, { url })));
    pending.resolve('jwt-new');

    expect(await Promise.all(results)).toEqual([
      { replayed: '/a' },
      { replayed: '/b' },
      { replayed: '/c' },
    ]);
    expect(task).toHaveBeenCalledTimes(1);
    expect(replay).toHaveBeenCalledTimes(3);
  });

  it('ends the session and rethrows when the refresh fails', async () => {
    const { handler, replay, onSessionLost } = setup(async () => {
      throw new Error('refresh refused');
    });
    const error = httpError(401, { url: '/machines' });

    await expect(handler(error)).rejects.toBe(error);
    expect(onSessionLost).toHaveBeenCalledTimes(1);
    expect(replay).not.toHaveBeenCalled();
  });

  it('never replays a request twice: a second 401 means the session is gone', async () => {
    const refresh = vi.fn(async () => 'jwt-new');
    const { handler, onSessionLost } = setup(refresh);
    const error = httpError(401, { url: '/machines', _retriedAfterRefresh: true });

    await expect(handler(error)).rejects.toBe(error);
    expect(refresh).not.toHaveBeenCalled();
    expect(onSessionLost).toHaveBeenCalledTimes(1);
  });

  it.each(['/auth/login', '/auth/refresh', '/auth/logout', '/api/v1/auth/refresh?x=1'])(
    'leaves a 401 from %s alone',
    async (url) => {
      const refresh = vi.fn(async () => 'jwt-new');
      const { handler, onSessionLost } = setup(refresh);
      const error = httpError(401, { url });

      await expect(handler(error)).rejects.toBe(error);
      expect(refresh).not.toHaveBeenCalled();
      expect(onSessionLost).not.toHaveBeenCalled();
    },
  );

  it('passes other errors through untouched', async () => {
    const refresh = vi.fn(async () => 'jwt-new');
    const { handler, onSessionLost } = setup(refresh);
    for (const error of [
      httpError(403, { url: '/users' }),
      httpError(500, { url: '/machines' }),
      httpError(401, undefined),
      new Error('Network Error'),
      undefined,
    ]) {
      await expect(handler(error)).rejects.toBe(error);
    }
    expect(refresh).not.toHaveBeenCalled();
    expect(onSessionLost).not.toHaveBeenCalled();
  });
});

describe('ensureSession', () => {
  it('needs no refresh while an access token is held', async () => {
    setAccessToken('jwt-1');
    const refresh = vi.fn(async () => 'jwt-2');
    await expect(ensureSession(refresh)).resolves.toBe(true);
    expect(refresh).not.toHaveBeenCalled();
  });

  it('tries a silent refresh when none is held (a reload)', async () => {
    const refresh = vi.fn(async () => {
      setAccessToken('jwt-2');
      return 'jwt-2';
    });
    await expect(ensureSession(refresh)).resolves.toBe(true);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('answers false, without throwing, when the refresh fails', async () => {
    const refresh = vi.fn(async () => {
      throw new Error('no cookie');
    });
    await expect(ensureSession(refresh)).resolves.toBe(false);
  });
});
