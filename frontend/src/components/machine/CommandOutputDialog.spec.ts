import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { Command } from 'src/services/commands';
import CommandOutputDialog from './CommandOutputDialog.vue';

const command = {
  id: 'c1',
  machine_id: 'm1',
  type: 'sfc',
  status: 'succeeded',
  created_by: 'a@b.c',
  created_at: '2026-11-10T20:00:00Z',
  expires_at: '2026-11-11T20:00:00Z',
  delivered_at: null,
  started_at: null,
  finished_at: '2026-11-10T20:05:00Z',
  result_output: 'Aucune violation d’intégrité.',
  error: 'Accès refusé',
} as Command;

/**
 * Audit U11: on a 375 px phone the card's former `min-width: 480px` pushed
 * the dialog off the screen. jsdom lays nothing out and applies no scoped
 * style, so the width is held from both ends of the contract: the card
 * carries the class, and the class's rule never asks for more than 95vw.
 */
describe('CommandOutputDialog', () => {
  it('shows the output, or the error, in the card the width rule applies to', async () => {
    const wrapper = mount(CommandOutputDialog, {
      props: { modelValue: true, command, kind: 'output' },
      attachTo: document.body,
    });
    await flushPromises();
    const card = document.body.querySelector('.q-dialog .q-card')!;

    expect(card.classList.contains('command-output-card')).toBe(true);
    // No width of its own on the element: the stylesheet alone decides.
    expect(card.getAttribute('style') ?? '').not.toMatch(/width/);
    expect(card.querySelector('pre.command-output')!.textContent).toBe(
      'Aucune violation d’intégrité.',
    );

    await wrapper.setProps({ kind: 'error' });
    expect(card.querySelector('pre.command-output')!.textContent).toBe('Accès refusé');
    wrapper.unmount();
  });

  it('never asks for a card wider than the screen (style contract)', () => {
    const sfc = readFileSync(join(__dirname, 'CommandOutputDialog.vue'), 'utf8');
    const rule = /\.command-output-card\s*\{([^}]*)\}/.exec(sfc);
    expect(rule, '.command-output-card has a rule').not.toBeNull();
    const declarations = Object.fromEntries(
      rule![1]!
        .split(';')
        .map((d) => d.trim())
        .filter(Boolean)
        .map((d) => {
          const at = d.indexOf(':');
          return [d.slice(0, at).trim(), d.slice(at + 1).trim()];
        }),
    );

    // 480 px on a desktop, and the screen's own width on anything narrower.
    expect(declarations['min-width']).toBe('min(480px, 95vw)');
    expect(declarations['max-width']).toBe('95vw');
    expect(declarations.width).toBeUndefined();
  });
});
