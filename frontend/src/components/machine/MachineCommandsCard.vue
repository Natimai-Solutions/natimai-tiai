<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="text-subtitle1">Dernières commandes</q-card-section>
    <q-separator />
    <q-table
      v-model:pagination="pagination"
      :rows="commands"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      :rows-per-page-options="[10, 25, 50]"
      no-data-label="Aucune commande."
      @request="onRequest"
    >
      <template #body-cell-type="props">
        <q-td :props="props">{{ commandTypeLabel(props.value) }}</q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="statusColor(props.value)">{{ statusLabel(props.value) }}</q-badge>
          <q-btn
            v-if="props.row.result_output"
            aria-label="Voir le résultat"
            flat
            dense
            round
            size="sm"
            icon="search"
            color="primary"
            class="q-ml-xs"
            @click="emit('show-detail', props.row, 'output')"
          >
            <q-tooltip>Voir le résultat</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.error"
            aria-label="Voir l'erreur"
            flat
            dense
            round
            size="sm"
            icon="error_outline"
            color="negative"
            class="q-ml-xs"
            @click="emit('show-detail', props.row, 'error')"
          >
            <q-tooltip>Voir l'erreur</q-tooltip>
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
import type { QTableColumn } from 'quasar';
import { DEFAULT_PAGE_SIZE, type TablePagination } from './types';
import { commandTypeLabel, type Command } from 'src/services/commands';
import { formatDateTime } from 'src/utils/format';

defineProps<{ commands: Command[]; loading: boolean }>();

const pagination = defineModel<TablePagination>('pagination', { required: true });

const emit = defineEmits<{
  refresh: [];
  'show-detail': [command: Command, kind: 'output' | 'error'];
}>();

const columns: QTableColumn<Command>[] = [
  { name: 'type', label: 'Type', field: 'type', align: 'left' },
  { name: 'status', label: 'Statut', field: 'status', align: 'left' },
  { name: 'created_by', label: 'Par', field: 'created_by', align: 'left' },
  { name: 'created_at', label: 'Créée le', field: 'created_at', align: 'left' },
  { name: 'finished_at', label: 'Terminée le', field: 'finished_at', align: 'left' },
];

const STATUS_COLORS: Record<string, string> = {
  pending: 'grey-7',
  delivered: 'blue-7',
  running: 'blue-7',
  succeeded: 'positive',
  failed: 'negative',
  expired: 'orange',
};

const STATUS_LABELS: Record<string, string> = {
  pending: 'En attente',
  delivered: 'Transmise',
  running: 'En cours',
  succeeded: 'Réussie',
  failed: 'Échec',
  expired: 'Expirée',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? 'grey-7';
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
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
