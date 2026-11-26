<template>
  <div>
    <div class="row items-center q-mb-sm">
      <div class="text-caption text-muted col">{{ t('trends.failures.caption') }}</div>
      <q-btn-toggle
        v-model="by"
        no-caps
        unelevated
        dense
        toggle-color="primary"
        class="q-ml-md"
        :options="byOptions"
        data-test="failures-by"
      />
    </div>
    <LoadErrorBanner
      v-if="loadError"
      :error="loadError"
      :loading="loading"
      :fallback="t('trends.failures.loadFailed')"
      @retry="load"
    />
    <q-table
      v-else
      flat
      bordered
      dense
      :rows="rows"
      :columns="columns"
      :row-key="rowKey"
      :loading="loading"
      :pagination="{ rowsPerPage: 0 }"
      hide-pagination
      :no-data-label="t('trends.failures.empty')"
      data-test="failures-table"
    >
      <template #body-cell-name="cell">
        <q-td :props="cell">
          <router-link v-if="linkOf(cell.row)" :to="linkOf(cell.row)!" class="row-link">
            {{ nameOf(cell.row) }}
          </router-link>
          <span v-else :class="{ 'text-muted': isAnonymous(cell.row) }">{{
            nameOf(cell.row)
          }}</span>
        </q-td>
      </template>
    </q-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import type { QTableColumn } from 'quasar';
import type { RouteLocationRaw } from 'vue-router';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import { getRecurringFailures, type FailureGrouping, type FailureRow } from 'src/services/trends';
import { formatDateTime, frNumber } from 'src/utils/format';

/**
 * The « incident » interventions of the period, by model or by room, against
 * the size of that model's or room's parc. A row opens the list of postes it
 * counts — except « unknown model », « no room » and the anonymous row of the
 * rooms outside the reader's scope, which the list cannot filter on.
 */
const props = defineProps<{ months: number }>();

const by = ref<FailureGrouping>('hw_model');
const rows = ref<FailureRow[]>([]);
const loading = ref(false);
const loadError = ref<unknown>(null);

const byOptions = computed(() => [
  { label: t('trends.failures.byModel'), value: 'hw_model' },
  { label: t('trends.failures.byRoom'), value: 'room' },
]);

function nameOf(row: FailureRow): string {
  if (by.value === 'hw_model') return row.hw_model ?? t('trends.failures.unknownModel');
  if (row.out_of_scope) return t('trends.failures.otherRoom');
  if (!row.room_id) return t('trends.failures.noRoom');
  const room = row.room_name ?? '—';
  return row.building_name ? `${row.building_name} — ${room}` : room;
}

function isAnonymous(row: FailureRow): boolean {
  return by.value === 'hw_model' ? !row.hw_model : !row.room_id;
}

function linkOf(row: FailureRow): RouteLocationRaw | null {
  if (by.value === 'hw_model') {
    // The list matches a model from its URL exactly (`machineQuery.ts`).
    return row.hw_model ? { name: 'machines', query: { hw_model: row.hw_model } } : null;
  }
  return row.room_id && !row.out_of_scope
    ? { name: 'machines', query: { room: row.room_id } }
    : null;
}

function rowKey(row: FailureRow): string {
  if (by.value === 'hw_model') return `m:${row.hw_model ?? ''}`;
  return row.out_of_scope ? 'r:other' : `r:${row.room_id ?? ''}`;
}

/** Nulls last whichever the direction: an empty parc is not a rate. */
function nullsLast(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a - b;
}

const columns = computed<QTableColumn<FailureRow>[]>(() => [
  {
    name: 'name',
    label:
      by.value === 'hw_model'
        ? t('trends.failures.columns.model')
        : t('trends.failures.columns.room'),
    field: (r) => nameOf(r),
    align: 'left',
    sortable: true,
  },
  {
    name: 'incidents',
    label: t('trends.failures.columns.incidents'),
    field: 'incidents',
    sortable: true,
  },
  {
    name: 'machines',
    label: t('trends.failures.columns.machines'),
    field: 'machines',
    sortable: true,
  },
  { name: 'parc', label: t('trends.failures.columns.parc'), field: 'parc', sortable: true },
  {
    name: 'per_100',
    label: t('trends.failures.columns.per100'),
    field: 'per_100',
    sortable: true,
    sort: (a: number | null, b: number | null) => nullsLast(a, b),
    format: (v: number | null) => (v === null ? '—' : frNumber(v, 1)),
  },
  {
    name: 'retired_incidents',
    label: t('trends.failures.columns.retiredIncidents'),
    field: 'retired_incidents',
    sortable: true,
    classes: 'text-muted',
  },
  {
    name: 'retired_machines',
    label: t('trends.failures.columns.retiredMachines'),
    field: 'retired_machines',
    sortable: true,
    classes: 'text-muted',
  },
  {
    name: 'last_at',
    label: t('trends.failures.columns.lastAt'),
    field: 'last_at',
    sortable: true,
    format: (v: string | null) => formatDateTime(v),
  },
]);

// Each load is numbered: a late answer to an earlier grouping or period is
// dropped rather than shown under the toggle now chosen.
let loadSeq = 0;

async function load(): Promise<void> {
  const seq = ++loadSeq;
  loading.value = true;
  try {
    const answer = await getRecurringFailures({ months: props.months, by: by.value });
    if (seq !== loadSeq) return;
    rows.value = answer;
    loadError.value = null;
  } catch (e) {
    if (seq !== loadSeq) return;
    loadError.value = e;
    rows.value = [];
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

// Rows of the other grouping, or its failure, are not shown under this one
// while it loads.
watch(by, () => {
  rows.value = [];
  loadError.value = null;
});
watch([by, () => props.months], () => void load());
onMounted(load);

defineExpose({ load });
</script>
