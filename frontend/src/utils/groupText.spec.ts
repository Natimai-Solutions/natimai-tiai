import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import catalogue from 'src/i18n/messages/groups';
import { groupDescription, groupName } from './groupText';

afterEach(() => setLocale('fr'));

describe('built-in groups in the reader’s language', () => {
  // The French is the server's seed, word for word: otherwise a group the
  // installation named would never be recognised as untouched.
  it('knows the seeds the server gives each built-in group', () => {
    const seeds = readFileSync(
      new URL('../../../backend/app/features/user/permissions.py', import.meta.url),
      'utf-8',
    );
    for (const { name, description } of Object.values(catalogue.fr.builtin)) {
      expect(seeds).toContain(`"${name}"`);
      expect(seeds).toContain(`"${description}"`);
    }
  });

  it('translates a built-in group that keeps its seeds, and only that', () => {
    const technicians = {
      name: 'Techniciens',
      description: 'Consulte le parc et exécute les commandes, courantes et à risque.',
      builtin_key: 'technician',
    };
    expect(groupName(technicians)).toBe('Techniciens');
    setLocale('en');
    expect(groupName(technicians)).toBe('Technicians');
    expect(groupDescription(technicians)).toBe(
      'Views the fleet and runs commands, routine and risky ones.',
    );
    // Renamed by an administrator: theirs, as typed.
    expect(groupName({ ...technicians, name: 'Équipe info' })).toBe('Équipe info');
    expect(groupDescription({ ...technicians, description: 'Nos techniciens' })).toBe(
      'Nos techniciens',
    );
    // A group of the operator's that happens to bear the name: not a built-in.
    expect(groupName({ name: 'Techniciens', builtin_key: null })).toBe('Techniciens');
    expect(groupName({ name: 'Techniciens', builtin_key: 'unknown' })).toBe('Techniciens');
  });

  it('keeps a built-in group’s stored name when another group of the list bears its translation', () => {
    const builtins = [
      { name: 'Administrateurs', builtin_key: 'admin' },
      { name: 'Lecture seule', builtin_key: 'readonly' },
    ].filter((g) => g.builtin_key in catalogue.fr.builtin);
    const list = [
      ...builtins,
      ...builtins.map((g) => ({ name: catalogue.en.builtin[g.builtin_key as 'admin'].name })),
    ];
    setLocale('en');
    const names = list.map((g) => groupName(g, list));
    expect(new Set(names).size).toBe(list.length);
    expect(names.slice(0, builtins.length)).toEqual(builtins.map((g) => g.name));
    // Alone, or beside groups of other names: translated as before.
    expect(groupName(builtins[0]!, builtins)).toBe(
      catalogue.en.builtin[builtins[0]!.builtin_key as 'admin'].name,
    );
    setLocale('fr');
    expect(list.map((g) => groupName(g, list))).toEqual(list.map((g) => g.name));
  });
});
