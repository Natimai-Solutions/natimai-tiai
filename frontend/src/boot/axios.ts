import { defineBoot } from '#q-app';
import axios, { type AxiosInstance } from 'axios';

declare module 'vue' {
  interface ComponentCustomProperties {
    $api: AxiosInstance;
  }
}

// Must match the key the auth store writes (see src/stores/auth.ts).
const TOKEN_KEY = 'tiai_token';

const api = axios.create({
  baseURL: import.meta.env.API_BASE_URL || '/api/v1',
});

// Attach the per-session JWT (if any) to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default defineBoot(({ app, router }) => {
  app.config.globalProperties.$api = api;

  // On 401, drop the stale token and bounce to the login page.
  api.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        if (router.currentRoute.value.name !== 'login') {
          void router.push({
            name: 'login',
            query: { redirect: router.currentRoute.value.fullPath },
          });
        }
      }
      return Promise.reject(error);
    },
  );
});

export { api };
