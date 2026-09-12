<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-md">
      <div class="text-h5 col-auto">Logiciels du parc</div>
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

    <q-card flat bordered>
      <q-card-section>
        <q-input
          v-model="search"
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
        no-data-label="Aucun logiciel inventorié pour l'instant."
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
          <q-td :props="props">{{ formatDate(props.value) }}</q-td>
        </template>
      </q-table>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import {
  exportSoftware,
  listSoftware,
  type SoftwareEntry,
  type SoftwareExportFormat,
  type SoftwareSortField,
} from 'src/services/software';
import { apiErrorMessage } from 'src/services/errors';
import { downloadBlob, formatDate } from 'src/utils/format';

const $q = useQuasar();

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

async function load() {
  loading.value = true;
  try {
    const p = pagination.value;
    const data = await listSoftware({
      ...(search.value ? { search: search.value } : {}),
      sort_by: p.sortBy,
      sort_desc: p.descending,
      page: p.page,
      page_size: p.rowsPerPage,
    });
    items.value = data.items;
    pagination.value = { ...pagination.value, rowsNumber: data.total };
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec du chargement') });
  } finally {
    loading.value = false;
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

onMounted(load);
</script>
