import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { effectScope } from 'vue';
import { AUTO_REFRESH_INTERVAL_MS, useAutoRefresh } from './useAutoRefresh';

/**
 * A stand-in for `document` — the tests run in node, where there is none. Only
 * the two members the composable touches, so a change to what it listens for
 * fails here rather than silently doing nothing.
 */
function fakeDocument() {
  const listeners: Array<() => void> = [];
  return {
    hidden: false,
    addEventListener: vi.fn((event: string, handler: () => void) => {
      if (event === 'visibilitychange') listeners.push(handler);
    }),
    removeEventListener: vi.fn((event: string, handler: () => void) => {
      const i = listeners.indexOf(handler);
      if (event === 'visibilitychange' && i >= 0) listeners.splice(i, 1);
    }),
    emitVisibilityChange: () => listeners.forEach((h) => h()),
  };
}

/** Run a composable inside a scope the test can dispose, as a component does. */
function inScope<T>(fn: () => T): { value: T; dispose: () => void } {
  const scope = effectScope();
  const value = scope.run(fn) as T;
  return { value, dispose: () => scope.stop() };
}

describe('AUTO_REFRESH_INTERVAL_MS', () => {
  // The console shows what the last heartbeat wrote, so a period shorter than
  // the agent's own (60 s) would only spend requests. Equal would beat against
  // it; longer by half a heartbeat is the deliberate choice.
  it('sits just above the agent heartbeat', () => {
    const heartbeatMs = 60_000;
    expect(AUTO_REFRESH_INTERVAL_MS).toBeGreaterThan(heartbeatMs);
    expect(AUTO_REFRESH_INTERVAL_MS).toBeLessThanOrEqual(2 * heartbeatMs);
  });
});

describe('useAutoRefresh', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('defaults to the exported cadence', async () => {
    // The pages pass no interval, so the constant is not merely documentation.
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { dispose } = inScope(() => useAutoRefresh(refresh));

    await vi.advanceTimersByTimeAsync(AUTO_REFRESH_INTERVAL_MS - 1);
    expect(refresh).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(refresh).toHaveBeenCalledTimes(1);

    dispose();
  });

  it('refreshes once per period, and not before', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

    // Nothing on mount: the page does its own first load, with its spinner.
    expect(refresh).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(999);
    expect(refresh).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(refresh).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(2000);
    expect(refresh).toHaveBeenCalledTimes(3);

    dispose();
  });

  it('stamps the last success, and only a success', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { value, dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

    expect(value.lastRefreshedAt.value).toBeNull();
    await vi.advanceTimersByTimeAsync(1000);
    const first = value.lastRefreshedAt.value;
    expect(first).toBeInstanceOf(Date);

    refresh.mockRejectedValueOnce(new Error('réseau'));
    await vi.advanceTimersByTimeAsync(1000);
    expect(value.lastRefreshedAt.value).toBe(first);

    dispose();
  });

  it('keeps ticking after a failure', async () => {
    // The point of swallowing: a flaky link must not silently stop the page
    // from ever refreshing again.
    const refresh = vi.fn().mockRejectedValue(new Error('502'));
    const { dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

    await vi.advanceTimersByTimeAsync(3000);
    expect(refresh).toHaveBeenCalledTimes(3);

    dispose();
  });

  it('never overlaps two refreshes', async () => {
    let release: (() => void) | undefined;
    const refresh = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    const { value, dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

    await vi.advanceTimersByTimeAsync(1000);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(value.refreshing.value).toBe(true);

    // Two more ticks while the first is still in flight: both skipped.
    await vi.advanceTimersByTimeAsync(2000);
    expect(refresh).toHaveBeenCalledTimes(1);

    release?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(value.refreshing.value).toBe(false);

    await vi.advanceTimersByTimeAsync(1000);
    expect(refresh).toHaveBeenCalledTimes(2);

    dispose();
  });

  it('skips a tick while paused', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    let paused = true;
    const { dispose } = inScope(() =>
      useAutoRefresh(refresh, { intervalMs: 1000, paused: () => paused }),
    );

    await vi.advanceTimersByTimeAsync(2000);
    expect(refresh).not.toHaveBeenCalled();

    paused = false;
    await vi.advanceTimersByTimeAsync(1000);
    expect(refresh).toHaveBeenCalledTimes(1);

    dispose();
  });

  it('stops on scope disposal', async () => {
    const doc = fakeDocument();
    vi.stubGlobal('document', doc);
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

    await vi.advanceTimersByTimeAsync(1000);
    expect(refresh).toHaveBeenCalledTimes(1);

    dispose();
    await vi.advanceTimersByTimeAsync(5000);
    expect(refresh).toHaveBeenCalledTimes(1);
    // The listener goes too: leaking one per visited page is a slow leak in a
    // console people leave open all day.
    expect(doc.removeEventListener).toHaveBeenCalledWith('visibilitychange', expect.any(Function));
  });

  describe('a hidden tab', () => {
    it('costs nothing, and catches up on return', async () => {
      const doc = fakeDocument();
      vi.stubGlobal('document', doc);
      const refresh = vi.fn().mockResolvedValue(undefined);
      const { dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

      doc.hidden = true;
      await vi.advanceTimersByTimeAsync(10_000);
      expect(refresh).not.toHaveBeenCalled();

      doc.hidden = false;
      doc.emitVisibilityChange();
      await vi.advanceTimersByTimeAsync(0);
      // Immediately, not at the next tick: coming back to the tab is exactly
      // when the reader wants what the postes reported meanwhile.
      expect(refresh).toHaveBeenCalledTimes(1);

      dispose();
    });

    it('does not catch up when no tick was missed', async () => {
      const doc = fakeDocument();
      vi.stubGlobal('document', doc);
      const refresh = vi.fn().mockResolvedValue(undefined);
      const { dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

      // Hidden and back within one period — nothing is stale.
      doc.hidden = true;
      await vi.advanceTimersByTimeAsync(200);
      doc.hidden = false;
      doc.emitVisibilityChange();
      await vi.advanceTimersByTimeAsync(0);
      expect(refresh).not.toHaveBeenCalled();

      dispose();
    });

    it('stays quiet while the tab is being hidden', async () => {
      const doc = fakeDocument();
      vi.stubGlobal('document', doc);
      const refresh = vi.fn().mockResolvedValue(undefined);
      const { dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

      doc.hidden = true;
      await vi.advanceTimersByTimeAsync(2000);
      // The event also fires on the way *out*; that must not refresh anything.
      doc.emitVisibilityChange();
      await vi.advanceTimersByTimeAsync(0);
      expect(refresh).not.toHaveBeenCalled();

      dispose();
    });

    it('does not catch up into a paused page', async () => {
      const doc = fakeDocument();
      vi.stubGlobal('document', doc);
      const refresh = vi.fn().mockResolvedValue(undefined);
      const { dispose } = inScope(() =>
        useAutoRefresh(refresh, { intervalMs: 1000, paused: () => true }),
      );

      doc.hidden = true;
      await vi.advanceTimersByTimeAsync(2000);
      doc.hidden = false;
      doc.emitVisibilityChange();
      await vi.advanceTimersByTimeAsync(0);
      expect(refresh).not.toHaveBeenCalled();

      dispose();
    });
  });

  describe('refreshNow', () => {
    it('refreshes at once and restarts the countdown', async () => {
      const refresh = vi.fn().mockResolvedValue(undefined);
      const { value, dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

      await vi.advanceTimersByTimeAsync(900);
      await value.refreshNow();
      expect(refresh).toHaveBeenCalledTimes(1);

      // The 100 ms left on the old countdown must not fire a second refresh…
      await vi.advanceTimersByTimeAsync(900);
      expect(refresh).toHaveBeenCalledTimes(1);
      // …the next one is a full period after the manual refresh.
      await vi.advanceTimersByTimeAsync(100);
      expect(refresh).toHaveBeenCalledTimes(2);

      dispose();
    });

    it('waits out a background refresh rather than joining it', async () => {
      // The pages call this straight after queueing a command. A request issued
      // before that command existed cannot show it, so returning its result
      // would leave the console claiming nothing happened.
      let release: (() => void) | undefined;
      const refresh = vi.fn(
        () =>
          new Promise<void>((resolve) => {
            release = resolve;
          }),
      );
      const { value, dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

      await vi.advanceTimersByTimeAsync(1000);
      expect(refresh).toHaveBeenCalledTimes(1);

      const manual = value.refreshNow();
      await vi.advanceTimersByTimeAsync(0);
      // Still just the one: the manual refresh is queued behind it, not merged.
      expect(refresh).toHaveBeenCalledTimes(1);

      const first = release;
      first?.();
      await vi.advanceTimersByTimeAsync(0);
      expect(refresh).toHaveBeenCalledTimes(2);

      release?.();
      await manual;
      expect(value.lastRefreshedAt.value).toBeInstanceOf(Date);

      dispose();
    });

    it('resolves even when the refresh fails', async () => {
      const refresh = vi.fn().mockRejectedValue(new Error('502'));
      const { value, dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

      await expect(value.refreshNow()).resolves.toBeUndefined();
      // And the timer is still running afterwards.
      await vi.advanceTimersByTimeAsync(1000);
      expect(refresh).toHaveBeenCalledTimes(2);

      dispose();
    });
  });

  it('works without a document at all', async () => {
    // The SSR/node path: no visibility to observe, but the timer must still run
    // rather than throwing on a missing global.
    expect(typeof document).toBe('undefined');
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { value, dispose } = inScope(() => useAutoRefresh(refresh, { intervalMs: 1000 }));

    await vi.advanceTimersByTimeAsync(1000);
    expect(refresh).toHaveBeenCalledTimes(1);

    value.stop();
    await vi.advanceTimersByTimeAsync(2000);
    expect(refresh).toHaveBeenCalledTimes(1);

    dispose();
  });
});
