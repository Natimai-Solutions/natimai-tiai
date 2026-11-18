import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DialogChainObject, QDialogOptions, QNotifyCreateOptions } from 'quasar';
import { setLocale, t } from 'src/i18n';
import { liveDialog, liveNotify } from './liveDialog';

afterEach(() => setLocale('fr'));

/** What `$q.dialog` returns, with the dismissal in the test's hands. */
function fakeDialog() {
  const dismissed: (() => void)[] = [];
  const chain = {
    update: vi.fn(() => chain),
    onDismiss: vi.fn((fn: () => void) => {
      dismissed.push(fn);
      return chain;
    }),
    onOk: vi.fn(() => chain),
  };
  const dialog = vi.fn((_options: QDialogOptions) => chain as unknown as DialogChainObject);
  return { dialog, chain, dismiss: () => dismissed.forEach((fn) => fn()) };
}

describe('liveDialog', () => {
  it('opens with the texts of the language shown, and rewords them on a change', () => {
    const { dialog, chain, dismiss } = fakeDialog();
    const returned = liveDialog({ dialog }, () => ({ title: t('machine.actions.revokeTitle') }));
    expect(returned).toBe(chain);
    expect(dialog).toHaveBeenCalledWith({ title: 'Révoquer le token' });

    setLocale('en');
    expect(chain.update).toHaveBeenLastCalledWith({ title: 'Revoke the token' });

    // Closed: a later change of language leaves it alone.
    dismiss();
    setLocale('fr');
    expect(chain.update).toHaveBeenCalledTimes(1);
  });
});

describe('liveNotify', () => {
  it('rewords a notification that stays, until it is dismissed', () => {
    const update = vi.fn();
    let options: QNotifyCreateOptions | undefined;
    const notify = vi.fn((o: QNotifyCreateOptions) => {
      options = o;
      return update;
    });
    const onDismiss = vi.fn();
    const returned = liveNotify(notify, () => ({
      message: t('layout.staleChunk.close'),
      timeout: 0,
      onDismiss,
    }));
    expect(returned).toBe(update);
    expect(options).toMatchObject({ message: t('layout.staleChunk.close'), group: false });
    const french = options!.message;

    setLocale('en');
    expect(update).toHaveBeenCalledTimes(1);
    const english = (update.mock.calls[0] as [QNotifyCreateOptions])[0];
    expect(english).toMatchObject({ timeout: 0, group: false });
    expect(english.message).not.toBe(french);
    expect(english.message).toBe(t('layout.staleChunk.close'));

    // Dismissed: the caller's own onDismiss runs, and no update follows.
    options!.onDismiss!();
    expect(onDismiss).toHaveBeenCalledTimes(1);
    setLocale('fr');
    expect(update).toHaveBeenCalledTimes(1);
  });
});

describe('the console’s confirmations', () => {
  it('all open through liveDialog', () => {
    const src = new URL('..', import.meta.url).pathname;
    const sources = (dir: string): string[] =>
      readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return sources(path);
        return /\.(vue|ts)$/.test(name) && !name.endsWith('.spec.ts') ? [path] : [];
      });
    const plain = sources(src).filter(
      (path) =>
        !path.endsWith('liveDialog.ts') && readFileSync(path, 'utf-8').includes('$q.dialog('),
    );
    expect(plain).toEqual([]);
  });
});
