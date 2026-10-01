<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-md">
      <div class="col-auto">
        <div class="text-h5">Journal d'audit</div>
        <div class="text-caption text-grey">
          Actions administratives, de la plus récente à la plus ancienne. Heures affichées dans
          votre fuseau ({{ timeZone }}).
        </div>
      </div>
      <q-space />
      <!-- No automatic refresh: the log is read like an archive, not watched
           like the parc — a page that reshuffled under a reader comparing two
           lines would be worse than one a click behind. -->
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          aria-label="Actualiser"
          :loading="loading"
          @click="load"
        >
          <q-tooltip>Actualiser</q-tooltip>
        </q-btn>
      </div>
    </div>

    <q-card flat bordered>
      <q-card-section>
        <AuditFiltersBar
          :model-value="filters"
          :actions="actions"
          @update:model-value="onFilters"
        />
      </q-card-section>
      <q-separator />
      <q-table
        v-model:pagination="pagination"
        :rows="rows"
        :columns="columns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[...AUDIT_PAGE_SIZE_OPTIONS]"
        :pagination-label="paginationLabel"
        :no-data-label="noDataLabel"
        class="audit-table"
        @request="onRequest"
        @row-click="(_evt, row) => openEntry(row)"
      >
        <template #body-cell-at="props">
          <q-td :props="props" class="text-no-wrap">{{ formatDateTime(props.value) }}</q-td>
        </template>

        <template #body-cell-action="props">
          <q-td :props="props">
            {{ auditActionLabel(props.value) }}
            <q-tooltip>{{ props.value }}</q-tooltip>
          </q-td>
        </template>

        <template #body-cell-resource="props">
          <q-td :props="props">
            {{ auditResourceTypeLabel(props.row.resource_type) }}
            <template v-if="props.row.resource_id">
              <!-- The fiche of a poste is the next click; `.stop` so following
                   the link does not also open the details. -->
              <router-link
                v-if="auditResourceLink(props.row.resource_type, props.row.resource_id)"
                :to="auditResourceLink(props.row.resource_type, props.row.resource_id)!"
                class="audit-id q-ml-xs"
                @click.stop
              >
                {{ shortId(props.row.resource_id) }}
              </router-link>
              <span v-else class="audit-id q-ml-xs">{{ shortId(props.row.resource_id) }}</span>
              <q-tooltip>{{ props.row.resource_id }}</q-tooltip>
            </template>
          </q-td>
        </template>

        <template #body-cell-summary="props">
          <q-td :props="props" class="audit-summary">{{ props.value }}</q-td>
        </template>

        <template #body-cell-open="props">
          <q-td :props="props" class="text-right">
            <q-btn
              flat
              dense
              round
              icon="visibility"
              aria-label="Voir le détail"
              @click.stop="openEntry(props.row)"
            >
              <q-tooltip>Voir le détail</q-tooltip>
            </q-btn>
          </q-td>
        </template>
      </q-table>
    </q-card>

    <AuditDetailsDialog
      v-model="detailsOpen"
      :entry="selected"
      @filter-resource="onFilterResource"
    />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import AuditDetailsDialog from 'src/components/audit/AuditDetailsDialog.vue';
import AuditFiltersBar from 'src/components/audit/AuditFiltersBar.vue';
import { listAudit, listAuditActions, type AuditEntry } from 'src/services/audit';
import { apiErrorMessage } from 'src/services/errors';
import {
  AUDIT_ACTION_LABELS,
  auditActionLabel,
  auditDetailsSummary,
  auditResourceLink,
  auditResourceTypeLabel,
  isUuid,
} from 'src/utils/auditLabels';
import {
  AUDIT_DEFAULT_PAGE_SIZE,
  AUDIT_PAGE_SIZE_OPTIONS,
  auditListParams,
  auditQueryFromState,
  auditStateFromQuery,
  emptyAuditFilters,
  hasAuditFilters,
  readerTimeZone,
  type AuditFilters,
} from 'src/utils/auditQuery';
import { formatDateTime } from 'src/utils/format';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();

// Read once: the period's days are turned into instants in this zone, and the
// header says which one, so "du 1er au 30" means what the reader thinks.
const timeZone = readerTimeZone();

const rows = ref<AuditEntry[]>([]);
const loading = ref(false);
const loadFailed = ref(false);
const filters = ref<AuditFilters>(emptyAuditFilters());
const pagination = ref({ page: 1, rowsPerPage: AUDIT_DEFAULT_PAGE_SIZE, rowsNumber: 0 });

// Offered by the action filter: what the log actually holds. Until it answers
// (or if it fails) the known catalogue stands in — the filter keeps working.
const actions = ref<string[]>(Object.keys(AUDIT_ACTION_LABELS));

const columns: QTableColumn<AuditEntry>[] = [
  { name: 'at', label: 'Date', field: 'at', align: 'left' },
  { name: 'actor', label: 'Auteur', field: 'actor', align: 'left' },
  { name: 'action', label: 'Action', field: 'action', align: 'left' },
  { name: 'resource', label: 'Ressource', field: 'resource_type', align: 'left' },
  {
    name: 'summary',
    label: 'Détails',
    field: (row) => auditDetailsSummary(row.action, row.details),
    align: 'left',
  },
  { name: 'open', label: '', field: 'id', align: 'right' },
];

const noDataLabel = computed(() =>
  loadFailed.value
    ? 'Impossible de charger le journal.'
    : hasAuditFilters(filters.value)
      ? 'Aucune action ne correspond à ces filtres.'
      : "Aucune action administrative enregistrée pour l'instant.",
);

// Le pack de langue français écrit « 1-50 sur N » avec un trait d'union ; le
// journal garde le tiret demi-cadratin, qui est le signe d'un intervalle. Les
// autres libellés du tableau (lignes par page, chargement) viennent du pack.
function paginationLabel(first: number, end: number, total: number): string {
  return `${first}–${end} sur ${total}`;
}

/** A UUID shortened to its first block — the tooltip carries the whole id. */
function shortId(id: string): string {
  return isUuid(id) ? `${id.slice(0, 8)}…` : id;
}

/** Read the filters and page from the URL. */
function applyQuery() {
  const state = auditStateFromQuery(route.query);
  filters.value = state.filters;
  pagination.value = { ...pagination.value, page: state.page, rowsPerPage: state.pageSize };
}

// The URL is the single source of truth: the filters and the table write into
// it, and the reload happens in the route watcher — so a pasted link, a filter
// change and a page turn all take the same path.
function pushQuery() {
  void router.replace({
    query: auditQueryFromState({
      filters: filters.value,
      page: pagination.value.page,
      pageSize: pagination.value.rowsPerPage,
    }),
  });
}

/** A filter change starts a new search: page 1 of it. */
function onFilters(next: AuditFilters) {
  filters.value = next;
  pagination.value = { ...pagination.value, page: 1 };
  pushQuery();
}

function onRequest(evt: { pagination: { page?: number; rowsPerPage?: number } }) {
  pagination.value = {
    ...pagination.value,
    page: evt.pagination.page ?? 1,
    rowsPerPage: evt.pagination.rowsPerPage ?? AUDIT_DEFAULT_PAGE_SIZE,
  };
  pushQuery();
}

watch(
  () => route.query,
  () => {
    // Leaving for a fiche changes the query too; that is not ours to read.
    if (route.name !== 'audit') return;
    applyQuery();
    void load();
  },
);

// Which fetch is the current one: a page turn issued while the previous one is
// still in the air must not have its rows overwritten by the slower answer.
let requestId = 0;

async function load() {
  const id = ++requestId;
  loading.value = true;
  try {
    const p = pagination.value;
    const data = await listAudit(
      auditListParams({ filters: filters.value, page: p.page, pageSize: p.rowsPerPage }, timeZone),
    );
    if (id !== requestId) return;
    loadFailed.value = false;
    if (!data.items.length && data.total > 0 && p.page > 1) {
      // A URL pointing past the end: fall back on the last page that exists.
      pagination.value = { ...pagination.value, page: Math.ceil(data.total / p.rowsPerPage) };
      pushQuery();
      return;
    }
    rows.value = data.items;
    pagination.value = { ...pagination.value, rowsNumber: data.total };
  } catch (e) {
    if (id !== requestId) return;
    loadFailed.value = true;
    rows.value = [];
    pagination.value = { ...pagination.value, rowsNumber: 0 };
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec du chargement du journal') });
  } finally {
    if (id === requestId) loading.value = false;
  }
}

async function loadActions() {
  try {
    const slugs = await listAuditActions();
    if (slugs.length) actions.value = slugs;
  } catch {
    // The catalogue already stands in; the table's own load reports errors.
  }
}

const selected = ref<AuditEntry | null>(null);
const detailsOpen = ref(false);

function openEntry(entry: AuditEntry) {
  selected.value = entry;
  detailsOpen.value = true;
}

/** « Toutes les actions sur cette ressource »: that id, every action, any author or date. */
function onFilterResource(resourceType: string, resourceId: string) {
  onFilters({ ...emptyAuditFilters(), resourceType, resourceId });
}

onMounted(() => {
  applyQuery();
  void load();
  void loadActions();
});
</script>

<style scoped>
.audit-table :deep(tbody tr) {
  cursor: pointer;
}
.audit-id {
  font-family: monospace;
  font-size: 12px;
}
.audit-summary {
  white-space: normal;
  min-width: 220px;
}
</style>
