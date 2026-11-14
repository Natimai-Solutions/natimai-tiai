import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SCROLL_RESTORE_TIMEOUT_MS, whenScrollable } from './scrollRestore';

describe('whenScrollable (audit U10)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  /** Track how a promise settles without awaiting it. */
  function watch<T>(promise: Promise<T>) {
    const state: { settled: boolean; value?: T } = { settled: false };
    void promise.then((value) => {
      state.settled = true;
      state.value = value;
    });
    return state;
  }

  it('answers at once when the page is already tall enough', async () => {
    const result = await whenScrollable({ left: 0, top: 800 }, { reachable: () => 2000 });
    expect(result).toEqual({ left: 0, top: 800 });
  });

  it('waits for the page to grow tall enough before scrolling', async () => {
    let height = 0;
    const state = watch(whenScrollable({ left: 0, top: 1800 }, { reachable: () => height }));

    await vi.advanceTimersByTimeAsync(500);
    expect(state.settled).toBe(false);

    // The list's rows arrive.
    height = 4000;
    await vi.advanceTimersByTimeAsync(100);
    expect(state.settled).toBe(true);
    expect(state.value).toEqual({ left: 0, top: 1800 });
  });

  it('gives up waiting after the timeout and scrolls as far as it can', async () => {
    const state = watch(whenScrollable({ left: 0, top: 1800 }, { reachable: () => 300 }));

    await vi.advanceTimersByTimeAsync(SCROLL_RESTORE_TIMEOUT_MS - 100);
    expect(state.settled).toBe(false);
    await vi.advanceTimersByTimeAsync(200);
    expect(state.settled).toBe(true);
    expect(state.value).toEqual({ left: 0, top: 1800 });
  });

  it('does not scroll at all once the reader has gone to another page', async () => {
    let current = true;
    const state = watch(
      whenScrollable({ left: 0, top: 1800 }, { reachable: () => 0, isCurrent: () => current }),
    );
    current = false;
    await vi.advanceTimersByTimeAsync(100);

    expect(state.settled).toBe(true);
    expect(state.value).toBe(false);
  });
});
