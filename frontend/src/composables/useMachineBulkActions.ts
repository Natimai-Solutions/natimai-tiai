import { ref, type Ref } from 'vue';
import { useQuasar } from 'quasar';
import { useRouter } from 'vue-router';
import { t } from 'src/i18n';
import { bulkCheckNotification, createChecksBulk, type CheckPayload } from 'src/services/checks';
import {
  bulkSendNotification,
  commandConfirm,
  createCommands,
  type CommandAction,
} from 'src/services/commands';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
import { windowText, type ForbiddenWindow } from 'src/services/schedules';
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import { notifyApprovalsChanged } from 'src/composables/useApprovalsBadge';
import {
  approveReenroll,
  approveReenrollNotification,
  wakeMachines,
  wakeNotification,
  type Machine,
} from 'src/services/machines';
import { placeMachines, placementNotification, unassignMachines } from 'src/services/rooms';
import { ROOM_NONE } from 'src/utils/machineListFilters';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

/**
 * What the machine list does to its selection: a command, a verification
 * request, a room. Each one empties the selection once the server has taken
 * it — which also resumes the list's auto-refresh, paused while rows are
 * selected.
 */
export function useMachineBulkActions(options: {
  selected: Ref<Machine[]>;
  /** The list's own reload, spinner included. */
  reload: () => Promise<void>;
  /** After a placement: the room dropdowns' counts have moved. */
  onPlaced: () => void;
}) {
  const { selected, reload, onPlaced } = options;
  const $q = useQuasar();
  const router = useRouter();

  const askOpen = ref(false);
  const placeOpen = ref(false);

  const selectedIds = () => selected.value.map((m) => m.id);

  /** Asking for a verification on the selection. */
  async function askSelection(payload: CheckPayload) {
    const ids = selectedIds();
    if (!ids.length) return;
    const res = await createChecksBulk(ids, payload);
    // Checks handed out change what « Mes tâches » counts — the asker's own
    // when the requests are theirs: the menu badge reads again (audit U19).
    notifyTasksChanged();
    notify($q, () => bulkCheckNotification(res));
    selected.value = [];
    await reload();
  }

  /**
   * Placing the selection: one room, or none (« Sans salle » unassigns). The
   * server reports which postes now disagree on the site rather than
   * refusing them. Never throws: a failure is said here, and the dialog stays
   * open for another try.
   */
  async function placeSelection(roomId: string | null) {
    const ids = selectedIds();
    if (!ids.length || !roomId) return;
    try {
      const res =
        roomId === ROOM_NONE ? await unassignMachines(ids) : await placeMachines(roomId, ids);
      // A poste follows its room's maintenance owner and cycle: moved, it
      // enters or leaves somebody's « Mes tâches » (audit U19).
      notifyTasksChanged();
      notify($q, () => placementNotification(res));
      placeOpen.value = false;
      selected.value = [];
      await reload();
      onPlaced();
    } catch (e) {
      notify($q, () => ({
        type: 'negative',
        message: apiErrorMessage(e, t('machines.bulk.placeFailed')),
      }));
    }
  }

  function runBulk(action: CommandAction) {
    const ids = selectedIds();
    if (!ids.length) return;
    if (!action.confirm) {
      void sendBulk(action, ids);
      return;
    }
    // The count is the whole point of the confirmation here: "sfc sur 1 poste"
    // and "sfc sur 340 postes" are very different decisions.
    const withSession = selected.value.filter((m) => m.session_user_present).length;
    liveDialog($q, () => commandConfirm(action, ids.length, withSession)).onOk(() => {
      void sendBulk(action, ids);
    });
  }

  // One send of a given command at a time: the menu entry clicked twice
  // before it closes, or the confirmation accepted twice in the same
  // instant, queued the command twice on every poste of the selection.
  // Another command still goes: refusing it silently lost what the operator
  // had just confirmed (verification of 2026-11-18).
  const sending = new Set<string>();

  async function sendBulk(action: CommandAction, ids: string[]) {
    if (sending.has(action.type)) return;
    sending.add(action.type);
    try {
      // The wake is emitted by the server, not queued for agents that — by
      // definition of the action — are not running. Everything around it is
      // the same: same menu, same selection, same notification slot.
      if (action.serverSide) {
        await wakeBulk(ids);
        return;
      }
      try {
        await sendCommand(action, ids, false);
      } catch (e) {
        if (apiErrorCode(e) === 'command.forbidden_window') {
          confirmForbidden(action, ids, e);
          return;
        }
        notify($q, () => ({
          type: 'negative',
          message: apiErrorMessage(e, t('machines.bulk.sendFailed')),
        }));
      }
    } finally {
      sending.delete(action.type);
    }
  }

  async function sendCommand(action: CommandAction, ids: string[], confirmed: boolean) {
    const res = await createCommands({
      type: action.type,
      machine_ids: ids,
      ...(confirmed ? { confirm_forbidden_window: true } : {}),
    });
    // C10: a request waiting for a second account, with a way to it.
    if (res.approval_id) notifyApprovalsChanged();
    notify($q, () => bulkSendNotification(res, () => void router.push({ name: 'approvals' })));
    selected.value = [];
  }

  /**
   * Inside a forbidden window (Paramètres): a risky command for several
   * postes goes only once the person says so — the window named.
   */
  function confirmForbidden(action: CommandAction, ids: string[], error: unknown) {
    const details = (
      error as { response?: { data?: { error?: { details?: { window?: ForbiddenWindow } } } } }
    )?.response?.data?.error?.details;
    const window = details?.window ? windowText(details.window) : '';
    liveDialog($q, () => ({
      title: t('schedules.forbiddenConfirm.title'),
      message: t('schedules.forbiddenConfirm.message', { window, count: ids.length }),
      cancel: { flat: true, noCaps: true, label: t('schedules.forbiddenConfirm.cancel') },
      ok: { color: 'negative', noCaps: true, label: t('schedules.forbiddenConfirm.ok') },
      persistent: true,
    })).onOk(() => {
      void (async () => {
        try {
          await sendCommand(action, ids, true);
        } catch (e) {
          notify($q, () => ({
            type: 'negative',
            message: apiErrorMessage(e, t('machines.bulk.sendFailed')),
          }));
        }
      })();
    });
  }

  async function wakeBulk(ids: string[]) {
    try {
      const res = await wakeMachines(ids);
      notify($q, () => wakeNotification(res));
      selected.value = [];
    } catch (e) {
      notify($q, () => ({
        type: 'negative',
        message: apiErrorMessage(e, t('machines.bulk.wakeFailed')),
      }));
    }
  }

  /** C2: allow the re-enrolment of the selection, after a confirmation. */
  function reenrollSelection() {
    const ids = selectedIds();
    if (!ids.length) return;
    liveDialog($q, () => ({
      title: t('machines.bulk.reenrollTitle'),
      message: t('machines.bulk.reenrollMessage', { count: ids.length }, ids.length),
      cancel: { flat: true, noCaps: true, label: t('machines.bulk.cancel') },
      ok: { unelevated: true, noCaps: true, label: t('machines.bulk.allow') },
      persistent: true,
    })).onOk(() => {
      void doReenroll(ids);
    });
  }

  async function doReenroll(ids: string[]) {
    try {
      const res = await approveReenroll(ids);
      notify($q, () => approveReenrollNotification(res));
      selected.value = [];
      await reload();
    } catch (e) {
      notify($q, () => ({
        type: 'negative',
        message: apiErrorMessage(e, t('machines.bulk.reenrollFailed')),
      }));
    }
  }

  return { askOpen, placeOpen, askSelection, placeSelection, runBulk, reenrollSelection };
}
