import { onScopeDispose, ref, type Ref } from 'vue';

/**
 * Cadence of the console's background refresh.
 *
 * Tied to the agent's own heartbeat (`DefaultHeartbeatInterval` = 60 s, cf.
 * `agent/internal/config/config.go`): the console can only ever show what the
 * last heartbeat wrote, so polling faster than the postes report would cost
 * requests without ever showing anything new.
 *
 * A little *longer* rather than exactly equal, and that is the whole reason
 * this is 90 and not 60. The two clocks are unrelated — one per poste, in fact
 * — so at the same period they drift in and out of phase and a reading would
 * sometimes be served a full cycle stale. Half a heartbeat of slack costs at
 * most 30 s of freshness and removes the beat frequency entirely.
 */
export const AUTO_REFRESH_INTERVAL_MS = 90_000;

export interface UseAutoRefreshOptions {
  /** Override the cadence. Defaults to {@link AUTO_REFRESH_INTERVAL_MS}. */
  intervalMs?: number;
  /**
   * Consulted before each tick; a true return skips it. For the page that has
   * a dialog open over its tables — pulling the rows out from under a reader
   * is the one way a background refresh can be worse than stale data.
   */
  paused?: () => boolean;
}

export interface AutoRefresh {
  /** True while a refresh is in flight. */
  refreshing: Ref<boolean>;
  /** When the last refresh succeeded; null until the first one does. */
  lastRefreshedAt: Ref<Date | null>;
  /** Refresh now, and restart the countdown so the next tick is a full period away. */
  refreshNow: () => Promise<void>;
  /** Stop polling. Called for you when the component's scope is disposed. */
  stop: () => void;
}

/**
 * Re-run `refresh` on a timer for as long as the calling component lives.
 *
 * Three things it does beyond `setInterval`, each of them a bug we would
 * otherwise have shipped:
 *
 *  - **Nothing while the tab is hidden.** A console left open on a second
 *    screen overnight would otherwise fire ~1000 requests per page, per user,
 *    for a screen nobody is looking at. The tick is skipped, and coming back
 *    to the tab refreshes immediately rather than waiting out the period —
 *    which is precisely the moment the reader wants fresh data.
 *  - **No overlap.** A slow response must not have a second request queued
 *    behind it; on a parc of a few thousand postes the dashboard's four
 *    parallel queries are not free.
 *  - **Failures are swallowed.** A background refresh is not a user action:
 *    popping a notification every 90 s over a flaky link, or blanking a page
 *    that was showing something useful, is worse than data that is one cycle
 *    old. The next tick simply tries again. (A 401 is the exception, and it is
 *    handled where it belongs — the axios interceptor bounces to the login
 *    page, cf. `src/boot/axios.ts`.)
 */
export function useAutoRefresh(
  refresh: () => Promise<unknown>,
  options: UseAutoRefreshOptions = {},
): AutoRefresh {
  const intervalMs = options.intervalMs ?? AUTO_REFRESH_INTERVAL_MS;
  const refreshing = ref(false);
  const lastRefreshedAt = ref<Date | null>(null);

  // Captured rather than read at each use: there is none under the unit tests,
  // which run in node.
  const doc = typeof document === 'undefined' ? null : document;

  let timer: ReturnType<typeof setInterval> | null = null;
  // A tick fell while the tab was hidden. Drives the catch-up on return, and is
  // the reason this is a flag rather than a comparison against
  // lastRefreshedAt: a page hidden before its first refresh has no timestamp
  // to compare, and is exactly the case that must catch up.
  let missed = false;

  function hidden(): boolean {
    return doc?.hidden === true;
  }

  // The refresh currently in flight, or null. Held as the promise rather than
  // as a boolean so a caller can *wait* for it instead of only detecting it —
  // which is what refreshNow needs.
  let inFlight: Promise<void> | null = null;

  function run(): Promise<void> {
    if (inFlight) return inFlight;
    refreshing.value = true;
    inFlight = (async () => {
      try {
        await refresh();
        lastRefreshedAt.value = new Date();
      } catch {
        // Deliberate: see the doc comment.
      } finally {
        refreshing.value = false;
        inFlight = null;
      }
    })();
    return inFlight;
  }

  function tick(): void {
    if (options.paused?.()) return;
    if (hidden()) {
      missed = true;
      return;
    }
    void run();
  }

  function onVisibilityChange(): void {
    if (hidden() || !missed) return;
    missed = false;
    if (options.paused?.()) return;
    void run();
  }

  function startTimer(): void {
    if (timer === null) timer = setInterval(tick, intervalMs);
  }

  function stopTimer(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function stop(): void {
    stopTimer();
    doc?.removeEventListener('visibilitychange', onVisibilityChange);
  }

  async function refreshNow(): Promise<void> {
    // Restarted, not merely left running: an automatic refresh landing a
    // second after the reader pressed the button is pure noise.
    stopTimer();
    missed = false;
    try {
      // A background refresh already in flight is waited out, not joined. The
      // pages call this right after queueing a command, and a request issued
      // before that command existed cannot show it — returning its result
      // would leave the console claiming nothing happened.
      if (inFlight) await inFlight;
      await run();
    } finally {
      startTimer();
    }
  }

  startTimer();
  doc?.addEventListener('visibilitychange', onVisibilityChange);
  onScopeDispose(stop);

  return { refreshing, lastRefreshedAt, refreshNow, stop };
}
