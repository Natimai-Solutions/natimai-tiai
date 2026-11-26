import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { TrendChartSeries } from 'src/services/trends';
import TrendChart from './TrendChart.vue';

const series = (values: (number | null)[], key = 'total', slot = 1): TrendChartSeries => ({
  key,
  label: key === 'total' ? 'Postes' : 'À jour',
  slot,
  values,
});

function mountChart(
  days: string[],
  list: TrendChartSeries[],
  provisionalDay: string | null = null,
) {
  return mount(TrendChart, { props: { days, series: list, provisionalDay } });
}

const DAYS = ['2026-11-20', '2026-11-21', '2026-11-22', '2026-11-23', '2026-11-24'];

describe('TrendChart', () => {
  it('breaks the line at a day never photographed rather than drawing a zero', () => {
    const w = mountChart(DAYS, [series([10, 11, null, 12, 13])]);
    const lines = w.findAll('polyline.trend-line');
    expect(lines).toHaveLength(2);
    expect(lines[0]!.attributes('points')!.split(' ')).toHaveLength(2);
    expect(lines[1]!.attributes('points')!.split(' ')).toHaveLength(2);
  });

  it('draws a lone day between two gaps as a dot', () => {
    const w = mountChart(DAYS, [series([10, null, 12, null, 13])]);
    expect(w.findAll('polyline.trend-line')).toHaveLength(0);
    expect(w.findAll('circle.trend-point')).toHaveLength(3);
  });

  it('dashes today’s point, which is taken again every hour', () => {
    const w = mountChart(DAYS, [series([10, 11, 12, 13, 14])], '2026-11-24');
    expect(w.findAll('polyline.trend-line')).toHaveLength(1);
    expect(w.find('polyline.trend-line').attributes('points')!.split(' ')).toHaveLength(4);
    expect(w.find('line.trend-provisional-line').exists()).toBe(true);
    expect(w.find('circle.trend-provisional-point').exists()).toBe(true);
  });

  it('draws no axis for a period without any photo', () => {
    const w = mountChart(DAYS, [series([null, null, null, null, null])]);
    expect(w.find('svg').exists()).toBe(false);
    expect(w.find('[data-test="trend-empty"]').text()).toBe(
      'Aucune photo du parc sur cette période.',
    );
  });

  it('draws a single day as a dot in the middle, with its date under it', () => {
    const w = mountChart(['2026-11-25'], [series([42])]);
    const dot = w.find('circle.trend-point');
    expect(dot.exists()).toBe(true);
    expect(Number(dot.attributes('cx'))).toBeGreaterThan(300);
    expect(w.findAll('text.trend-tick').map((t) => t.text())).toContain('25 nov.');
  });

  it('gives each series its slot’s colour and a legend from two series on', () => {
    const w = mountChart(DAYS, [series([1, 2, 3, 4, 5]), series([1, 1, 1, 1, 1], 'up_to_date', 4)]);
    const groups = w.findAll('svg g[style]');
    expect(groups.map((g) => g.attributes('style'))).toEqual([
      'color: var(--ti-series-1);',
      'color: var(--ti-series-4);',
    ]);
    expect(w.find('.trend-legend').text()).toContain('À jour');
    expect(
      mountChart(DAYS, [series([1, 2, 3, 4, 5])])
        .find('.trend-legend')
        .exists(),
    ).toBe(false);
  });

  it('shows every series’ value for the day hovered, a dash for a gap', async () => {
    const w = mountChart(DAYS, [
      series([10, 11, null, 12, 13]),
      series([1, 2, 3, 4, 5], 'up_to_date', 2),
    ]);
    await w.findAll('rect.trend-hit')[2]!.trigger('mouseenter');
    const tip = w.find('[data-test="trend-tooltip"]');
    expect(tip.text()).toContain('22/11/2026');
    expect(tip.text()).toContain('Postes');
    expect(tip.text()).toContain('—');
    expect(tip.text()).toContain('3');
  });
});
