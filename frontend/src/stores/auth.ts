import { defineStore } from 'pinia';

import {
  getMe,
  login as loginRequest,
  logout as logoutRequest,
  updateMe,
  verifySecondFactor as verifySecondFactorRequest,
  type AccountLanguage,
  type SecondFactorChallenge,
  type User,
} from 'src/services/auth';
import {
  accessToken,
  endSession,
  onForbidden,
  onSessionEnd,
  setAccessToken,
} from 'src/services/session';
import { forgetDrafts, forgetDraftsOfOthers } from 'src/utils/drafts';
import { permissionKey, type Action, type Resource } from 'src/utils/permissions';

// Permissions cached for the router guard, which runs outside any component
// and so cannot await the profile fetch. Purely cosmetic: it decides whether
// to show a page, never whether the API answers — the backend re-checks every
// call, so a tampered value only earns a 403.
export const PERMISSIONS_KEY = 'tiai_permissions';

interface AuthState {
  user: User | null;
  /** Why the last profile read failed; null once one succeeds. */
  profileError: unknown;
}

/** A 403 re-reads the profile at most this often: a page of ten 403s is one read. */
export const FORBIDDEN_REFRESH_MIN_MS = 30_000;
/** And the profile is read again on its own at this pace while the console is open. */
export const PROFILE_REFRESH_MS = 5 * 60_000;
let lastForbiddenRefresh = 0;

export function readCachedPermissions(): string[] {
  try {
    const raw = localStorage.getItem(PERMISSIONS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((p): p is string => typeof p === 'string') : [];
  } catch {
    return [];
  }
}

function forgetCachedPermissions(): void {
  try {
    localStorage.removeItem(PERMISSIONS_KEY);
  } catch {
    // Storage disabled: nothing was cached.
  }
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    user: null,
    profileError: null,
  }),
  getters: {
    /**
     * Whether an access token is held. It lives in memory (`services/session`),
     * so this is false right after a reload until the router's silent refresh
     * has run — which is why the guard asks `ensureSession`, not this.
     */
    isAuthenticated: (): boolean => accessToken.value !== null,
    permissions: (state): Set<string> => new Set(state.user?.permissions ?? []),
    /**
     * Whether the profile grants `resource:action`. False until the profile is
     * loaded — buttons appear once it is, which is the safe direction.
     */
    can(): (resource: Resource, action: Action) => boolean {
      return (resource, action) => this.permissions.has(permissionKey(resource, action));
    },
    /** Account management: the pages behind « Utilisateurs » and « Groupes ». */
    canManageUsers(): boolean {
      return this.can('user', 'read');
    },
  },
  actions: {
    /**
     * Log in with a password. Returns the challenge when the account has a
     * second factor (C7): nothing is open yet, the page asks for the code
     * and calls `verifySecondFactor`.
     */
    async login(email: string, password: string): Promise<SecondFactorChallenge | null> {
      const answer = await loginRequest(email, password);
      if ('second_factor_required' in answer) return answer;
      setAccessToken(answer.access_token);
      await this.fetchMe();
      return null;
    },
    async verifySecondFactor(challenge: string, code: string) {
      const { access_token } = await verifySecondFactorRequest(challenge, code);
      setAccessToken(access_token);
      await this.fetchMe();
    },
    async fetchMe() {
      try {
        this.user = await getMe();
      } catch (e) {
        this.profileError = e;
        throw e;
      }
      this.profileError = null;
      // Whoever is identified here — a login, a session restored by its
      // cookie, which another tab may have logged into as somebody else —
      // only finds their own drafts: those of the account before are gone.
      forgetDraftsOfOthers(this.user.id);
      try {
        localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(this.user.permissions));
      } catch {
        // Storage disabled: the guard reads the loaded profile anyway.
      }
    },
    /**
     * Read the profile again in the background — every few minutes, and after
     * a 403 — so that rights changed by an administrator reach the menus
     * without F5. Never throws; an older profile stays until a read succeeds.
     */
    async refreshProfile() {
      if (!this.isAuthenticated) return;
      try {
        await this.fetchMe();
      } catch {
        // Kept: the profile read earlier is still the best guess.
      }
    },
    /** A 403 was answered: read the profile again, once per burst of them. */
    async onForbidden() {
      const now = Date.now();
      if (now - lastForbiddenRefresh < FORBIDDEN_REFRESH_MIN_MS) return;
      lastForbiddenRefresh = now;
      await this.refreshProfile();
    },
    /**
     * Load the profile when it is not yet: after a reload, the router's silent
     * refresh puts a token back but no profile. The guard awaits this before
     * rendering a page, so that a page testing `can()` while it loads sees the
     * real permissions — not the empty set of a profile still on its way,
     * which made the dashboard skip its threat list for good. Never throws: a
     * failed fetch leaves the page to show its own error.
     */
    async ensureProfile() {
      if (this.user) return;
      try {
        await this.fetchMe();
      } catch {
        // The page's own requests report the outage.
      }
    },
    /**
     * Store console preferences on the account. Merged key by key server-side
     * (a `null` removes a key), and the profile is refreshed from the answer
     * so every page reads the same document.
     */
    async savePreferences(patch: Record<string, unknown>) {
      this.user = await updateMe({ preferences: patch });
    },
    /**
     * Store the account's language, or `null` to follow the browser. The
     * console switches as soon as the profile comes back (`boot/i18n`).
     */
    async saveLanguage(language: AccountLanguage | null) {
      this.user = await updateMe({ language });
    },
    /**
     * Log out for real: the server revokes the session — the access token
     * stops working at once, the refresh cookie is cleared — then the console
     * forgets it. A failed call (network down, session already over) still
     * logs out locally: the operator asked to leave, and stays out.
     *
     * The drafts go too (`useDraft`): they are kept for a session that ends
     * under a form, not for one its owner closes — and whoever logs out
     * before leaving a shared poste expects nothing of theirs to stay in the
     * tab. A session lost to a 401 keeps them, for its owner alone.
     */
    async logout() {
      try {
        await logoutRequest();
      } catch {
        // Nothing to do: the local half below is what the operator sees.
      }
      forgetDrafts();
      endSession();
    },
    /** Drop what the console derived from the session (the profile, the
     * permissions the router reads). Called through `onSessionEnd`. */
    forgetProfile() {
      this.user = null;
      this.profileError = null;
      lastForbiddenRefresh = 0;
      forgetCachedPermissions();
    },
  },
});

// Wherever the session ends — logout here, or the 401 handler in boot/axios
// once a refresh fails — the profile goes with it.
onSessionEnd(() => useAuthStore().forgetProfile());
// A 403 anywhere: the account's groups may have changed under it.
onForbidden(() => void useAuthStore().onForbidden());
