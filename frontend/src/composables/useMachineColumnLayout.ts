import { computed, ref, watch, type Ref } from 'vue';
import { useQuasar } from 'quasar';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import {
  PREF_MACHINE_COLUMNS,
  isDefaultMachineColumns,
  resolveMachineColumns,
  type MachineColumnKey,
} from 'src/utils/machineColumns';
import { visibleMachineColumns } from 'src/utils/machineListTable';

/**
 * Which columns the machine list shows, and in what order — kept on the
 * account (`preferences.machines_columns`), not in the URL: a search is shared
 * by pasting a link, a layout is personal.
 */
export function useMachineColumnLayout(usageWindowDays: Ref<number>) {
  const $q = useQuasar();
  const auth = useAuthStore();

  const columnOrder = ref<MachineColumnKey[]>(
    resolveMachineColumns(auth.user?.preferences?.[PREF_MACHINE_COLUMNS]),
  );
  // The profile may arrive after the page (a reload restores it in the
  // layout), hence the watch.
  watch(
    () => auth.user?.preferences?.[PREF_MACHINE_COLUMNS],
    (saved) => {
      columnOrder.value = resolveMachineColumns(saved);
    },
  );

  const visibleColumns = computed(() =>
    visibleMachineColumns(columnOrder.value, usageWindowDays.value),
  );

  /**
   * Persist a layout on the account. The default is stored as an absence, so
   * a reader who comes back to it is not carrying a copy of the catalogue.
   * Rethrows, so the dialog stays open on a failure.
   */
  async function saveColumns(next: MachineColumnKey[]) {
    try {
      await auth.savePreferences({
        [PREF_MACHINE_COLUMNS]: isDefaultMachineColumns(next) ? null : next,
      });
      columnOrder.value = next;
    } catch (e) {
      $q.notify({
        type: 'negative',
        message: apiErrorMessage(e, "Impossible d'enregistrer les colonnes"),
      });
      throw e;
    }
  }

  return { columnOrder, visibleColumns, saveColumns };
}
