<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <div class="text-h5 col-auto">Postes</div>
      <q-space />
      <q-input
        v-model="search"
        dense
        outlined
        debounce="300"
        placeholder="Nom, IP, antivirus ou UUID…"
        class="col-auto"
        style="min-width: 260px"
        @update:model-value="pushQuery"
      >
        <template #append><q-icon name="search" /></template>
      </q-input>
      <!--< q-input
        v-model="domain"
        dense
        outlined
        debounce="300"
        placeholder="Domaine"
        class="col-auto"
        style="width: 160px"
        @update:model-value="pushQuery"
      /> -->
      <q-select
        v-model="antivirus"
        :options="antivirusOptions"
        emit-value
        map-options
        dense
        outlined
        class="col-auto"
        style="width: 200px"
        @update:model-value="pushQuery"
      />
      <q-select
        v-model="status"
        :options="statusOptions"
        emit-value
        map-options
        dense
        outlined
        class="col-auto"
        style="width: 190px"
        @update:model-value="pushQuery"
      />
      <q-select
        v-model="wu"
        :options="wuOptions"
        emit-value
        map-options
        dense
        outlined
        class="col-auto"
        style="width: 210px"
        @update:model-value="pushQuery"
      />
      <q-toggle
        v-model="threatsOnly"
        dense
        label="Menaces actives"
        class="col-auto"
        @update:model-value="pushQuery"
      />
    </div>

    <div v-if="selected.length" class="row items-center q-mb-sm">
      <div class="text-caption text-grey q-mr-md">{{ selected.length }} sélectionné(s)</div>
      <q-btn-dropdown color="primary" dense label="Action groupée" icon="bolt">
        <q-list>
          <template v-for="section in actionGroups" :key="section.group">
            <q-item-label header class="q-py-xs">{{ section.label }}</q-item-label>
            <q-item
              v-for="action in section.actions"
              :key="action.type"
              v-close-popup
              clickable
              @click="runBulk(action)"
            >
              <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
              <q-item-section>{{ action.label }}</q-item-section>
            </q-item>
          </template>
        </q-list>
      </q-btn-dropdown>
    </div>

    <q-table
      v-model:selected="selected"
      v-model:pagination="pagination"
      :rows="rows"
      :columns="columns"
      row-key="id"
      selection="multiple"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      binary-state-sort
      @request="onRequest"
      @row-click="(_evt, row, index) => goDetail(row, index)"
    >
      <template #body-cell-hostname="props">
        <q-td :props="props">
          <!-- Leading, so a column of dots reads as one glance down the list. -->
          <q-icon
            :name="onlineIcon(props.row.is_online)"
            :color="onlineColor(props.row.is_online)"
            size="12px"
            class="q-mr-sm"
          >
            <q-tooltip>
              {{ onlineLabel(props.row.is_online) }} — dernier contact
              {{ timeAgoLabel(props.row.last_seen) }}
            </q-tooltip>
          </q-icon>
          {{ props.value || props.row.machine_uuid }}
          <q-icon
            v-if="props.row.needs_verification"
            name="warning"
            color="orange"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>À vérifier — identité du poste à confirmer (doublon possible)</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-antivirus="props">
        <q-td :props="props">
          <q-badge :color="protectionColor(props.row.is_up_to_date)">
            {{ antivirusLabel(props.row.av_product_name) }}
          </q-badge>
          <q-tooltip>{{ antivirusTooltip(props.row) }}</q-tooltip>
        </q-td>
      </template>
      <template #body-cell-windows_update="props">
        <q-td :props="props">
          <q-badge :color="wuPendingColor(props.row.wu_pending_count)">
            {{ wuPendingLabel(props.row.wu_pending_count) }}
          </q-badge>
          <q-icon
            v-if="props.row.wu_reboot_required"
            name="restart_alt"
            color="orange"
            size="18px"
            class="q-ml-xs"
          >
            <q-tooltip>Redémarrage requis</q-tooltip>
          </q-icon>
          <q-tooltip>
            {{
              props.row.wu_pending_count === null
                ? 'Windows Update jamais remonté par l’agent'
                : `${props.row.wu_pending_count} mise(s) à jour en attente`
            }}
          </q-tooltip>
        </q-td>
      </template>
      <template #body-cell-session="props">
        <q-td :props="props">
          <q-badge :color="sessionColor(props.row.session_user_present)">
            {{ sessionLabel(props.row.session_user_present, props.row.session_username) }}
          </q-badge>
          <q-tooltip>Au dernier contact : {{ formatDateTime(props.row.last_seen) }}</q-tooltip>
        </q-td>
      </template>
      <template #body-cell-last_seen="props">
        <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import { useAutoRefresh } from 'src/composables/useAutoRefresh';
import {
  listAntivirusProducts,
  listMachines,
  wakeMachines,
  wakeNotification,
  type ListMachinesParams,
  type Machine,
  type MachineSortField,
  type MachineStatus,
  type WindowsUpdateFilter,
} from 'src/services/machines';
import {
  bulkSendNotification,
  commandActionGroups,
  createCommands,
  type CommandAction,
} from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import {
  DEFAULT_PAGE_SIZE,
  MACHINE_STATUSES,
  PAGE_SIZE_OPTIONS,
  WU_FILTERS,
  queryValue,
} from 'src/utils/machineQuery';
import {
  antivirusLabel,
  antivirusStatusLabel,
  formatDateTime,
  onlineColor,
  onlineIcon,
  onlineLabel,
  protectionColor,
  protectionLabel,
  sessionColor,
  sessionLabel,
  timeAgoLabel,
  wuPendingColor,
  wuPendingLabel,
} from 'src/utils/format';

const $q = useQuasar();
const router = useRouter();
const route = useRoute();

const rows = ref<Machine[]>([]);
const selected = ref<Machine[]>([]);
const loading = ref(false);
const search = ref('');
const domain = ref('');
const antivirus = ref<string | null>(null);
const status = ref<MachineStatus | null>(null);
const wu = ref<WindowsUpdateFilter | null>(null);
const threatsOnly = ref(false);

/** Sortable columns ↔ their API field: the table speaks in column names, the
 * URL and the server in field names. */
const SORT_FIELD_BY_COLUMN: Record<string, MachineSortField> = {
  hostname: 'hostname',
  domain: 'domain',
  antivirus: 'av_product_name',
  windows_update: 'wu_pending_count',
  session: 'session_user_present',
  last_seen: 'last_seen',
};
const COLUMN_BY_SORT_FIELD = Object.fromEntries(
  Object.entries(SORT_FIELD_BY_COLUMN).map(([column, field]) => [field, column]),
) as Record<string, string>;

/** Server-side pagination state. `rowsNumber` present makes the q-table hand
 * every page/sort interaction to `onRequest` instead of slicing `rows` — the
 * server holds the fleet, the table only ever holds one page of it. */
const pagination = ref({
  sortBy: 'last_seen' as string | null,
  descending: true,
  page: 1,
  rowsPerPage: DEFAULT_PAGE_SIZE,
  rowsNumber: 0,
});

// Filled from the fleet on mount: the products installed are data, not a list
// the console can know in advance. The count sits in the label so the dropdown
// doubles as an inventory of a mixed parc.
const antivirusOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les antivirus', value: null },
]);

// « Antivirus » in the labels, not just « à jour » : since the Windows Update
// filter joined it, this axis has to say which of the two updates it means.
const statusOptions = [
  { label: 'Antivirus : Tous statuts', value: null },
  { label: 'Antivirus à jour', value: 'up_to_date' },
  { label: 'Antivirus périmé', value: 'outdated' },
  { label: 'À vérifier', value: 'needs_verification' },
  { label: 'Inactif', value: 'inactive' },
];

const wuOptions = [
  { label: 'Windows Update : Tous statuts', value: null },
  { label: 'MAJ Windows requises', value: 'pending' },
  { label: 'Redémarrage requis', value: 'reboot_required' },
];

// bulkOnly: the two diagnostics stay on the detail page. Their value is reading
// one machine's output; fired on a selection they queue a report per poste that
// nobody will open.
const actionGroups = commandActionGroups({ bulkOnly: true });

const columns: QTableColumn<Machine>[] = [
  { name: 'hostname', label: 'Nom', field: 'hostname', align: 'left', sortable: true },
  { name: 'domain', label: 'Domaine', field: 'domain', align: 'left', sortable: true },
  // Not sortable: a string sort would put 192.168.1.10 before 192.168.1.9, and
  // an octet-aware comparator is not worth it on a column people search, not sort.
  {
    name: 'ip_address',
    label: 'Adresse IP',
    field: 'ip_address',
    align: 'left',
    format: (val: string | null) => val ?? '—',
  },
  { name: 'os_version', label: 'OS', field: 'os_version', align: 'left' },
  // name ≠ field like the session column below: the cell renders the product and
  // its state together, while `field` keeps a sensible sort key. Sortable because
  // grouping a mixed parc by product is exactly what this column is for.
  // The badge colour carries the overall state (`is_up_to_date`) and the tooltip
  // the signature detail — one column where there used to be three.
  {
    name: 'antivirus',
    label: 'Antivirus',
    field: 'av_product_name',
    align: 'left',
    sortable: true,
  },
  // Sortable, and it is the sort that matters: "show me the postes furthest
  // behind" is the whole point of the column. A null count (never reported)
  // sorts apart from a zero, which is the distinction the badge makes too.
  {
    name: 'windows_update',
    label: 'MAJ Windows',
    field: 'wu_pending_count',
    align: 'center',
    sortable: true,
  },
  // name ≠ field on purpose: the cell renders presence *and* username, while
  // `field` still gives the sort a sensible key (present / absent / unknown).
  {
    name: 'session',
    label: 'Session',
    field: 'session_user_present',
    align: 'center',
    sortable: true,
  },
  { name: 'last_seen', label: 'Vu le', field: 'last_seen', align: 'left', sortable: true },
];

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

/** One line: overall state, what the Security Center says of the product, and
 * the signature version — the detail the badge colour compresses. */
function antivirusTooltip(m: Machine): string {
  const parts = [
    protectionLabel(m.is_up_to_date),
    antivirusStatusLabel(
      m.av_product_name,
      m.av_product_enabled,
      m.av_product_signatures_up_to_date,
    ),
  ];
  if (m.signature_version) parts.push(`signatures ${m.signature_version}`);
  return parts.join(' · ');
}

/** Read the filters, sort and page from the URL — the dashboard cards land
 * here with one set, and the detail page's back arrow with another. */
function applyQuery() {
  const q = route.query;
  search.value = queryValue(q.search) ?? '';
  domain.value = queryValue(q.domain) ?? '';
  antivirus.value = queryValue(q.antivirus);
  const s = queryValue(q.status);
  status.value = s && MACHINE_STATUSES.includes(s) ? (s as MachineStatus) : null;
  const w = queryValue(q.wu_status);
  wu.value = w && WU_FILTERS.includes(w) ? (w as WindowsUpdateFilter) : null;
  threatsOnly.value = queryValue(q.with_active_threats) === 'true';

  const sortField = queryValue(q.sort_by);
  const sortColumn = sortField ? COLUMN_BY_SORT_FIELD[sortField] : undefined;
  const page = Number(queryValue(q.page) ?? '1');
  const pageSize = Number(queryValue(q.page_size) ?? String(DEFAULT_PAGE_SIZE));
  pagination.value = {
    ...pagination.value,
    // No sort in the URL = the server's default order, freshest first — shown
    // as such rather than as "unsorted".
    sortBy: sortColumn ?? 'last_seen',
    descending: sortColumn ? queryValue(q.sort_desc) !== 'false' : true,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    rowsPerPage: PAGE_SIZE_OPTIONS.includes(pageSize) ? pageSize : DEFAULT_PAGE_SIZE,
  };
}

/** The whole list state as URL query params, defaults omitted so the common
 * URL stays short. Shared by the address bar and the links into a fiche. */
function buildQuery(): Record<string, string> {
  const query: Record<string, string> = {};
  if (search.value) query.search = search.value;
  if (domain.value) query.domain = domain.value;
  if (antivirus.value) query.antivirus = antivirus.value;
  if (status.value) query.status = status.value;
  if (wu.value) query.wu_status = wu.value;
  if (threatsOnly.value) query.with_active_threats = 'true';
  const p = pagination.value;
  const field = p.sortBy ? SORT_FIELD_BY_COLUMN[p.sortBy] : undefined;
  if (field && !(field === 'last_seen' && p.descending)) {
    query.sort_by = field;
    query.sort_desc = String(p.descending);
  }
  if (p.page > 1) query.page = String(p.page);
  if (p.rowsPerPage !== DEFAULT_PAGE_SIZE) query.page_size = String(p.rowsPerPage);
  return query;
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

// Which fetch is the current one. A background refresh started 90 s ago and a
// page turn issued just now are both in flight at once, and whichever answers
// last would otherwise win — putting page 1's rows under a table that says page
// 2, and writing its own stale page number back over the user's.
let requestId = 0;

/** Fetch the current page of the current query. */
async function fetchMachines() {
  const id = ++requestId;
  const p = pagination.value;
  const params: ListMachinesParams = { page: p.page, page_size: p.rowsPerPage };
  if (search.value) params.search = search.value;
  if (domain.value) params.domain = domain.value;
  if (antivirus.value) params.antivirus = antivirus.value;
  if (status.value) params.status = status.value;
  if (wu.value) params.wu_status = wu.value;
  if (threatsOnly.value) params.with_active_threats = true;
  const field = p.sortBy ? SORT_FIELD_BY_COLUMN[p.sortBy] : undefined;
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
  // Merged into the *current* pagination, never the snapshot taken above: the
  // user may have turned the page while this request was in the air, and
  // writing the snapshot back would silently undo it.
  pagination.value = { ...pagination.value, rowsNumber: data.total };
}

// The machine list follows the fleet like the dashboard does: agents report
// every minute, so a page left open shows postes coming online without a
// keypress. Paused while rows are selected — a bulk action being composed must
// not have its rows shuffled underneath it.
const { refreshNow } = useAutoRefresh(fetchMachines, {
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

async function loadAntivirusOptions() {
  try {
    const products = await listAntivirusProducts();
    antivirusOptions.value = [
      { label: 'Tous les antivirus', value: null },
      ...products.map((p) => ({ label: `${p.name} (${p.count})`, value: p.name })),
    ];
  } catch {
    // A filter that failed to populate must not blank the machine list: the
    // dropdown simply keeps its "Tous antivirus" entry.
  }
}

function runBulk(action: CommandAction) {
  const ids = selected.value.map((m) => m.id);
  if (!ids.length) return;
  if (!action.confirm) {
    void sendBulk(action, ids);
    return;
  }
  // The count is the whole point of the confirmation here: "sfc sur 1 poste" and
  // "sfc sur 340 postes" are very different decisions.
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
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'envoi des commandes") });
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

onMounted(() => {
  applyQuery();
  void reload();
  void loadAntivirusOptions();
});
</script>
