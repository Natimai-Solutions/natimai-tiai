<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-md">
      <h1 class="text-h5 q-my-none col-auto">Logiciels du parc</h1>
      <q-space />
      <div class="col-auto">
        <!-- Excel or CSV, as the fleet export offers: the same catalogue, and
             a real date in the last column when Excel is the destination. -->
        <q-btn-dropdown
          outline
          no-caps
          color="positive"
          icon="download"
          label="Exporter"
          :loading="exporting"
        >
          <q-list>
            <q-item v-close-popup clickable @click="doExport('xlsx')">
              <q-item-section avatar><q-icon name="table_chart" /></q-item-section>
              <q-item-section>Excel (.xlsx)</q-item-section>
            </q-item>
            <q-item v-close-popup clickable @click="doExport('csv')">
              <q-item-section avatar><q-icon name="description" /></q-item-section>
              <q-item-section>CSV</q-item-section>
            </q-item>
          </q-list>
          <q-tooltip>Télécharger le catalogue filtré (Excel ou CSV)</q-tooltip>
        </q-btn-dropdown>
      </div>
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          aria-label="Actualiser"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>

    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />

    <q-card flat bordered>
      <q-card-section>
        <q-input
          v-model="search"
          aria-label="Rechercher un logiciel"
          dense
          outlined
          clearable
          debounce="300"
          placeholder="Nom ou éditeur…"
          @update:model-value="onSearch"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </q-card-section>
      <q-separator />
      <q-table
        v-model:pagination="pagination"
        :rows="items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[25, 50, 100]"
        :no-data-label="noDataLabel"
        @request="onRequest"
      >
        <!-- The count is the column the page exists for, so it is a link and not
             a number: reading "148 postes" and having no way to see which ones
             would be the whole feature stopping one click short. -->
        <template #body-cell-machine_count="props">
          <q-td :props="props">
            <q-btn
              flat
              dense
              no-caps
              color="primary"
              :label="`${props.value} poste(s)`"
              :to="{ name: 'machines', query: { software_id: props.row.id } }"
            />
          </q-td>
        </template>
        <template #body-cell-first_seen="props">
          <q-td :props="props">{{ localDate(props.value) }}</q-td>
        </template>
      </q-table>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import {
  exportSoftware,
  listSoftware,
  type SoftwareEntry,
  type SoftwareExportFormat,
  type SoftwareSortField,
} from 'src/services/software';
import { apiErrorMessage } from 'src/services/errors';
import { downloadBlob } from 'src/utils/format';
import { queryValue } from 'src/utils/machineQuery';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();
const loadError = ref<unknown>(null);

const items = ref<SoftwareEntry[]>([]);
const loading = ref(false);
const exporting = ref(false);
const search = ref('');

// Most widespread first, and that default is the useful one: the top of the list
// is the standard the parc actually runs, and the bottom is where the one poste
// with an unapproved program sits.
const pagination = ref({
  page: 1,
  rowsPerPage: 25,
  rowsNumber: 0,
  sortBy: 'machine_count' as SoftwareSortField,
  descending: true,
});

const columns: QTableColumn<SoftwareEntry>[] = [
  { name: 'name', label: 'Nom', field: 'name', align: 'left', sortable: true },
  { name: 'version', label: 'Version', field: 'version', align: 'left', sortable: true },
  { name: 'publisher', label: 'Éditeur', field: 'publisher', align: 'left', sortable: true },
  {
    name: 'machine_count',
    label: 'Postes',
    field: 'machine_count',
    align: 'right',
    sortable: true,
  },
  {
    name: 'first_seen',
    label: 'Vu depuis',
    field: 'first_seen',
    align: 'left',
  },
];

const SORT_FIELDS: SoftwareSortField[] = ['name', 'version', 'publisher', 'machine_count'];

/**
 * The search, the order and the page live in the URL (audit B20): « 148
 * postes » opens the machine list, and coming back must find the catalogue
 * where the reader left it.
 */
function applyQuery() {
  const q = route.query;
  search.value = queryValue(q.search) ?? '';
  const sort = queryValue(q.sort) as SoftwareSortField | null;
  const page = Number(queryValue(q.page) ?? '1');
  const size = Number(queryValue(q.page_size) ?? '25');
  pagination.value = {
    ...pagination.value,
    sortBy: sort && SORT_FIELDS.includes(sort) ? sort : 'machine_count',
    descending: queryValue(q.desc) !== 'false',
    page: Number.isInteger(page) && page > 0 ? page : 1,
    rowsPerPage: [25, 50, 100].includes(size) ? size : 25,
  };
}

/** The page's state as the URL writes it, defaults left out. */
function buildQuery(): Record<string, string> {
  const p = pagination.value;
  const query: Record<string, string> = {};
  if (search.value) query.search = search.value;
  if (p.sortBy !== 'machine_count') query.sort = p.sortBy;
  if (!p.descending) query.desc = 'false';
  if (p.page > 1) query.page = String(p.page);
  if (p.rowsPerPage !== 25) query.page_size = String(p.rowsPerPage);
  return query;
}

function pushQuery() {
  void router.replace({ query: buildQuery() });
}

// The URL changed from outside the page — the drawer's « Logiciels » link, or
// Back — and the search, order or page with it: the page follows (audit T42).
// Its own writes come back here too, and change nothing.
watch(
  () => route.query,
  () => {
    const before = JSON.stringify(buildQuery());
    applyQuery();
    if (JSON.stringify(buildQuery()) !== before) void load();
  },
);

/** A first-seen instant, as the day it was in the reader's time zone. */
function localDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString('fr-FR') : '—';
}

// Three different empty tables, three different sentences (audit U09).
const noDataLabel = computed(() => {
  if (loadError.value) return 'Le catalogue n’a pas pu être chargé.';
  if (search.value) return `Aucun logiciel ne correspond à « ${search.value} ».`;
  return "Aucun logiciel inventorié pour l'instant.";
});

// Which load is the current one: a search typed while the previous one is in
// the air must not have the older answer written over its own.
let requestId = 0;

async function load() {
  const id = ++requestId;
  loading.value = true;
  loadError.value = null;
  pushQuery();
  try {
    const p = pagination.value;
    const data = await listSoftware({
      ...(search.value ? { search: search.value } : {}),
      sort_by: p.sortBy,
      sort_desc: p.descending,
      page: p.page,
      page_size: p.rowsPerPage,
    });
    if (id !== requestId) return;
    if (!data.items.length && data.total > 0 && p.page > 1) {
      // A page past the end — a URL kept from a bigger catalogue: the last
      // page that exists, rather than « aucun logiciel » over a total of 120.
      pagination.value = {
        ...pagination.value,
        page: Math.ceil(data.total / p.rowsPerPage),
        rowsNumber: data.total,
      };
      void load();
      return;
    }
    items.value = data.items;
    pagination.value = { ...pagination.value, rowsNumber: data.total };
  } catch (e) {
    if (id !== requestId) return;
    loadError.value = e;
    items.value = [];
  } finally {
    if (id === requestId) loading.value = false;
  }
}

/** A new search starts at the first page — its results have nothing to do with
 * the page the reader was on. */
function onSearch() {
  pagination.value = { ...pagination.value, page: 1 };
  void load();
}

function onRequest(evt: {
  pagination: { page?: number; rowsPerPage?: number; sortBy?: string; descending?: boolean };
}) {
  pagination.value = {
    ...pagination.value,
    page: evt.pagination.page ?? 1,
    rowsPerPage: evt.pagination.rowsPerPage ?? 25,
    sortBy: (evt.pagination.sortBy as SoftwareSortField) ?? 'machine_count',
    descending: evt.pagination.descending ?? true,
  };
  void load();
}

async function doExport(format: SoftwareExportFormat) {
  exporting.value = true;
  try {
    const blob = await exportSoftware(format, search.value ? { search: search.value } : {});
    downloadBlob(blob, `logiciels.${format}`);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'export") });
  } finally {
    exporting.value = false;
  }
}

onMounted(() => {
  applyQuery();
  void load();
});
</script>
