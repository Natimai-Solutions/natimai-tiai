import { ref, type Ref } from 'vue';
import { useQuasar } from 'quasar';
import { bulkCheckNotification, createChecksBulk, type CheckPayload } from 'src/services/checks';
import { bulkSendNotification, createCommands, type CommandAction } from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import { wakeMachines, wakeNotification, type Machine } from 'src/services/machines';
import { placeMachines, placementNotification, unassignMachines } from 'src/services/rooms';
import { ROOM_NONE } from 'src/utils/machineListFilters';

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

  const askOpen = ref(false);
  const placeOpen = ref(false);

  const selectedIds = () => selected.value.map((m) => m.id);

  /** Asking for a verification on the selection. */
  async function askSelection(payload: CheckPayload) {
    const ids = selectedIds();
    if (!ids.length) return;
    $q.notify(bulkCheckNotification(await createChecksBulk(ids, payload)));
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
      $q.notify(placementNotification(res));
      placeOpen.value = false;
      selected.value = [];
      await reload();
      onPlaced();
    } catch (e) {
      $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Affectation impossible') });
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
    $q.dialog({
      title: action.label,
      message: [`Lancer « ${action.label} » sur ${ids.length} poste(s) ?`, action.hint]
        .filter(Boolean)
        .join(' '),
      cancel: true,
      persistent: true,
    }).onOk(() => {
      void sendBulk(action, ids);
    });
  }

  async function sendBulk(action: CommandAction, ids: string[]) {
    // The wake is emitted by the server, not queued for agents that — by
    // definition of the action — are not running. Everything around it is the
    // same: same menu, same selection, same notification slot.
    if (action.serverSide) {
      await wakeBulk(ids);
      return;
    }
    try {
      const res = await createCommands({ type: action.type, machine_ids: ids });
      $q.notify(bulkSendNotification(res));
      selected.value = [];
    } catch (e) {
      $q.notify({
        type: 'negative',
        message: apiErrorMessage(e, "Échec de l'envoi des commandes"),
      });
    }
  }

  async function wakeBulk(ids: string[]) {
    try {
      $q.notify(wakeNotification(await wakeMachines(ids)));
      selected.value = [];
    } catch (e) {
      $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec du réveil') });
    }
  }

  return { askOpen, placeOpen, askSelection, placeSelection, runBulk };
}
