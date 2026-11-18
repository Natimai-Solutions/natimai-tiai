import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DialogChainObject, QDialogOptions } from 'quasar';
import { setLocale, t } from 'src/i18n';
import { liveDialog } from './liveDialog';

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

  it('all notify through src/utils/notify.ts', () => {
    const src = new URL('..', import.meta.url).pathname;
    const sources = (dir: string): string[] =>
      readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return sources(path);
        return /\.(vue|ts)$/.test(name) && !name.endsWith('.spec.ts') ? [path] : [];
      });
    // The one way in from outside a component, handed to notify itself.
    const adapter = '{ notify: (options) => Notify.create(options) }';
    const plain = sources(src).filter(
      (path) =>
        !path.endsWith(join('utils', 'notify.ts')) &&
        /\$q\.notify\(|useQuasar\(\)\.notify\(|Notify\.create\(/.test(
          readFileSync(path, 'utf-8').split(adapter).join(''),
        ),
    );
    expect(plain).toEqual([]);
  });
});
