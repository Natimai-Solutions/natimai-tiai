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

  // The guarantee of an update: until English is complete, nothing switches.
  it('stays French whatever the browser and the account say while English is not offered', () => {
    expect(ENGLISH_AVAILABLE).toBe(false);
    expect(availableLocales()).toEqual(['fr']);
    expect(resolveLocale('en', ['en-US'])).toBe('fr');
    expect(resolveLocale(null, ['en-GB', 'en'])).toBe('fr');
  });
});
