import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/approvals', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/approvals')>()),
  listApprovals: vi.fn(),
  getApprovalSummary: vi.fn(),
  getApproval: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import {
  getApproval,
  getApprovalSummary,
  listApprovals,
  type Approval,
} from 'src/services/approvals';
import { useAuthStore } from 'src/stores/auth';
import ApprovalsPage from './ApprovalsPage.vue';

const Stub = defineComponent({ render: () => h('div') });

function request(fields: Partial<Approval> = {}): Approval {
  return {
    id: 'ap-1',
    kind: 'command',
    status: 'pending',
    command_type: 'reboot',
    package_id: null,
    package_name: null,
    target: { kind: 'all' },
    machine_count: 45,
    threshold: 40,
    ttl_minutes: null,
    schedule_id: null,
    schedule_name: null,
    requested_by: 'tech@school.example',
    requested_at: '2026-11-25T10:00:00Z',
    expires_at: '2026-11-26T10:00:00Z',
    decided_by: null,
    decided_at: null,
    note: null,
    result_code: null,
    result_params: null,
    created: null,
    skipped: null,
    left_out: null,
    ...fields,
  };
}

const list = (items: Approval[]) => ({ items, total: items.length, page: 1, page_size: 50 });

async function mountPage() {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().user = {
    id: 'u',
    email: 'head@school.example',
    permissions: ['command:execute', 'risky_command:execute'],
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/approvals', name: 'approvals', component: Stub }],
  });
  await router.push('/approvals');
  const wrapper = mount(ApprovalsPage, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { QPage: { template: '<div><slot /></div>' } } },
  });
  await flushPromises();
  return wrapper;
}

describe('ApprovalsPage in English (C10)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    setLocale('en');
    vi.mocked(getApprovalSummary).mockResolvedValue({
      enabled: true,
      to_decide: 1,
      mine_pending: 0,
    });
  });
  afterEach(() => setLocale('fr'));

  it('words the tabs, the columns and the statuses', async () => {
    vi.mocked(listApprovals).mockImplementation(async (params) =>
      params?.view === 'mine'
        ? list([
            request({ id: 'm-1', status: 'expired' }),
            request({ id: 'm-2', status: 'rejected', decided_by: 'head', note: 'Exams' }),
          ])
        : list([request()]),
    );
    const w = await mountPage();
    expect(w.find('[data-test="tab-to-decide"]').text()).toContain('To approve');
    expect(w.text()).toContain('the whole fleet');
    expect(w.text()).toContain('Restart the computer');
    await w.find('[data-test="tab-mine"]').trigger('click');
    await flushPromises();
    expect(w.findAll('[data-test="approval-status"]').map((c) => c.text())).toEqual([
      'Expired',
      'Rejected',
    ]);
    expect(w.text()).toContain('Rejected by head: Exams');
  });

  it('agrees the decision’s summary and the hidden postes with their number', async () => {
    vi.mocked(listApprovals).mockResolvedValue(list([request({ machine_count: 1 })]));
    vi.mocked(getApproval).mockResolvedValue({
      ...request({ machine_count: 1 }),
      machines: [],
      hidden: 1,
      schedule: null,
    });
    const w = await mountPage();
    await w.find('[data-test="approve"]').trigger('click');
    await flushPromises();
    const summary = document.querySelector('[data-test="approval-summary"]')?.textContent ?? '';
    expect(summary).toContain('asks for “Restart the computer” on 1 computer (the whole fleet).');
    expect(document.querySelector('[data-test="approval-hidden"]')?.textContent).toContain(
      '+ 1 computer out of your scope',
    );
    w.unmount();
  });
});
