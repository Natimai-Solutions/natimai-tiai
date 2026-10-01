import { defineBoot } from '#q-app';
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';

import {
  createUnauthorizedHandler,
  endSession,
  getAccessToken,
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
            query: { redirect: router.currentRoute.value.fullPath },
          });
        }
      },
    }),
  );
});

export { api };
