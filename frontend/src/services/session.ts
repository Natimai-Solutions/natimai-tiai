import { ref } from 'vue';

/**
 * The console's side of a server session (backend `app.features.auth_session`).
 *
 * Two tokens. The access token is a short JWT (15 min by default) sent as a
 * bearer on every call; it lives here, in memory, and nowhere else — not in
 * localStorage, where any script running in the page could read it and keep
 * it. The refresh token is an HttpOnly cookie the page never sees: the
 * browser sends it on `/auth/*` only, and `POST /auth/refresh` trades it for a
 * new access token.
 *
 * Holding the access token in memory means a reload starts without one; the
 * router then asks for a silent refresh before deciding the operator has to log
 * in (`ensureSession`).
 *
 * Nothing here imports axios: the logic is plain functions over injected
 * callbacks, tested on their own (`session.spec.ts`), and wired to the axios
 * instance by `boot/axios.ts`.
 */

/** The current access token, reactive so that `isAuthenticated` follows it. */
export const accessToken = ref<string | null>(null);

export function getAccessToken(): string | null {
  return accessToken.value;
}

export function setAccessToken(token: string | null): void {
  accessToken.value = token;
}

const sessionEndListeners = new Set<() => void>();

/**
 * Be told when the session ends, wherever that is decided. The auth store
 * listens to forget the profile: the 401 handler in `boot/axios` ends sessions
 * too, and cannot import the store without an import cycle (store → services
 * → boot). Returns the unsubscribe function.
 */
export function onSessionEnd(listener: () => void): () => void {
  sessionEndListeners.add(listener);
  return () => sessionEndListeners.delete(listener);
}

/** Forget the access token and tell whoever keeps state derived from it. */
export function endSession(): void {
  setAccessToken(null);
  sessionEndListeners.forEach((listener) => listener());
}

/**
 * Wrap `task` so that concurrent callers share one run of it.
 *
 * Three requests failing with 401 together must cause one `POST /auth/refresh`,
 * not three: refresh tokens are single-use, and the second and third would
 * present a token the first had just traded away. Once the run settles, the
 * next call starts a fresh one.
 */
export function singleFlight<T>(task: () => Promise<T>): () => Promise<T> {
  let inFlight: Promise<T> | null = null;
  return () => {
    if (!inFlight) {
      inFlight = task().finally(() => {
        inFlight = null;
      });
    }
    return inFlight;
  };
}

/**
 * The auth routes a 401 must not trigger a refresh for: a wrong password on
 * login is not an expired session, the refresh itself failing is what ends
 * one, and logout answers 204 whatever happens.
 */
const NO_REFRESH_PATHS = ['/auth/login', '/auth/refresh', '/auth/logout'];

function isNoRefreshPath(url: string | undefined): boolean {
  if (!url) return false;
  const path = url.split('?')[0] ?? '';
  return NO_REFRESH_PATHS.some((p) => path === p || path.endsWith(p));
}

/** The part of an axios request config the 401 handler reads and marks. */
export interface ReplayableConfig {
  url?: string;
  /** Set on a request replayed after a refresh: never replayed twice. */
  _retriedAfterRefresh?: boolean;
}

interface MaybeHttpError<C> {
  response?: { status?: number };
  config?: C;
}

export interface UnauthorizedHandlerDeps<C extends ReplayableConfig> {
  /** Obtain a new access token (single-flighted by the caller). */
  refresh: () => Promise<string>;
  /** Send the request again; the new token is already in place. */
  replay: (config: C) => Promise<unknown>;
  /** The session is over: forget it and send the operator to the login page. */
  onSessionLost: () => void;
}

/**
 * Build the axios response-error handler that turns « access token expired »
 * into one refresh and a replay, invisibly to the page that made the call.
 *
 * - not a 401, or a 401 from login / refresh / logout: passed through as is;
 * - a 401 on a request already replayed once: the session is gone for good
 *   (revoked from another device, password reset by an administrator…);
 * - otherwise: one shared refresh, then the request again — and if the
 *   refresh fails, the session is lost and the original error is rethrown.
 */
export function createUnauthorizedHandler<C extends ReplayableConfig>(
  deps: UnauthorizedHandlerDeps<C>,
): (error: unknown) => Promise<unknown> {
  return async (error: unknown) => {
    const { response, config } = (error ?? {}) as MaybeHttpError<C>;
    if (response?.status !== 401 || !config || isNoRefreshPath(config.url)) {
      throw error;
    }
    if (config._retriedAfterRefresh) {
      deps.onSessionLost();
      throw error;
    }
    try {
      await deps.refresh();
    } catch {
      deps.onSessionLost();
      throw error;
    }
    config._retriedAfterRefresh = true;
    return deps.replay(config);
  };
}

/**
 * Whether there is a session to work with, trying a silent refresh first when
 * no access token is held (a reload, a new tab). Never throws: a failed
 * refresh only means « log in ».
 */
export async function ensureSession(refresh: () => Promise<string>): Promise<boolean> {
  if (getAccessToken()) return true;
  try {
    await refresh();
    return getAccessToken() !== null;
  } catch {
    return false;
  }
}
