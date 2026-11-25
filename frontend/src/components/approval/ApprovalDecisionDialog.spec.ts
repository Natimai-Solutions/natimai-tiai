import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const shown = vi.hoisted(() => [] as { type?: string; message?: string }[]);
vi.mock('src/utils/notify', () => ({
  notify: (_q: unknown, build: () => { type?: string; message?: string }) => {
    shown.push(build());
    return () => undefined;
  },
}));
const dialogs = vi.hoisted(() => [] as { message?: string }[]);
vi.mock('src/utils/liveDialog', () => ({
  liveDialog: (_q: unknown, build: () => { message?: string }) => {
    dialogs.push(build());
    return { onOk: (ok: () => void) => ok() };
  },
}));
vi.mock('src/services/approvals', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/approvals')>()),
  getApproval: vi.fn(),
  approveApproval: vi.fn(),
  rejectApproval: vi.fn(),
}));

import { approvalsVersion } from 'src/composables/useApprovalsBadge';
import {
  approveApproval,
  getApproval,
  rejectApproval,
  type Approval,
  type ApprovalDetail,
} from 'src/services/approvals';
import ApprovalDecisionDialog from './ApprovalDecisionDialog.vue';

function request(fields: Partial<Approval> = {}): Approval {
  return {
    id: 'ap-1',
    kind: 'command',
    status: 'pending',
    command_type: 'reboot',
    package_id: null,
    package_name: null,
    target: { kind: 'machines' },
    machine_count: 25,
    threshold: 20,
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

function detail(fields: Partial<ApprovalDetail> = {}): ApprovalDetail {
  return {
    ...request(),
    machines: Array.from({ length: 25 }, (_, i) => ({
      id: `m-${i}`,
      hostname: `PC-${String(i).padStart(2, '0')}`,
      room: null,
    })),
    hidden: 0,
    schedule: null,
    ...fields,
  };
}

function refused(code: string, details?: Record<string, unknown>) {
  return Object.assign(new Error('x'), {
    response: { status: 409, data: { error: { code, details } } },
  });
}

async function open(mode: 'approve' | 'reject' = 'approve') {
  const w = mount(ApprovalDecisionDialog, {
    props: { modelValue: true, approval: request(), mode },
    attachTo: document.body,
  });
  await flushPromises();
  return w;
}

const el = (test: string) => document.querySelector<HTMLElement>(`[data-test="${test}"]`);

describe('ApprovalDecisionDialog (C10)', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    shown.length = 0;
    dialogs.length = 0;
    vi.mocked(getApproval).mockReset().mockResolvedValue(detail());
    vi.mocked(approveApproval).mockReset();
    vi.mocked(rejectApproval).mockReset();
  });

  it('approves, then says what was sent and has the badge read again', async () => {
    vi.mocked(approveApproval).mockResolvedValue(
      request({ status: 'approved', created: 22, skipped: 1, left_out: 2 }),
    );
    const w = await open();
    const before = approvalsVersion.value;
    el('approval-approve')!.click();
    await flushPromises();
    expect(approveApproval).toHaveBeenCalledWith('ap-1', false);
    expect(shown.at(-1)).toEqual({
      type: 'positive',
      message:
        '22 commande(s) envoyée(s) ; 1 déjà en attente ; 2 poste(s) laissé(s) de côté (supprimés, révoqués ou hors de portée de l’auteur)',
    });
    expect(approvalsVersion.value).toBe(before + 1);
    expect(w.emitted('done')).toHaveLength(1);
    expect(w.emitted('update:modelValue')?.at(-1)).toEqual([false]);
    w.unmount();
  });

  it('rejects with a reason passed on to the author', async () => {
    vi.mocked(rejectApproval).mockResolvedValue(request({ status: 'rejected' }));
    const w = await open('reject');
    const input = document.querySelector<HTMLTextAreaElement>('.q-dialog textarea')!;
    input.value = '  Pas pendant le bac blanc ';
    input.dispatchEvent(new Event('input'));
    await flushPromises();
    el('approval-reject')!.click();
    await flushPromises();
    expect(rejectApproval).toHaveBeenCalledWith('ap-1', 'Pas pendant le bac blanc');
    expect(shown.at(-1)).toEqual({ type: 'positive', message: 'Demande refusée' });
    w.unmount();
  });

  it('asks the approver to confirm a forbidden window open now, then approves', async () => {
    vi.mocked(approveApproval)
      .mockRejectedValueOnce(
        refused('command.forbidden_window', {
          window: { days: [0, 1, 2, 3, 4], start: '07:30', end: '12:00' },
        }),
      )
      .mockResolvedValueOnce(request({ status: 'approved', created: 25, skipped: 0 }));
    const w = await open();
    el('approval-approve')!.click();
    await flushPromises();
    expect(dialogs).toHaveLength(1);
    expect(dialogs[0]!.message).toContain(
      'Approuver quand même cette commande à risque sur 25 postes',
    );
    expect(dialogs[0]!.message).toContain('07:30–12:00');
    expect(approveApproval).toHaveBeenNthCalledWith(1, 'ap-1', false);
    expect(approveApproval).toHaveBeenNthCalledWith(2, 'ap-1', true);
    w.unmount();
  });

  it.each([
    ['approval.package_changed', 'Le paquet a été modifié depuis la demande : elle est close'],
    ['approval.package_gone', 'Le paquet a été supprimé depuis la demande : elle est close'],
    ['approval.not_pending', 'Cette demande a déjà été décidée, annulée ou a expiré'],
  ])('on %s, says so and has the list read again', async (code, message) => {
    vi.mocked(approveApproval).mockRejectedValue(refused(code));
    const w = await open();
    const before = approvalsVersion.value;
    el('approval-approve')!.click();
    await flushPromises();
    expect(shown.at(-1)).toEqual({ type: 'negative', message });
    expect(approvalsVersion.value).toBe(before + 1);
    expect(w.emitted('done')).toHaveLength(1);
    w.unmount();
  });

  it('folds a long list of postes, and counts those out of the reader’s scope', async () => {
    vi.mocked(getApproval).mockResolvedValue(detail({ hidden: 3 }));
    const w = await open();
    expect(getApproval).toHaveBeenCalledWith('ap-1');
    const names = () => el('approval-machines')!.textContent;
    expect(names()).toContain('PC-19');
    expect(names()).not.toContain('PC-20');
    expect(el('approval-hidden')!.textContent).toContain('+ 3 postes hors de votre portée');
    el('approval-show-all')!.click();
    await flushPromises();
    expect(names()).toContain('PC-24');
    w.unmount();
  });
});
