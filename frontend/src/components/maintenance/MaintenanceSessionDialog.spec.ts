import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QDialog } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  recordSession: vi.fn(),
}));

import { recordSession } from 'src/services/maintenance';
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
    vi.mocked(recordSession)
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

    expect(recordSession).toHaveBeenCalledWith(
      expect.objectContaining({
        room_id: 'r',
        items: [
          { machine_id: 'a', note: null },
          { machine_id: 'b', note: null },
        ],
        skipped: [{ machine_id: 'c', note: 'éteint' }],
      }),
    );
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });
});
