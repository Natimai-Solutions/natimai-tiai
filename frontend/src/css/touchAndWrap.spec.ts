import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Stylesheet contracts jsdom cannot lay out: the rules are read from the
 * sources (the browser checks of the release measured them).
 */
const source = (path: string) => readFileSync(join(__dirname, '..', path), 'utf8');
const flat = (text: string) => text.replace(/\s+/g, ' ');

describe('links readable in dark mode', () => {
  it('draws the audit log’s resource link in the text colour, underlined', () => {
    const css = flat(source('pages/AuditPage.vue'));
    expect(css).toMatch(/a\.audit-id \{[^}]*color: inherit;[^}]*text-decoration: underline;/);
  });
});

describe('name links as touch targets', () => {
  it('gives .row-link a taller hit box on a coarse pointer, out of the flow', () => {
    const css = flat(source('css/app.scss'));
    expect(css).toMatch(
      /@media \(pointer: coarse\) \{ \.row-link \{ position: relative; &::after \{ content: ''; position: absolute; inset: -12px 0; \}/,
    );
  });

  it('gives the machine list’s name the same, its padding given back by its margin', () => {
    const css = flat(source('components/machines-list/MachinesTable.vue'));
    expect(css).toMatch(
      /@media \(pointer: coarse\) \{ \.machine-name__link \{ padding-block: 12px; margin-block: -12px; \}/,
    );
  });
});

describe('long unbreakable values on a phone', () => {
  it('breaks a threat name on the dashboard', () => {
    const page = source('pages/DashboardPage.vue');
    expect(page).toMatch(/<q-item-label class="threat-name">\{\{\s*threatNameLabel/);
    expect(flat(page)).toMatch(/\.threat-name \{ overflow-wrap: anywhere; \}/);
  });

  it('breaks a value shown as code in a package sentence', () => {
    expect(flat(source('components/package/PackageRichText.vue'))).toMatch(
      /<style scoped>.*code \{ overflow-wrap: anywhere; \}/,
    );
  });

  it('breaks a group name inside its chip on « Mon compte »', () => {
    const page = source('pages/AccountPage.vue');
    expect(page).toMatch(/class="q-ml-none account-group-chip"/);
    expect(flat(page)).toMatch(
      /\.account-group-chip :deep\(\.q-chip__content\) \{ white-space: normal; overflow-wrap: anywhere; \}/,
    );
  });
});
