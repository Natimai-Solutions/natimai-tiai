import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { CommandMonth, Indicators } from 'src/services/trends';
import IndicatorsCard from './IndicatorsCard.vue';

const cmd = (month: string, over: Partial<CommandMonth> = {}): CommandMonth => ({
  month,
  succeeded: 0,
  failed: 0,
  expired: 0,
  unanswered: 0,
  ...over,
});

function indicators(over: Partial<Indicators> = {}): Indicators {
  return {
    months: ['2026-10', '2026-11'],
    checks: [
      {
        month: '2026-10',
        closed: 12,
        median_hours: 5.5,
        p90_hours: 48,
        with_due: 4,
        on_time_due: 3,
      },
      { month: '2026-11', closed: 1, median_hours: 1, p90_hours: 1, with_due: 0, on_time_due: 0 },
    ],
    maintenance: [
      { month: '2026-10', done: 4, on_time: 3 },
      { month: '2026-11', done: 0, on_time: 0 },
    ],
    commands: [
      cmd('2026-10', { succeeded: 9, failed: 1, expired: 2, unanswered: 3 }),
      cmd('2026-11'),
    ],
    deployments: {
      direct: [cmd('2026-10', { succeeded: 1, failed: 1 }), cmd('2026-11')],
      scheduled: [cmd('2026-10', { succeeded: 3 }), cmd('2026-11')],
      halted_runs: [2, 0],
    },
    retention: { commands_days: 365, schedule_runs_days: 180 },
    ...over,
  };
}

const card = (w: ReturnType<typeof mount>, key: string) => w.find(`[data-test="indicator-${key}"]`);

describe('IndicatorsCard', () => {
  it('reads the last full month, not the one in progress', () => {
    const w = mount(IndicatorsCard, { props: { data: indicators(), months: 2 } });
    const checks = card(w, 'checks').text();
    expect(checks).toContain('octobre 2026');
    expect(checks).toContain('Médiane : 5,5 h');
    expect(checks).toContain('9 sur 10 closes en moins de 48,0 h');
    expect(checks).toContain('Échéance tenue : 3 sur 4');
    expect(card(w, 'maintenance').text()).toContain('75 % à l’heure');
    // 9 / (9 + 1): the expired and the unanswered are outside the rate.
    expect(card(w, 'commands').text()).toContain('90 % de réussite');
    expect(card(w, 'commands').text()).toContain('Hors du taux : 2 expirées, 3 sans réponse');
    const deployments = card(w, 'deployments').text();
    expect(deployments).toContain('Directs : 50 %');
    expect(deployments).toContain('Planifiés : 100 %');
    expect(deployments).toContain('Exécutions en anneaux arrêtées : 2');
  });

  it('shows no card for a section the account may not read', () => {
    const w = mount(IndicatorsCard, {
      props: { data: indicators({ checks: null, deployments: null }), months: 2 },
    });
    expect(card(w, 'checks').exists()).toBe(false);
    expect(card(w, 'deployments').exists()).toBe(false);
    expect(card(w, 'commands').exists()).toBe(true);
    const none = mount(IndicatorsCard, {
      props: {
        data: indicators({ checks: null, maintenance: null, commands: null, deployments: null }),
        months: 2,
      },
    });
    expect(none.find('[data-test="indicators-none"]').exists()).toBe(true);
  });

  it('warns when the commands are purged sooner than the period asked', () => {
    const short = mount(IndicatorsCard, { props: { data: indicators(), months: 3 } });
    expect(short.findAll('[data-test="indicators-retention"]').length).toBe(0);
    // Twelve months fit in the commands' 365 days, not in the runs' 180.
    const year = mount(IndicatorsCard, { props: { data: indicators(), months: 12 } });
    expect(year.findAll('[data-test="indicators-retention"]').map((n) => n.text())).toEqual([
      expect.stringContaining('Exécutions de planification conservées : 180 jours.'),
    ]);
    const long = mount(IndicatorsCard, { props: { data: indicators(), months: 24 } });
    const warnings = long.findAll('[data-test="indicators-retention"]').map((n) => n.text());
    expect(warnings).toEqual([
      expect.stringContaining(
        'Historique conservé : 365 jours ; les mois plus anciens sont vides.',
      ),
      expect.stringContaining('Historique conservé : 365 jours'),
      expect.stringContaining('Exécutions de planification conservées : 180 jours.'),
    ]);
  });

  it('does not warn when nothing is purged (COMMAND_RETENTION_DAYS = 0)', () => {
    const data = indicators({ retention: { commands_days: null, schedule_runs_days: 180 } });
    const w = mount(IndicatorsCard, {
      props: { data: { ...data, deployments: null }, months: 24 },
    });
    expect(w.findAll('[data-test="indicators-retention"]').length).toBe(0);
  });

  it('says « — » for a month without anything to rate', () => {
    const data = indicators({
      months: ['2026-11'],
      commands: [cmd('2026-11', { expired: 1 })],
    });
    const w = mount(IndicatorsCard, { props: { data, months: 1 } });
    expect(card(w, 'commands').text()).toContain('—');
  });
});
