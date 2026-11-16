/**
 * Coming back to a page with Back: the router hands over where the reader
 * was, but on the tick after the navigation, before the page's data has
 * arrived. A list of 100 postes is then a few pixels tall, the browser clamps
 * the position to that, and the reader lands at the top (audit U10).
 *
 * So the position is held back until the document is tall enough to reach
 * it. It is dropped — no scroll at all — when that never happens within the
 * timeout (the list is shorter than it was: scrolling « as far as possible »
 * three seconds in would throw a reader who has started reading to the
 * bottom), when the reader scrolls by themselves in the meantime, or when
 * they have gone to another page.
 *
 * The window is what scrolls in this console: the layout (MainLayout.vue) is
 * a plain q-layout, not a `container` one with a scroll area of its own.
 */

export interface ScrollTarget {
  left: number;
  top: number;
}

/** Long enough for a slow list, short enough not to jump under a reader who moved on. */
export const SCROLL_RESTORE_TIMEOUT_MS = 3000;
const POLL_MS = 50;

/** How far down the window can scroll right now. */
export function maxScrollTop(): number {
  return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
}

/** The keys that scroll a page. */
const SCROLL_KEYS = new Set([
  'ArrowUp',
  'ArrowDown',
  'PageUp',
  'PageDown',
  'Home',
  'End',
  ' ',
  'Spacebar',
]);

/** A key pressed in a field types or moves the caret: it does not scroll the page. */
function inField(target: unknown): boolean {
  const el = target as { tagName?: unknown; isContentEditable?: unknown } | null;
  if (!el || typeof el.tagName !== 'string') return false;
  return el.isContentEditable === true || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
}

/** What `watchReaderScroll` listens on; the window, outside a spec. */
export type ScrollInputSource = Pick<Window, 'addEventListener' | 'removeEventListener'>;

export interface ReaderScrollDeps {
  source?: ScrollInputSource;
  /** Where the window is scrolled to now. */
  position?: () => number;
  /** The furthest reachable position. */
  reachable?: () => number;
}

/**
 * Call `taken` when the reader scrolls by themselves: the wheel, a finger, a
 * scroll key, or the scrollbar — which raises no input event, only `scroll`.
 * Nothing here scrolls the window while this listens, so a `scroll` event is
 * the reader's, with one exception: the browser moves the window up by itself
 * when the page under it gets shorter (the page being left was scrolled
 * further than the one arriving is tall yet). That move ends exactly at the
 * bottom of the page; the reader's own, upwards, cannot.
 * Returns what stops the listening.
 */
export function watchReaderScroll(taken: () => void, deps: ReaderScrollDeps = {}): () => void {
  const source = deps.source ?? window;
  const position = deps.position ?? (() => window.scrollY);
  const reachable = deps.reachable ?? maxScrollTop;
  let last = position();

  const onInput = () => taken();
  const onKey = (event: Event) => {
    const key = (event as KeyboardEvent).key;
    if (SCROLL_KEYS.has(key) && !inField(event.target)) taken();
  };
  const onScroll = () => {
    const now = position();
    const moved = now !== last;
    const clampedByBrowser = now < last && now >= reachable() - 1;
    last = now;
    if (moved && !clampedByBrowser) taken();
  };

  source.addEventListener('wheel', onInput, { passive: true });
  source.addEventListener('touchmove', onInput, { passive: true });
  source.addEventListener('keydown', onKey);
  source.addEventListener('scroll', onScroll, { passive: true });
  return () => {
    source.removeEventListener('wheel', onInput);
    source.removeEventListener('touchmove', onInput);
    source.removeEventListener('keydown', onKey);
    source.removeEventListener('scroll', onScroll);
  };
}

export interface WhenScrollableOptions {
  timeoutMs?: number;
  intervalMs?: number;
  /** The furthest reachable position; the document's, by default. */
  reachable?: () => number;
  /**
   * False once another navigation has happened: a position held back for
   * the list must not be applied to the fiche opened from it meanwhile.
   */
  isCurrent?: () => boolean;
  /**
   * Hear the reader scroll by themselves — `taken` — and return what stops
   * the listening. `watchReaderScroll` on the window, by default.
   */
  onReaderScroll?: (taken: () => void) => () => void;
}

/**
 * Resolve with `target` once the page can scroll that far, or with `false` —
 * no scroll at all — if it still cannot after the timeout, if the reader has
 * scrolled by themselves, or if they have navigated elsewhere in the meantime.
 */
export function whenScrollable(
  target: ScrollTarget,
  options: WhenScrollableOptions = {},
): Promise<ScrollTarget | false> {
  const timeoutMs = options.timeoutMs ?? SCROLL_RESTORE_TIMEOUT_MS;
  const intervalMs = options.intervalMs ?? POLL_MS;
  const reachable = options.reachable ?? maxScrollTop;
  const isCurrent = options.isCurrent ?? (() => true);
  const onReaderScroll =
    options.onReaderScroll ??
    ((taken: () => void) =>
      typeof window === 'undefined' ? () => undefined : watchReaderScroll(taken, { reachable }));
  return new Promise((resolve) => {
    let waited = 0;
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopListening = () => undefined as void;

    const settle = (value: ScrollTarget | false) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      stopListening();
      resolve(value);
    };
    const check = () => {
      if (!isCurrent()) return settle(false);
      if (reachable() >= target.top) return settle(target);
      // Still too short: the list is not what it was. Scrolling now would
      // land at its bottom, further than anyone asked — give up instead.
      if (waited >= timeoutMs) return settle(false);
      waited += intervalMs;
      timer = setTimeout(check, intervalMs);
    };

    check();
    // Reachable at once: nothing is pending, nothing to listen for.
    if (!settled) stopListening = onReaderScroll(() => settle(false));
  });
}
