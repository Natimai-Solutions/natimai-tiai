import { afterEach, describe, expect, it, vi } from 'vitest';

// The summary names a command type through the commands service, which pulls
// in the HTTP client; nothing here makes a request.
vi.mock('boot/axios', () => ({ api: {} }));

import { setLocale, t } from 'src/i18n';
import auditMessages from 'src/i18n/messages/audit';
import {
  AUDIT_ACTION_LABELS,
  AUDIT_DETAIL_KEY_LABELS,
  AUDIT_RESOURCE_TYPE_LABELS,
  auditActionLabel,
  auditActionOptions,
  auditDetailKeyLabel,
  auditDetailValue,
  auditDetailsSummary,
  auditResourceTypeLabel,
  auditResourceTypeOptions,
  formatTtlMinutes,
  isKnownAuditAction,
} from './auditLabels';

afterEach(() => setLocale('fr'));

describe('audit labels — catalogue', () => {
  it('words every action, resource type and detail key in both languages', () => {
    for (const locale of ['fr', 'en'] as const) {
      setLocale(locale);
      for (const table of [
        AUDIT_ACTION_LABELS,
        AUDIT_RESOURCE_TYPE_LABELS,
        AUDIT_DETAIL_KEY_LABELS,
      ]) {
        for (const key of Object.values(table)) {
          const text = t(key);
          expect(text, `${locale} ${key}`).not.toBe(key);
          expect(text, `${locale} ${key}`).not.toBe('');
        }
      }
    }
  });

  it('keeps the same actions in both languages', () => {
    expect(Object.keys(auditMessages.en.actions)).toEqual(Object.keys(auditMessages.fr.actions));
  });

  it('knows a slug only when it names a label — not a group of them, nor a property of every object', () => {
    expect(isKnownAuditAction('machine.merge')).toBe(true);
    expect(isKnownAuditAction('machine')).toBe(false);
    expect(isKnownAuditAction('machine.merge.extra')).toBe(false);
    expect(isKnownAuditAction('toString')).toBe(false);
    expect(auditActionLabel('constructor')).toBe('constructor');
    expect(auditResourceTypeLabel('__proto__')).toBe('__proto__');
    expect(auditDetailKeyLabel('hasOwnProperty')).toBe('hasOwnProperty');
  });
});

describe('audit labels — in English', () => {
  it('labels actions, resource types and detail keys', () => {
    setLocale('en');
    expect(auditActionLabel('machine.revoke_token')).toBe('Computer token revoked');
    expect(auditActionLabel('user.reset_password')).toBe('Password reset');
    expect(auditActionLabel('robot.self_destruct')).toBe('robot.self_destruct');
    expect(auditResourceTypeLabel('machine')).toBe('Computer');
    expect(auditResourceTypeLabel('settings')).toBe('Settings');
    expect(auditDetailKeyLabel('source_hostname')).toBe('Merged page (name)');
    expect(auditDetailKeyLabel('maintenance_cycle_days')).toBe('maintenance_cycle_days');
  });

  it('sorts the action filter by its English labels', () => {
    setLocale('en');
    expect(auditActionOptions(['user.delete', 'machine.merge', 'building.create'])).toEqual([
      { value: 'user.delete', label: 'Account deleted' },
      { value: 'building.create', label: 'Building created' },
      { value: 'machine.merge', label: 'Two computer pages merged' },
    ]);
    expect(auditResourceTypeOptions()[0]).toEqual({ value: 'machine', label: 'Computer' });
  });

  it('words detail values', () => {
    setLocale('en');
    expect(auditDetailValue(true)).toBe('Yes');
    expect(auditDetailValue(false)).toBe('No');
    expect(auditDetailValue('slow_attempts', 'via')).toBe('spaced-out attempts (24 h)');
    expect(auditDetailValue('password_change', 'via')).toBe('password change');
    // A test e-mail's outcome, stored in French by the server.
    expect(auditDetailValue('oui', 'ok')).toBe('yes');
    expect(auditDetailValue('non', 'ok')).toBe('no');
    expect(auditDetailValue('oui', 'to')).toBe('oui');
    expect(auditDetailValue(1234)).toBe('1,234');
  });

  it('sums up entries', () => {
    setLocale('en');
    expect(
      auditDetailsSummary('machine.merge', { hostname: 'PC-A', source_hostname: 'PC-A-OLD' }),
    ).toBe('PC-A · absorbed “PC-A-OLD”');
    expect(auditDetailsSummary('machine.merge', { hostname: 'PC-A', source_withheld: true })).toBe(
      'PC-A · absorbed a page outside your scope',
    );
    expect(auditDetailsSummary('user.reset_password', { email: 'm@x', generated: true })).toBe(
      'm@x · password generated',
    );
    expect(auditDetailsSummary('user.reset_password', { email: 'm@x', generated: false })).toBe(
      'm@x · password typed in',
    );
    expect(auditDetailsSummary('user.update', { email: 'm@x', fields: ['full_name'] })).toBe(
      'm@x · fields: full_name',
    );
    expect(auditDetailsSummary('room.place_machines', { name: 'CDI', machine_ids: ['a'] })).toBe(
      'CDI · 1 computer',
    );
    expect(
      auditDetailsSummary('room.place_machines', { name: 'CDI', machine_ids: ['a', 'b'] }),
    ).toBe('CDI · 2 computers');
    expect(
      auditDetailsSummary('room.sync_directory', { placed: 12, unplaced: 1, rooms_created: 1 }),
    ).toBe('12 computers placed · 1 not placed · 1 room created');
    expect(auditDetailsSummary('settings.email_test', { to: 'it@x', ok: 'non' })).toBe(
      'to it@x · failed',
    );
    expect(auditDetailsSummary('settings.email_test', { to: 'it@x', ok: 'oui' })).toBe(
      'to it@x · sent',
    );
    expect(
      auditDetailsSummary('machine.wake_bulk', { machine_ids: ['a', 'b'], woken: 2, failed: 1 }),
    ).toBe('2 computers · 2 sent · 1 failed');
    expect(
      auditDetailsSummary('machine.wake_bulk', { machine_ids: ['a'], woken: 1, relayed: true }),
    ).toBe('1 computer · 1 handed to a relay');
  });

  it('sums up a bulk command, whatever its target', () => {
    setLocale('en');
    const base = { command_type: 'teleport', created: 3, skipped: 2, ttl_minutes: 2880 };
    const tail = '3 created · 2 skipped, already in progress · valid for 2 d';
    expect(auditDetailsSummary('command.bulk', { ...base, target: 'all' })).toBe(
      `teleport · the whole fleet · ${tail}`,
    );
    expect(
      auditDetailsSummary('command.bulk', { ...base, target: 'domain', domain: 'LYCEE' }),
    ).toBe(`teleport · domain “LYCEE” · ${tail}`);
    expect(auditDetailsSummary('command.bulk', { ...base, target: 'domain', domain: '' })).toBe(
      `teleport · computers outside any domain · ${tail}`,
    );
    expect(
      auditDetailsSummary('command.bulk', { ...base, target: 'location', location: 'Taravao' }),
    ).toBe(`teleport · location “Taravao” · ${tail}`);
    expect(
      auditDetailsSummary('command.bulk', { ...base, target: 'status', status: 'outdated' }),
    ).toBe(`teleport · computers not up to date · ${tail}`);
    expect(
      auditDetailsSummary('command.bulk', { ...base, target: 'status', status: 'quantum' }),
    ).toBe(`teleport · computers quantum · ${tail}`);
    expect(auditDetailsSummary('command.bulk', { ...base, target: 'machines', requested: 1 })).toBe(
      `teleport · 1 listed computer · ${tail}`,
    );
  });

  it('writes a lifetime in its largest unit', () => {
    setLocale('en');
    expect(formatTtlMinutes(45)).toBe('45 min');
    expect(formatTtlMinutes(60)).toBe('1 h');
    expect(formatTtlMinutes(1440)).toBe('1 d');
  });
});

describe('audit labels — the language changes under them', () => {
  it('follows the language of the moment, not the one at load', () => {
    expect(auditActionLabel('machine.merge')).toBe('Fusion de deux fiches poste');
    setLocale('en');
    expect(auditActionLabel('machine.merge')).toBe('Two computer pages merged');
    setLocale('fr');
    expect(auditActionLabel('machine.merge')).toBe('Fusion de deux fiches poste');
  });

  it('keeps the French summary word for word', () => {
    expect(auditDetailsSummary('room.place_machines', { name: 'CDI', machine_ids: ['a'] })).toBe(
      'CDI · 1 poste(s)',
    );
    expect(auditDetailValue('oui', 'ok')).toBe('oui');
  });
});
