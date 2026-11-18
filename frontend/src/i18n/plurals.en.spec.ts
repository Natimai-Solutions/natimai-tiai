import { afterEach, describe, expect, it } from 'vitest';
import { setLocale, t } from 'src/i18n';
import { commandMessage } from 'src/services/commands';
import { cpuLabel } from 'src/utils/format';

/**
 * English counts agree with their number; the French, single-form as it
 * always was, reads the same with or without the count (verification of
 * 2026-11-18).
 */
afterEach(() => setLocale('fr'));

describe('counts in English', () => {
  it('agree with one and with several', () => {
    setLocale('en');
    expect(t('format.cpu.cores', { count: 1 }, 1)).toBe('1 core');
    expect(t('format.cpu.threads', { count: 8 }, 8)).toBe('8 threads');
    expect(t('machine.alerts.defenderSignatures', { days: 1 }, 1)).toBe(
      'Defender: signatures 1 day old',
    );
    expect(t('machine.alerts.inventoryStale', { days: 40 }, 40)).toContain('40 days old');
    expect(t('account.passwordPolicy.minutes', { count: 1 }, 1)).toBe('1 minute');
    expect(t('rooms.placement.mismatch', { moved: 'X', count: 1 }, 1)).toBe(
      'X — of which 1 reports another location than the room',
    );
    expect(commandMessage('wu.install_incomplete', { failed: 1, selected: 3 })).toBe(
      '1 of 3 updates was not installed',
    );
    expect(commandMessage('wu.install_incomplete', { failed: 2, selected: 3 })).toBe(
      '2 of 3 updates were not installed',
    );
  });

  it('leave the French as it was', () => {
    expect(t('format.cpu.cores', { count: 1 }, 1)).toBe('1 cœurs');
    expect(t('machine.alerts.defenderSignatures', { days: 1 }, 1)).toBe(
      t('machine.alerts.defenderSignatures', { days: 1 }),
    );
    expect(t('account.passwordPolicy.minutes', { count: 1 }, 1)).toBe('1 minutes');
    expect(commandMessage('wu.install_incomplete', { failed: 1, selected: 3 })).toBe(
      "1 mise(s) à jour sur 3 n'ont pas été installées",
    );
    expect(typeof cpuLabel).toBe('function');
  });
});
