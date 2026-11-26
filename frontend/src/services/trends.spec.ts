import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn() },
}));

import { api } from 'boot/axios';
import { setLocale } from 'src/i18n';
import fr from 'src/i18n/messages/trends';
import {
  DEFAULT_TREND_KEYS,
  TREND_BASE_KEYS,
  TREND_KEYS,
  downloadReport,
  getIndicators,
  getRecurringFailures,
  getTrends,
} from './trends';

describe('the trends service (C9)', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.get).mockResolvedValue({ data: {} });
  });
  afterEach(() => setLocale('fr'));

  it('asks for the series by key, comma-separated', async () => {
    await getTrends({ months: 3, keys: ['total', 'alerts.disk_low'] });
    expect(api.get).toHaveBeenCalledWith('/stats/trends', {
      params: { months: 3, keys: 'total,alerts.disk_low' },
    });
  });

  it('leaves the keys out when none are named (the server draws its defaults)', async () => {
    await getTrends({ months: 12 });
    expect(api.get).toHaveBeenCalledWith('/stats/trends', { params: { months: 12 } });
  });

  it('reads the indicators and the failures for the period', async () => {
    await getIndicators(24);
    await getRecurringFailures({ months: 12, by: 'room' });
    expect(api.get).toHaveBeenNthCalledWith(1, '/stats/indicators', { params: { months: 24 } });
    expect(api.get).toHaveBeenNthCalledWith(2, '/stats/recurring-failures', {
      params: { months: 12, by: 'room' },
    });
  });

  it('downloads the report as a blob, in the language shown', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob() });
    await downloadReport(12);
    setLocale('en');
    await downloadReport(3);
    expect(api.get).toHaveBeenNthCalledWith(1, '/stats/report.xlsx', {
      params: { months: 12 },
      responseType: 'blob',
    });
    expect(api.get).toHaveBeenNthCalledWith(2, '/stats/report.xlsx', {
      params: { months: 3, lang: 'en' },
      responseType: 'blob',
    });
  });

  it('offers only keys the server knows, the defaults among them', () => {
    // `counters.ALL_KEYS`: 23 counters + `outdated`, 8 rules, 10 checks.
    expect(TREND_KEYS).toHaveLength(42);
    expect(new Set(TREND_KEYS).size).toBe(TREND_KEYS.length);
    for (const key of DEFAULT_TREND_KEYS) expect(TREND_KEYS).toContain(key);
  });

  it('has a label in both languages for every counter', () => {
    for (const key of TREND_BASE_KEYS) {
      expect(fr.fr.series[key], key).toBeTruthy();
      expect(fr.en.series[key], key).toBeTruthy();
    }
  });
});
