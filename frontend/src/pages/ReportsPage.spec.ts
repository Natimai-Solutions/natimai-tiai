import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { QBtn, QInput, QSelect } from 'quasar';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/reports', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/reports')>()),
  listReports: vi.fn(),
  convertReport: vi.fn(),
  attachReport: vi.fn(),
  closeReport: vi.fn(),
}));
vi.mock('src/services/checks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/checks')>()),
  listAssignableUsers: vi.fn(),
}));

import { listAssignableUsers } from 'src/services/checks';
import {
  attachReport,
  closeReport,
  convertReport,
  listReports,
  type Report,
} from 'src/services/reports';
import { useAuthStore } from 'src/stores/auth';
import ReportsPage from './ReportsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

const report = (over: Partial<Report>): Report => ({
  id: 'r-1',
  asset_id: 'a-1',
  machine_id: 'm-1',
  subject: 'A101-PC01',
  room_name: 'A101',
  building_name: 'Bât. A',
  category: 'printing',
  text: 'Bourrage papier',
  contact: 'Salle B12',
  language: 'fr',
  status: 'new',
  created_at: '2026-11-20T04:00:00Z',
  handled_at: null,
  handled_by: null,
  handling_note: null,
  check_id: null,
  open_check_id: null,
  ...over,
});

async function mountPage(permissions: string[]) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = { id: 'u', email: 'a@b.c', permissions } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/reports', name: 'reports', component: Stub },
      { path: '/machines/:id', name: 'machine-detail', component: Stub },
    ],
  });
  await router.push('/reports');
  const wrapper = mount(ReportsPage, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  const button = (label: string) =>
    wrapper.findAllComponents(QBtn).find((b) => b.props('label') === label);
  return { wrapper, button };
}

const ALL = ['report:read', 'report:write', 'check:write'];

describe('ReportsPage', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.mocked(listReports)
      .mockReset()
      .mockResolvedValue({
        items: [report({}), report({ id: 'r-2', open_check_id: 'c-9', subject: 'A101-PC02' })],
        total: 2,
        page: 1,
        page_size: 50,
        new: 2,
        enabled: false,
      });
    vi.mocked(listAssignableUsers).mockResolvedValue([{ id: 'u-1', name: 'Alice' }]);
    for (const fn of [convertReport, attachReport, closeReport]) {
      vi.mocked(fn)
        .mockReset()
        .mockResolvedValue(report({ status: 'converted' }));
    }
  });

  it('lists the reports to sort, with their contact, and says the form is closed', async () => {
    const { wrapper } = await mountPage(['report:read']);
    const text = wrapper.text();
    expect(text).toContain('Bourrage papier');
    expect(text).toContain('Contact : Salle B12');
    expect(text).toContain('Impression');
    expect(text).toContain('Le formulaire de signalement est fermé');
    // Read-only: no action.
    expect(wrapper.findAllComponents(QBtn).some((b) => b.props('label') === 'Rejeter')).toBe(false);
  });

  it('opens a verification, or attaches to the one open', async () => {
    const { wrapper, button } = await mountPage(ALL);
    await button('Ouvrir une vérification')!.trigger('click');
    await flushPromises();
    const dialogSelects = wrapper.findAllComponents(QSelect);
    dialogSelects
      .find((s) => s.props('label') === 'Affecter à')!
      .vm.$emit('update:modelValue', 'u-1');
    dialogSelects
      .find((s) => s.props('label') === 'Priorité')!
      .vm.$emit('update:modelValue', 'high');
    await flushPromises();
    await button('Valider')!.trigger('click');
    await flushPromises();
    expect(convertReport).toHaveBeenCalledWith('r-1', {
      assigned_to_id: 'u-1',
      priority: 'high',
      due_date: null,
    });
    await button('Rattacher à la vérification en cours')!.trigger('click');
    await flushPromises();
    expect(attachReport).toHaveBeenCalledWith('r-2');
  });

  it('closes or rejects with a note; without check:write, nothing to open', async () => {
    const { wrapper, button } = await mountPage(['report:read', 'report:write']);
    expect(button('Ouvrir une vérification')).toBeUndefined();
    await wrapper
      .findAllComponents(QBtn)
      .find((b) => b.props('label') === 'Rejeter')!
      .trigger('click');
    await flushPromises();
    wrapper
      .findAllComponents(QInput)
      .find((i) => i.props('label') === 'Note')!
      .vm.$emit('update:modelValue', ' Doublon ');
    await flushPromises();
    await button('Valider')!.trigger('click');
    await flushPromises();
    expect(closeReport).toHaveBeenCalledWith('r-1', 'Doublon', true);
  });
});
