/**
 * Where the drafts of `useDraft` live, and how they are forgotten.
 *
 * In sessionStorage: per tab, gone with it — never on the disk of a shared
 * poste. And per account: a key reads `tiai.draft.<user id>.<form>`, so the
 * text one account typed is never the draft of another one logging in on the
 * same tab. Plain functions, apart from the composable, because the auth
 * store calls them (a composable importing the store that imports it would
 * close a cycle).
 */
export const DRAFT_PREFIX = 'tiai.draft.';

export function draftStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** The storage key of `key` for the account `userId`. */
export function draftKey(userId: string, key: string): string {
  return `${DRAFT_PREFIX}${userId}.${key}`;
}

function forgetWhere(doomed: (key: string) => boolean): void {
  try {
    const store = draftStore();
    if (!store) return;
    // Collected first: removing while walking by index skips entries.
    const keys: string[] = [];
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i);
      if (key?.startsWith(DRAFT_PREFIX) && doomed(key)) keys.push(key);
    }
    keys.forEach((key) => store.removeItem(key));
  } catch {
    // Storage refused: nothing was kept either.
  }
}

/** Forget every draft of the tab — the account logs out, and is done here. */
export function forgetDrafts(): void {
  forgetWhere(() => true);
}

/**
 * Forget the drafts that are not `userId`'s: another account has just been
 * identified on this tab. Those written before drafts had an owner (no user
 * id in the key) go too — nobody can tell whose they were.
 */
export function forgetDraftsOfOthers(userId: string): void {
  const mine = draftKey(userId, '');
  forgetWhere((key) => !key.startsWith(mine));
}
