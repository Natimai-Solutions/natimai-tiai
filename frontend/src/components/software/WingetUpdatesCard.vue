<template>
  <div>
    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />
    <q-card flat bordered>
      <q-card-section class="text-caption text-muted">
        <span v-if="loaded && !reporting" data-test="winget-none-reporting">
          {{ t('compliance.updates.noneReporting') }}
        </span>
        <span v-else>{{ t('compliance.updates.caption', { reporting }) }}</span>
      </q-card-section>
      <q-card-section class="row items-center q-col-gutter-md q-pt-none">
        <div class="col-12 col-sm">
          <q-input
            v-model="search"
            :aria-label="t('compliance.updates.search')"
            :placeholder="t('compliance.updates.search')"
            dense
            outlined
            clearable
            debounce="300"
            @update:model-value="load"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </div>
        <div class="col-auto">
          <q-toggle
            v-model="outdatedOnly"
            :label="t('compliance.updates.outdatedOnly')"
            @update:model-value="load"
          />
        </div>
      </q-card-section>
      <q-separator />
      <q-table
        :rows="items"
        :columns="columns"
        row-key="winget_id"
        :loading="loading"
        flat
        :pagination="{ rowsPerPage: 50 }"
        :rows-per-page-options="[25, 50, 100, 0]"
        :no-data-label="t('compliance.updates.empty')"
      >
        <template #body-cell-name="props">
          <q-td :props="props">
            <div>{{ props.row.name ?? props.row.winget_id }}</div>
            <div class="text-caption text-muted">{{ props.row.winget_id }}</div>
          </q-td>
        </template>
        <template #body-cell-outdated="props">
          <q-td :props="props">
            <q-btn
              v-if="props.row.outdated"
              flat
              dense
              no-caps
              color="negative"
              :label="String(props.row.outdated)"
              :to="{ name: 'machines', query: { winget_outdated: props.row.winget_id } }"
            >
              <q-tooltip>{{ t('compliance.updates.seeMachines') }}</q-tooltip>
            </q-btn>
            <span v-else class="text-muted">0</span>
          </q-td>
        </template>
        <template #body-cell-rate="props">
          <q-td :props="props">
            <q-linear-progress
              :value="props.row.up_to_date_percent / 100"
              :color="props.row.up_to_date_percent >= 90 ? 'positive' : 'warning'"
              size="10px"
              rounded
              class="q-mb-xs"
            />
            {{ frNumber(props.row.up_to_date_percent, 0) }} %
          </q-td>
        </template>
      </q-table>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import type { QTableColumn } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import { listWingetUpdates, type WingetUpdate } from 'src/services/compliance';
import { frNumber } from 'src/utils/format';

const items = ref<WingetUpdate[]>([]);
const reporting = ref(0);
const search = ref<string | null>('');
const outdatedOnly = ref(true);
const loading = ref(false);
const loaded = ref(false);
const loadError = ref<unknown>(null);

const columns = computed<QTableColumn<WingetUpdate>[]>(() => [
  {
    name: 'name',
    field: 'name',
    label: t('compliance.updates.columns.name'),
    align: 'left',
    sortable: true,
  },
  {
    name: 'installed',
    field: 'installed',
    label: t('compliance.updates.columns.installed'),
    align: 'right',
    sortable: true,
  },
  {
    name: 'outdated',
    field: 'outdated',
    label: t('compliance.updates.columns.outdated'),
    align: 'right',
    sortable: true,
  },
  {
    name: 'available',
    field: 'available',
    label: t('compliance.updates.columns.available'),
    align: 'left',
    format: (v: string | null) => v ?? '—',
  },
  {
    name: 'rate',
    field: 'up_to_date_percent',
    label: t('compliance.updates.columns.rate'),
    align: 'left',
    sortable: true,
  },
]);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const res = await listWingetUpdates({
      ...(search.value ? { search: search.value } : {}),
      outdated_only: outdatedOnly.value,
    });
    items.value = res.items;
    reporting.value = res.reporting;
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  } finally {
    loading.value = false;
    loaded.value = true;
  }
}

onMounted(load);

defineExpose({ load });
</script>
