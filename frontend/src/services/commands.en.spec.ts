import { afterEach, describe, expect, it, vi } from 'vitest';
import { setLocale } from 'src/i18n';

vi.mock('boot/axios', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import {
  bulkSendNotification,
  commandActionGroups,
  commandActions,
  commandConfirm,
  commandGroupLabels,
  commandRowLabel,
  commandStatusLabel,
  commandTypeLabel,
  singleSendNotification,
} from './commands';

afterEach(() => setLocale('fr'));

const FRENCH = /[éèàùçâêîôû«»]|\bposte|\blancer\b/i;

function action(type: string) {
  const found = commandActions.find((a) => a.type === type);
  if (!found) throw new Error(type);
  return found;
}

describe('the command catalogue in English', () => {
  it('labels every action, hint and group in English', () => {
    setLocale('en');
    for (const a of commandActions) {
      expect(a.label, a.type).not.toMatch(FRENCH);
      if (a.confirm) expect(a.hint, a.type).not.toMatch(FRENCH);
    }
    for (const section of commandActionGroups()) {
      expect(section.label).not.toMatch(FRENCH);
    }
    expect(action('flush_dns').label).toBe('Flush the DNS cache');
    expect(commandGroupLabels.power).toBe('Power');
    expect(commandTypeLabel('package_install')).toBe('Software installation');
    expect(commandTypeLabel('install_package')).toBe('install_package');
    expect(commandRowLabel({ type: 'package_uninstall', package_name: '7-Zip 23.01' })).toBe(
      'Software uninstallation — 7-Zip 23.01',
    );
    expect(commandStatusLabel('failed')).toBe('Failed');
    expect(commandStatusLabel('unknown_status')).toBe('unknown_status');
  });

  it('follows a change of language, menus built before it included', () => {
    const groups = commandActionGroups();
    const flush = action('flush_dns');
    expect(flush.label).toBe('Vider le cache DNS');
    expect(groups.find((g) => g.group === 'power')?.label).toBe('Alimentation');
    setLocale('en');
    expect(flush.label).toBe('Flush the DNS cache');
    expect(groups.find((g) => g.group === 'power')?.label).toBe('Power');
    expect(commandGroupLabels.inventory).toBe('Inventory');
  });

  it('keeps the French catalogue as it was', () => {
    expect(commandGroupLabels.inventory).toBe('Inventaire');
    expect(action('reboot').label).toBe('Redémarrer le poste');
    expect(commandStatusLabel('expired')).toBe('Expirée');
  });
});

describe('confirmations and notifications in English', () => {
  it('asks before a restart, the button saying what it does', () => {
    setLocale('en');
    const c = commandConfirm(action('reboot'), 12, 3);
    expect(c.title).toBe('Restart the computer');
    expect(c.ok.label).toBe('Restart 12 computers');
    expect(c.message).toContain('Run “Restart the computer” on 12 computers?');
    expect(c.message).toContain('Of which 3 with a user signed in.');
    expect(c.cancel.label).toBe('Cancel');
    expect(c.message).not.toMatch(FRENCH);

    const one = commandConfirm(action('shutdown'), 1, 1);
    expect(one.ok.label).toBe('Shut down the computer');
    expect(one.message).toContain('A user is signed in on this computer.');
    expect(commandConfirm(action('full_scan'), 4).ok.label).toBe('Run on 4 computers');
    expect(commandConfirm(action('full_scan'), 1).ok.label).toBe('Run');
  });

  it('says what a send did', () => {
    setLocale('en');
    expect(bulkSendNotification({ created: ['a'], count: 1 }).message).toBe('1 command sent');
    expect(bulkSendNotification({ created: ['a', 'b'], count: 2, skipped: 3, revoked: 1 })).toEqual(
      {
        type: 'warning',
        message: '2 commands sent — 3 already pending, 1 with a revoked token, skipped',
      },
    );
    expect(bulkSendNotification({ created: [], count: 0, skipped: 340, revoked: 1 }).message).toBe(
      'Nothing to send: this command is already pending on 340 computers; 1 computer with a revoked token.',
    );
    const flush = action('flush_dns');
    expect(singleSendNotification(flush, { created: ['x'], count: 1 }).message).toBe(
      'Command sent',
    );
    expect(
      singleSendNotification(flush, { created: [], count: 0, skipped: 1, reason: 'running' })
        .message,
    ).toBe('“Flush the DNS cache” is already running on this computer.');
    expect(singleSendNotification(flush, { created: [], count: 0, revoked: 1 }).message).toBe(
      '“Flush the DNS cache” not sent: this computer’s token is revoked.',
    );
  });

  it('keeps the French notifications word for word', () => {
    expect(bulkSendNotification({ created: [], count: 0, skipped: 2, revoked: 1 }).message).toBe(
      'Rien à envoyer : cette commande est déjà en attente sur 2 poste(s) ; 1 poste(s) au token révoqué.',
    );
    expect(bulkSendNotification({ created: [], count: 0 }).message).toBe(
      '0 commande(s) envoyée(s)',
    );
    expect(bulkSendNotification({ created: ['a'], count: 1, skipped: 1 }).message).toBe(
      '1 commande(s) envoyée(s) — 1 déjà en attente, ignoré(s)',
    );
  });
});
