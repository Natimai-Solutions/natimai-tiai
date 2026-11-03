import { describe, expect, it } from 'vitest';
import { escapeHtml } from './html';

describe('escapeHtml', () => {
  it('neutralises markup', () => {
    expect(escapeHtml('<img src=x onerror="alert(1)">')).toBe(
      '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
    );
  });

  it('escapes the ampersand first, so nothing is escaped twice', () => {
    expect(escapeHtml("R&D 'B12'")).toBe('R&amp;D &#39;B12&#39;');
  });

  it('leaves plain names alone', () => {
    expect(escapeHtml('Salle B12 — Bâtiment C')).toBe('Salle B12 — Bâtiment C');
  });
});
