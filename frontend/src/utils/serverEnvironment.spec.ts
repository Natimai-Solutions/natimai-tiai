import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import type { EnvGroup, EnvItem } from 'src/services/settings';
import { bytesText, envDescription, envGroupLabel, envValue } from './serverEnvironment';

/**
 * The server's own French for its environment, with the codes, raw values and
 * formats it sends beside it (backend/tests/test_settings_texts.py writes and
 * checks them). The console must write the same from the codes: an
 * installation updated to the bilingual console reads what it read before.
 */
interface Fixture {
  environment: { name: string; groups: EnvGroup[] }[];
  environment_items: EnvItem[];
}
const FIXTURE = JSON.parse(
  readFileSync(
    new URL('../../../backend/tests/data/settings_texts_fr.json', import.meta.url),
    'utf-8',
  ),
) as Fixture;

const allItems = [
  ...FIXTURE.environment.flatMap((s) => s.groups.flatMap((g) => g.items)),
  ...FIXTURE.environment_items,
];

afterEach(() => setLocale('fr'));

describe('the environment in French', () => {
  it.each(FIXTURE.environment.map((s) => [s.name, s] as const))(
    'words the %s scenario as the server does',
    (_name, scenario) => {
      for (const group of scenario.groups) {
        expect(envGroupLabel(group)).toBe(group.label);
        for (const item of group.items) {
          expect(envValue(item), item.key).toBe(item.value);
          expect(envDescription(item), item.key).toBe(item.description);
        }
      }
    },
  );

  it.each(FIXTURE.environment_items.map((i) => [i.key, i.raw, i] as const))(
    'words %s = %j as the server does',
    (_key, _raw, item) => {
      expect(envValue(item)).toBe(item.value);
    },
  );

  it('has a description for every variable the server lists', () => {
    // A server-only description would show in French to an English reader.
    setLocale('en');
    for (const item of allItems) {
      expect(envDescription(item), item.key).not.toBe(item.description);
    }
  });
});

describe('the environment in English', () => {
  const item = (fields: Partial<EnvItem>): EnvItem => ({
    key: 'X',
    value: 'x',
    description: 'x',
    ...fields,
  });

  it('words groups, values and descriptions', () => {
    setLocale('en');
    expect(envGroupLabel({ code: 'wol', label: 'Réveil des postes', items: [] })).toBe(
      'Waking computers (Wake-on-LAN)',
    );
    expect(envValue(item({ value: 'oui', raw: true, format: 'bool' }))).toBe('yes');
    expect(envValue(item({ value: 'non', raw: false, format: 'bool' }))).toBe('no');
    expect(envValue(item({ value: '4 (vendredi)', raw: 4, format: 'weekday' }))).toBe('4 (Friday)');
    expect(envValue(item({ value: 'ad_ou (…)', raw: 'ad_ou', format: 'room_source' }))).toBe(
      'ad_ou (by the directory’s organisational unit)',
    );
    expect(
      envValue(
        item({
          value: 'smtp (…)',
          raw: 'smtp',
          format: 'mail_state',
          params: { configured: true },
        }),
      ),
    ).toBe('smtp (configured in the environment)');
    expect(
      envValue(
        item({
          value: 'défini (illisible)',
          raw: null,
          format: 'proxy',
          params: { unreadable: true },
        }),
      ),
    ).toBe('set (unreadable)');
    expect(envValue(item({ value: '10.0.0.1:3128', raw: '10.0.0.1:3128', format: 'proxy' }))).toBe(
      '10.0.0.1:3128',
    );
    expect(
      envDescription(item({ key: 'WOL_PORT', description: 'Port UDP du paquet magique' })),
    ).toBe('UDP port of the magic packet');
  });

  it('writes sizes with the English units and decimal point', () => {
    setLocale('en');
    expect(bytesText(2 * 1024 ** 3)).toBe('2147483648 (2 GiB)');
    expect(bytesText(1536 * 1024 ** 2)).toBe('1610612736 (1.5 GiB)');
    expect(bytesText(1024 ** 2 + 512 * 1024)).toBe('1572864 (1.5 MiB)');
    expect(bytesText(1000)).toBe('1000 bytes');
    setLocale('fr');
    expect(bytesText(1536 * 1024 ** 2)).toBe('1610612736 (1,5 Gio)');
  });

  it('shows the server’s French for what it does not know', () => {
    setLocale('en');
    // An older server: no code, no format.
    expect(envGroupLabel({ label: 'Salles', items: [] })).toBe('Salles');
    expect(envValue(item({ value: 'oui' }))).toBe('oui');
    // A newer one: an unknown group, variable or format.
    expect(envGroupLabel({ code: 'later', label: 'Plus tard', items: [] })).toBe('Plus tard');
    expect(envDescription(item({ key: 'NEW_VARIABLE', description: 'Nouvelle' }))).toBe('Nouvelle');
    expect(envValue(item({ value: '3 (mercredi)', raw: 3, format: 'later' }))).toBe('3 (mercredi)');
    // A raw value that does not fit its format.
    expect(envValue(item({ value: 'oui', raw: 'yes', format: 'bool' }))).toBe('oui');
    // Not set stays not set.
    expect(envValue(item({ value: null, raw: null, format: 'plain' }))).toBeNull();
  });
});
