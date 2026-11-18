import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/stats', () => ({ getOverview: vi.fn() }));

import { getOverview, type StatsOverview } from 'src/services/stats';
import {
  rememberFleetThresholds,
  resetFleetThresholds,
  useFleetThresholds,
} from './useFleetThresholds';

const overview = (percent: number) => ({ low_disk_free_percent: percent }) as StatsOverview;
/** Let the read in flight settle. */
const settle = () => vi.advanceTimersByTimeAsync(0);

/**
 * The threshold the list and the fiche colour their disks by — the one the
 * dashboard counts with. Its wiring had no test: the composable could stop
 * reading and nothing failed.
 */
describe('useFleetThresholds', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-18T08:00:00Z'));
    vi.mocked(getOverview).mockReset();
    resetFleetThresholds();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('reads the threshold from the overview, unknown until it answers', async () => {
    vi.mocked(getOverview).mockResolvedValue(overview(15));
    const { lowDiskPercent } = useFleetThresholds();
    expect(lowDiskPercent.value).toBeUndefined();
    await settle();
    expect(getOverview).toHaveBeenCalledTimes(1);
    expect(lowDiskPercent.value).toBe(15);
  });

  it('shares one value and one read between the pages that ask together', async () => {
    vi.mocked(getOverview).mockResolvedValue(overview(15));
    const list = useFleetThresholds();
    const fiche = useFleetThresholds();
    await settle();
    expect(getOverview).toHaveBeenCalledTimes(1);
    expect(fiche.lowDiskPercent).toBe(list.lowDiskPercent);
  });

  it('keeps the value for five minutes, then reads it again', async () => {
    vi.mocked(getOverview).mockResolvedValue(overview(15));
    useFleetThresholds();
    await settle();

    vi.advanceTimersByTime(4 * 60_000);
    useFleetThresholds();
    await settle();
    expect(getOverview).toHaveBeenCalledTimes(1);

    vi.mocked(getOverview).mockResolvedValue(overview(20));
    vi.advanceTimersByTime(2 * 60_000);
    const { lowDiskPercent } = useFleetThresholds();
    await settle();
    expect(getOverview).toHaveBeenCalledTimes(2);
    expect(lowDiskPercent.value).toBe(20);
  });

  it('takes the value the settings page or the dashboard hands over, without a read', async () => {
    rememberFleetThresholds({ low_disk_free_percent: 30 });
    const { lowDiskPercent } = useFleetThresholds();
    await settle();
    expect(lowDiskPercent.value).toBe(30);
    expect(getOverview).not.toHaveBeenCalled();

    // Saved again in « Paramètres »: every page showing a disk follows.
    rememberFleetThresholds({ low_disk_free_percent: 12 });
    expect(lowDiskPercent.value).toBe(12);
    // An answer without the figure (an older server) changes nothing.
    rememberFleetThresholds({});
    expect(lowDiskPercent.value).toBe(12);
  });

  it('stays unknown when the read fails, and tries again on the next use', async () => {
    vi.mocked(getOverview).mockRejectedValueOnce(new Error('offline'));
    const { lowDiskPercent } = useFleetThresholds();
    await settle();
    expect(lowDiskPercent.value).toBeUndefined();

    vi.mocked(getOverview).mockResolvedValue(overview(15));
    useFleetThresholds();
    await settle();
    expect(getOverview).toHaveBeenCalledTimes(2);
    expect(lowDiskPercent.value).toBe(15);
  });
});
