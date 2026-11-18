import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import {
  installBlockerTexts,
  invalidText,
  problemText,
  refusedNameText,
  signatureText,
  type Cause,
} from './packageText';

/**
 * The server's own French sentences, with the codes and parameters it sends
 * beside them (backend/tests/test_package_texts.py writes and checks them).
 * The console must write the same from the codes: an installation updated to
 * the bilingual console reads what it read before.
 */
interface Case {
  kind: 'problem' | 'file_name' | 'invalid' | 'signature';
  code?: string;
  params?: Record<string, unknown>;
  name?: string;
  cause?: Cause;
  message: string;
}
const CASES = JSON.parse(
  readFileSync(
    new URL('../../../backend/tests/data/package_texts_fr.json', import.meta.url),
    'utf-8',
  ),
) as Case[];

function worded(c: Case): string | null {
  switch (c.kind) {
    case 'problem':
      return problemText({ code: c.code!, params: c.params ?? {} });
    case 'file_name':
      return refusedNameText(c.name!, c.cause!);
    case 'invalid':
      return invalidText(c.cause!);
    case 'signature':
      return signatureText(c.cause!);
  }
}

afterEach(() => setLocale('fr'));

describe('package diagnostics, from their codes', () => {
  it('has the server’s cases to check', () => {
    expect(CASES.length).toBeGreaterThan(40);
    expect(new Set(CASES.map((c) => c.kind))).toEqual(
      new Set(['problem', 'file_name', 'invalid', 'signature']),
    );
  });

  it.each(CASES.map((c) => [c.message.slice(0, 60), c] as const))(
    'writes in French what the server writes: %s',
    (_label, c) => {
      expect(worded(c)).toBe(c.message);
    },
  );

  it('writes every case in English too, without a French word left', () => {
    setLocale('en');
    for (const c of CASES) {
      const text = worded(c);
      expect(text, c.message).toBeTruthy();
      expect(text, c.message).not.toBe(c.message);
      // The case's own data (a file named « a»b.txt ») is not a French word.
      const data = [c.name, ...JSON.stringify(c.cause?.params ?? {}).split('"')];
      const words = data.reduce((rest, d) => (d ? rest!.split(d).join('') : rest), text)!;
      expect(words, c.message).not.toMatch(/«|»| refusé|n'est pas|paquet/);
    }
  });

  it('agrees the verb with the files next to the executable', () => {
    setLocale('en');
    const one = {
      code: 'untrusted',
      params: { reason: 'loadable', file: 's.exe', files: ['a.dll'] },
    };
    const two = { ...one, params: { ...one.params, files: ['a.dll', 'b.dll'] } };
    expect(problemText(one)).toContain('“a.dll” is next to “s.exe”');
    expect(problemText(one)).toContain('remove it from');
    expect(problemText(two)).toContain('“a.dll”, “b.dll” are next to');
    expect(problemText(two)).toContain('remove them from');
  });
});

describe('a server older or newer than the console', () => {
  it('shows the server’s sentence for a problem without parameters', () => {
    setLocale('en');
    expect(problemText({ code: 'install_missing', message: '« a » n’est pas là' })).toBe(
      '« a » n’est pas là',
    );
  });

  it('shows the server’s sentence for a code it does not know', () => {
    expect(problemText({ code: 'brand_new', params: {}, message: 'Nouveau' })).toBe('Nouveau');
    expect(problemText({ code: 'untrusted', params: { reason: 'brand_new' }, message: 'N' })).toBe(
      'N',
    );
    expect(invalidText({ code: 'brand_new' })).toBeNull();
    expect(signatureText({ code: 'brand_new' })).toBeNull();
    expect(refusedNameText('a', { code: 'brand_new' })).toBeNull();
    expect(
      invalidText({ code: 'run_file_refused', params: { file: 'x', refusal: { code: 'z' } } }),
    ).toBeNull();
  });

  it('reads the blockers as codes when the server sends them, as sentences otherwise', () => {
    setLocale('en');
    expect(installBlockerTexts({ install_blockers: ['Aucun fichier déposé'] })).toEqual([
      'Aucun fichier déposé',
    ]);
    expect(
      installBlockerTexts({
        install_blockers: ['Aucun fichier déposé'],
        install_blocker_problems: [
          { code: 'no_files', params: {}, message: 'Aucun fichier déposé' },
        ],
      }),
    ).toEqual(['No file uploaded']);
  });
});
