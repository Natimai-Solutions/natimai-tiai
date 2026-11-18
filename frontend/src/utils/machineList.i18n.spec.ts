import { afterEach, describe, expect, it, vi } from 'vitest';

// The service's notifications are pure; its requests are not exercised here.
vi.mock('boot/axios', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { setLocale } from 'src/i18n';
import { approveReenrollNotification, wakeNotification } from 'src/services/machines';
import { chassisLabelOf } from 'src/composables/useMachineFleetOptions';
import {
  DISK_OPTIONS,
  STATUS_OPTIONS,
  diskOptionsFor,
  emptyMachineFilters,
  initialFleetOptions,
  machineFilterChips,
  unmatchedExactFilters,
} from 'src/utils/machineListFilters';
import {
  MACHINE_COLUMN_LABELS,
  MACHINE_TABLE_COLUMNS,
  antivirusTooltip,
  visibleMachineColumns,
} from 'src/utils/machineListTable';
import { hoursLabel, usageFilterLabel, usageSettingsError } from 'src/utils/usageFilter';
import { machineDetail } from 'src/test/fixtures';

/**
 * The machine list's utilities in English (plan `dev/plan-console-bilingue.md`,
 * I6) — and in French where a text is put together from pieces. The French
 * texts themselves are asserted by each utility's own spec.
 */

const FRENCH = /[éèàùçêô«»]/;

afterEach(() => setLocale('fr'));

describe('the usage filter', () => {
  it('writes hours and the chip in English', () => {
    setLocale('en');
    expect(hoursLabel(12.4)).toBe('12.4 h');
    expect(usageFilterLabel({ below: 10, above: null }, 7)).toBe('On less than 10 h over 7 d');
    expect(usageFilterLabel({ below: null, above: 30 }, null)).toBe('On more than 30 h');
    expect(usageFilterLabel({ below: 30, above: 10 }, 28)).toBe(
      'On between 10 h and 30 h over 28 d',
    );
    expect(usageFilterLabel({ below: null, above: null }, 7)).toBe('Usage');
  });

  it('says why settings are refused, in either language', () => {
    expect(usageSettingsError(7, 10, 200)).toBe(
      'Le seuil « toujours allumé » dépasse les 168 heures que compte la fenêtre.',
    );
    setLocale('en');
    expect(usageSettingsError(0, 1, 2)).toBe(
      'The window must be a whole number of days, from 1 to 90.',
    );
    expect(usageSettingsError(7, 10, 5)).toBe(
      'The “rarely used” threshold must stay below the “always on” threshold.',
    );
    expect(usageSettingsError(7, 10, 200)).toBe(
      'The “always on” threshold exceeds the 168 hours in the window.',
    );
  });
});

describe('the filter dropdowns and chips', () => {
  it('word the constant dropdowns in the language shown, the same list instance', () => {
    const status = STATUS_OPTIONS;
    expect(status[1]!.label).toBe('Antivirus à jour');
    setLocale('en');
    expect(STATUS_OPTIONS).toBe(status);
    expect(status.map((o) => o.label)).toEqual([
      'Antivirus: all statuses',
      'Antivirus up to date',
      'Antivirus outdated',
      'Identity to confirm',
      'Inactive',
    ]);
    expect(diskOptionsFor(15).map((o) => o.label)).toEqual([
      'Disk space: all',
      'Less than 10% free',
      'Less than 15% free',
      'Less than 20% free',
    ]);
    expect(diskOptionsFor(20)).toBe(DISK_OPTIONS);
  });

  it('keep the words in a copy of an entry, as a comparison sees them', () => {
    setLocale('en');
    expect(JSON.stringify(initialFleetOptions().agent)).toBe(
      '[{"label":"Agent: all versions","value":null}]',
    );
  });

  it('name every chip in English', () => {
    setLocale('en');
    const f = {
      ...emptyMachineFilters(),
      domain: 'LYCEE',
      status: 'outdated' as const,
      ramOp: 'min' as const,
      ramGb: 16,
      diskFree: 10,
      usageBelow: 10,
      softwareId: 4,
      aging: 'true' as const,
      enrollment: 'pending' as const,
      maintenance: 'due_soon',
      scan: 'both:30',
    };
    const labels = machineFilterChips(f, initialFleetOptions(), 7).map((c) => c.label);
    expect(labels).toEqual([
      'Domain: LYCEE',
      'Re-enrolment to allow',
      'Maintenance due soon',
      'Antivirus outdated',
      'Both scans > 1 month',
      'Memory ≥ 16 GiB',
      'Less than 10% free',
      'On less than 10 h over 7 d',
      'Computers with a given program',
      'Hardware due for renewal',
    ]);
    for (const label of labels) expect(label).not.toMatch(FRENCH);
  });

  it('names an unmatched facet in English', () => {
    setLocale('en');
    const options = initialFleetOptions();
    options.model = [...options.model, { label: 'OptiPlex 7010 (3)', value: 'OptiPlex 7010' }];
    const f = { ...emptyMachineFilters(), model: 'OptiPlex' };
    expect(unmatchedExactFilters(f, options)).toEqual([
      { key: 'model', facet: 'Model', value: 'OptiPlex' },
    ]);
  });

  it('names the chassis kinds in English', () => {
    setLocale('en');
    expect(chassisLabelOf('all-in-one')).toBe('All-in-one');
    expect(chassisLabelOf('desktop')).toBe('Desktop');
    expect(chassisLabelOf('boat')).toBe('boat');
  });
});

describe('the table columns', () => {
  it('head every column in English, and follow a change of language', () => {
    expect(MACHINE_COLUMN_LABELS.last_seen).toBe('Vu le');
    setLocale('en');
    expect(MACHINE_COLUMN_LABELS.last_seen).toBe('Last seen');
    expect(MACHINE_COLUMN_LABELS.agent).toBe('Agent version');
    const labels = MACHINE_TABLE_COLUMNS.map((c) => c.label);
    expect(labels).toContain('IP address');
    for (const label of labels) expect(label).not.toMatch(FRENCH);
    const [usage] = visibleMachineColumns(['usage'], 28);
    expect(usage!.label).toBe('Hours on (28 d)');
    // A copy of a column carries the words of the moment, as the q-table's do.
    expect({ ...MACHINE_TABLE_COLUMNS[0]! }.label).toBe('Name');
    setLocale('fr');
    expect(usage!.label).toBe('Allumé (28 j)');
  });

  it('writes the antivirus tooltip’s signature version in English', () => {
    setLocale('en');
    expect(antivirusTooltip({ ...machineDetail(), signature_version: '1.401.2' })).toMatch(
      / · signatures 1\.401\.2$/,
    );
  });
});

describe('the bulk notifications', () => {
  it('say what a re-enrolment did, in English, with plurals', () => {
    setLocale('en');
    expect(approveReenrollNotification({ approved: 0, skipped: 2 }).message).toBe(
      'No re-enrolment to allow among the selected computers.',
    );
    expect(approveReenrollNotification({ approved: 1, skipped: 0 }).message).toBe(
      'Re-enrolment allowed for 1 computer',
    );
    expect(approveReenrollNotification({ approved: 3, skipped: 1 }).message).toBe(
      'Re-enrolment allowed for 3 computers — 1 without a pending request, skipped',
    );
  });

  it('say what a wake did, in English', () => {
    setLocale('en');
    expect(wakeNotification({ results: [], woken: 4, failed: 0 }).message).toBe(
      'Wake packet sent to 4 computers — the computer will report in when it next starts',
    );
    expect(wakeNotification({ results: [], woken: 1, failed: 2 }).message).toBe(
      'Wake packet sent to 1 computer — 2 with no known target',
    );
    expect(wakeNotification({ results: [], woken: 2, failed: 1, relayed: true }).message).toBe(
      'Wake handed to the neighbouring computers of 2 computers — 1 with no target or relay',
    );
    expect(wakeNotification({ results: [], woken: 0, failed: 5 }).message).toBe(
      'Wake failed on 5 computers: no packet sent.',
    );
    // The server's own reason is quoted as it comes.
    const only = { machine_id: 'a', hostname: 'PC-01', ok: false, detail: 'no MAC known' };
    expect(wakeNotification({ results: [only], woken: 0, failed: 1 }).message).toBe(
      'Wake failed: no MAC known',
    );
  });

  it('keep the French sentences as they were', () => {
    expect(approveReenrollNotification({ approved: 3, skipped: 1 }).message).toBe(
      'Ré-enrôlement autorisé pour 3 poste(s) — 1 sans demande en attente, ignoré(s)',
    );
    expect(wakeNotification({ results: [], woken: 2, failed: 1, relayed: true }).message).toBe(
      'Réveil confié aux postes voisins de 2 poste(s) — 1 sans cible ni relais',
    );
  });
});
