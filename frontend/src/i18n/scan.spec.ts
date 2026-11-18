import { describe, expect, it } from 'vitest';
import { scanSource } from './scan';

/**
 * The heuristic behind `noHardcodedFrench.spec.ts`: what it must see, and
 * what it must leave alone. A guard that misses common French reads as a
 * clean console while English readers still meet French.
 */

function vue(template: string, script = ''): string {
  return `<script setup lang="ts">\n${script}\n</script>\n\n${template}\n`;
}

const lines = (source: string, path = 'Sample.vue') => scanSource(source, path).map((f) => f.line);

describe('scanSource', () => {
  it.each([
    ['an attribute of common words', '<template><q-input label="Mot de passe" /></template>'],
    ['a text of common words', '<template><div>Tableau de bord</div></template>'],
    ['a lone label', '<template><q-tab label="Inventaire" /></template>'],
    ['a single-quoted attribute', "<template><q-btn title='Fermer la fenêtre' /></template>"],
    [
      'a single-quoted attribute without accents',
      "<template><q-btn title='Mot de passe' /></template>",
    ],
    ['a template with a lang', '<template lang="html"><div>Fermer</div></template>'],
    ['a text around an interpolation', '<template><span>Tableau {{ n }} de bord</span></template>'],
  ])('sees French in %s', (_, template) => {
    expect(lines(vue(template))).toEqual([5]);
  });

  it.each([
    ['common words', "notify('Mise en forme');"],
    ['a word of the vocabulary', "const title = 'Machines inconnues';"],
    ['a capitalised label', "const label = 'Inventaire';"],
    ['an accent', "const label = 'Paramètres généraux';"],
    ['a template literal', 'const label = `${n} postes par salle`;'],
  ])('sees French in code: %s', (_, code) => {
    expect(lines(code, 'sample.ts')).toEqual([1]);
    expect(lines(vue('<template><div /></template>', code))).toEqual([2]);
  });

  it('sees French in a bound expression and an interpolation', () => {
    const template = `<template>
  <q-btn :label="ok ? 'Mise en forme' : t('a')" />
  <span>{{ n ? 'Inventaire' : '' }}</span>
</template>`;
    expect(lines(vue(template))).toEqual([6, 7]);
  });

  it('reports the line of the text, in a file of several lines', () => {
    const template = `<template>
  <div>
    <span>
      Tableau de bord
    </span>
  </div>
</template>`;
    expect(scanSource(vue(template), 'Sample.vue')).toEqual([{ line: 8, text: 'Tableau de bord' }]);
  });

  it('leaves alone what is not interface text', () => {
    const template = `<template>
  <!-- Le tableau de bord du poste -->
  <q-table row-key="id" class="row q-gutter-sm" :rows="rows" @click="open('machines')">
    <template #body-cell-name="{ row }">{{ row.name }} ({{ t('machines.list.title') }})</template>
  </q-table>
  <div>Windows Update</div>
</template>`;
    const script = `// Le poste n'est pas joignable : on attend.
/* Tableau de bord */
const key = 'diagnostic';
const path = \`/machines/\${id}/software\`;
const re = /d'un poste/;
const day = 'lundi';
const locales = ['fr', 'en'];`;
    expect(lines(vue(template, script))).toEqual([]);
  });

  it('keeps a line that says i18n-ignore', () => {
    const code = "const re = new RegExp('Mot de passe'); // i18n-ignore: the server's own text";
    expect(lines(code, 'sample.ts')).toEqual([]);
  });

  it('is not misled by quotes in comments and regular expressions', () => {
    const code = `const re = /'/;
// the server's own text
const a = \`/packages/\${id}\`;
/** l'administrateur */
const b = 'Mise en forme';`;
    expect(lines(code, 'sample.ts')).toEqual([5]);
  });
});
