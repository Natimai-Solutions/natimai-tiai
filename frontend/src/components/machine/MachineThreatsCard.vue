<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="text-subtitle1">{{ t('machine.threats.title') }}</q-card-section>
    <q-separator />
    <q-card-section v-if="failed" class="q-pa-sm">
      <CardLoadError
        :what="t('machine.threats.what')"
        :loading="loading"
        @retry="emit('refresh')"
      />
    </q-card-section>
    <q-table
      v-model:pagination="pagination"
      :rows="threats"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      :rows-per-page-options="[10, 25, 50]"
      :no-data-label="failed ? t('machine.threats.notLoaded') : t('machine.threats.none')"
      @request="onRequest"
    >
      <template #body-cell-severity="props">
        <q-td :props="props">
          <q-badge :color="threatSeverityColor(props.value)">
            {{ threatSeverityLabel(props.value) }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="threatStatusColor(props.value)">
            {{ threatStatusLabel(props.value) }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-detected_at="props">
        <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
      </template>
    </q-table>
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { QTableColumn } from 'quasar';
import { t } from 'src/i18n';
import CardLoadError from 'src/components/CardLoadError.vue';
import { DEFAULT_PAGE_SIZE, type TablePagination } from './types';
import type { Threat } from 'src/services/threats';
import {
  formatDateTime,
  threatSeverityColor,
  threatSeverityLabel,
  threatStatusColor,
  threatNameLabel,
  threatStatusLabel,
} from 'src/utils/format';

/** `failed`: the last read of this list failed — the rows, if any, are an earlier read's. */
defineProps<{ threats: Threat[]; loading: boolean; failed?: boolean }>();

const pagination = defineModel<TablePagination>('pagination', { required: true });

// The page is turned here, then the page owner refetches: the card holds the
// state QTable writes to, the page holds the request that goes with it.
const emit = defineEmits<{ refresh: [] }>();

// A computed: the headers follow the language when it changes.
const columns = computed<QTableColumn<Threat>[]>(() => [
  {
    name: 'threat_name',
    label: t('machine.threats.columns.name'),
    field: 'threat_name',
    align: 'left',
    format: (v: string | null) => threatNameLabel(v),
    classes: 'cell-wrap',
  },
  {
    name: 'severity',
    label: t('machine.threats.columns.severity'),
    field: 'severity',
    align: 'left',
  },
  { name: 'status', label: t('machine.threats.columns.status'), field: 'status', align: 'left' },
  {
    name: 'detected_at',
    label: t('machine.threats.columns.detectedAt'),
    field: 'detected_at',
    align: 'left',
  },
]);

/** Turn a page of the threat history (server-side). */
function onRequest(evt: { pagination: { page?: number; rowsPerPage?: number } }) {
  pagination.value = {
    ...pagination.value,
    page: evt.pagination.page ?? 1,
    rowsPerPage: evt.pagination.rowsPerPage ?? DEFAULT_PAGE_SIZE,
  };
  emit('refresh');
}
</script>
