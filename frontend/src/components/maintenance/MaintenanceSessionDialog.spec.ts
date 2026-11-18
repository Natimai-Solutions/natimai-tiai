import { flushPromises, mount } from '@vue/test-utils';
import { QBtn, QDialog, Screen } from 'quasar';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  recordSessionInParts: vi.fn(),
}));
vi.mock('src/composables/useTasksBadge', () => ({ notifyTasksChanged: vi.fn() }));

import { notifyTasksChanged } from 'src/composables/useTasksBadge';
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
    vi.mocked(notifyTasksChanged).mockReset();
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

  function cancelButton() {
    return [...document.querySelectorAll<HTMLButtonElement>('.q-dialog button')].find((b) =>
      b.textContent?.includes('Annuler'),
    )!;
  }

  it('refreshes the page when a visit cut half-way is abandoned', async () => {
    vi.mocked(recordSessionInParts).mockImplementationOnce(async (_payload, progress) => {
      progress!.sessionId = 's-1';
      progress!.sent = 250;
      throw new Error('réseau');
    });
    const wrapper = await open();
    await submitForm();
    expect(wrapper.emitted('recorded')).toBeUndefined();

    cancelButton().click();
    await flushPromises();
    // What stays recorded is said before anything is abandoned.
    expect(document.body.textContent).toContain("Abandonner l'envoi ?");
    expect(document.body.textContent).toContain('250 poste(s) sur 2 sont enregistrés');
    expect(closes(wrapper)).toBe(0);
    pluginButton('Abandonner').click();
    await flushPromises();

    // The part recorded is on the page behind: its lists are read again.
    expect(closes(wrapper)).toBe(1);
    expect(wrapper.emitted('recorded')).toHaveLength(1);
    expect(notifyTasksChanged).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('offers no way out while a part is on its way', async () => {
    let finish!: () => void;
    vi.mocked(recordSessionInParts).mockImplementationOnce(
      () => new Promise((resolve) => (finish = () => resolve({} as never))),
    );
    const wrapper = await open();
    await typeNote('PC-A', 'clavier HS');
    await submitForm();

    // « Annuler » then « Abandonner » closed the dialog and abandoned
    // nothing: the parts kept leaving behind it.
    expect(cancelButton().disabled).toBe(true);
    await pressEscape();
    expect(document.body.textContent).not.toContain('Abandonner');
    expect(closes(wrapper)).toBe(0);
    // Nor a second sending beside the first.
    await submitForm();
    expect(recordSessionInParts).toHaveBeenCalledTimes(1);

    finish();
    await flushPromises();
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });

  it('keeps a visit whose first part got no answer, and sends it again as the same visit', async () => {
    vi.mocked(recordSessionInParts)
      // No answer: the server may have recorded the part, or never seen it.
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValue({} as never);
    const wrapper = await open();
    await submitForm();

    expect(closes(wrapper)).toBe(0);
    const banner = inDialog('[data-test="session-pending"]').textContent.replace(/\s+/g, ' ');
    expect(banner).toContain('peut-être déjà enregistrée');
    expect(banner).toContain('sans en créer une seconde');
    expect(submitButton().textContent).toContain("Reprendre l'envoi");
    // Frozen: what is sent again is what was sent.
    expect(inDialog<HTMLInputElement>('input[aria-label="Note pour PC-A"]').disabled).toBe(true);
    await submitForm();

    const [first, second] = vi.mocked(recordSessionInParts).mock.calls;
    expect(second![0]).toStrictEqual(first![0]);
    // The same progress, so the same client id: no second visit.
    const id = (first![1] as SessionProgress).clientId;
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
    expect(second![1]).toMatchObject({ clientId: id, sessionId: null, sent: 0 });
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });

  it('says a visit may be recorded when its unanswered first part is abandoned', async () => {
    vi.mocked(recordSessionInParts).mockRejectedValueOnce(new Error('Network Error'));
    const wrapper = await open();
    await submitForm();
    cancelButton().click();
    await flushPromises();
    expect(document.body.textContent).toContain('la séance est peut-être enregistrée');
    pluginButton('Abandonner').click();
    await flushPromises();
    expect(closes(wrapper)).toBe(1);
    expect(wrapper.emitted('recorded')).toHaveLength(1);
    wrapper.unmount();
  });

  /** What axios rejects with when the server answers an error. */
  function refusal(status: number, code: string, details: Record<string, unknown> = {}) {
    return Object.assign(new Error(code), {
      response: { status, data: { error: { code, details } } },
    });
  }

  it('gives the form back when the server refuses the first part: nothing is recorded', async () => {
    vi.mocked(recordSessionInParts).mockRejectedValueOnce(
      refusal(422, 'maintenance.items.not_in_room', { machine_ids: ['b'], hostnames: ['PC-B'] }),
    );
    const wrapper = await open();
    const notify = vi.spyOn(wrapper.vm.$q, 'notify');
    await submitForm();

    expect(document.querySelector('[data-test="session-pending"]')).toBeNull();
    expect(submitButton().textContent).toContain('Enregistrer');
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Ces postes ne sont pas dans la salle de la séance : PC-B',
      }),
    );
    // The poste named is unticked by hand, and the visit sent anew.
    inDialog<HTMLElement>('[aria-label="PC-B : fait"]').click();
    await flushPromises();
    await submitForm();
    const [first, second] = vi.mocked(recordSessionInParts).mock.calls;
    expect(second![0].items).toEqual([{ machine_id: 'a', note: null }]);
    expect((second![1] as SessionProgress).clientId).not.toBe(
      (first![1] as SessionProgress).clientId,
    );
    wrapper.unmount();
  });

  it('lets a resumed visit leave out the postes that left the room since', async () => {
    vi.mocked(recordSessionInParts)
      .mockImplementationOnce(async (_payload, progress) => {
        // PC-A is recorded; the next part is refused for PC-B, moved since.
        progress!.sessionId = 's-1';
        progress!.sent = 1;
        throw refusal(422, 'maintenance.items.not_in_room', {
          machine_ids: ['b'],
          hostnames: ['PC-B'],
        });
      })
      .mockResolvedValue({} as never);
    const wrapper = await open();
    await typeNote('PC-C', 'éteint');
    await submitForm();

    const banner = inDialog('[data-test="session-refused"]').textContent.replace(/\s+/g, ' ');
    expect(banner).toContain('ne sont plus dans la salle');
    expect(banner).toContain('PC-B');
    expect(banner).not.toContain('PC-A');
    const notify = vi.spyOn(wrapper.vm.$q, 'notify');
    inDialog<HTMLElement>('[data-test="session-drop"]').click();
    await flushPromises();

    const [first, second] = vi.mocked(recordSessionInParts).mock.calls;
    // The same visit, without the poste refused; what is recorded stays.
    expect(second![1]).toMatchObject({
      clientId: (first![1] as SessionProgress).clientId,
      sessionId: 's-1',
      sent: 1,
      total: 2,
    });
    expect(second![0]).toMatchObject({
      items: [{ machine_id: 'a', note: null }],
      skipped: [{ machine_id: 'c', note: 'éteint' }],
    });
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Maintenance enregistrée sur 1 poste(s)' }),
    );
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });

  it('shows a dropped poste unticked and removed when the resumed send stops again', async () => {
    vi.mocked(recordSessionInParts)
      .mockImplementationOnce(async (_payload, progress) => {
        progress!.sessionId = 's-1';
        progress!.sent = 1;
        throw refusal(422, 'maintenance.items.not_in_room', {
          machine_ids: ['b'],
          hostnames: ['PC-B'],
        });
      })
      // The send without PC-B stops too: the dialog stays, and its list must
      // say what the visit now holds.
      .mockRejectedValueOnce(new Error('Network Error'));
    const wrapper = await open();
    await submitForm();
    expect(inDialog('.q-card').textContent).toContain('2 poste(s) coché(s)');
    inDialog<HTMLElement>('[data-test="session-drop"]').click();
    await flushPromises();

    expect(closes(wrapper)).toBe(0);
    const row = [...document.querySelectorAll<HTMLElement>('.q-dialog tbody tr')].find((r) =>
      r.textContent?.includes('PC-B'),
    )!;
    expect(row.querySelector('[aria-label="PC-B : fait"]')!.getAttribute('aria-checked')).toBe(
      'false',
    );
    expect(row.textContent).toContain('Retiré de cette séance');
    // One fewer poste ticked: what the visit records now.
    expect(inDialog('.q-card').textContent).toContain('1 poste(s) coché(s)');
    wrapper.unmount();
  });

  it('names a poste that no longer exists, and leaves it out the same way', async () => {
    vi.mocked(recordSessionInParts)
      .mockImplementationOnce(async (_payload, progress) => {
        progress!.sessionId = 's-1';
        progress!.sent = 1;
        throw refusal(404, 'machine.not_found', { machine_ids: ['b'] });
      })
      .mockResolvedValue({} as never);
    const wrapper = await open();
    await submitForm();
    const banner = inDialog('[data-test="session-refused"]').textContent.replace(/\s+/g, ' ');
    expect(banner).toContain('n’existent plus');
    expect(banner).toContain('PC-B');
    inDialog<HTMLElement>('[data-test="session-drop"]').click();
    await flushPromises();
    expect(vi.mocked(recordSessionInParts).mock.calls[1]![0].items).toEqual([
      { machine_id: 'a', note: null },
    ]);
    wrapper.unmount();
  });

  // Review gap-1-2: the part that creates the visit refused for a poste.
  it('names a poste gone before the first part, and sends the visit anew without it', async () => {
    vi.mocked(recordSessionInParts)
      .mockRejectedValueOnce(refusal(404, 'machine.not_found', { machine_ids: ['b'] }))
      .mockResolvedValue({} as never);
    const wrapper = await open();
    await typeNote('PC-B', 'une note');
    await submitForm();

    // Nothing is recorded: no pending sending, the form is the user's again.
    expect(document.querySelector('[data-test="session-pending"]')).toBeNull();
    expect(submitButton().textContent).toContain('Enregistrer');
    const banner = inDialog('[data-test="session-refused"]').textContent.replace(/\s+/g, ' ');
    expect(banner).toContain('n’existent plus');
    expect(banner).toContain('PC-B');
    inDialog<HTMLElement>('[data-test="session-drop"]').click();
    await flushPromises();

    const [first, second] = vi.mocked(recordSessionInParts).mock.calls;
    // A new visit, without the poste — done or left out with its note.
    expect(second![0]).toMatchObject({ items: [{ machine_id: 'a', note: null }], skipped: [] });
    expect((second![1] as SessionProgress).clientId).not.toBe(
      (first![1] as SessionProgress).clientId,
    );
    expect(closes(wrapper)).toBe(1);
    wrapper.unmount();
  });

  it('offers to remove a poste refused when an interrupted first part is resumed', async () => {
    vi.mocked(recordSessionInParts)
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockRejectedValueOnce(
        refusal(422, 'maintenance.items.not_in_room', { machine_ids: ['b'], hostnames: ['PC-B'] }),
      )
      // Sent without PC-B, it stops again: the list says what was left out.
      .mockRejectedValueOnce(new Error('Network Error'));
    const wrapper = await open();
    await submitForm();
    expect(submitButton().textContent).toContain("Reprendre l'envoi");
    await submitForm();

    const banner = inDialog('[data-test="session-refused"]').textContent.replace(/\s+/g, ' ');
    expect(banner).toContain('ne sont plus dans la salle');
    expect(banner).toContain('PC-B');
    inDialog<HTMLElement>('[data-test="session-drop"]').click();
    await flushPromises();

    expect(vi.mocked(recordSessionInParts).mock.calls[2]![0].items).toEqual([
      { machine_id: 'a', note: null },
    ]);
    const row = [...document.querySelectorAll<HTMLElement>('.q-dialog tbody tr')].find((r) =>
      r.textContent?.includes('PC-B'),
    )!;
    expect(row.querySelector('[aria-label="PC-B : fait"]')!.getAttribute('aria-checked')).toBe(
      'false',
    );
    expect(row.textContent).toContain('Retiré de cette séance');
    wrapper.unmount();
  });

  // Review gap2-2-1: fifty postes refused stay a sentence.
  it('names the first few postes refused, then how many more', async () => {
    const ids = ['b', ...Array.from({ length: 49 }, (_, i) => `x${i + 1}`)];
    vi.mocked(recordSessionInParts).mockImplementationOnce(async (_payload, progress) => {
      progress!.sessionId = 's-1';
      progress!.sent = 1;
      throw refusal(422, 'maintenance.items.not_in_room', { machine_ids: ids });
    });
    const wrapper = await open();
    await submitForm();
    const banner = inDialog('[data-test="session-refused"]').textContent.replace(/\s+/g, ' ');
    expect(banner).toContain(
      'Ces postes ne sont plus dans la salle depuis le début de la saisie : PC-B, x1, x2, x3, x4 et 45 autre(s). Ils ne peuvent pas être ajoutés à la séance.',
    );
    expect(banner).not.toContain('x5');
    wrapper.unmount();
  });

  // Review gap-1-4: on a wider screen too, the list scrolls between a fixed
  // title and the fixed state and buttons of a sending that stopped.
  it('keeps the card within the window, its list scrolling', async () => {
    const wrapper = await open();
    const card = inDialog<HTMLElement>('[data-test="session-card"]');
    expect(card.classList).toContain('column');
    // Bounded by the window (jsdom folds `max-height` into its own spelling).
    expect(card.getAttribute('style')).toContain('100vh');
    expect(inDialog('[data-test="session-list"]').classList).toContain('scroll');
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
