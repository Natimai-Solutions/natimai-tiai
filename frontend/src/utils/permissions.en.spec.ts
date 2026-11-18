import { afterEach, describe, expect, it, vi } from 'vitest';

// The password policy composable reads the server through the HTTP client;
// nothing here makes a request.
vi.mock('boot/axios', () => ({ api: {} }));

import { setLocale } from 'src/i18n';
import { durationLabel } from 'src/composables/usePasswordPolicy';
import { moreRightsAccount, moreRightsGroup } from './authority';
import { PERMISSION_CATALOGUE, permissionLabel, permissionRows } from './permissions';
import { describeUserAgent } from './userAgent';

afterEach(() => setLocale('fr'));

const FIREFOX_WINDOWS =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0';

describe('the permission grid', () => {
  it('reads in French as before', () => {
    const rows = permissionRows();
    expect(rows.map((r) => r.resourceLabel)).toEqual([
      'Postes',
      'Menaces',
      'Commandes',
      'Commandes à risque',
      'Salles et bâtiments',
      'Historique des interventions',
      'Vérifications demandées',
      'Maintenance',
      'Paramètres',
      'Comptes et groupes',
      "Journal d'audit",
      'Paquets logiciels',
    ]);
    const machine = rows[0]!.entries;
    expect(machine.map((e) => [e.key, e.label, e.hint])).toEqual([
      [
        'machine:read',
        'Consulter',
        'Le tableau de bord, la liste et la fiche des postes, les logiciels, les exports.',
      ],
      [
        'machine:write',
        'Gérer',
        'Révoquer un token, autoriser un ré-enrôlement, fusionner des doublons.',
      ],
    ]);
    // No hint where the label says it all.
    expect(rows[1]!.entries[0]!.hint).toBeUndefined();
    expect(permissionLabel('command:read')).toBe("Commandes — consulter l'historique");
    expect(permissionLabel('nope:read')).toBe('nope:read');
  });

  it('reads in English, every permission worded', () => {
    setLocale('en');
    const rows = permissionRows();
    expect(rows[0]!.resourceLabel).toBe('Computers');
    expect(rows[0]!.entries[1]!.label).toBe('Manage');
    expect(rows[0]!.entries[1]!.hint).toBe(
      'Revoke a token, allow a re-enrolment, merge duplicates.',
    );
    expect(permissionLabel('risky_command:execute')).toBe(
      'Risky commands — run the risky commands',
    );
    const entries = rows.flatMap((r) => r.entries);
    expect(entries.map((e) => e.key)).toEqual(PERMISSION_CATALOGUE.map((e) => e.key));
    for (const entry of entries) {
      expect(`${entry.resourceLabel} ${entry.label} ${entry.hint ?? ''}`).not.toMatch(/[éèàùç«»]/);
    }
  });
});

describe('what a manager may not lay hands on', () => {
  it('says so in the language shown', () => {
    expect(moreRightsAccount()).toBe('Ce compte détient plus de droits que vous');
    expect(moreRightsGroup()).toBe('Ce groupe accorde plus de droits que vous n’en détenez');
    setLocale('en');
    expect(moreRightsAccount()).toBe('This account holds more permissions than you');
    expect(moreRightsGroup()).toBe('This group grants more permissions than you hold');
  });
});

describe('describeUserAgent in English', () => {
  it('names the device', () => {
    setLocale('en');
    expect(describeUserAgent(FIREFOX_WINDOWS)).toBe('Firefox on Windows');
    expect(describeUserAgent('SomeClient (Windows NT 10.0)')).toBe('Browser on Windows');
    expect(describeUserAgent('Firefox/140.0')).toBe('Firefox');
    expect(describeUserAgent(null)).toBe('Unknown device');
    expect(describeUserAgent('curl/8.5.0')).toBe('Unknown device');
  });
});

describe('durationLabel — a reset link’s lifetime', () => {
  it('reads in French as before', () => {
    expect(durationLabel(60)).toBe('une heure');
    expect(durationLabel(120)).toBe('2 heures');
    expect(durationLabel(30)).toBe('30 minutes');
  });

  it('reads in English', () => {
    setLocale('en');
    expect(durationLabel(60)).toBe('one hour');
    expect(durationLabel(120)).toBe('2 hours');
    expect(durationLabel(30)).toBe('30 minutes');
  });
});
