import { describe, expect, it } from 'vitest';
import { availableLocales, ENGLISH_AVAILABLE, resolveLocale } from './locales';

describe('resolveLocale', () => {
  const both = ['fr', 'en'] as const;

  it('takes the account’s choice first', () => {
    expect(resolveLocale('en', ['fr-FR'], both)).toBe('en');
    expect(resolveLocale('fr', ['en-US'], both)).toBe('fr');
  });

  it('follows the browser when the account chose nothing', () => {
    expect(resolveLocale(null, ['en-US', 'fr'], both)).toBe('en');
    expect(resolveLocale(undefined, ['de-DE', 'fr-CA'], both)).toBe('fr');
    expect(resolveLocale(null, ['EN'], both)).toBe('en');
  });

  it('falls back to French for a browser speaking neither', () => {
    expect(resolveLocale(null, ['de-DE', 'es'], both)).toBe('fr');
    expect(resolveLocale(null, [], both)).toBe('fr');
  });

  it('ignores a choice the console does not offer, or no language at all', () => {
    expect(resolveLocale('xx', ['en'], both)).toBe('en');
    expect(resolveLocale('en', ['en-US'], ['fr'])).toBe('fr');
  });

  // English is complete (plan, I6): offered, and followed from the browser
  // for an account that chose nothing.
  it('offers English now that the console is translated', () => {
    expect(ENGLISH_AVAILABLE).toBe(true);
    expect(availableLocales()).toEqual(['fr', 'en']);
    expect(resolveLocale('en', ['fr-FR'])).toBe('en');
    expect(resolveLocale(null, ['en-GB', 'en'])).toBe('en');
    expect(resolveLocale(null, ['fr-FR'])).toBe('fr');
  });
});
