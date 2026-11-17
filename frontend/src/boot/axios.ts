import { defineBoot } from '#q-app';
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';

import {
  createUnauthorizedHandler,
  endSession,
  getAccessToken,
  notifyForbidden,
  setAccessToken,
  singleFlight,
} from 'src/services/session';

declare module 'vue' {
  interface ComponentCustomProperties {
    $api: AxiosInstance;
  }
}

declare module 'axios' {
  interface InternalAxiosRequestConfig {
    /** See `ReplayableConfig` in services/session. */
    _retriedAfterRefresh?: boolean;
  }
}

// Where an earlier version kept the JWT. Dropped on start: a token left in
// localStorage is readable by any script in the page, and the server no
// longer accepts one without a session anyway.
const LEGACY_TOKEN_KEY = 'tiai_token';

const api = axios.create({
  baseURL: import.meta.env.API_BASE_URL || '/api/v1',
});

// Attach the in-memory access token (if any) to every request.
api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

interface TokenResponse {
  access_token: string;
}

/**
 * Trade the refresh cookie for a new access token. Shared by every caller
 * that asks at the same time — the 401 handler, the router's silent refresh
 * on reload — so one round trip serves them all (`singleFlight`).
 */
export const refreshSession = singleFlight(async () => {
  const { data } = await api.post<TokenResponse>('/auth/refresh', undefined, {
    withCredentials: true,
  });
  setAccessToken(data.access_token);
  return data.access_token;
});

export default defineBoot(({ app, router }) => {
  app.config.globalProperties.$api = api;
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // Storage disabled: there is nothing to clean up then.
  }

  api.interceptors.response.use(
    (response) => response,
    createUnauthorizedHandler<InternalAxiosRequestConfig>({
      refresh: refreshSession,
      replay: (config) => api.request(config),
      onSessionLost: () => {
        // The auth store hears of it through `onSessionEnd` and drops the
        // profile; importing the store here would close an import cycle.
        endSession();
        if (router.currentRoute.value.name !== 'login') {
          void router.push({
            name: 'login',
            // `ended`: the login page says « Votre session a pris fin »
            // rather than greeting the reader as if they had just arrived.
            query: { redirect: router.currentRoute.value.fullPath, ended: '1' },
          });
        }
      },
    }),
  );

  // A 403: the account's rights may have changed since the profile was read.
  // The store reads it again (throttled), and the menus follow.
  api.interceptors.response.use(
    (response) => response,
    (error: unknown) => {
      const { response, config } = (error ?? {}) as {
        response?: { status?: number };
        config?: { url?: string };
      };
      if (response?.status === 403 && !config?.url?.endsWith('/auth/me')) notifyForbidden();
      // Passed on as it came: the pages read the axios error itself.
      // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
      return Promise.reject(error);
    },
  );
});

export { api };
