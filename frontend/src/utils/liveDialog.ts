/**
 * Confirmations that follow a live change of language.
 *
 * `$q.dialog(options)` takes its texts as strings, composed once, when it
 * opens: a change of language that arrives while it is on screen (a profile
 * read, plan §8) would leave it in the old language behind a page that
 * switched. This takes a function that builds the options instead, and builds
 * them again on each change of language for as long as the dialog is shown.
 * Notifications: `src/utils/notify.ts`.
 */
import type { DialogChainObject, QDialogOptions, QVueGlobals } from 'quasar';
import { onLocaleChange } from 'src/i18n';

/** `$q.dialog(build())`, its texts built again when the language changes. */
export function liveDialog(
  $q: Pick<QVueGlobals, 'dialog'>,
  build: () => QDialogOptions,
): DialogChainObject {
  const dialog = $q.dialog(build());
  const stop = onLocaleChange(() => dialog.update(build()));
  return dialog.onDismiss(stop);
}
