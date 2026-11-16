import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SCROLL_RESTORE_TIMEOUT_MS,
  maxScrollTop,
  watchReaderScroll,
  whenScrollable,
} from './scrollRestore';

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

  /** The reader's scroll input, as a spec fires it. */
  function reader() {
    let taken: (() => void) | null = null;
    const stop = vi.fn(() => {
      taken = null;
    });
    return {
      onReaderScroll: vi.fn((cb: () => void) => {
        taken = cb;
        return stop;
      }),
      scroll: () => taken?.(),
      stop,
    };
  }

  it('answers at once when the page is already tall enough', async () => {
    const input = reader();
    const result = await whenScrollable(
      { left: 0, top: 800 },
      { reachable: () => 2000, onReaderScroll: input.onReaderScroll },
    );
    expect(result).toEqual({ left: 0, top: 800 });
    // Nothing was pending: nothing was listened to, nothing is left behind.
    expect(input.onReaderScroll).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('waits for the page to grow tall enough before scrolling', async () => {
    let height = 0;
    const input = reader();
    const state = watch(
      whenScrollable(
        { left: 0, top: 1800 },
        { reachable: () => height, onReaderScroll: input.onReaderScroll },
      ),
    );

    await vi.advanceTimersByTimeAsync(500);
    expect(state.settled).toBe(false);

    // The list's rows arrive.
    height = 4000;
    await vi.advanceTimersByTimeAsync(100);
    expect(state.settled).toBe(true);
    expect(state.value).toEqual({ left: 0, top: 1800 });
    expect(input.stop).toHaveBeenCalledTimes(1);
  });

  it('gives up after the timeout rather than scroll to the bottom of a shorter page', async () => {
    const input = reader();
    const state = watch(
      whenScrollable(
        { left: 0, top: 1800 },
        { reachable: () => 300, onReaderScroll: input.onReaderScroll },
      ),
    );

    await vi.advanceTimersByTimeAsync(SCROLL_RESTORE_TIMEOUT_MS - 100);
    expect(state.settled).toBe(false);
    await vi.advanceTimersByTimeAsync(200);
    expect(state.settled).toBe(true);
    // No scroll at all: the position asked for cannot be reached, and the
    // browser would clamp it to the bottom under a reader who is reading.
    expect(state.value).toBe(false);
    expect(input.stop).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('drops the position as soon as the reader scrolls by themselves', async () => {
    let height = 300;
    const input = reader();
    const state = watch(
      whenScrollable(
        { left: 0, top: 1800 },
        { reachable: () => height, onReaderScroll: input.onReaderScroll },
      ),
    );
    await vi.advanceTimersByTimeAsync(200);
    expect(state.settled).toBe(false);

    input.scroll();
    await vi.advanceTimersByTimeAsync(0);
    expect(state.settled).toBe(true);
    expect(state.value).toBe(false);
    expect(input.stop).toHaveBeenCalledTimes(1);

    // The rows arriving later move nothing: no check is left running.
    height = 4000;
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not scroll at all once the reader has gone to another page', async () => {
    let current = true;
    const input = reader();
    const state = watch(
      whenScrollable(
        { left: 0, top: 1800 },
        { reachable: () => 0, isCurrent: () => current, onReaderScroll: input.onReaderScroll },
      ),
    );
    current = false;
    await vi.advanceTimersByTimeAsync(100);

    expect(state.settled).toBe(true);
    expect(state.value).toBe(false);
    expect(input.stop).toHaveBeenCalledTimes(1);
  });
});

describe('watchReaderScroll', () => {
  function setup(start = 0, max = 5000) {
    const source = new EventTarget();
    const state = { y: start, max };
    const taken = vi.fn();
    const stop = watchReaderScroll(taken, {
      source,
      position: () => state.y,
      reachable: () => state.max,
    });
    return { source, state, taken, stop };
  }

  function key(source: EventTarget, name: string, target?: unknown) {
    const event = Object.assign(new Event('keydown'), { key: name });
    if (target) Object.defineProperty(event, 'target', { value: target });
    source.dispatchEvent(event);
  }

  it('hears the wheel and a finger', () => {
    for (const type of ['wheel', 'touchmove']) {
      const { source, taken } = setup();
      source.dispatchEvent(new Event(type));
      expect(taken, type).toHaveBeenCalledTimes(1);
    }
  });

  it('hears the keys that scroll a page, not the others', () => {
    for (const name of ['PageDown', 'PageUp', 'ArrowDown', 'ArrowUp', 'Home', 'End', ' ']) {
      const { source, taken } = setup();
      key(source, name);
      expect(taken, name).toHaveBeenCalledTimes(1);
    }
    const { source, taken } = setup();
    key(source, 'a');
    key(source, 'Tab');
    key(source, 'Enter');
    expect(taken).not.toHaveBeenCalled();
  });

  it('does not take a key typed in a field for a scroll', () => {
    const { source, taken } = setup();
    key(source, ' ', { tagName: 'INPUT' });
    key(source, 'ArrowDown', { tagName: 'TEXTAREA' });
    key(source, 'End', { tagName: 'DIV', isContentEditable: true });
    expect(taken).not.toHaveBeenCalled();

    key(source, 'PageDown', { tagName: 'BUTTON' });
    expect(taken).toHaveBeenCalledTimes(1);
  });

  it('hears the scrollbar, which raises nothing but scroll events', () => {
    const down = setup(0);
    down.state.y = 240;
    down.source.dispatchEvent(new Event('scroll'));
    expect(down.taken).toHaveBeenCalledTimes(1);

    // Upwards, to somewhere that is not the bottom of the page.
    const up = setup(900);
    up.state.y = 400;
    up.source.dispatchEvent(new Event('scroll'));
    expect(up.taken).toHaveBeenCalledTimes(1);
  });

  it('does not take the browser clamping the window to a shorter page for the reader', () => {
    // The fiche being left was scrolled to 600; the list arriving is still
    // 200 px taller than the window: the browser moves the window up to there.
    const { source, state, taken } = setup(600, 5000);
    state.max = 200;
    state.y = 200;
    source.dispatchEvent(new Event('scroll'));
    expect(taken).not.toHaveBeenCalled();

    // A scroll event with no vertical move is not a scroll down the page.
    source.dispatchEvent(new Event('scroll'));
    expect(taken).not.toHaveBeenCalled();

    // The reader then scrolls up from there: theirs.
    state.max = 4000;
    state.y = 120;
    source.dispatchEvent(new Event('scroll'));
    expect(taken).toHaveBeenCalledTimes(1);
  });

  it('stops listening when told to', () => {
    const { source, state, taken, stop } = setup();
    stop();
    source.dispatchEvent(new Event('wheel'));
    source.dispatchEvent(new Event('touchmove'));
    key(source, 'PageDown');
    state.y = 300;
    source.dispatchEvent(new Event('scroll'));
    expect(taken).not.toHaveBeenCalled();
  });
});

describe('maxScrollTop', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('is how much taller than the window the document is, never less than nothing', () => {
    vi.stubGlobal('window', { innerHeight: 900 });
    vi.stubGlobal('document', { documentElement: { scrollHeight: 4100 } });
    expect(maxScrollTop()).toBe(3200);

    vi.stubGlobal('document', { documentElement: { scrollHeight: 400 } });
    expect(maxScrollTop()).toBe(0);
  });
});
