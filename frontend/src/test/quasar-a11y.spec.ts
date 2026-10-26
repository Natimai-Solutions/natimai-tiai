/**
 * Garde-fou d'accessibilité pour les composants Quasar, qu'un linter HTML ne
 * sait pas lire : chaque contrôle a un nom, et rien de cliquable n'échappe au
 * clavier.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..');

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (entry.endsWith('.vue')) out.push(full);
  }
  return out;
}

/** Opening tags of `tag`, attributes included, across line breaks. */
function openingTags(content: string, tag: string): string[] {
  return [...content.matchAll(new RegExp(`<${tag}\\b([^>]*?)/?>`, 'gs'))].map((m) => m[1] ?? '');
}

const NAMED = /(^|\s)(:?label|aria-label|:aria-label)=/;

describe('accessibilité des composants Quasar', () => {
  const files = walk(ROOT);
  it('parcourt des fichiers', () => {
    expect(files.length).toBeGreaterThan(0);
  });
  for (const file of files) {
    it(file.replace(/^.*frontend\//, ''), () => {
      const content = readFileSync(file, 'utf8');
      // Un tooltip ne donne pas de nom accessible : un bouton sans texte en
      // porte un explicitement.
      for (const attrs of openingTags(content, 'q-btn')) {
        if (/(^|\s):?icon=/.test(attrs)) {
          expect(attrs, 'q-btn icône sans label ni aria-label').toMatch(NAMED);
        }
      }
      // Un placeholder disparaît à la saisie et n'est pas un libellé.
      for (const tag of ['q-input', 'q-select']) {
        for (const attrs of openingTags(content, tag)) {
          expect(attrs, `${tag} sans label ni aria-label`).toMatch(NAMED);
        }
      }
      // Une carte ou un bloc cliquable n'est pas atteignable au clavier : un
      // lien (`router-link`, `:to`) ou un bouton à la place.
      for (const tag of ['q-card', 'div', 'span']) {
        for (const attrs of openingTags(content, tag)) {
          // `@click.stop` alone only shields a cell of buttons from the row's
          // own click: it handles nothing.
          expect(attrs, `${tag} @click : utiliser un lien ou un bouton`).not.toMatch(
            /@click(?!\.stop(\s|$))(\.[a-z]+)*=/,
          );
        }
      }
    });
  }
});
