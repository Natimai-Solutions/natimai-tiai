import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QDialog, Screen } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  recordSessionInParts: vi.fn(),
}));

import { recordSessionInParts, type SessionProgress } from 'src/services/maintenance';
import MaintenanceSessionDialog from './MaintenanceSessionDialog.vue';

const machines = [
  { id: 'a', hostname: 'PC-A', preselect: true },
  { id: 'b', hostname: 'PC-B', preselect: true },
  { id: 'c', hostname: 'PC-C', preselect: false },
];

async function open() {
  const wrapper = mount(MaintenanceSessionDialog, {
    props: { modelValue: false, roomId: 'r', roomName: 'B12', machines },
    attachTo: document.body,
  });
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  return wrapper;
}

/** The dialog's content lives in a portal under <body>, not under the wrapper. */
function inDialog<T extends Element>(selector: string): T {
  return document.querySelector<T>(`.q-dialog ${selector}`)!;
}

async function typeNote(hostname: string, text: string) {
  const input = inDialog<HTMLInputElement>(`input[aria-label="Note pour ${hostname}"]`);
  input.value = text;
  input.dispatchEvent(new Event('input'));
  await flushPromises();
}

async function pressEscape() {
  inDialog<HTMLElement>('input').dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }),
  );
  await flushPromises();
}

function closes(wrapper: Awaited<ReturnType<typeof open>>) {
  return (wrapper.emitted('update:modelValue') ?? []).filter(([v]) => v === false).length;
}

function pluginButton(label: string): HTMLElement {
  return [...document.querySelectorAll<HTMLElement>('.q-dialog-plugin button')].find((b) =>
    b.textContent?.includes(label),
  )!;
}

describe('MaintenanceSessionDialog (audit T29, U14)', () => {
  beforeEach(() => {
    vi.mocked(recordSessionInParts)
      .mockReset()
      .mockResolvedValue({} as never);
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('is persistent: a click beside the card does not throw the input away', async () => {
    const wrapper = await open();
    expect(wrapper.findComponent(QDialog).props('persistent')).toBe(true);
    wrapper.unmount();
  });

  it('closes on Annuler at once when nothing was typed', async () => {
    const wrapper = await open();
    await wrapper
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Annuler')!
      .trigger('click');

    expect(closes(wrapper)).toBe(1);
    expect(document.body.textContent).not.toContain('Abandonner la saisie ?');
    wrapper.unmount();
  });

  it('asks before Échap throws a typed note away, and keeps it on « Continuer la saisie »', async () => {
    const wrapper = await open();
    await typeNote('PC-A', 'clavier HS');
    await pressEscape();

    expect(closes(wrapper)).toBe(0);
    expect(document.body.textContent).toContain('Abandonner la saisie ?');

    pluginButton('Continuer la saisie').click();
    await flushPromises();
    expect(closes(wrapper)).toBe(0);
    expect(inDialog<HTMLInputElement>('input[aria-label="Note pour PC-A"]').value).toBe(
      'clavier HS',
    );
    wrapper.unmount();
  });

  it('closes on a confirmed Annuler once something was typed', async () => {
    const wrapper = await open();
    await typeNote('PC-B', 'absent');
    await wrapper
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Annuler')!
      .trigger('click');
    expect(closes(wrapper)).toBe(0);

    pluginButton('Abandonner').click();
    await flushPromises();
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });

  it('sends the ticked postes, and the unticked ones with a note as skipped', async () => {
    const wrapper = await open();
    await typeNote('PC-C', 'éteint');
    inDialog<HTMLFormElement>('form').dispatchEvent(
      new Event('submit', { cancelable: true, bubbles: true }),
    );
    await flushPromises();

    expect(recordSessionInParts).toHaveBeenCalledWith(
      expect.objectContaining({
        room_id: 'r',
        items: [
          { machine_id: 'a', note: null },
          { machine_id: 'b', note: null },
        ],
        skipped: [{ machine_id: 'c', note: 'éteint' }],
      }),
      expect.objectContaining({ sessionId: null, sent: 0, total: 3 }),
    );
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });

  function submitButton() {
    return [...document.querySelectorAll<HTMLButtonElement>('.q-dialog button[type="submit"]')][0]!;
  }

  async function submitForm() {
    inDialog<HTMLFormElement>('form').dispatchEvent(
      new Event('submit', { cancelable: true, bubbles: true }),
    );
    await flushPromises();
  }

  it('records a visit with nothing done once it says why (audit T30)', async () => {
    const wrapper = await open();
    // Untick the two preselected: nothing done, nothing said yet.
    for (const host of ['PC-A', 'PC-B']) {
      inDialog<HTMLElement>(`[aria-label="${host} : fait"]`).click();
    }
    await flushPromises();
    expect(submitButton().disabled).toBe(true);
    expect(document.body.textContent).toContain('Aucun poste coché');

    await typeNote('PC-B', 'salle fermée');
    expect(submitButton().disabled).toBe(false);
    const notify = vi.spyOn(wrapper.vm.$q, 'notify');
    await submitForm();
    expect(recordSessionInParts).toHaveBeenCalledWith(
      expect.objectContaining({ items: [], skipped: [{ machine_id: 'b', note: 'salle fermée' }] }),
      expect.anything(),
    );
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Séance enregistrée : aucun poste fait' }),
    );
    wrapper.unmount();
  });

  it('keeps a visit cut half-way and resumes it into the same visit (audit T30)', async () => {
    vi.mocked(recordSessionInParts)
      .mockImplementationOnce(async (_payload, progress) => {
        // The first part went through, the next one did not.
        progress!.sessionId = 's-1';
        progress!.sent = 250;
        throw new Error('réseau');
      })
      .mockResolvedValue({} as never);
    const wrapper = await open();
    await submitForm();

    expect(closes(wrapper)).toBe(0);
    expect(inDialog('[data-test="session-pending"]').textContent.replace(/\s+/g, ' ')).toContain(
      '250 poste(s) sur 2',
    );
    expect(submitButton().textContent).toContain("Reprendre l'envoi");
    await submitForm();

    const [first, second] = vi.mocked(recordSessionInParts).mock.calls;
    // The same payload and the same progress: the rest, not a second visit.
    expect(second![0]).toStrictEqual(first![0]);
    expect((second![1] as SessionProgress).sessionId).toBe('s-1');
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });

  describe('on a phone (audit U23)', () => {
    beforeEach(() => {
      Screen.lt.sm = true;
    });
    afterEach(() => {
      Screen.lt.sm = false;
    });

    it('takes the whole screen and lists each poste with its note below, no table', async () => {
      const wrapper = await open();
      expect(wrapper.findComponent(QDialog).props('maximized')).toBe(true);
      // No width of its own: the maximized dialog gives it the screen's.
      expect(inDialog('[data-test="session-card"]').getAttribute('style') ?? '').not.toMatch(
        /width/,
      );
      expect(document.querySelector('.q-dialog .q-markup-table')).toBeNull();
      const list = inDialog('[data-test="session-rows"]');
      expect(list.querySelectorAll('input[aria-label^="Note pour"]')).toHaveLength(3);
      // Full-size checkboxes on a touch screen, not the dense ones.
      expect(list.querySelector('.q-checkbox--dense')).toBeNull();

      await typeNote('PC-C', 'éteint');
      await submitForm();
      expect(recordSessionInParts).toHaveBeenCalledWith(
        expect.objectContaining({ skipped: [{ machine_id: 'c', note: 'éteint' }] }),
        expect.anything(),
      );
      wrapper.unmount();
    });

    it('stays a centred card with its table on a wider screen', async () => {
      Screen.lt.sm = false;
      const wrapper = await open();
      expect(wrapper.findComponent(QDialog).props('maximized')).toBe(false);
      expect(document.querySelector('.q-dialog .q-markup-table')).not.toBeNull();
      wrapper.unmount();
    });
  });
});
