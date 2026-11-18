import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * A field's error follows a live switch of language (plan §8): Quasar keeps
 * the message a rule returned and runs the rules again on a change of them
 * only with `reactive-rules`. Every field with `:rules` carries it; the
 * template builds its rules again when the language changes.
 */
const SRC = new URL('..', import.meta.url).pathname;

function components(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return components(path);
    return name.endsWith('.vue') ? [path] : [];
  });
}

// Edited by another change of the same release, which gives its field the attribute.
const ELSEWHERE = new Set(['components/maintenance/MaintenanceSettingsDialog.vue']);

describe('validation messages follow the language', () => {
  const files = components(SRC)
    .map((path) => relative(SRC, path))
    .filter(
      (file) => !ELSEWHERE.has(file) && readFileSync(join(SRC, file), 'utf-8').includes(':rules='),
    );

  it('has fields to check', () => {
    expect(files.length).toBeGreaterThan(5);
  });

  it.each(files)('%s', (file) => {
    const lines = readFileSync(join(SRC, file), 'utf-8').split('\n');
    const bare = lines.flatMap((line, i) => {
      if (!line.includes(':rules=')) return [];
      // The opening tag the attribute belongs to, up to this line.
      let start = i;
      while (start > 0 && !/<q-[a-z-]+/.test(lines[start]!)) start -= 1;
      const tag = lines.slice(start, i + 1).join('\n');
      return /\breactive-rules\b/.test(tag) ? [] : [`${i + 1}: ${line.trim()}`];
    });
    expect(bare).toEqual([]);
  });
});
