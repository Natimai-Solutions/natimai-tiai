import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn, QForm, QInput, QSelect } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/session', () => ({ ensureSession: vi.fn(), getAccessToken: () => null }));
vi.mock('boot/axios', () => ({ api: {}, refreshSession: vi.fn() }));
vi.mock('src/services/reports', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/reports')>()),
  getReportForm: vi.fn(),
  submitReport: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import { getReportForm, submitReport } from 'src/services/reports';
import { ensureSession } from 'src/services/session';
import LabelPage from './LabelPage.vue';

const Stub = defineComponent({ render: () => h('div') });

async function scan(token = 'tok-1') {
  setActivePinia(createPinia());
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/a/:token', name: 'label', component: Stub },
      { path: '/a/:token/open', name: 'asset-token', component: Stub },
      { path: '/login', name: 'login', component: Stub },
    ],
  });
  await router.push(`/a/${token}`);
  const wrapper = mount(LabelPage, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { wrapper, router };
}

describe('LabelPage — where a label leads', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    setLocale('fr');
    vi.mocked(ensureSession).mockReset().mockResolvedValue(false);
    vi.mocked(getReportForm).mockReset();
    vi.mocked(submitReport).mockReset().mockResolvedValue(undefined);
  });

  it('sends the staff, signed in, on to the poste', async () => {
    vi.mocked(ensureSession).mockResolvedValue(true);
    const { router } = await scan();
    expect(router.currentRoute.value.name).toBe('asset-token');
    expect(router.currentRoute.value.params.token).toBe('tok-1');
    expect(getReportForm).not.toHaveBeenCalled();
  });

  it('sends anybody else to the sign-in while the form is closed', async () => {
    vi.mocked(getReportForm).mockResolvedValue({ enabled: false, categories: [] });
    const { router } = await scan();
    expect(router.currentRoute.value.name).toBe('login');
    expect(router.currentRoute.value.query.redirect).toBe('/a/tok-1');
  });

  it('opens the form, sends the report, and thanks', async () => {
    vi.mocked(getReportForm).mockResolvedValue({
      enabled: true,
      categories: ['hardware', 'printing'],
    });
    const { wrapper } = await scan();
    const select = wrapper.findComponent(QSelect);
    expect((select.props('options') as { label: string }[]).map((o) => o.label)).toEqual([
      'Matériel',
      'Impression',
    ]);
    select.vm.$emit('update:modelValue', 'printing');
    const inputs = wrapper.findAllComponents(QInput);
    inputs[0]!.vm.$emit('update:modelValue', '  Bourrage papier  ');
    inputs[1]!.vm.$emit('update:modelValue', ' Salle B12 ');
    await flushPromises();
    await wrapper.findComponent(QForm).trigger('submit');
    await flushPromises();
    expect(submitReport).toHaveBeenCalledWith('tok-1', {
      category: 'printing',
      text: 'Bourrage papier',
      contact: 'Salle B12',
      language: 'fr',
    });
    expect(wrapper.text()).toContain('Merci, votre signalement a été transmis.');
  });

  it('says when too many reports were sent, and offers the staff sign-in', async () => {
    vi.mocked(getReportForm).mockResolvedValue({ enabled: true, categories: ['hardware'] });
    vi.mocked(submitReport).mockImplementation(() =>
      Promise.reject(
        Object.assign(new Error('429'), {
          response: { status: 429, data: { error: { code: 'request.rate_limited' } } },
        }),
      ),
    );
    const { wrapper } = await scan();
    wrapper.findAllComponents(QInput)[0]!.vm.$emit('update:modelValue', 'Plus de son');
    await flushPromises();
    await wrapper.findComponent(QForm).trigger('submit');
    await flushPromises();
    expect(wrapper.text()).toContain('Trop de signalements depuis ce poste');
    const staff = wrapper
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Personnel : se connecter')!;
    expect(staff.props('to')).toEqual({ name: 'login', query: { redirect: '/a/tok-1' } });
  });

  it('says a label leads nowhere', async () => {
    vi.mocked(getReportForm).mockImplementation(() => Promise.reject(new Error('404')));
    const { wrapper } = await scan();
    expect(wrapper.text()).toContain('Cette étiquette ne correspond à aucun matériel.');
  });
});
