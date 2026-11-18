import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QForm, QInput } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  login: vi.fn(() => Promise.resolve({ access_token: 't' })),
  getMe: vi.fn(() => Promise.resolve({ id: 'me', email: 'a@b.c', permissions: [] })),
}));

import { setAccessToken } from 'src/services/session';
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
