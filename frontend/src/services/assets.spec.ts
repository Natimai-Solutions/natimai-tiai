import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { assetKindLabel, assetStatusLabel, labelUrl, qrPath, warrantyClass } from './assets';

describe('assets helpers', () => {
  afterEach(() => setLocale('fr'));

  it('colours a warranty by the state the server read', () => {
    expect(warrantyClass('expired')).toBe('text-negative');
    expect(warrantyClass('soon')).toBe('text-warn');
    expect(warrantyClass('active')).toBe('');
    expect(warrantyClass(undefined)).toBe('');
  });

  it('names statuses and kinds in both languages, and the unknown as they are', () => {
    expect(assetStatusLabel('on_loan')).toBe('Prêté');
    expect(assetKindLabel('projector')).toBe('Vidéoprojecteur');
    expect(assetStatusLabel('lost')).toBe('lost');
    setLocale('en');
    expect(assetStatusLabel('retired')).toBe('Retired');
  });

  it('puts the token, not an id, in the label', () => {
    expect(labelUrl('a b/c', 'https://tiai.lycee.pf')).toBe('https://tiai.lycee.pf/a/a%20b%2Fc');
  });

  it('draws a QR code as one path of dark modules', () => {
    const qr = qrPath('https://tiai.lycee.pf/a/abcdefghijklmnopqrstuv');
    expect(qr.size).toBeGreaterThanOrEqual(21);
    expect(qr.path).toMatch(/^M\d+,\d+h1v1h-1z/);
    // The three finder patterns: the top-left module is dark.
    expect(qr.path.startsWith('M0,0h1v1h-1z')).toBe(true);
  });
});
