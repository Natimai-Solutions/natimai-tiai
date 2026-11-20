import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { alertDetailText, alertRuleLabel, checkInstructionsText, isAlertRule } from './alerts';

describe('alerts wording', () => {
  afterEach(() => setLocale('fr'));

  it('names each rule, and an unknown one as it is', () => {
    expect(alertRuleLabel('disk_low')).toBe('Disque système presque plein');
    expect(alertRuleLabel('retired_rule')).toBe('retired_rule');
    expect(isAlertRule('inactive')).toBe(true);
    expect(isAlertRule('nope')).toBe(false);
  });

  it('words the detail of each rule', () => {
    expect(
      alertDetailText('disk_low', { free_percent: 4.5, threshold_percent: 10, free_mb: 900 }),
    ).toBe('4.5 % libres (seuil : 10 %)');
    expect(
      alertDetailText('disk_unhealthy', { disks: [{ model: 'WD Blue', health: 'Warning' }] }),
    ).toBe('WD Blue (Warning)');
    expect(alertDetailText('volume_unencrypted', { letter: 'C:', status: 'FullyDecrypted' })).toBe(
      'Volume C: — FullyDecrypted',
    );
    expect(alertDetailText('reboot_pending', { since: '2026-11-02T20:00:00+00:00' })).toBe(
      'Demandé par Windows Update le 02/11/2026',
    );
    expect(
      alertDetailText('os_unsupported', {
        os_version: 'Windows 10 Pro 22H2 (Build 19045)',
        end_of_support: '2025-10-14',
      }),
    ).toBe('Windows 10 Pro 22H2 (Build 19045), plus mis à jour depuis le 14/10/2025');
    expect(
      alertDetailText('os_unsupported', { os_version: 'Windows 10 Pro', end_of_support: null }),
    ).toBe('Windows 10 Pro, plus mis à jour');
    expect(
      alertDetailText('forbidden_software', {
        programs: [{ name: 'uTorrent' }, { name: 'BitComet' }],
        count: 5,
      }),
    ).toBe('uTorrent, BitComet et 3 autre(s)');
    expect(alertDetailText('inactive', { last_seen: '2026-10-01T10:00:00+00:00' })).toBe(
      'Dernier contact le 01/10/2026',
    );
    // A missing detail does not throw.
    expect(alertDetailText('disk_low', null)).toBe('? % libres (seuil : ? %)');
  });

  it('dates an instant by the reader’s day, a calendar date as written', () => {
    // 04:00 UTC on the 20th is 18:00 on the 19th in Papeete (the suite's
    // zone): the reader last saw the poste on the 19th.
    expect(alertDetailText('inactive', { last_seen: '2026-11-20T04:00:00+00:00' })).toBe(
      'Dernier contact le 19/11/2026',
    );
    expect(alertDetailText('reboot_pending', { since: '2026-11-20T04:00:00+00:00' })).toBe(
      'Demandé par Windows Update le 19/11/2026',
    );
    expect(alertDetailText('warranty_ending', { warranty_end: '2026-12-01' })).toBe(
      'Garantie jusqu’au 01/12/2026',
    );
  });

  it('says the warranty ends within the threshold when the date is not sent', () => {
    // A reader without asset:read, or a verification.
    expect(alertDetailText('warranty_ending', { threshold_days: 30 })).toBe(
      'Garantie terminée dans moins de 30 jours',
    );
    expect(alertDetailText('warranty_ending', { threshold_days: 1 })).toBe(
      'Garantie terminée dans moins de 1 jour',
    );
    setLocale('en');
    expect(alertDetailText('warranty_ending', { threshold_days: 30 })).toBe(
      'Warranty ends within 30 days',
    );
    expect(alertDetailText('warranty_ending', { threshold_days: 1 })).toBe(
      'Warranty ends within 1 day',
    );
  });

  it('words in English', () => {
    setLocale('en');
    expect(alertRuleLabel('os_unsupported')).toBe('Windows out of support');
    expect(alertDetailText('inactive', { last_seen: '2026-10-01T10:00:00+00:00' })).toBe(
      'Last contact on 01/10/2026',
    );
  });

  it('words a verification the server opened, and leaves a typed one alone', () => {
    expect(
      checkInstructionsText({
        instructions: 'Alerte : …',
        instructions_code: 'alert.disk_low',
        instructions_params: { free_percent: 2, threshold_percent: 10 },
      }),
    ).toBe('Alerte : Disque système presque plein — 2 % libres (seuil : 10 %)');
    expect(checkInstructionsText({ instructions: 'Changer la souris' })).toBe('Changer la souris');
    // An unknown code falls back to the server's French.
    expect(
      checkInstructionsText({ instructions: 'Texte serveur', instructions_code: 'alert.nope' }),
    ).toBe('Texte serveur');
  });
});
