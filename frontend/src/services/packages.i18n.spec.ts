import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import {
  formatSize,
  methodAMaxLabel,
  packageChoiceLabel,
  trustLabel,
  type Package,
} from './packages';

const GIB = 1024 ** 3;

function pkg(over: Partial<Package>): Package {
  return {
    id: 'p',
    kind: 'files',
    name: 'Tool',
    version: '1',
    install_run: 'setup.exe',
    winget_id: null,
    method_a_max_bytes: 8 * GIB,
    created_at: '2026-11-04T20:00:00Z',
    ...over,
  } as Package;
}

describe('package words in both languages', () => {
  afterEach(() => setLocale('fr'));

  it('says how a package reaches a poste', () => {
    expect(trustLabel('signed')).toBe('Signé (méthode B)');
    expect(trustLabel('none')).toBe('Non signé');
    setLocale('en');
    expect(trustLabel('signed')).toBe('Signed (method B)');
    expect(trustLabel('publisher')).toBe('Publisher (method A)');
    expect(trustLabel('none')).toBe('Unsigned');
    expect(trustLabel('winget')).toBe('winget');
  });

  it('writes sizes with the reader’s units and decimal mark', () => {
    expect(formatSize(512)).toBe('512 o');
    expect(formatSize(1536)).toBe('1,5 Kio');
    expect(methodAMaxLabel(pkg({}))).toBe('8 Gio');
    setLocale('en');
    expect(formatSize(512)).toBe('512 B');
    expect(formatSize(1536)).toBe('1.5 KiB');
    expect(formatSize(250 * 1024 * 1024)).toBe('250 MiB');
    expect(formatSize(3 * GIB)).toBe('3.0 GiB');
    expect(methodAMaxLabel(pkg({ method_a_max_bytes: 16 * GIB }))).toBe('16 GiB');
  });

  it('tells two packages of one name apart in English', () => {
    const a = pkg({ id: 'a' });
    const b = pkg({ id: 'b', kind: 'winget', winget_id: 'X.Tool', install_run: null });
    const c = pkg({ id: 'c', install_run: null });
    setLocale('en');
    expect(packageChoiceLabel(a, [a, b, c])).toMatch(/^Tool 1 \(files, setup\.exe — created /);
    expect(packageChoiceLabel(b, [a, b, c])).toMatch(/^Tool 1 \(winget X\.Tool — created /);
    expect(packageChoiceLabel(c, [a, b, c])).toMatch(/^Tool 1 \(files, no file to run — created /);
    expect(packageChoiceLabel(a, [a, b, c])).toContain('04/11/2026');
  });
});
