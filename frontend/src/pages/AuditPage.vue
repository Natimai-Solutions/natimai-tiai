<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-md">
      <div class="col-auto">
        <h1 class="text-h5 q-my-none">{{ t('audit.page.title') }}</h1>
        <div class="text-caption text-muted">
          {{ t('audit.page.intro', { zone: timeZone }) }}
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
          :aria-label="t('audit.page.refresh')"
          :loading="loading"
          @click="load"
        >
          <q-tooltip>{{ t('audit.page.refresh') }}</q-tooltip>
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
      >
        <template #body-cell-at="props">
          <!-- The date opens the entry: the first column, always in view — the
               eye button at the end of a wide row is off-screen on most
               screens, and the row itself is text to select. -->
          <q-td :props="props" class="text-no-wrap">
            <button
              type="button"
              class="row-link audit-open"
              :title="t('audit.page.viewDetails')"
              @click="openEntry(props.row)"
            >
              {{ formatDateTime(props.value) }}
            </button>
          </q-td>
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
              <router-link
                v-if="auditResourceLink(props.row.resource_type, props.row.resource_id)"
                :to="auditResourceLink(props.row.resource_type, props.row.resource_id)!"
                class="audit-id q-ml-xs"
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
              :aria-label="t('audit.page.viewDetails')"
              @click="openEntry(props.row)"
            >
              <q-tooltip>{{ t('audit.page.viewDetails') }}</q-tooltip>
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
import { t } from 'src/i18n';
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
import { dash, formatDateTime } from 'src/utils/format';
import { notify } from 'src/utils/notify';

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

// A computed: the labels follow the language, which can change on the page.
const columns = computed<QTableColumn<AuditEntry>[]>(() => [
  { name: 'at', label: t('audit.page.columns.at'), field: 'at', align: 'left' },
  { name: 'actor', label: t('audit.page.columns.actor'), field: 'actor', align: 'left' },
  // Hidden on a phone, where the five others already fill the width.
  {
    name: 'ip',
    label: t('audit.page.columns.ip'),
    field: 'ip',
    align: 'left',
    format: (v: string | null | undefined) => dash(v),
    classes: 'gt-xs',
    headerClasses: 'gt-xs',
  },
  { name: 'action', label: t('audit.page.columns.action'), field: 'action', align: 'left' },
  {
    name: 'resource',
    label: t('audit.page.columns.resource'),
    field: 'resource_type',
    align: 'left',
  },
  {
    name: 'summary',
    label: t('audit.page.columns.summary'),
    field: (row) => auditDetailsSummary(row.action, row.details),
    align: 'left',
  },
  { name: 'open', label: '', field: 'id', align: 'right' },
]);

const noDataLabel = computed(() =>
  loadFailed.value
    ? t('audit.page.empty.failed')
    : hasAuditFilters(filters.value)
      ? t('audit.page.empty.filtered')
      : t('audit.page.empty.none'),
);

// Le pack de langue français écrit « 1-50 sur N » avec un trait d'union ; le
// journal garde le tiret demi-cadratin, qui est le signe d'un intervalle. Les
// autres libellés du tableau (lignes par page, chargement) viennent du pack.
function paginationLabel(first: number, end: number, total: number): string {
  return t('audit.page.pagination', { first, end, total });
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
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('audit.page.loadFailed')),
    }));
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

/** The eye button opens an entry's details; the rest of the row is text to
 *  select and copy, double-click included — no row click to guess against. */
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
.audit-open {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  cursor: pointer;
}
.audit-open:focus-visible {
  outline: 2px solid var(--q-primary);
  outline-offset: 2px;
}
.audit-id {
  font-family: monospace;
  font-size: 12px;
}
/* The text colour, underlined, as .row-link: the browser's blue is 1.79:1 on
   a dark card. */
a.audit-id {
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.audit-summary {
  white-space: normal;
  min-width: 220px;
}
</style>
