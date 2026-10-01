import { defineStore } from 'pinia';

import {
  getMe,
  login as loginRequest,
  logout as logoutRequest,
  updateMe,
  type User,
} from 'src/services/auth';
import { accessToken, endSession, onSessionEnd, setAccessToken } from 'src/services/session';
import { permissionKey, type Action, type Resource } from 'src/utils/permissions';

// Permissions cached for the router guard, which runs outside any component
// and so cannot await the profile fetch. Purely cosmetic: it decides whether
// to show a page, never whether the API answers — the backend re-checks every
// call, so a tampered value only earns a 403.
export const PERMISSIONS_KEY = 'tiai_permissions';

interface AuthState {
  user: User | null;
}

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
    async login(email: string, password: string) {
      const { access_token } = await loginRequest(email, password);
      setAccessToken(access_token);
      await this.fetchMe();
    },
    async fetchMe() {
      this.user = await getMe();
      localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(this.user.permissions));
    },
    /**
     * Store console preferences on the account. Merged key by key server-side
     * (a `null` removes a key), and the profile is refreshed from the answer
     * so every page reads the same document.
     */
    async savePreferences(patch: Record<string, unknown | null>) {
      this.user = await updateMe({ preferences: patch });
    },
    /**
     * Log out for real: the server revokes the session — the access token
     * stops working at once, the refresh cookie is cleared — then the console
     * forgets it. A failed call (network down, session already over) still
     * logs out locally: the operator asked to leave, and stays out.
     */
    async logout() {
      try {
        await logoutRequest();
      } catch {
        // Nothing to do: the local half below is what the operator sees.
      }
      endSession();
    },
    /** Drop what the console derived from the session (the profile, the
     * permissions the router reads). Called through `onSessionEnd`. */
    forgetProfile() {
      this.user = null;
      forgetCachedPermissions();
    },
  },
});

// Wherever the session ends — logout here, or the 401 handler in boot/axios
// once a refresh fails — the profile goes with it.
onSessionEnd(() => useAuthStore().forgetProfile());
