<template>
  <q-page padding>
    <MachinesToolbar
      :loading="loading"
      :last-refreshed-at="lastRefreshedAt"
      @columns="columnsOpen = true"
      @export="exportOpen = true"
      @refresh="reload"
    />

    <MachinesFiltersBar
      :model-value="filters"
      :options="fleetOptions"
      :usage-thresholds="usageThresholds"
      :usage-window-days="usageWindowDays"
      @update:model-value="onFilters"
    />

    <MachinesBulkBar
      :count="selected.length"
      :can-place="canPlace"
      :can-check="auth.can('check', 'write')"
      :action-groups="actionGroups"
      @place="placeOpen = true"
      @ask="askOpen = true"
      @run="runBulk"
    />

    <MachinesTable
      v-model:selected="selected"
      v-model:pagination="pagination"
      :rows="rows"
      :columns="visibleColumns"
      :loading="loading"
      :agent-latest="agentLatest"
      :usage-window-days="usageWindowDays"
      @request="onRequest"
      @open="goDetail"
    />

    <CheckRequestDialog
      v-model="askOpen"
      :check="null"
      :subtitle="`${selected.length} poste(s) sélectionné(s)`"
      :save="askSelection"
    />

    <MachinePlaceDialog
      v-model="placeOpen"
      :count="selected.length"
      :rooms="rooms"
      :save="placeSelection"
    />

    <!-- The filtered fleet, columns at the reader's choice. It reads
         `filterParams` live, so opening it after a filter change exports what
         the table shows. -->
    <MachineExportDialog
      v-model="exportOpen"
      :params="filterParams"
      :count="pagination.rowsNumber"
    />

    <MachineColumnsDialog
      v-model:open="columnsOpen"
      :columns="columnOrder"
      :labels="MACHINE_COLUMN_LABELS"
      :save="saveColumns"
    />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import CheckRequestDialog from 'src/components/check/CheckRequestDialog.vue';
import MachineColumnsDialog from 'src/components/machine/MachineColumnsDialog.vue';
import MachineExportDialog from 'src/components/machine/MachineExportDialog.vue';
import MachinePlaceDialog from 'src/components/machines-list/MachinePlaceDialog.vue';
import MachinesBulkBar from 'src/components/machines-list/MachinesBulkBar.vue';
import MachinesFiltersBar from 'src/components/machines-list/MachinesFiltersBar.vue';
import MachinesTable from 'src/components/machines-list/MachinesTable.vue';
import MachinesToolbar from 'src/components/machines-list/MachinesToolbar.vue';
import { useAutoRefresh } from 'src/composables/useAutoRefresh';
import { useMachineBulkActions } from 'src/composables/useMachineBulkActions';
import { useMachineColumnLayout } from 'src/composables/useMachineColumnLayout';
import { useMachineFleetOptions } from 'src/composables/useMachineFleetOptions';
import { commandActionGroups } from 'src/services/commands';
import { listMachines, type ListMachinesParams, type Machine } from 'src/services/machines';
import { useAuthStore } from 'src/stores/auth';
import { DEFAULT_PAGE_SIZE } from 'src/utils/machineQuery';
import {
  emptyMachineFilters,
  machineFiltersFromQuery,
  machineFiltersToParams,
  machineFiltersToQuery,
  type MachineFilters,
} from 'src/utils/machineListFilters';
import {
  MACHINE_COLUMN_LABELS,
  initialMachinePagination,
  machinePaginationFromQuery,
  machinePaginationToQuery,
  sortFieldOf,
} from 'src/utils/machineListTable';
import type { UsageThresholds } from 'src/utils/usageFilter';

/**
 * The machine list. The pieces live in `components/machines-list/` and the
 * translations in `utils/machineListFilters.ts` / `utils/machineListTable.ts`;
 * what stays here is the wiring between the URL, the server and those pieces.
 */

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const rows = ref<Machine[]>([]);
const selected = ref<Machine[]>([]);
const loading = ref(false);
const filters = ref<MachineFilters>(emptyMachineFilters());
const pagination = ref(initialMachinePagination());

// What the last list response said about the parc: the agent reference the
// rows are flagged against, the usage window and the thresholds the usage
// presets are drawn from.
const agentLatest = ref<string | null>(null);
const usageWindowDays = ref(7);
const usageThresholds = ref<UsageThresholds | null>(null);

const {
  options: fleetOptions,
  rooms,
  manualMode,
  loadAll: loadFleetOptions,
  loadRooms,
} = useMachineFleetOptions();

const { columnOrder, visibleColumns, saveColumns } = useMachineColumnLayout(usageWindowDays);
const columnsOpen = ref(false);
const exportOpen = ref(false);

// Moving postes by hand: the permission, and a server not in a directory mode.
const canPlace = computed(() => auth.can('room', 'write') && manualMode.value);

// bulkOnly: the two diagnostics stay on the detail page. Their value is reading
// one machine's output; fired on a selection they queue a report per poste that
// nobody will open. Filtered on the profile's permissions, so the menu never
// offers what the backend would refuse — and disappears for an account that
// may run nothing.
const actionGroups = computed(() =>
  commandActionGroups({ bulkOnly: true, permissions: auth.permissions }),
);

/** Read the filters, sort and page from the URL. */
function applyQuery() {
  filters.value = machineFiltersFromQuery(route.query);
  pagination.value = machinePaginationFromQuery(route.query, pagination.value);
}

/** The whole list state as URL query params. Shared by the address bar and
 * the links into a fiche. */
function buildQuery(): Record<string, string> {
  return {
    ...machineFiltersToQuery(filters.value),
    ...machinePaginationToQuery(pagination.value),
  };
}

// The URL is the single source of truth for the list state: widgets and the
// table push into it, and the reload happens in the route watcher — so a link
// from the dashboard, a pasted URL, a widget change and a page turn all take
// the same path.
function pushQuery() {
  // A filter change starts a new search: page 1 of it, sort kept.
  pagination.value = { ...pagination.value, page: 1 };
  void router.replace({ query: buildQuery() });
}

function onFilters(next: MachineFilters) {
  filters.value = next;
  pushQuery();
}

/** Every page/sort/page-size interaction of the server-side table lands here. */
function onRequest(evt: {
  pagination: { sortBy?: string | null; descending?: boolean; page?: number; rowsPerPage?: number };
}) {
  const p = evt.pagination;
  pagination.value = {
    sortBy: p.sortBy ?? null,
    descending: p.descending ?? true,
    page: p.page ?? 1,
    rowsPerPage: p.rowsPerPage ?? DEFAULT_PAGE_SIZE,
    rowsNumber: pagination.value.rowsNumber,
  };
  void router.replace({ query: buildQuery() });
}

watch(
  () => route.query,
  () => {
    applyQuery();
    void reload();
  },
);

/** Open a poste, carrying the whole list query plus the row's absolute rank in
 * it (`i`). The detail page uses the query to come back to this exact search,
 * and the rank to walk to the previous/next result of it. */
function goDetail(row: Machine, rowIndex: number) {
  const p = pagination.value;
  const i = (p.page - 1) * p.rowsPerPage + rowIndex;
  void router.push({
    name: 'machine-detail',
    params: { id: row.id },
    query: { ...buildQuery(), i: String(i) },
  });
}

/** The current filters as API params, for the list and the export alike. */
const filterParams = computed<ListMachinesParams>(() => machineFiltersToParams(filters.value));

// Which fetch is the current one. A background refresh started 90 s ago and a
// page turn issued just now are both in flight at once, and whichever answers
// last would otherwise win — putting page 1's rows under a table that says page
// 2, and writing its own stale page number back over the user's.
let requestId = 0;

/** Fetch the current page of the current query. */
async function fetchMachines() {
  const id = ++requestId;
  const p = pagination.value;
  const params: ListMachinesParams = {
    ...filterParams.value,
    page: p.page,
    page_size: p.rowsPerPage,
  };
  const field = sortFieldOf(p);
  if (field) {
    params.sort_by = field;
    params.sort_desc = p.descending;
  }
  const data = await listMachines(params);
  // Superseded while we waited: these rows answer a question nobody is asking
  // any more, and the fetch that replaced us will write its own.
  if (id !== requestId) return;
  if (!data.items.length && data.total > 0 && p.page > 1) {
    // The page evaporated under us — the fleet shrank, or a filter came from a
    // URL pointing past the end. Fall back on the last page that still exists.
    pagination.value = {
      ...pagination.value,
      page: Math.ceil(data.total / p.rowsPerPage),
      rowsNumber: data.total,
    };
    void router.replace({ query: buildQuery() });
    return;
  }
  rows.value = data.items;
  agentLatest.value = data.agent_latest_version;
  usageWindowDays.value = data.usage_days;
  usageThresholds.value = { low: data.usage_low_hours, high: data.usage_high_hours };
  // Merged into the *current* pagination, never the snapshot taken above: the
  // user may have turned the page while this request was in the air, and
  // writing the snapshot back would silently undo it.
  pagination.value = { ...pagination.value, rowsNumber: data.total };
}

// The machine list follows the fleet like the dashboard does: agents report
// every minute, so a page left open shows postes coming online without a
// keypress. Paused while rows are selected — a bulk action being composed must
// not have its rows shuffled underneath it.
const { lastRefreshedAt, refreshNow } = useAutoRefresh(fetchMachines, {
  paused: () => selected.value.length > 0,
});

/** The user-visible load: spinner on, and the auto-refresh countdown restarts
 * so the next background tick lands a full period away. */
async function reload() {
  loading.value = true;
  try {
    await refreshNow();
  } finally {
    loading.value = false;
  }
}

const { askOpen, placeOpen, askSelection, placeSelection, runBulk } = useMachineBulkActions({
  selected,
  reload,
  onPlaced: () => void loadRooms(),
});

onMounted(() => {
  applyQuery();
  void reload();
  loadFleetOptions();
});
</script>
