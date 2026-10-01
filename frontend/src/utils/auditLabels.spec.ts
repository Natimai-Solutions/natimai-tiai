import { describe, expect, it } from 'vitest';

import {
  AUDIT_ACTION_LABELS,
  auditActionLabel,
  auditActionOptions,
  auditDetailKeyLabel,
  auditDetailValue,
  auditDetailsSummary,
  auditResourceLink,
  auditResourceTypeLabel,
  isUuid,
} from './auditLabels';

const MACHINE_ID = '0d4c1a52-7e1b-4c4f-9a35-2b1f0c9e11aa';

describe('auditActionLabel', () => {
  it('labels a known action in French', () => {
    expect(auditActionLabel('machine.revoke_token')).toBe("Révocation du token d'un poste");
  });

  it('labels the two newest actions', () => {
    expect(auditActionLabel('machine.merge')).toBe('Fusion de deux fiches poste');
    expect(auditActionLabel('user.reset_password')).toBe("Réinitialisation d'un mot de passe");
  });

  // An action added server-side before the console knows it must stay readable.
  it('falls back on the raw slug for an unknown action', () => {
    expect(auditActionLabel('robot.self_destruct')).toBe('robot.self_destruct');
  });

  it('covers every slug the backend records', () => {
    const slugs = [
      'building.create',
      'building.update',
      'building.delete',
      'check.update',
      'group.create',
      'group.update',
      'group.delete',
      'intervention.update',
      'intervention.delete',
      'machine.allow_reenroll',
      'machine.revoke_token',
      'machine.merge',
      'maintenance.machine_settings',
      'maintenance.room_settings',
      'room.create',
      'room.update',
      'room.delete',
      'room.place_machines',
      'room.sync_directory',
      'room.unassign_machines',
      'settings.update',
      'user.create',
      'user.update',
      'user.delete',
      'user.reset_password',
    ];
    expect(Object.keys(AUDIT_ACTION_LABELS).sort()).toEqual([...slugs].sort());
  });
});

describe('auditResourceTypeLabel', () => {
  it('labels known resource types', () => {
    expect(auditResourceTypeLabel('machine')).toBe('Poste');
    expect(auditResourceTypeLabel('user')).toBe('Compte');
    expect(auditResourceTypeLabel('settings')).toBe('Paramètres');
  });

  it('falls back on the raw type', () => {
    expect(auditResourceTypeLabel('printer')).toBe('printer');
  });
});

describe('auditDetailKeyLabel', () => {
  it('labels known keys and falls back on the raw one', () => {
    expect(auditDetailKeyLabel('source_hostname')).toBe('Fiche fusionnée (nom)');
    expect(auditDetailKeyLabel('maintenance_cycle_days')).toBe('maintenance_cycle_days');
  });
});

describe('auditActionOptions', () => {
  it('deduplicates and sorts by label, unknown slugs included', () => {
    expect(
      auditActionOptions(['user.delete', 'machine.merge', 'zz.unknown', 'user.delete']),
    ).toEqual([
      { value: 'machine.merge', label: 'Fusion de deux fiches poste' },
      { value: 'user.delete', label: "Suppression d'un compte" },
      { value: 'zz.unknown', label: 'zz.unknown' },
    ]);
  });
});

describe('isUuid / auditResourceLink', () => {
  it('recognises UUIDs only', () => {
    expect(isUuid(MACHINE_ID)).toBe(true);
    expect(isUuid('PC-CDI-01')).toBe(false);
    expect(isUuid(42)).toBe(false);
  });

  it('links a poste to its fiche', () => {
    expect(auditResourceLink('machine', MACHINE_ID)).toEqual({
      name: 'machine-detail',
      params: { id: MACHINE_ID },
    });
  });

  it('does not link other resources, nor a poste without a UUID', () => {
    expect(auditResourceLink('user', MACHINE_ID)).toBeNull();
    expect(auditResourceLink('machine', '')).toBeNull();
  });
});

describe('auditDetailValue', () => {
  it('renders each kind of JSON value', () => {
    expect(auditDetailValue(null)).toBe('—');
    expect(auditDetailValue(undefined)).toBe('—');
    expect(auditDetailValue('')).toBe('—');
    expect(auditDetailValue(true)).toBe('Oui');
    expect(auditDetailValue(false)).toBe('Non');
    expect(auditDetailValue('PC-01')).toBe('PC-01');
    expect(auditDetailValue(12)).toBe('12');
    expect(auditDetailValue([])).toBe('—');
    expect(auditDetailValue(['a', 'b'])).toBe('a, b');
    expect(auditDetailValue([{ a: 1 }])).toBe('[\n  {\n    "a": 1\n  }\n]');
    expect(auditDetailValue({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});

describe('auditDetailsSummary', () => {
  it('names the poste of a revocation', () => {
    expect(
      auditDetailsSummary('machine.revoke_token', { hostname: 'PC-CDI-01', machine_uuid: 'x' }),
    ).toBe('PC-CDI-01');
  });

  it('says which record a merge absorbed', () => {
    expect(
      auditDetailsSummary('machine.merge', {
        hostname: 'PC-CDI-01',
        source_id: 'b',
        source_hostname: 'PC-CDI-01-OLD',
      }),
    ).toBe('PC-CDI-01 · a absorbé « PC-CDI-01-OLD »');
  });

  it('falls back on the source UUID when the merged record had no name', () => {
    expect(auditDetailsSummary('machine.merge', { source_id: 'b', source_machine_uuid: 'u' })).toBe(
      'a absorbé « u »',
    );
    expect(auditDetailsSummary('machine.merge', { source_id: 'b' })).toBe('a absorbé « b »');
  });

  it('says whether a reset password was generated or typed — never the password', () => {
    expect(
      auditDetailsSummary('user.reset_password', { email: 'marie@test.local', generated: true }),
    ).toBe('marie@test.local · mot de passe généré');
    expect(
      auditDetailsSummary('user.reset_password', { email: 'marie@test.local', generated: false }),
    ).toBe('marie@test.local · mot de passe saisi');
  });

  it('lists the changed fields', () => {
    expect(
      auditDetailsSummary('user.update', {
        email: 'marie@test.local',
        fields: ['full_name', 'is_active'],
      }),
    ).toBe('marie@test.local · champs : full_name, is_active');
  });

  it('counts the postes moved', () => {
    expect(
      auditDetailsSummary('room.place_machines', { name: 'CDI', machine_ids: ['a', 'b'] }),
    ).toBe('CDI · 2 poste(s)');
  });

  it('sums up a directory sync', () => {
    expect(
      auditDetailsSummary('room.sync_directory', {
        source: 'ad',
        placed: 12,
        unplaced: 1,
        rooms_created: 2,
      }),
    ).toBe('12 poste(s) placé(s) · 1 non placé(s) · 2 salle(s) créée(s)');
  });

  it('names the changed settings, which carry their values as keys', () => {
    expect(
      auditDetailsSummary('settings.update', { maintenance_cycle_days: '90', due_soon: null }),
    ).toBe('champs : maintenance_cycle_days, due_soon');
    expect(
      auditDetailsSummary('maintenance.room_settings', { name: 'CDI', cycle_days: '30' }),
    ).toBe('CDI · champs : cycle_days');
  });

  it('answers a dash when there is nothing to say', () => {
    expect(auditDetailsSummary('settings.update', {})).toBe('—');
    expect(auditDetailsSummary('robot.unknown', { whatever: 1 })).toBe('—');
  });
});
