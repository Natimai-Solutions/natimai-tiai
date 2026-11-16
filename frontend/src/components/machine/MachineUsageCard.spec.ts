import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { machineDetail } from 'src/test/fixtures';

vi.mock('src/services/machines', () => ({ getMachineUsage: vi.fn() }));

import { getMachineUsage, type MachineUsage } from 'src/services/machines';
import MachineUsageCard from './MachineUsageCard.vue';

function usage(): MachineUsage {
  const daily = Array.from({ length: 28 }, (_, i) => {
    const d = new Date(Date.UTC(2026, 9, 1 + i));
    return { date: d.toISOString().slice(0, 10), hours: i === 27 ? 7.5 : 0 };
  });
  return {
    days: 28,
    tz: 'UTC',
    total_hours: 7.5,
    daily,
    first_seen: '2026-01-01T00:00:00Z',
    usage_since: '2026-01-01T00:00:00Z',
  };
}

describe('MachineUsageCard', () => {
  beforeEach(() => vi.mocked(getMachineUsage).mockReset());

  // Item 1: a failed read says so, with a way to try again.
  it('offers « Réessayer » when the usage could not be read, and reads it again', async () => {
    vi.mocked(getMachineUsage).mockRejectedValueOnce(new Error('500'));
    const w = mount(MachineUsageCard, { props: { machine: machineDetail() } });
    await flushPromises();
    expect(w.text()).toContain("Impossible de charger l'utilisation de ce poste");

    vi.mocked(getMachineUsage).mockResolvedValueOnce(usage());
    await w
      .findAll('button')
      .find((b) => b.text().includes('Réessayer'))!
      .trigger('click');
    await flushPromises();
    expect(getMachineUsage).toHaveBeenCalledTimes(2);
    expect(w.text()).not.toContain('Impossible de charger');
  });

  // Item 12: each focusable column has a name a screen reader can read.
  it('names every day column « <jour> : N h »', async () => {
    vi.mocked(getMachineUsage).mockResolvedValue(usage());
    const w = mount(MachineUsageCard, { props: { machine: machineDetail() } });
    await flushPromises();
    const cols = w.findAll('.usage-col');
    expect(cols).toHaveLength(28);
    for (const c of cols)
      expect(c.attributes('aria-label')).toMatch(/ : (\d+(,\d)? h|non mesuré)$/);
    expect(cols[27]!.attributes('aria-label')).toMatch(/ : 7,5 h$/);
  });
});
