import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { assetKindLabel, assetStatusLabel, labelUrl, qrPath, warrantyState } from './assets';

describe('assets helpers', () => {
  afterEach(() => setLocale('fr'));

  it('reads where a warranty stands', () => {
    const today = new Date(2026, 10, 20);
    expect(warrantyState(null, today)).toBe('none');
    expect(warrantyState('2026-11-19', today)).toBe('expired');
    expect(warrantyState('2026-11-20', today)).toBe('soon');
    expect(warrantyState('2027-01-19', today)).toBe('soon');
    expect(warrantyState('2027-06-01', today)).toBe('active');
    expect(warrantyState('garbage', today)).toBe('none');
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
