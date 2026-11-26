import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/utils/liveDialog', () => ({
  liveDialog: () => ({ onOk: (ok: () => void) => ok() }),
}));
vi.mock('src/services/approvals', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/approvals')>()),
  listApprovals: vi.fn(),
  getApprovalSummary: vi.fn(),
  getApproval: vi.fn(),
  approveApproval: vi.fn(),
  rejectApproval: vi.fn(),
  cancelApproval: vi.fn(),
}));

import { approvalsVersion } from 'src/composables/useApprovalsBadge';
import {
  approveApproval,
  cancelApproval,
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
    target: { kind: 'domain', value: 'LYCEE' },
    machine_count: 45,
    threshold: 40,
    ttl_minutes: null,
    schedule_id: null,
    schedule_name: null,
    requested_by: 'tech@lycee.example',
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
  // q-tabs measures itself with a ResizeObserver, which jsdom has not.
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
    email: 'chef@lycee.example',
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

const mine = [
  request({ id: 'm-1', status: 'pending' }),
  request({
    id: 'm-2',
    status: 'rejected',
    decided_by: 'chef@lycee.example',
    note: 'Pas pendant le bac blanc',
  }),
  request({ id: 'm-3', status: 'failed', result_code: 'package_changed' }),
  request({ id: 'm-4', status: 'approved', decided_by: 'chef@lycee.example', created: 45 }),
];

describe('ApprovalsPage (C10)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.mocked(listApprovals)
      .mockReset()
      .mockImplementation(async (params) =>
        params?.view === 'mine' ? list(mine) : list([request()]),
      );
    vi.mocked(getApprovalSummary)
      .mockReset()
      .mockResolvedValue({ enabled: true, to_decide: 1, mine_pending: 1 });
    vi.mocked(cancelApproval)
      .mockReset()
      .mockResolvedValue(request({ status: 'cancelled' }));
    vi.mocked(getApproval)
      .mockReset()
      .mockResolvedValue({ ...request(), machines: [], hidden: 0, schedule: null });
    vi.mocked(approveApproval)
      .mockReset()
      .mockResolvedValue(request({ status: 'approved', created: 45, skipped: 0, left_out: 0 }));
  });

  it('lists what the reader may decide, with the author, the target and the count', async () => {
    const w = await mountPage();
    expect(listApprovals).toHaveBeenCalledWith({ view: 'to_decide', page: 1, page_size: 50 });
    const text = w.text();
    expect(text).toContain('tech@lycee.example');
    expect(text).toContain('Redémarrer le poste');
    expect(text).toContain('le domaine LYCEE');
    expect(text).toContain('45');
    expect(w.find('[data-test="approve"]').exists()).toBe(true);
    expect(w.find('[data-test="reject"]').exists()).toBe(true);
    // The tab carries the count.
    expect(w.find('[data-test="tab-to-decide"]').text()).toContain('1');
  });

  it('shows one’s own requests with their status chips, and cancels a pending one', async () => {
    const w = await mountPage();
    await w.find('[data-test="tab-mine"]').trigger('click');
    await flushPromises();
    expect(listApprovals).toHaveBeenLastCalledWith({ view: 'mine', page: 1, page_size: 50 });
    const chips = w.findAll('[data-test="approval-status"]').map((c) => c.text());
    expect(chips).toEqual(['En attente', 'Refusée', 'En échec', 'Approuvée']);
    const text = w.text();
    expect(text).toContain('Refusée par chef@lycee.example : Pas pendant le bac blanc');
    expect(text).toContain('Le paquet a été modifié depuis la demande.');
    // Only the pending one can be cancelled; no decision on one's own.
    expect(w.findAll('[data-test="cancel"]')).toHaveLength(1);
    expect(w.find('[data-test="approve"]').exists()).toBe(false);

    const before = approvalsVersion.value;
    vi.mocked(listApprovals).mockClear();
    await w.find('[data-test="cancel"]').trigger('click');
    await flushPromises();
    expect(cancelApproval).toHaveBeenCalledWith('m-1');
    // The badge reads again, and so does the list.
    expect(approvalsVersion.value).toBe(before + 1);
    expect(listApprovals).toHaveBeenCalled();
  });

  // A late answer for « À approuver » is not shown, with its actions, under
  // « Mes demandes » chosen since.
  it('drops a late answer to a tab left since', async () => {
    const w = await mountPage();
    await w.find('[data-test="tab-mine"]').trigger('click');
    await flushPromises();
    let answerToDecide!: (r: ReturnType<typeof list>) => void;
    vi.mocked(listApprovals).mockImplementation((params) =>
      params?.view === 'mine'
        ? Promise.resolve(list(mine))
        : new Promise((ok) => (answerToDecide = ok)),
    );
    await w.find('[data-test="tab-to-decide"]').trigger('click');
    await flushPromises();
    await w.find('[data-test="tab-mine"]').trigger('click');
    await flushPromises();
    answerToDecide(list([request({ id: 'other', requested_by: 'autre@lycee.example' })]));
    await flushPromises();
    expect(w.text()).not.toContain('autre@lycee.example');
    expect(w.findAll('[data-test="approval-status"]')).toHaveLength(4);
    expect(w.find('[data-test="approve"]').exists()).toBe(false);
  });

  it('says when approval is off, while the remaining requests can still be decided', async () => {
    vi.mocked(getApprovalSummary).mockResolvedValue({
      enabled: false,
      to_decide: 1,
      mine_pending: 0,
    });
    const w = await mountPage();
    expect(w.find('[data-test="approvals-subtitle"]').text()).toContain(
      'L’approbation à deux est désactivée',
    );
    expect(w.find('[data-test="approve"]').exists()).toBe(true);
  });

  it('reads the list and the badge again after a decision', async () => {
    const w = await mountPage();
    await w.find('[data-test="approve"]').trigger('click');
    await flushPromises();
    const before = approvalsVersion.value;
    vi.mocked(listApprovals).mockClear();
    (document.querySelector('[data-test="approval-approve"]') as HTMLElement).click();
    await flushPromises();
    expect(approveApproval).toHaveBeenCalledWith('ap-1', false);
    expect(approvalsVersion.value).toBe(before + 1);
    expect(listApprovals).toHaveBeenCalledWith({ view: 'to_decide', page: 1, page_size: 50 });
    w.unmount();
  });
});
