import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { bulkCheckNotification, closingNoteText, formerAssigneeNote } from './checks';
import { interventionHeading, interventionKindLabel, interventionTitle } from './interventions';
import {
  cycleLabel,
  dueLabel,
  maintenanceStateLabel,
  originLabel,
  ownerLabel,
} from './maintenance';
import {
  placementNotification,
  roomSourceLabel,
  syncNotification,
  syncPreviewMessage,
} from './rooms';

/**
 * What the rooms, maintenance, checks and journal services say, in both
 * languages (plan console bilingue, lot D). The French cases are those the
 * services' own specs already pin; here, the English, and the texts the
 * server stores under a code.
 */

afterEach(() => setLocale('fr'));

describe('rooms', () => {
  const done = { placed: 3, unplaced: 1, rooms_created: 2 };

  it('words a re-sync in English', () => {
    setLocale('en');
    expect(syncNotification(done)).toEqual({
      type: 'positive',
      message: 'Computers filed: 3, removed: 1; rooms created: 2',
    });
    const rooms = Array.from({ length: 7 }, (_, i) => `S${i + 1}`);
    const n = syncNotification({ ...done, undecided: 1, undecided_rooms: rooms });
    expect(n.message).toBe(
      'Computers filed: 3, removed: 1; rooms created: 2 — 1 computer left where it was',
    );
    expect(n.caption).toBe(
      'No organisational unit holds a majority for “S1”, “S2”, “S3”, “S4”, “S5” and other rooms. Rename the room created by hand, then sync again: the computers will go to the room of their organisational unit.',
    );
    expect(n.actions).toEqual([{ label: 'Close', color: 'white' }]);
    expect(syncNotification({ ...done, undecided: 4 }).message).toContain(
      '4 computers left where they were',
    );
    expect(syncNotification({ ...done, undecided: 4 }).caption).toMatch(
      /^No organisational unit holds a majority\. /,
    );
  });

  it('words the dry run in English', () => {
    setLocale('en');
    expect(
      syncPreviewMessage({ ...done, moved_out: 5, undecided: 2, undecided_rooms: ['B12'] }),
    ).toBe(
      'Computers that will change room: 5; rooms that will be created: 2. Of which 1 taken out of any room. 2 computers will stay where they are (undecided room). Computers without any directory information stay where they are. Start the re-sync?',
    );
  });

  it('words a placement in both languages', () => {
    expect(placementNotification({ moved: 1, mismatched: ['a'] }).message).toBe(
      "1 poste(s) affecté(s) — 1 dont l'agent déclare un autre emplacement que la salle",
    );
    setLocale('en');
    expect(placementNotification({ moved: 1, mismatched: [] }).message).toBe('1 computer placed');
    expect(placementNotification({ moved: 3, mismatched: ['a', 'b'] }).message).toBe(
      '3 computers placed — of which 2 report another location than the room',
    );
  });

  it('names the placement mode, an unknown one as is', () => {
    expect(roomSourceLabel('ad_ou')).toBe("par l'unité d'organisation de l'objet ordinateur");
    setLocale('en');
    expect(roomSourceLabel('manual')).toBe('by hand, from the console');
    expect(roomSourceLabel('ad_location')).toBe('by the Location attribute of the computer object');
    expect(roomSourceLabel('ad_site')).toBe('ad_site');
  });
});

describe('maintenance', () => {
  const now = new Date('2026-11-11T12:00:00Z');

  it('words a due date in English', () => {
    setLocale('en');
    expect(dueLabel('2026-11-01T12:00:00Z', now)).toBe('10 days overdue');
    expect(dueLabel('2026-11-10T11:00:00Z', now)).toBe('1 day overdue');
    expect(dueLabel('2026-11-11T08:00:00Z', now)).toBe('overdue since today');
    expect(dueLabel('2026-12-24T12:00:00Z', now)).toMatch(/^due on \d{2}\/\d{2}\/2026$/);
  });

  it('names states, origins, cycles and owners in English', () => {
    setLocale('en');
    expect(maintenanceStateLabel('overdue')).toBe('Overdue');
    expect(maintenanceStateLabel('due_soon')).toBe('Due soon');
    expect(maintenanceStateLabel('ok')).toBe('Up to date');
    expect(maintenanceStateLabel('excluded')).toBe('Excluded');
    expect(maintenanceStateLabel('odd')).toBe('odd');
    expect(originLabel('machine')).toBe("the computer's own");
    expect(cycleLabel(90, 'room')).toBe('90 days (from the room)');
    expect(cycleLabel(1, 'global')).toBe('1 day (fleet default)');
    expect(cycleLabel(0, 'machine')).toBe("excluded from maintenance (the computer's own)");
    expect(ownerLabel({ id: 'u', name: 'Mary', active: false })).toBe('Mary (deactivated)');
  });

  it('keeps the French of a one-day cycle as it was', () => {
    expect(cycleLabel(1, 'global')).toBe('1 jours (défaut du parc)');
    expect(dueLabel('2026-11-10T11:00:00Z', now)).toBe('en retard depuis 1 jour');
  });
});

describe('checks', () => {
  it('words a former assignee and a bulk request in English', () => {
    setLocale('en');
    expect(formerAssigneeNote({ id: 'u', name: 'Mary', reachable: false })).toBe(
      'Mary can no longer see this computer',
    );
    expect(formerAssigneeNote({ id: 'u', name: 'Paul', active: false, reachable: false })).toBe(
      'Paul, deactivated',
    );
    expect(bulkCheckNotification({ created: 1, skipped: 0 }).message).toBe('1 check requested');
    expect(bulkCheckNotification({ created: 2, skipped: 3 }).message).toBe(
      '2 checks requested — 3 computers already had one open',
    );
  });

  it('words a closing note the server wrote, and leaves a typed one as is', () => {
    const merged = {
      closing_note: 'Fermée par la fusion du poste dans un autre.',
      closing_note_code: 'check.closed.merged',
    };
    expect(closingNoteText(merged)).toBe('Fermée par la fusion du poste dans un autre.');
    setLocale('en');
    expect(closingNoteText(merged)).toBe('Closed when the computer was merged into another.');
    // An older server, a code this console does not know, a note typed.
    expect(closingNoteText({ closing_note: 'Fermée par la fusion du poste dans un autre.' })).toBe(
      'Fermée par la fusion du poste dans un autre.',
    );
    expect(closingNoteText({ closing_note: 'x', closing_note_code: 'check.closed.new' })).toBe('x');
    expect(closingNoteText({ closing_note: 'Cable', closing_note_code: null })).toBe('Cable');
  });
});

describe('interventions', () => {
  it('names the kinds in English', () => {
    setLocale('en');
    expect(interventionKindLabel('incident')).toBe('Fault / incident');
    expect(interventionKindLabel('verification')).toBe('Check');
    expect(interventionKindLabel('verification', 'fr')).toBe('Vérification');
    expect(interventionKindLabel('unknown')).toBe('unknown');
  });

  it('words a title the server wrote, and leaves the others as stored', () => {
    const skipped = {
      title: 'Maintenance non faite — A101',
      title_code: 'maintenance.skipped',
      title_params: { room: 'A101' },
    };
    expect(interventionTitle(skipped)).toBe('Maintenance non faite — A101');
    setLocale('en');
    expect(interventionTitle(skipped)).toBe('Maintenance not done — A101');
    expect(
      interventionTitle({ title: 'Maintenance non faite', title_code: 'maintenance.skipped' }),
    ).toBe('Maintenance not done');
    expect(interventionTitle({ title: 'Old', title_code: 'maintenance.other' })).toBe('Old');
    expect(interventionTitle({ title: 'Disk swap' })).toBe('Disk swap');
  });

  it('heads a line in English, without repeating a French kind written before the codes', () => {
    setLocale('en');
    expect(interventionHeading({ kind: 'verification', title: 'Vérification' })).toBe('Check');
    expect(interventionHeading({ kind: 'verification', title: 'Vérification — écran' })).toBe(
      'Check — écran',
    );
    expect(interventionHeading({ kind: 'maintenance', title: 'Maintenance — A101' })).toBe(
      'Maintenance — A101',
    );
    expect(interventionHeading({ kind: 'incident', title: null })).toBe('Fault / incident');
    expect(
      interventionHeading({
        kind: 'other',
        title: 'Maintenance non faite — B12',
        title_code: 'maintenance.skipped',
        title_params: { room: 'B12' },
      }),
    ).toBe('Other — Maintenance not done — B12');
  });
});

/**
 * The texts the server stores beside a code: the console's French is the
 * server's, word for word — `backend/tests/test_journal_texts.py` checks the
 * same file against what the server writes.
 */
describe('journal texts shared with the server', () => {
  const cases = JSON.parse(
    readFileSync(
      new URL('../../../backend/tests/data/journal_texts_fr.json', import.meta.url),
      'utf-8',
    ),
  ) as { kind: string; code: string; params: Record<string, unknown>; text: string }[];

  it.each(cases)('$kind $code $params', (c) => {
    const worded =
      c.kind === 'closing_note'
        ? closingNoteText({ closing_note: null, closing_note_code: c.code })
        : interventionTitle({ title: null, title_code: c.code, title_params: c.params });
    expect(worded).toBe(c.text);
  });

  it('covers every code the console words', () => {
    expect(new Set(cases.map((c) => c.code))).toEqual(
      new Set(['maintenance.skipped', 'check.closed.merged']),
    );
  });
});
