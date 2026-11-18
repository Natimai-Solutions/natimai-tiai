import { flushPromises, mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import type { Command } from 'src/services/commands';
import CommandOutputDialog from './CommandOutputDialog.vue';

const lost: Command = {
  id: 'c1',
  machine_id: 'm1',
  type: 'sfc_scan',
  status: 'failed',
  created_by: 'a@b.c',
  created_at: '2026-11-10T20:00:00Z',
  expires_at: '2026-11-11T20:00:00Z',
  delivered_at: null,
  started_at: null,
  finished_at: '2026-11-10T20:05:00Z',
  result_output: null,
  error:
    "Sans réponse du poste 6 h après la remise : commande considérée comme perdue (poste éteint, agent arrêté ou mis à jour pendant l'exécution). Relancez-la si besoin.",
  result_code: 'command.unanswered',
  result_params: { hours: 6 },
};

afterEach(() => {
  setLocale('fr');
  document.body.innerHTML = '';
});

function dialogText(): string {
  return document.body.querySelector('.q-dialog .q-card')?.textContent ?? '';
}

function shown(): string {
  return document.body.querySelector('pre.command-output')?.textContent ?? '';
}

describe('CommandOutputDialog in English', () => {
  it('words the verdict from its code, and its frame, in English', async () => {
    setLocale('en');
    const wrapper = mount(CommandOutputDialog, {
      props: { modelValue: true, command: lost, kind: 'error' },
      attachTo: document.body,
    });
    await flushPromises();
    expect(shown()).toBe(
      'No answer from the computer 6 h after delivery: the command is considered lost (computer off, agent stopped or updated while it ran). Run it again if needed.',
    );
    const text = dialogText();
    expect(text).toContain('Error details');
    expect(text).toContain('Check system integrity (sfc) — finished on');
    expect(text).toContain('Copy');
    expect(text).toContain('Close');
    expect(text).not.toMatch(/[éèàùçâêîôû«»]/);
    wrapper.unmount();
  });

  it('shows the stored French as it was in French, and switches live', async () => {
    const wrapper = mount(CommandOutputDialog, {
      props: { modelValue: true, command: lost, kind: 'error' },
      attachTo: document.body,
    });
    await flushPromises();
    expect(shown()).toBe(lost.error);
    expect(dialogText()).toContain("Détail de l'erreur");
    setLocale('en');
    await nextTick();
    expect(shown()).toMatch(/^No answer from the computer 6 h/);
    expect(dialogText()).toContain('Error details');
    wrapper.unmount();
  });
});
