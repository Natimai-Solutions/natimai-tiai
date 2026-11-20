import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { apiErrorMessage } from './errors';
import {
  localText,
  runCauseText,
  runSummary,
  suspendedText,
  targetText,
  whenText,
  windowText,
  type ScheduleRun,
  type ScheduleTarget,
} from './schedules';

const target = (over: Partial<ScheduleTarget>): ScheduleTarget => ({
  kind: 'all',
  machine_ids: [],
  value: null,
  label: null,
  machine_count: null,
  ...over,
});

const run = (over: Partial<ScheduleRun>): ScheduleRun => ({
  id: 'r',
  started_at: '2026-11-25T04:00:00Z',
  finished_at: null,
  status: 'done',
  result_code: null,
  result_params: null,
  created: 12,
  skipped: 1,
  left_out: 0,
  woken: 0,
  shut_down: 0,
  kept_on: 0,
  stage: 0,
  ...over,
});

describe('schedules wording', () => {
  afterEach(() => setLocale('fr'));

  it('says when, in the console’s zone as the server wrote it', () => {
    expect(
      whenText({
        recurrence: 'once',
        run_at_local: '2026-11-25T18:00',
        weekdays: [],
        time_of_day: null,
      }),
    ).toBe('Le 25/11/2026 à 18:00');
    expect(
      whenText({
        recurrence: 'weekly',
        run_at_local: null,
        weekdays: [4, 2],
        time_of_day: '07:30',
      }),
    ).toBe('Chaque mercredi, vendredi à 07:30');
    expect(
      whenText({
        recurrence: 'weekly',
        run_at_local: null,
        weekdays: [0, 1, 2, 3, 4, 5, 6],
        time_of_day: '18:00',
      }),
    ).toBe('Tous les jours à 18:00');
    expect(localText('2026-11-25T18:00')).toBe('25/11/2026 18:00');
    expect(localText(null)).toBe('—');
  });

  it('names the target', () => {
    expect(targetText(target({ kind: 'all' }))).toBe('Tout le parc');
    expect(targetText(target({ kind: 'room', label: 'Bât. A — A101' }))).toBe(
      'Salle Bât. A — A101',
    );
    expect(targetText(target({ kind: 'room', label: null }))).toBe('Salle ou bâtiment supprimé');
    expect(targetText(target({ kind: 'location', value: 'Taravao' }))).toBe('Emplacement Taravao');
    expect(
      targetText(
        target({ kind: 'machines', label: 'PC-1, PC-2, PC-3', machine_count: 5, machine_ids: [] }),
      ),
    ).toBe('PC-1, PC-2, PC-3 et 2 autre(s)');
    expect(targetText(target({ kind: 'machines', label: 'PC-1', machine_count: 1 }))).toBe('PC-1');
  });

  it('says what a run did and why it stopped', () => {
    expect(runSummary(run({ woken: 3, shut_down: 2, kept_on: 1 }))).toBe(
      '12 commande(s), 1 déjà en attente · 3 réveillé(s) · 2 éteint(s) · 1 laissé(s) allumé(s)',
    );
    expect(
      runCauseText(
        run({
          status: 'halted',
          result_code: 'ring_failed',
          result_params: { stage: 1, failed: 2, finished: 4, percent: 50, threshold: 20 },
        }),
      ),
    ).toBe('Étape 1 : 2 échec(s) sur 4 (50 %), au-delà du seuil de 20 %.');
    expect(
      runCauseText(
        run({
          result_code: 'permission_lost',
          result_params: { permission: 'risky_command:execute' },
        }),
      ),
    ).toBe('Son auteur n’a plus le droit « risky_command:execute ».');
    expect(suspendedText('author_inactive')).toBe('Le compte de son auteur est désactivé.');
    expect(runCauseText(run({ result_code: 'something_new' }))).toBe('something_new');
    setLocale('en');
    expect(
      runCauseText(run({ result_code: 'ring_no_result', result_params: { stage: 1, created: 3 } })),
    ).toBe('Stage 1: none of the 3 computer(s) answered.');
  });

  it('names a forbidden window, and a refusal that falls in one', () => {
    const w = { days: [0, 4], start: '07:30', end: '12:00' };
    expect(windowText(w)).toBe('lundi, vendredi 07:30–12:00');
    const refusal = {
      response: {
        status: 409,
        data: { error: { code: 'schedule.forbidden_window', details: { window: w } } },
      },
    };
    expect(apiErrorMessage(refusal)).toContain('lundi, vendredi 07:30–12:00');
    expect(apiErrorMessage(refusal)).toContain('plage interdite');
  });
});
