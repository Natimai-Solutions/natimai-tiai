// The console's shell in English (plan `dev/plan-console-bilingue.md`, I6):
// the menu and header, the pages without an account (sign-in, forgotten and
// new password), the « no page » and 404 pages, and the two load-error
// banners — each one following a change of language while it is shown.
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { computed, defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  getMe: vi.fn(),
  checkPasswordResetToken: vi.fn(() => Promise.resolve('valid')),
  requestPasswordReset: vi.fn(() => Promise.resolve()),
}));
vi.mock('src/services/checks', () => ({
  listChecks: vi.fn(() => Promise.resolve({ items: [], total: 2 })),
}));
vi.mock('src/services/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/maintenance')>()),
  getDue: vi.fn(() => Promise.resolve({ overdue: 1 })),
}));
// The policy's own words are another batch's: a fixed English duration here.
vi.mock('src/composables/usePasswordPolicy', () => ({
  usePasswordPolicy: () => ({
    passwordMin: computed(() => 12),
    resetExpiry: computed(() => '1 hour'),
  }),
}));

import { setLocale } from 'src/i18n';
import CardLoadError from 'src/components/CardLoadError.vue';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import MainLayout from 'src/layouts/MainLayout.vue';
import { getMe, type User } from 'src/services/auth';
import { setAccessToken } from 'src/services/session';
import { useAuthStore } from 'src/stores/auth';
import ErrorNotFound from './ErrorNotFound.vue';
import ForgotPasswordPage from './ForgotPasswordPage.vue';
import LoginPage from './LoginPage.vue';
import NoAccessPage from './NoAccessPage.vue';
import ResetPasswordPage from './ResetPasswordPage.vue';

const Stub = defineComponent({ render: () => h('div') });
const slot = { template: '<div><slot /></div>' };
const FRENCH = /[éèàùçêô«»]/;

const ALL = [
  'machine:read',
  'package:read',
  'check:read',
  'maintenance:read',
  'room:read',
  'user:read',
  'settings:read',
  'audit:read',
];

function routerAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: Stub },
      ...[
        'machines',
        'software',
        'packages',
        'tasks',
        'rooms',
        'users',
        'groups',
        'settings',
        'audit',
        'account',
        'login',
        'forgot-password',
        'reset-password',
        'no-access',
      ].map((name) => ({ path: `/${name}`, name, component: Stub })),
    ],
  });
  return { router, ready: router.push(path) };
}

async function mountPage(component: object, path: string, user: User | null = null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = user;
  const { router, ready } = routerAt(path);
  await ready;
  const w = mount(component, {
    global: {
      plugins: [pinia, router],
      stubs: {
        QLayout: slot,
        QPageContainer: slot,
        QPage: slot,
        QHeader: slot,
        QDrawer: slot,
      },
    },
  });
  await flushPromises();
  return w;
}

afterEach(() => setLocale('fr'));

describe('MainLayout in English', () => {
  const me: User = {
    id: 'me',
    email: 'me@school.example',
    full_name: null,
    email_preference: 'none',
    preferences: {},
    groups: [],
    permissions: ALL,
  };

  it('names the menu and the header buttons in English', async () => {
    setAccessToken('token');
    setLocale('en');
    const w = await mountPage(MainLayout, '/machines', me);
    const menu = w.findAll('.q-item .q-item__section--main').map((i) => i.text());
    expect(menu).toEqual([
      'Dashboard',
      'Computers',
      'Alerts',
      'Software',
      'Packages',
      'My tasks',
      'Rooms',
      'Users',
      'Groups',
      'Settings',
      'Audit log',
    ]);
    expect(w.text()).toContain('Skip to content');
    expect(w.find('[aria-label="My account"]').exists()).toBe(true);
    expect(w.find('[aria-label="Sign out"]').exists()).toBe(true);
    expect(w.find('[aria-label="Menu"]').exists()).toBe(true);
    expect(w.text()).not.toMatch(FRENCH);
    w.unmount();
  });

  it('says in English that the profile could not be read', async () => {
    setAccessToken('token');
    vi.mocked(getMe).mockRejectedValueOnce({
      response: { status: 500, data: { error: { code: 'internal.server_error' } } },
    });
    setLocale('en');
    const w = await mountPage(MainLayout, '/machines', null);
    const banner = w.findComponent(LoadErrorBanner).text();
    expect(banner).toContain('Could not load your profile: menus and actions are incomplete — ');
    expect(banner).toContain('Try again');
    expect(banner).not.toMatch(FRENCH);
    w.unmount();
  });

  it('switches the menu while it is open', async () => {
    setAccessToken('token');
    const w = await mountPage(MainLayout, '/machines', me);
    expect(w.text()).toContain('Tableau de bord');
    expect(w.text()).toContain("Journal d'audit");
    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Dashboard');
    expect(w.text()).toContain('Audit log');
    expect(w.text()).not.toContain('Tableau de bord');
    w.unmount();
  });
});

describe('the pages without an account, in English', () => {
  it('signs in', async () => {
    setLocale('en');
    const w = await mountPage(LoginPage, '/login?ended=1');
    for (const words of [
      'Fleet monitoring',
      'Your session has ended',
      'E-mail',
      'Password',
      'Sign in',
      'Forgotten your password?',
    ]) {
      expect(w.text()).toContain(words);
    }
    expect(w.text()).not.toMatch(FRENCH);
  });

  it('asks for a reset link, and says it was sent', async () => {
    setLocale('en');
    const w = await mountPage(ForgotPasswordPage, '/forgot-password');
    expect(w.text()).toContain('Forgotten password');
    expect(w.text()).toContain('Send the link');
    expect(w.text()).toContain('Back to sign-in');
    expect(w.text()).not.toMatch(FRENCH);
    await w.find('input').setValue('someone@school.example');
    await w.find('form').trigger('submit');
    await flushPromises();
    expect(w.text()).toContain(
      'If an account exists for someone@school.example, a reset link has just been sent. It expires in 1 hour.',
    );
    expect(w.text()).not.toMatch(FRENCH);
  });

  it('sets a new password', async () => {
    setLocale('en');
    const w = await mountPage(ResetPasswordPage, '/reset-password?token=abc');
    for (const words of [
      'New password',
      '12 characters minimum',
      'Confirm the password',
      'Set the password',
      'Back to sign-in',
    ]) {
      expect(w.text()).toContain(words);
    }
    expect(w.text()).not.toMatch(FRENCH);
  });

  it('says a link without a token is incomplete', async () => {
    setLocale('en');
    const w = await mountPage(ResetPasswordPage, '/reset-password');
    expect(w.text()).toContain('Incomplete link: it holds no reset token.');
  });

  it('switches the sign-in page while it is open', async () => {
    const w = await mountPage(LoginPage, '/login');
    expect(w.text()).toContain('Se connecter');
    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Sign in');
    expect(w.text()).not.toContain('Se connecter');
  });
});

describe('the pages with nothing to show, in English', () => {
  it('says no page is available', async () => {
    setLocale('en');
    const w = await mountPage(NoAccessPage, '/no-access');
    expect(w.text()).toContain('No page available');
    expect(w.text()).toContain('Ask an administrator');
    expect(w.text()).toContain('My account');
    expect(w.text()).not.toMatch(FRENCH);
  });

  it('says a page is not found', async () => {
    setLocale('en');
    const w = await mountPage(ErrorNotFound, '/');
    expect(w.text()).toContain('Page not found');
    expect(w.text()).toContain('Back to home');
    expect(w.text()).not.toMatch(FRENCH);
  });
});

describe('the load-error banners', () => {
  it('say the server did not answer, in the language shown', async () => {
    const w = mount(LoadErrorBanner, { props: { error: null } });
    expect(w.text()).toContain('Chargement impossible : le serveur ne répond pas.');
    expect(w.text()).toContain('Réessayer');
    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Could not load: the server is not responding.');
    expect(w.text()).toContain('Try again');
  });

  it('keep the text they are given', () => {
    const w = mount(LoadErrorBanner, { props: { error: null, fallback: 'Profile missing.' } });
    expect(w.text()).toContain('Profile missing.');
  });

  it('name what a card could not load', async () => {
    const w = mount(CardLoadError, { props: { what: 'les menaces' } });
    expect(w.text()).toContain('Impossible de charger les menaces.');
    setLocale('en');
    await w.setProps({ what: 'the threats' });
    expect(w.text()).toContain('Could not load the threats.');
    expect(w.text()).toContain('Try again');
  });
});
