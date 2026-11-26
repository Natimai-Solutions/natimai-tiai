import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from 'boot/axios';
import { setLocale } from 'src/i18n';
import {
  approvalAction,
  approvalCauseText,
  approvalOutcome,
  approvalStatusLabel,
  approvalTarget,
  approveApproval,
  approvedNotification,
  cancelApproval,
  getApproval,
  getApprovalSummary,
  listApprovals,
  rejectApproval,
  type Approval,
} from './approvals';

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

describe('the approvals service (C10)', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset().mockResolvedValue({ data: {} });
    vi.mocked(api.post).mockReset().mockResolvedValue({ data: {} });
  });
  afterEach(() => setLocale('fr'));

  it('lists a view with its paging', async () => {
    await listApprovals({ view: 'mine', page: 2, page_size: 50 });
    expect(api.get).toHaveBeenCalledWith('/approvals', {
      params: { view: 'mine', page: 2, page_size: 50 },
    });
  });

  it('reads the summary and one request', async () => {
    await getApprovalSummary();
    expect(api.get).toHaveBeenCalledWith('/approvals/summary');
    await getApproval('ap-1');
    expect(api.get).toHaveBeenCalledWith('/approvals/ap-1');
  });

  it('approves, with the forbidden window confirmed or not', async () => {
    await approveApproval('ap-1');
    expect(api.post).toHaveBeenCalledWith('/approvals/ap-1/approve', {
      confirm_forbidden_window: false,
    });
    await approveApproval('ap-1', true);
    expect(api.post).toHaveBeenLastCalledWith('/approvals/ap-1/approve', {
      confirm_forbidden_window: true,
    });
  });

  it('rejects with a reason, or none; cancels', async () => {
    await rejectApproval('ap-1', 'Pas pendant le bac blanc');
    expect(api.post).toHaveBeenCalledWith('/approvals/ap-1/reject', {
      note: 'Pas pendant le bac blanc',
    });
    await rejectApproval('ap-1', '');
    expect(api.post).toHaveBeenLastCalledWith('/approvals/ap-1/reject', { note: null });
    await cancelApproval('ap-1');
    expect(api.post).toHaveBeenLastCalledWith('/approvals/ap-1/cancel');
  });

  it('words the action, with the package of a deployment', () => {
    expect(approvalAction(request())).toBe('Redémarrer le poste');
    expect(
      approvalAction(request({ command_type: 'package_install', package_name: '7-Zip 23.01' })),
    ).toContain('7-Zip 23.01');
  });

  it('words the target as asked', () => {
    expect(approvalTarget(request())).toBe('le domaine LYCEE');
    expect(approvalTarget(request({ target: { kind: 'all' } }))).toBe('tout le parc');
    expect(approvalTarget(request({ target: { kind: 'machines' } }))).toBe('une liste de postes');
    expect(
      approvalTarget(request({ kind: 'schedule', schedule_name: 'Mises à jour du mercredi' })),
    ).toBe('planification « Mises à jour du mercredi »');
  });

  it('words the outcome of a closed request', () => {
    expect(approvalStatusLabel('failed')).toBe('En échec');
    expect(
      approvalOutcome(
        request({ status: 'rejected', decided_by: 'chef@lycee.example', note: 'Trop tôt' }),
      ),
    ).toBe('Refusée par chef@lycee.example : Trop tôt');
    expect(
      approvalOutcome(
        request({
          status: 'approved',
          decided_by: 'chef@lycee.example',
          created: 40,
          skipped: 3,
          left_out: 2,
        }),
      ),
    ).toContain('40 commande(s) envoyée(s), 3 déjà en attente, 2 laissé(s) de côté');
    expect(
      approvalCauseText({
        result_code: 'permission_lost',
        result_params: { permission: 'risky_command:execute' },
      }),
    ).toBe('L’auteur n’a plus le droit « risky_command:execute ».');
    // A package refusal keeps the API's code: its own wording.
    expect(approvalCauseText({ result_code: 'package.retired', result_params: null })).toBe(
      'Ce paquet est retiré : il ne peut plus être installé',
    );
  });

  it('agrees with its numbers in English', () => {
    setLocale('en');
    expect(approvedNotification(request({ status: 'approved', created: 1, skipped: 0 }))).toBe(
      '1 command sent',
    );
    expect(
      approvedNotification(request({ status: 'approved', created: 40, skipped: 2, left_out: 1 })),
    ).toBe(
      '40 commands sent; 2 already pending; 1 computer left out (deleted, revoked or out of the author’s scope)',
    );
    expect(approvalTarget(request({ target: { kind: 'all' } }))).toBe('the whole fleet');
  });
});
