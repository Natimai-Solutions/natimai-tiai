/**
 * Garde-fou dark mode (repris de natimai-paie) : aucun aplat clair fixe ni
 * ternaire de thème dans le code de la console. Les fonds passent par
 * `surface-*`, le texte secondaire par `text-muted` (src/css/surfaces.scss).
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..');

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry !== 'test') walk(full, out);
    } else if (/\.(vue|ts)$/.test(entry) && !entry.endsWith('.spec.ts')) {
      out.push(full);
    }
  }
  return out;
}

const FORBIDDEN: Array<[RegExp, string]> = [
  [
    /\bbg-(blue|orange|grey|green|red|amber|teal|purple|indigo|cyan|lime|yellow|brown)-[1-4]\b/,
    'bg-<teinte>-1/2/3/4 : utiliser surface-*',
  ],
  [
    /\$q\.dark\.isActive\s*\?/,
    'ternaire $q.dark.isActive : utiliser surface-* ou une variable --ti-*',
  ],
  [/\bbg-white\b/, 'bg-white : utiliser var(--ti-surface-card)'],
  // $grey (2,7:1 sur blanc) est illisible en clair ; grey-7/8 le sont en sombre.
  [/\btext-grey(-[5-9]|-10)?\b(?!-)/, 'text-grey* : utiliser text-muted'],
  [/rgba\(\s*0\s*,\s*0\s*,\s*0\s*,/, 'noir translucide fixe : utiliser var(--ti-border)'],
  // 2,2:1 et 2,6:1 sur blanc.
  [
    /\btext-(orange|positive|warning|amber)(-[0-9]+)?\b(?!-)/,
    'text-orange/positive : utiliser text-warn / text-ok',
  ],
  // Noir sur une carte sombre : la valeur disparaît.
  [/\btext-(black|dark)\b|color="(black|dark)"/, 'text-black/text-dark : utiliser text-strong'],
];

describe('dark mode : aucune couleur claire fixe', () => {
  const files = walk(ROOT);
  it('parcourt des fichiers', () => {
    expect(files.length).toBeGreaterThan(0);
  });
  for (const file of files) {
    it(file.replace(/^.*frontend\//, ''), () => {
      const content = readFileSync(file, 'utf8');
      for (const [pattern, why] of FORBIDDEN) {
        expect(content, why).not.toMatch(pattern);
      }
    });
  }
});
