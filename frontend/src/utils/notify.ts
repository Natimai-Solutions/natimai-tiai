/**
 * The console's notifications: every `$q.notify` goes through `notify`.
 *
 * Two things a plain `$q.notify(options)` cannot do:
 *
 * - Follow a live change of language. Its texts are strings, composed once:
 *   a change of language that arrives while it is on screen (a profile read,
 *   plan §8) would leave it in the old language behind a page that switched.
 *   `notify` takes a function that builds the options instead, and builds them
 *   again on each change of language for as long as the notification is shown
 *   — a message composed from an API error is composed again from the error.
 *
 * - Keep clear of a dialog's buttons. A notification shows at the bottom of
 *   the screen, where a dialog has its actions (« Enregistrer », « Reprendre
 *   l'envoi »): one raised while a dialog is open shows at the top instead.
 *   A dialog on its way out does not count, so the « saved » that closes a
 *   dialog still shows where it always did.
 *
 * Identical notifications still group into one, with its « 2 », « 3 »
 * badge, as Quasar groups them; one that stays (timeout 0) or is not grouped
 * (`group: false`) is updated in place.
 */
import type { QNotifyCreateOptions, QNotifyUpdateOptions } from 'quasar';
import { nextTick } from 'vue';
import { onLocaleChange } from 'src/i18n';

/** `$q`, or anything with Quasar's `notify` (`Notify.create` outside a component). */
export type Notifier = {
  notify: (options: QNotifyCreateOptions) => (props?: QNotifyUpdateOptions) => void;
};

type Position = NonNullable<QNotifyCreateOptions['position']>;

/**
 * Whether a dialog is on screen, one leaving excepted: Vue's transition marks
 * the one closing (`…-leave-from`, `…-leave-active`) as soon as it starts.
 */
export function dialogOpen(): boolean {
  if (typeof document === 'undefined') return false;
  return Array.from(document.querySelectorAll('.q-dialog__inner')).some(
    (el) => !/-leave-/.test(el.className),
  );
}

/**
 * Where a notification shows: where its options say, else at the top while a
 * dialog is open — its buttons are at the bottom — and at the bottom otherwise.
 */
export function notifyPosition(options: QNotifyCreateOptions): Position {
  return options.position ?? (dialogOpen() ? 'top' : 'bottom');
}

/** What Quasar groups by: the same words, the same buttons, the same place. */
function groupKey(options: QNotifyCreateOptions, position: Position): string {
  return [
    options.message,
    options.caption,
    options.multiLine,
    ...(options.actions ?? []).map((a) => `${a.label}*${a.icon}`),
    position,
  ].join('|');
}

interface Grouped {
  /** The latest to raise it: the one that shows it again. */
  q: Notifier;
  build: () => QNotifyCreateOptions;
  position: Position;
  key: string;
  count: number;
  dismiss: () => void;
  stop: () => void;
  /** Taken down to be shown again in another language: not a dismissal. */
  relabelling: boolean;
  onDismiss: (() => void)[];
}

/** The grouped notifications on screen, by what Quasar groups them by. */
const grouped = new Map<string, Grouped>();

function showGrouped(entry: Grouped): void {
  const built = entry.build();
  entry.key = groupKey(built, entry.position);
  grouped.set(entry.key, entry);
  entry.dismiss = entry.q.notify({
    ...built,
    position: entry.position,
    group: entry.key,
    onDismiss: () => {
      if (entry.relabelling) return;
      entry.stop();
      if (grouped.get(entry.key) === entry) grouped.delete(entry.key);
      entry.onDismiss.forEach((fn) => fn());
    },
  });
}

function createGrouped(q: Notifier, build: () => QNotifyCreateOptions, position: Position) {
  const first = build();
  const key = groupKey(first, position);
  const existing = grouped.get(key);
  const onDismiss = first.onDismiss;
  if (existing) {
    // Quasar groups it with the one shown: its badge counts one more.
    existing.count += 1;
    existing.q = q;
    existing.build = build;
    if (onDismiss) existing.onDismiss.push(onDismiss);
    showGrouped(existing);
    return () => existing.dismiss();
  }
  const entry: Grouped = {
    q,
    build,
    position,
    key,
    count: 1,
    dismiss: () => {},
    stop: () => {},
    relabelling: false,
    onDismiss: onDismiss ? [onDismiss] : [],
  };
  showGrouped(entry);
  // A grouped notification cannot be updated (Quasar): taken down and shown
  // again, as many times as it was raised, so that its badge keeps its count.
  entry.stop = onLocaleChange(() => {
    if (grouped.get(entry.key) === entry) grouped.delete(entry.key);
    entry.relabelling = true;
    entry.dismiss();
    entry.relabelling = false;
    for (let i = 0; i < entry.count; i++) showGrouped(entry);
  });
  return () => entry.dismiss();
}

function createUpdated(q: Notifier, build: () => QNotifyCreateOptions, position: Position) {
  let stop = () => {};
  const options = (): QNotifyCreateOptions => {
    const built = build();
    return {
      ...built,
      position,
      // Quasar updates only a notification that is not grouped.
      group: false,
      onDismiss: () => {
        stop();
        built.onDismiss?.();
      },
    };
  };
  const update = q.notify(options());
  stop = onLocaleChange(() => update(options()));
  return () => update();
}

/**
 * `$q.notify(build())`, its texts built again on each change of language
 * until it is dismissed, shown clear of an open dialog's buttons. Returns a
 * function that dismisses it.
 *
 * Raised while a dialog is open, it shows once the current changes are on
 * screen, so that a dialog closed in the same handler — before or after this
 * call — no longer counts as open.
 */
export function notify(q: Notifier, build: () => QNotifyCreateOptions): () => void {
  // No dialog open, none can be closing: shown at once.
  if (!dialogOpen()) return notifyNow(q, build);
  let dismiss: (() => void) | null = null;
  let cancelled = false;
  void Promise.resolve()
    .then(() => nextTick())
    .then(() => {
      if (cancelled) return;
      dismiss = notifyNow(q, build);
    });
  return () => {
    cancelled = true;
    dismiss?.();
  };
}

/** `notify`, shown at once. */
export function notifyNow(q: Notifier, build: () => QNotifyCreateOptions): () => void {
  const first = build();
  const position = notifyPosition(first);
  const stays = first.group === false || first.timeout === 0;
  return stays ? createUpdated(q, build, position) : createGrouped(q, build, position);
}
