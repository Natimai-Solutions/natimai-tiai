import { defineStore } from 'pinia';

import { getMe, login as loginRequest, type User } from 'src/services/auth';

// Same key the axios boot reads to attach the Bearer header (kept in sync via
// localStorage rather than a cross-import to avoid a boot/store import cycle).
const TOKEN_KEY = 'tiai_token';
// Role cached for the router guard, which runs outside any component and so
// cannot await the profile fetch. Purely cosmetic: it decides whether to show
// the admin pages, never whether the API answers — the backend re-checks every
// call, so a tampered value only earns a 403.
const ROLE_KEY = 'tiai_role';

interface AuthState {
  token: string | null;
  user: User | null;
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem(TOKEN_KEY),
    user: null,
  }),
  getters: {
    isAuthenticated: (state): boolean => !!state.token,
    isAdmin: (state): boolean => state.user?.role === 'admin',
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
      localStorage.setItem(ROLE_KEY, this.user.role);
    },
    logout() {
      this.setToken(null);
      this.user = null;
      localStorage.removeItem(ROLE_KEY);
    },
  },
});
