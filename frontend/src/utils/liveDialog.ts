/**
 * Confirmations and notifications that follow a live change of language.
 *
 * `$q.dialog(options)` and `$q.notify(options)` take their texts as strings,
 * composed once, when they open: a change of language that arrives while one
 * is on screen (a profile read, plan §8) would leave it in the old language
 * behind a page that switched. These take a function that builds the options
 * instead, and build them again on each change of language for as long as the
 * dialog or the notification is shown.
 */
import type {
  DialogChainObject,
  QDialogOptions,
  QNotifyCreateOptions,
  QNotifyUpdateOptions,
  QVueGlobals,
} from 'quasar';
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

type Notify = (options: QNotifyCreateOptions) => (props?: QNotifyUpdateOptions) => void;

/**
 * `notify(build())`, its texts built again when the language changes, until
 * it is dismissed. Returns what Quasar returns: called with no argument, it
 * dismisses the notification.
 *
 * Never grouped (`group: false`): Quasar updates only a notification that is
 * not, and the one that stays (timeout 0) is the one that needs it.
 */
export function liveNotify(
  notify: Notify,
  build: () => QNotifyCreateOptions,
): (props?: QNotifyUpdateOptions) => void {
  let stop = () => {};
  const options = (): QNotifyCreateOptions => {
    const built = build();
    return {
      ...built,
      group: false,
      onDismiss: () => {
        stop();
        built.onDismiss?.();
      },
    };
  };
  const update = notify(options());
  stop = onLocaleChange(() => update(options()));
  return update;
}
