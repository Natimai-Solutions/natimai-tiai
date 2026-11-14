/**
 * Coming back to a page with Back: the router hands over where the reader
 * was, but on the tick after the navigation, before the page's data has
 * arrived. A list of 100 postes is then a few pixels tall, the browser clamps
 * the position to that, and the reader lands at the top (audit U10).
 *
 * So the position is held back until the document is tall enough to reach
 * it, or until a timeout — after which the browser scrolls as far as it can.
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
}

/**
 * Resolve with `target` once the page can scroll that far (or once the
 * timeout has passed), or with `false` — no scroll at all — if the reader has
 * navigated elsewhere in the meantime.
 */
export function whenScrollable(
  target: ScrollTarget,
  options: WhenScrollableOptions = {},
): Promise<ScrollTarget | false> {
  const timeoutMs = options.timeoutMs ?? SCROLL_RESTORE_TIMEOUT_MS;
  const intervalMs = options.intervalMs ?? POLL_MS;
  const reachable = options.reachable ?? maxScrollTop;
  const isCurrent = options.isCurrent ?? (() => true);
  return new Promise((resolve) => {
    let waited = 0;
    const check = () => {
      if (!isCurrent()) {
        resolve(false);
        return;
      }
      if (reachable() >= target.top || waited >= timeoutMs) {
        resolve(target);
        return;
      }
      waited += intervalMs;
      setTimeout(check, intervalMs);
    };
    check();
  });
}
