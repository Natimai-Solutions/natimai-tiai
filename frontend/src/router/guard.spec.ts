// @vitest-environment jsdom
// The router's guard and title, as the app builds them: which page an account
// lands on, where a live session sent to /login goes, and which title a query
// change keeps.
import { type Router } from 'vue-router';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => {
  const value: {
    permissions: string[];
    token: string | null;
    sessionAlive: boolean;
    enrolmentOnly: boolean;
  } = {
    permissions: [],
    token: 'token',
    sessionAlive: true,
    enrolmentOnly: false,
  };
  return value;
});

vi.mock('boot/axios', () => ({ refreshSession: vi.fn() }));
vi.mock('src/services/session', () => ({
  ensureSession: () => Promise.resolve(state.sessionAlive),
  getAccessToken: () => state.token,
}));
vi.mock('src/stores/auth', () => ({
  useAuthStore: () => ({
    ensureProfile: () => Promise.resolve(),
    get user() {
      return { permissions: state.permissions, enrolment_only: state.enrolmentOnly };
    },
  }),
  readCachedPermissions: () => state.permissions,
}));
vi.mock('./routes', () => {
  const page = { render: () => null };
  return {
    default: [
      { path: '/login', name: 'login', component: page, meta: { title: 'Connexion' } },
      {
        path: '/',
        name: 'dashboard',
        component: page,
        meta: { requiresAuth: true, requiresPermission: 'machine:read', title: 'Tableau de bord' },
      },
      {
        path: '/machines/:id',
        name: 'machine-detail',
        component: page,
        meta: { requiresAuth: true, requiresPermission: 'machine:read', title: 'Poste' },
      },
      {
        path: '/rooms',
        name: 'rooms',
        component: page,
        meta: { requiresAuth: true, requiresPermission: 'room:read', title: 'Salles' },
      },
      {
        path: '/equipment',
        name: 'assets',
        component: page,
        meta: { requiresAuth: true, requiresPermission: 'asset:read', title: 'Matériels' },
      },
      { path: '/account', name: 'account', component: page, meta: { requiresAuth: true } },
      { path: '/no-access', name: 'no-access', component: page, meta: { requiresAuth: true } },
    ],
  };
});

let router: Router;

beforeAll(async () => {
  window.scrollTo = vi.fn();
  const createAppRouter = (await import('./index')).default as unknown as () => Router;
  router = createAppRouter();
});

beforeEach(async () => {
  state.permissions = ['machine:read', 'room:read'];
  state.token = 'token';
  state.sessionAlive = true;
  state.enrolmentOnly = false;
  await router.push('/account');
});

describe('a session for enrolment only (C7)', () => {
  it('keeps it on « Mon compte », whatever the page asked', async () => {
    state.enrolmentOnly = true;
    await router.push('/machines/abc');
    expect(router.currentRoute.value.name).toBe('account');
    await router.push('/');
    expect(router.currentRoute.value.name).toBe('account');
    state.enrolmentOnly = false;
    await router.push('/machines/abc');
    expect(router.currentRoute.value.name).toBe('machine-detail');
  });
});

describe('landing page (permissions)', () => {
  it('sends an account without machine:read from « / » to the first page it can read', async () => {
    state.permissions = ['room:read'];
    await router.push('/');
    expect(router.currentRoute.value.name).toBe('rooms');
  });

  it('opens Matériels for an account that reads the purchases and not the parc', async () => {
    state.permissions = ['asset:read', 'room:read'];
    await router.push('/');
    expect(router.currentRoute.value.name).toBe('assets');
  });

  it('sends an account that can read nothing to « Aucune page accessible »', async () => {
    state.permissions = [];
    await router.push('/machines/abc');
    expect(router.currentRoute.value.name).toBe('no-access');
  });

  it('opens the dashboard for an account that may read the parc', async () => {
    await router.push('/');
    expect(router.currentRoute.value.name).toBe('dashboard');
  });
});

describe('/login with a live session', () => {
  it('goes where ?redirect= says', async () => {
    await router.push('/login?redirect=/rooms');
    expect(router.currentRoute.value.fullPath).toBe('/rooms');
  });

  it('never leaves the console for a redirect to another site', async () => {
    await router.push('/login?redirect=//evil.example/x');
    expect(router.currentRoute.value.name).toBe('dashboard');
  });
});

describe('session ended while the console runs', () => {
  it('tells the login page so', async () => {
    state.sessionAlive = false;
    state.token = null;
    await router.push('/rooms');
    expect(router.currentRoute.value.name).toBe('login');
    expect(router.currentRoute.value.query).toMatchObject({ redirect: '/rooms', ended: '1' });
  });
});

describe('document title', () => {
  it('keeps the title the page set when only the query changes (a fiche tab)', async () => {
    await router.push('/machines/abc');
    document.title = 'PC-01 — Tia’i';
    await router.push('/machines/abc?tab=hardware');
    expect(document.title).toBe('PC-01 — Tia’i');
    await router.push('/rooms');
    expect(document.title).toContain('Salles');
  });
});
