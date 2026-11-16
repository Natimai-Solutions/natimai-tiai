import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { describe, expect, it } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import LoginPage from './LoginPage.vue';

const Stub = defineComponent({ render: () => h('div') });
const slot = { template: '<div><slot /></div>' };

async function mountPage(query: string) {
  setActivePinia(createPinia());
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: Stub },
      { path: '/forgot-password', name: 'forgot-password', component: Stub },
    ],
  });
  await router.push(`/login${query}`);
  const w = mount(LoginPage, {
    global: { plugins: [router], stubs: { QLayout: slot, QPageContainer: slot, QPage: slot } },
  });
  await flushPromises();
  return w;
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
