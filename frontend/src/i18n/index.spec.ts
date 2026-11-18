import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  currentLocale,
  errorCodeMessage,
  i18n,
  intlTag,
  onLocaleChange,
  setLocale,
  t,
} from './index';
import errorCodes from './messages/errorCodes';
import { en, fr } from './messages';

/** Every leaf of a catalogue, as `a.b.c` → text. */
function leaves(tree: object, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'string'
      ? [[`${prefix}${key}`, value] as [string, string]]
      : leaves(value as object, `${prefix}${key}.`),
  );
}

afterEach(() => setLocale('fr'));

describe('the catalogues', () => {
  it('have the same keys in both languages', () => {
    expect(leaves(en).map(([k]) => k)).toEqual(leaves(fr).map(([k]) => k));
    expect(Object.keys(errorCodes.en).sort()).toEqual(Object.keys(errorCodes.fr).sort());
  });

  // vue-i18n reads `@`, `|`, `{` and `}` as syntax: a text that holds one by
  // accident would come out mangled. Every text without a placeholder must
  // come out exactly as written.
  it('render every text without a placeholder as written, in both languages', () => {
    for (const [locale, catalogue] of [
      ['fr', fr],
      ['en', en],
    ] as const) {
      setLocale(locale);
      for (const [key, text] of leaves(catalogue)) {
        // A literal brace is written {'{'}: it must come out as one.
        const literal = text.replaceAll("{'{'}", '{').replaceAll("{'}'}", '}');
        if (literal !== text ? /\{[a-z]/.test(text) : text.includes('{')) continue;
        // A plural (« … | … ») comes out as its first form.
        const first = literal.split(' | ')[0]!;
        expect(t(key), key).toBe(first);
      }
    }
  });

  it('fill the placeholders', () => {
    expect(t('errors.fieldReason', { field: 'nom', reason: 'trop long' })).toBe(
      'champ « nom » : trop long',
    );
    setLocale('en');
    expect(t('errors.fieldReason', { field: 'name', reason: 'too long' })).toBe(
      'field “name”: too long',
    );
  });
});

describe('setLocale', () => {
  it('switches the texts, the error messages and the formats', () => {
    expect(currentLocale()).toBe('fr');
    expect(errorCodeMessage('machine.not_found')).toBe('Poste introuvable');
    expect(intlTag()).toBe('fr-FR');

    setLocale('en');
    expect(currentLocale()).toBe('en');
    expect(i18n.global.locale.value).toBe('en');
    expect(errorCodeMessage('machine.not_found')).toBe('Computer not found');
    expect(t('common.language.label')).toBe('Language');
    expect(intlTag()).toBe('en-GB');
  });

  // The suite runs on `node`: a stand-in `document` is enough to see the
  // line that writes the page's lang (screen readers, hyphenation).
  it('sets the page’s lang', () => {
    const documentElement = { lang: 'fr' };
    vi.stubGlobal('document', { documentElement });
    try {
      setLocale('en');
      expect(documentElement.lang).toBe('en');
      setLocale('fr');
      expect(documentElement.lang).toBe('fr');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('tells its listeners, until they leave', () => {
    const listener = vi.fn();
    const leave = onLocaleChange(listener);
    setLocale('en');
    expect(listener).toHaveBeenCalledWith('en');
    leave();
    setLocale('fr');
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('knows no message for an unknown code, nor for a property of every object', () => {
    expect(errorCodeMessage('nope.nope')).toBeNull();
    expect(errorCodeMessage('toString')).toBeNull();
  });
});
