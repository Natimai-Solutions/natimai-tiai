import { watch, type Ref } from 'vue';

/** Where drafts live: per tab, gone with it — never on the disk of a shared poste. */
export const DRAFT_PREFIX = 'tiai.draft.';

function store(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
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
 * another. A function, so a dialog reused for several postes reads it late.
 */
export function useDraft(
  key: string | (() => string),
  refs: Record<string, Ref<unknown>>,
): { restore: () => boolean; clear: () => void } {
  const storageKey = () => DRAFT_PREFIX + (typeof key === 'function' ? key() : key);
  // Not while restoring: the restore itself would be written back.
  let restoring = false;

  watch(
    () => Object.fromEntries(Object.entries(refs).map(([name, r]) => [name, r.value])),
    (values) => {
      if (restoring) return;
      try {
        store()?.setItem(storageKey(), JSON.stringify(values));
      } catch {
        // Full or refused: the form still works, only the safety net is gone.
      }
    },
    { deep: true },
  );

  function restore(): boolean {
    let saved: Record<string, unknown> | null = null;
    try {
      const raw = store()?.getItem(storageKey());
      saved = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
    } catch {
      saved = null;
    }
    if (!saved || typeof saved !== 'object') return false;
    restoring = true;
    for (const [name, r] of Object.entries(refs)) {
      if (name in saved) r.value = saved[name];
    }
    // The watcher runs after this tick; the flag goes once it has.
    void Promise.resolve().then(() => {
      restoring = false;
    });
    return true;
  }

  function clear(): void {
    try {
      store()?.removeItem(storageKey());
    } catch {
      // Nothing was kept.
    }
  }

  return { restore, clear };
}
