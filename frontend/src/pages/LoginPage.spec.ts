import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  login: vi.fn(() => Promise.resolve({ access_token: 't' })),
  verifySecondFactor: vi.fn(() => Promise.resolve({ access_token: 't2' })),
  getAuthMethods: vi.fn(() => Promise.resolve({ oidc_enabled: false, oidc_label: 'Microsoft' })),
  getMe: vi.fn(() => Promise.resolve({ id: 'me', email: 'a@b.c', permissions: [] })),
}));

import { getAuthMethods, login, verifySecondFactor } from 'src/services/auth';
import { getAccessToken, setAccessToken } from 'src/services/session';
import LoginPage from './LoginPage.vue';

const Stub = defineComponent({ render: () => h('div') });
const slot = { template: '<div><slot /></div>' };

async function mountWithRouter(query: string) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: Stub },
      { path: '/login', name: 'login', component: Stub },
      { path: '/forgot-password', name: 'forgot-password', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
      { path: '/:other(.*)*', name: 'elsewhere', component: Stub },
    ],
  });
  await router.push(`/login${query}`);
  const w = mount(LoginPage, {
    global: {
      plugins: [pinia, router],
      stubs: { QLayout: slot, QPageContainer: slot, QPage: slot },
    },
  });
  await flushPromises();
  return { w, router };
}

async function mountPage(query: string) {
  return (await mountWithRouter(query)).w;
}

describe('LoginPage — a session that ended (item 7)', () => {
  it('says « Votre session a pris fin » when sent here by an ended session', async () => {
    expect((await mountPage('?redirect=/machines&ended=1')).text()).toContain(
      'Votre session a pris fin',
    );
  });

  it('greets a plain visit without it', async () => {
    expect((await mountPage('?redirect=/machines')).text()).not.toContain('session a pris fin');
  });
});

// Surviving mutation: `/login?redirect=` is a link anybody can craft; logging
// in through it must land inside the console (router/access.safeRedirect).
describe('LoginPage — where a login lands', () => {
  beforeEach(() => setAccessToken(null));

  async function logInWith(query: string) {
    const { w, router } = await mountWithRouter(query);
    const push = vi.spyOn(router, 'push');
    const [email, password] = w.findAllComponents(QInput);
    email!.vm.$emit('update:modelValue', 'a@b.c');
    password!.vm.$emit('update:modelValue', 'secret');
    await flushPromises();
    w.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();
    return { router, target: push.mock.calls.at(-1)?.[0] };
  }

  it('goes back to the page of the console the reader was sent from', async () => {
    const { router, target } = await logInWith(
      `?redirect=${encodeURIComponent('/machines/m-5?tab=history')}&ended=1`,
    );
    expect(target).toBe('/machines/m-5?tab=history');
    expect(router.currentRoute.value.fullPath).toBe('/machines/m-5?tab=history');
  });

  it.each([
    '//evil.example/login',
    'https://evil.example/',
    '/\\evil.example',
    'javascript:alert(1)',
  ])('goes home rather than to « %s »', async (redirect) => {
    const { router, target } = await logInWith(`?redirect=${encodeURIComponent(redirect)}`);
    expect(target).toBe('/');
    expect(router.currentRoute.value.fullPath).toBe('/');
  });

  it('goes home without a redirect', async () => {
    expect((await logInWith('')).target).toBe('/');
  });
});

describe('LoginPage — second factor (C7)', () => {
  beforeEach(() => {
    setAccessToken(null);
    vi.mocked(verifySecondFactor).mockReset().mockResolvedValue({
      access_token: 't2',
      token_type: 'bearer',
    });
  });

  it('asks for the code after a right password, then lands where it was going', async () => {
    vi.mocked(login).mockResolvedValueOnce({
      second_factor_required: true,
      challenge: 'ch-1',
      expires_in: 300,
    });
    const { w, router } = await mountWithRouter('?redirect=/machines/m-5');
    const push = vi.spyOn(router, 'push');
    const [email, password] = w.findAllComponents(QInput);
    email!.vm.$emit('update:modelValue', 'a@b.c');
    password!.vm.$emit('update:modelValue', 'secret');
    await flushPromises();
    w.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();

    expect(push).not.toHaveBeenCalled();
    expect(getAccessToken()).toBeNull();
    expect(w.find('[data-test="second-factor-step"]').exists()).toBe(true);
    const [code] = w.findAllComponents(QInput);
    expect(code!.props('label')).toBe('Code à six chiffres');
    code!.vm.$emit('update:modelValue', ' 123456 ');
    await flushPromises();
    w.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();
    expect(verifySecondFactor).toHaveBeenCalledWith('ch-1', '123456');
    expect(getAccessToken()).toBe('t2');
    expect(push.mock.calls.at(-1)?.[0]).toBe('/machines/m-5');
  });

  it('offers a backup code, and keeps the step after a wrong code', async () => {
    vi.mocked(login).mockResolvedValueOnce({
      second_factor_required: true,
      challenge: 'ch-2',
      expires_in: 300,
    });
    vi.mocked(verifySecondFactor).mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 401, data: { error: { code: 'auth.second_factor.invalid' } } },
    });
    const { w } = await mountWithRouter('');
    const [email, password] = w.findAllComponents(QInput);
    email!.vm.$emit('update:modelValue', 'a@b.c');
    password!.vm.$emit('update:modelValue', 'secret');
    await flushPromises();
    w.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();

    const toggle = w.findAll('button').find((b) => b.text() === 'Utiliser un code de secours');
    await toggle!.trigger('click');
    const [code] = w.findAllComponents(QInput);
    expect(code!.props('label')).toBe('Code de secours');
    code!.vm.$emit('update:modelValue', 'ABCDE-FGHJK');
    await flushPromises();
    w.findComponent(QForm).vm.$emit('submit', new Event('submit'));
    await flushPromises();
    expect(verifySecondFactor).toHaveBeenCalledWith('ch-2', 'ABCDE-FGHJK');
    expect(w.find('[data-test="second-factor-step"]').exists()).toBe(true);
    expect(getAccessToken()).toBeNull();

    const back = w.findAll('button').find((b) => b.text() === 'Recommencer');
    await back!.trigger('click');
    expect(w.find('[data-test="second-factor-step"]').exists()).toBe(false);
  });
});

describe('LoginPage — sign-in through the directory (C7)', () => {
  it('offers the directory when the server does, and goes there by navigation', async () => {
    vi.mocked(getAuthMethods).mockResolvedValueOnce({
      oidc_enabled: true,
      oidc_label: 'Microsoft',
    });
    const assign = vi.fn();
    vi.stubGlobal('location', { ...window.location, assign });
    const w = await mountPage('?redirect=/machines/m-5');
    const button = w.find('[data-test="sso-button"]');
    expect(button.text()).toContain('Se connecter avec Microsoft');
    await button.trigger('click');
    expect(assign).toHaveBeenCalledWith('/api/v1/auth/oidc/start?redirect=%2Fmachines%2Fm-5');
    vi.unstubAllGlobals();
  });

  it('shows no directory button when the server offers none', async () => {
    const w = await mountPage('');
    expect(w.find('[data-test="sso-button"]').exists()).toBe(false);
  });

  it('says why the directory sign-in came back refused', async () => {
    let w = await mountPage('?sso_error=auth.oidc.no_group');
    expect(w.find('[data-test="sso-error"]').text()).toContain(
      'n’appartient à aucun groupe autorisé',
    );
    w = await mountPage('?sso_error=auth.oidc.something_new');
    expect(w.find('[data-test="sso-error"]').text()).toContain(
      'La connexion par l’annuaire a échoué',
    );
  });
});
