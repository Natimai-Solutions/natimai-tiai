// @vitest-environment jsdom
// (Quasar's Notify renders its notifications into the page.)
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createApp, nextTick } from 'vue';
import { Notify, Quasar, type QNotifyCreateOptions } from 'quasar';
import { setLocale, t } from 'src/i18n';
import { apiErrorMessage } from 'src/services/errors';
import { dialogOpen, notify, notifyNow, notifyPosition } from './notify';

/** Quasar's own Notify, as the app installs it: grouping, badges, places. */
const quasar = { notify: (options: QNotifyCreateOptions) => Notify.create(options) };

beforeAll(() => {
  if (!window.screen.orientation) {
    Object.defineProperty(window.screen, 'orientation', {
      configurable: true,
      value: {
        type: 'landscape-primary',
        angle: 0,
        addEventListener() {},
        removeEventListener() {},
      },
    });
  }
  createApp({ render: () => null })
    .use(Quasar, { plugins: { Notify } })
    .mount(document.createElement('div'));
});

const open: (() => void)[] = [];
afterEach(() => {
  open.splice(0).forEach((dismiss) => dismiss());
  document.querySelectorAll('[data-test-dialog]').forEach((el) => el.remove());
  setLocale('fr');
});

/** What is on screen: the text of each notification, its badge, and where. */
async function shown() {
  await nextTick();
  // One taken down stays in jsdom, its leave transition never ending.
  const notifications = Array.from(document.querySelectorAll<HTMLElement>('.q-notification'));
  return notifications
    .filter((el) => !/leave/.test(el.className))
    .map((el) => ({
      message: el.querySelector('.q-notification__message')?.firstChild?.textContent?.trim(),
      caption: el.querySelector('.q-notification__caption')?.textContent?.trim(),
      badge: el.querySelector('.q-notification__badge')?.textContent?.trim() ?? null,
      top: !!el.closest('.q-notifications__list--top'),
    }));
}

/** A dialog on screen, as QDialog renders it; `leaving`, as Vue marks one closing. */
function fakeDialog(leaving = false): HTMLElement {
  const el = document.createElement('div');
  el.className = `q-dialog__inner flex${leaving ? ' q-transition--scale-leave-active' : ''}`;
  el.dataset.testDialog = '';
  document.body.appendChild(el);
  return el;
}

/** A refusal as the API answers it. */
const refusal = { response: { status: 403, data: { error: { code: 'auth.permission.denied' } } } };

describe('notify: a live change of language', () => {
  it('rewords a brief notification on screen', async () => {
    open.push(notifyNow(quasar, () => ({ type: 'positive', message: t('common.language.saved') })));
    const french = (await shown())[0]!.message;
    expect(french).toBe(t('common.language.saved'));

    setLocale('en');
    const after = await shown();
    expect(after).toHaveLength(1);
    expect(after[0]!.message).toBe(t('common.language.saved'));
    expect(after[0]!.message).not.toBe(french);
  });

  it('words an API error again from the error, not from the sentence first shown', async () => {
    open.push(
      notifyNow(quasar, () => ({
        type: 'negative',
        message: apiErrorMessage(refusal, t('maintenance.session.saveFailed')),
      })),
    );
    expect((await shown())[0]!.message).toBe("Vous n'avez pas la permission requise");
    setLocale('en');
    const [english] = await shown();
    expect(english!.message).toBe(apiErrorMessage(refusal));
    expect(english!.message).not.toBe("Vous n'avez pas la permission requise");
  });

  it('groups identical notifications as Quasar does, and keeps the count across a change', async () => {
    const build = () => ({ type: 'positive', message: t('common.language.saved') });
    open.push(notifyNow(quasar, build), notifyNow(quasar, build), notifyNow(quasar, build));
    expect(await shown()).toEqual([
      expect.objectContaining({ message: t('common.language.saved'), badge: '3' }),
    ]);

    setLocale('en');
    expect(await shown()).toEqual([
      expect.objectContaining({ message: t('common.language.saved'), badge: '3' }),
    ]);
    // Grouped again in the new language: a fourth one counts with them.
    open.push(notifyNow(quasar, build));
    expect(await shown()).toEqual([expect.objectContaining({ badge: '4' })]);
  });

  it('updates in place one that stays, until it is dismissed; its own onDismiss runs', async () => {
    const onDismiss = vi.fn();
    const create = vi.spyOn(quasar, 'notify');
    const dismiss = notifyNow(quasar, () => ({
      message: t('layout.staleChunk.close'),
      timeout: 0,
      onDismiss,
    }));
    expect(create.mock.calls[0]![0]).toMatchObject({ group: false, timeout: 0 });
    const french = (await shown())[0]!.message;

    setLocale('en');
    expect(create).toHaveBeenCalledTimes(1);
    const [english] = await shown();
    expect(english!.message).toBe(t('layout.staleChunk.close'));
    expect(english!.message).not.toBe(french);

    dismiss();
    expect(onDismiss).toHaveBeenCalledTimes(1);
    setLocale('fr');
    expect(await shown()).toEqual([]);
    create.mockRestore();
  });

  it('leaves a dismissed one alone, and calls the caller’s onDismiss once', async () => {
    const onDismiss = vi.fn();
    const create = vi.spyOn(quasar, 'notify');
    const dismiss = notifyNow(quasar, () => ({ message: t('common.language.saved'), onDismiss }));
    setLocale('en');
    // Taken down and shown again in English: not a dismissal.
    expect(onDismiss).not.toHaveBeenCalled();
    dismiss();
    expect(onDismiss).toHaveBeenCalledTimes(1);
    const calls = create.mock.calls.length;
    setLocale('fr');
    expect(create).toHaveBeenCalledTimes(calls);
    create.mockRestore();
  });
});

describe('notify: clear of a dialog’s buttons', () => {
  it('shows at the bottom, at the top while a dialog is open', async () => {
    expect(dialogOpen()).toBe(false);
    expect(notifyPosition({ message: 'x' })).toBe('bottom');
    fakeDialog();
    expect(dialogOpen()).toBe(true);
    expect(notifyPosition({ message: 'x' })).toBe('top');
    // A place the caller chose stays the caller's.
    expect(notifyPosition({ message: 'x', position: 'bottom-right' })).toBe('bottom-right');

    open.push(notifyNow(quasar, () => ({ type: 'negative', message: t('common.language.saved') })));
    expect(await shown()).toEqual([expect.objectContaining({ top: true })]);
  });

  it('does not count a dialog on its way out', () => {
    fakeDialog(true);
    expect(dialogOpen()).toBe(false);
  });

  it('places it once the handler’s own changes are on screen', async () => {
    // The « saved » that closes its dialog: raised while the dialog is still
    // open, the dialog starts closing just after — it shows at the bottom.
    const dialog = fakeDialog();
    open.push(notify(quasar, () => ({ type: 'positive', message: t('common.language.saved') })));
    dialog.classList.add('q-transition--scale-leave-active');
    await Promise.resolve();
    await nextTick();
    await vi.waitFor(async () =>
      expect(await shown()).toEqual([expect.objectContaining({ top: false })]),
    );

    // An error in a dialog that stays open: at the top.
    fakeDialog();
    open.push(notify(quasar, () => ({ type: 'negative', message: t('layout.staleChunk.close') })));
    await vi.waitFor(async () =>
      expect(await shown()).toContainEqual(
        expect.objectContaining({ message: t('layout.staleChunk.close'), top: true }),
      ),
    );
  });

  it('is not shown at all when dismissed before it shows (raised in a dialog)', async () => {
    fakeDialog();
    const create = vi.spyOn(quasar, 'notify');
    notify(quasar, () => ({ message: 'x' }))();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(create).not.toHaveBeenCalled();
    create.mockRestore();
  });
});
