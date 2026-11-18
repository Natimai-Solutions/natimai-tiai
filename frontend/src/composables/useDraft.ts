import { watch, type Ref } from 'vue';
import { useAuthStore } from 'src/stores/auth';
import { draftKey, draftStore } from 'src/utils/drafts';

export interface UseDraftOptions {
  /**
   * What the draft was typed about, when the key alone does not say: the
   * selection of the bulk form. Kept with the draft and compared as a whole
   * on `restore()` — a draft is only given back to the very same scope, and
   * a draft typed for another one takes the slot.
   */
  scope?: () => string;
}

/** A draft as stored: the fields, and the scope they were typed for. */
interface StoredDraft {
  scope: string | null;
  values: Record<string, unknown>;
}

/**
 * Keep what is being typed in a form across the end of a session (item 7):
 * the access token expires, the console sends the reader to the login page,
 * and the long text of a dialog went with the page. Every change of `refs` is
 * written to sessionStorage under `key`; `restore()` puts it back when the
 * form opens again, `clear()` forgets it once the form was sent.
 *
 * `key` names the form, and what it is about when that matters
 * (`check-request:<machine id>`): a draft for one poste must not open on
 * another. A function, so a dialog reused for several postes reads it late;
 * `null` from it means « nothing to keep here ».
 *
 * A draft belongs to the account that typed it: stored under its user id
 * (`utils/drafts`), neither written nor read while no profile is loaded. The
 * tab of a shared poste sees several accounts in a row, and the text of one —
 * left there by a session that ended — must not open ready to send under the
 * name of the next. The auth store forgets the drafts on logout, and those of
 * anybody else as soon as it knows who is there.
 */
export function useDraft(
  key: string | (() => string | null),
  refs: Record<string, Ref<unknown>>,
  options: UseDraftOptions = {},
): { restore: () => boolean; clear: () => void } {
  const auth = useAuthStore();

  /** Where this form's draft goes now; null when there is no place for it. */
  function storageKey(): string | null {
    const userId = auth.user?.id;
    const name = typeof key === 'function' ? key() : key;
    return userId && name ? draftKey(userId, name) : null;
  }
  const scope = () => options.scope?.() ?? null;

  // Not while restoring: the restore itself would be written back.
  let restoring = false;

  watch(
    () => Object.fromEntries(Object.entries(refs).map(([name, r]) => [name, r.value])),
    (values) => {
      if (restoring) return;
      const at = storageKey();
      if (!at) return;
      try {
        const draft: StoredDraft = { scope: scope(), values };
        draftStore()?.setItem(at, JSON.stringify(draft));
      } catch {
        // Full or refused: the form still works, only the safety net is gone.
      }
    },
    { deep: true },
  );

  function restore(): boolean {
    const at = storageKey();
    if (!at) return false;
    let saved: Partial<StoredDraft> | null = null;
    try {
      const raw = draftStore()?.getItem(at);
      saved = raw ? (JSON.parse(raw) as Partial<StoredDraft>) : null;
    } catch {
      saved = null;
    }
    const values = saved?.values;
    if (!saved || !values || typeof values !== 'object') return false;
    // Typed for something else (another selection): not this form's draft.
    if ((saved.scope ?? null) !== scope()) return false;
    restoring = true;
    for (const [name, r] of Object.entries(refs)) {
      if (name in values) r.value = values[name];
    }
    // The watcher runs after this tick; the flag goes once it has.
    void Promise.resolve().then(() => {
      restoring = false;
    });
    return true;
  }

  function clear(): void {
    const at = storageKey();
    if (!at) return;
    try {
      draftStore()?.removeItem(at);
    } catch {
      // Nothing was kept.
    }
  }

  return { restore, clear };
}
