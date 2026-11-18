import { ref, type Ref } from 'vue';
import { getOverview, type StatsOverview } from 'src/services/stats';

/**
 * The parc's thresholds a page needs to colour what it shows the way the
 * dashboard counts it: « disque presque plein » below N % free. They are
 * server settings (« Paramètres »), served with `/stats/overview` — readable
 * with machine:read, unlike `/settings`.
 *
 * One shared value for the whole console, read at most every five minutes:
 * the fiche and the list both need it, and neither is worth a second call per
 * load. The dashboard, which reads the overview anyway, and the settings page,
 * which changes it, hand it over directly (`rememberFleetThresholds`).
 */
const lowDiskPercent = ref<number | undefined>(undefined);
const MAX_AGE_MS = 5 * 60 * 1000;
let fetchedAt = 0;
let inFlight: Promise<void> | null = null;

export function rememberFleetThresholds(
  s: Partial<Pick<StatsOverview, 'low_disk_free_percent'>>,
): void {
  if (typeof s.low_disk_free_percent === 'number') {
    lowDiskPercent.value = s.low_disk_free_percent;
    fetchedAt = Date.now();
  }
}

/** Forget what was read — for the specs: a threshold must not travel from one to the next. */
export function resetFleetThresholds(): void {
  lowDiskPercent.value = undefined;
  fetchedAt = 0;
  inFlight = null;
}

function refresh(): Promise<void> {
  if (inFlight) return inFlight;
  if (fetchedAt && Date.now() - fetchedAt < MAX_AGE_MS) return Promise.resolve();
  inFlight = getOverview()
    .then(rememberFleetThresholds)
    .catch(() => {
      // The default thresholds stand in; the page's own requests report outages.
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

export function useFleetThresholds(): { lowDiskPercent: Ref<number | undefined> } {
  void refresh();
  return { lowDiskPercent };
}
