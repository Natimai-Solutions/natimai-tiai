import { defineStore } from 'pinia';

import { getMe, login as loginRequest, type User } from 'src/services/auth';
import { permissionKey, type Action, type Resource } from 'src/utils/permissions';

// Same key the axios boot reads to attach the Bearer header (kept in sync via
// localStorage rather than a cross-import to avoid a boot/store import cycle).
const TOKEN_KEY = 'tiai_token';
// Permissions cached for the router guard, which runs outside any component
// and so cannot await the profile fetch. Purely cosmetic: it decides whether
// to show a page, never whether the API answers — the backend re-checks every
// call, so a tampered value only earns a 403.
export const PERMISSIONS_KEY = 'tiai_permissions';

interface AuthState {
  token: string | null;
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

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem(TOKEN_KEY),
    user: null,
  }),
  getters: {
    isAuthenticated: (state): boolean => !!state.token,
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
    setToken(token: string | null) {
      this.token = token;
      if (token) {
        localStorage.setItem(TOKEN_KEY, token);
      } else {
        localStorage.removeItem(TOKEN_KEY);
      }
    },
    async login(email: string, password: string) {
      const { access_token } = await loginRequest(email, password);
      this.setToken(access_token);
      await this.fetchMe();
    },
    async fetchMe() {
      this.user = await getMe();
      localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(this.user.permissions));
    },
    logout() {
      this.setToken(null);
      this.user = null;
      localStorage.removeItem(PERMISSIONS_KEY);
    },
  },
});
