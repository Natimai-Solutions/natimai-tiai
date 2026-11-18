<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="text-subtitle1">{{ t('commands.card.title') }}</q-card-section>
    <q-separator />
    <q-card-section v-if="failed" class="q-pa-sm">
      <CardLoadError :what="t('commands.card.what')" :loading="loading" @retry="emit('refresh')" />
    </q-card-section>
    <q-table
      v-model:pagination="pagination"
      :rows="commands"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      :rows-per-page-options="[10, 25, 50]"
      :no-data-label="failed ? t('commands.card.notLoaded') : t('commands.card.empty')"
      @request="onRequest"
    >
      <template #body-cell-type="props">
        <q-td :props="props" class="cell-wrap">{{ commandRowLabel(props.row) }}</q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="statusColor(props.value)">{{ statusLabel(props.value) }}</q-badge>
          <q-btn
            v-if="props.row.result_output"
            :aria-label="t('commands.card.showOutput')"
            flat
            dense
            round
            size="sm"
            icon="search"
            color="primary"
            class="q-ml-xs"
            @click="emit('show-detail', props.row, 'output')"
          >
            <q-tooltip>{{ t('commands.card.showOutput') }}</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.error"
            :aria-label="t('commands.card.showError')"
            flat
            dense
            round
            size="sm"
            icon="error_outline"
            color="negative"
            class="q-ml-xs"
            @click="emit('show-detail', props.row, 'error')"
          >
            <q-tooltip>{{ t('commands.card.showError') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
      <template #body-cell-created_at="props">
        <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
      </template>
      <template #body-cell-finished_at="props">
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
import { commandRowLabel, commandStatusLabel, type Command } from 'src/services/commands';
import { formatDateTime } from 'src/utils/format';

/** `failed`: the last read of this list failed — the rows, if any, are an earlier read's. */
defineProps<{ commands: Command[]; loading: boolean; failed?: boolean }>();

const pagination = defineModel<TablePagination>('pagination', { required: true });

const emit = defineEmits<{
  refresh: [];
  'show-detail': [command: Command, kind: 'output' | 'error'];
}>();

// A computed: the headers follow a change of language.
const columns = computed<QTableColumn<Command>[]>(() => [
  { name: 'type', label: t('commands.card.columns.type'), field: 'type', align: 'left' },
  { name: 'status', label: t('commands.card.columns.status'), field: 'status', align: 'left' },
  {
    name: 'created_by',
    label: t('commands.card.columns.createdBy'),
    field: 'created_by',
    align: 'left',
  },
  {
    name: 'created_at',
    label: t('commands.card.columns.createdAt'),
    field: 'created_at',
    align: 'left',
  },
  {
    name: 'finished_at',
    label: t('commands.card.columns.finishedAt'),
    field: 'finished_at',
    align: 'left',
  },
]);

const STATUS_COLORS: Record<string, string> = {
  pending: 'grey-7',
  delivered: 'blue-7',
  running: 'blue-7',
  succeeded: 'positive',
  failed: 'negative',
  expired: 'orange',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? 'grey-7';
}

function statusLabel(status: string): string {
  return commandStatusLabel(status);
}

/** Turn a page of the command history (server-side). */
function onRequest(evt: { pagination: { page?: number; rowsPerPage?: number } }) {
  pagination.value = {
    ...pagination.value,
    page: evt.pagination.page ?? 1,
    rowsPerPage: evt.pagination.rowsPerPage ?? DEFAULT_PAGE_SIZE,
  };
  emit('refresh');
}
</script>
