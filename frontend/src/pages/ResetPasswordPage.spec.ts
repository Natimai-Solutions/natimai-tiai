import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/auth')>()),
  checkPasswordResetToken: vi.fn(),
}));

import { QForm } from 'quasar';
import { checkPasswordResetToken } from 'src/services/auth';
import ResetPasswordPage from './ResetPasswordPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function mountPage(query: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/reset-password', name: 'reset-password', component: Stub },
      { path: '/forgot-password', name: 'forgot-password', component: Stub },
      { path: '/login', name: 'login', component: Stub },
    ],
  });
  await router.push(`/reset-password${query}`);
  // The layout around the card needs a browser's ResizeObserver; the card is all this reads.
  const slot = { template: '<div><slot /></div>' };
  const w = mount(ResetPasswordPage, {
    global: { plugins: [router], stubs: { QLayout: slot, QPageContainer: slot, QPage: slot } },
  });
  await flushPromises();
  return w;
}

describe('ResetPasswordPage — the link checked as the page opens (C7)', () => {
  it('says a dead link is no longer valid, and points to « Mot de passe oublié »', async () => {
    vi.mocked(checkPasswordResetToken).mockResolvedValueOnce('invalid');
    const w = await mountPage('?token=old');
    expect(checkPasswordResetToken).toHaveBeenCalledWith('old');
    expect(w.text()).toContain("Ce lien n'est plus valable");
    expect(w.text()).toContain('Mot de passe oublié');
    expect(w.findComponent(QForm).exists()).toBe(false);
  });

  it('shows the form for a live link, and for a server that cannot tell', async () => {
    vi.mocked(checkPasswordResetToken).mockResolvedValueOnce('valid');
    expect((await mountPage('?token=fresh')).findComponent(QForm).exists()).toBe(true);
    vi.mocked(checkPasswordResetToken).mockResolvedValueOnce('unknown');
    expect((await mountPage('?token=fresh')).findComponent(QForm).exists()).toBe(true);
  });
});
