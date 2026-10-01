import { describe, expect, it } from 'vitest';

import { describeUserAgent } from './userAgent';

describe('describeUserAgent', () => {
  it.each([
    [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0',
      'Firefox sur Windows',
    ],
    [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0',
      'Edge sur Windows',
    ],
    [
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
      'Chrome sur macOS',
    ],
    [
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
      'Safari sur macOS',
    ],
    [
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
      'Safari sur iOS',
    ],
    [
      'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36',
      'Chrome sur Android',
    ],
    [
      'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 OPR/120.0.0.0',
      'Opera sur Linux',
    ],
    [
      'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
      'Chrome sur ChromeOS',
    ],
  ])('reads %s', (userAgent, expected) => {
    expect(describeUserAgent(userAgent)).toBe(expected);
  });

  it('names what it can when only half is recognisable', () => {
    expect(describeUserAgent('Firefox/140.0')).toBe('Firefox');
    expect(describeUserAgent('SomeClient (Windows NT 10.0)')).toBe('Navigateur sur Windows');
  });

  it('falls back on an unknown device', () => {
    expect(describeUserAgent(null)).toBe('Appareil inconnu');
    expect(describeUserAgent('')).toBe('Appareil inconnu');
    expect(describeUserAgent('curl/8.5.0')).toBe('Appareil inconnu');
  });
});
