<template>
  <q-card v-if="updates.length" flat bordered class="q-mt-md">
    <q-card-section class="text-subtitle1">
      {{ t('machine.pendingUpdates.title') }}
      <div class="text-caption text-muted">
        {{ t('machine.pendingUpdates.readAt')
        }}<template v-if="machine.wu_last_search">
          ({{ formatDateTime(machine.wu_last_search) }})</template
        >
        {{ t('machine.pendingUpdates.searchHint') }}
      </div>
    </q-card-section>
    <q-separator />
    <q-table
      :rows="updates"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      :rows-per-page-options="[10, 25, 50]"
      :no-data-label="t('machine.pendingUpdates.none')"
    >
      <template #body-cell-severity="cell">
        <q-td :props="cell">
          <q-badge :color="wuSeverityColor(cell.value)">
            {{ wuSeverityLabel(cell.value) }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-type="cell">
        <q-td :props="cell">{{ wuTypeLabel(cell.value) }}</q-td>
      </template>
      <template #body-cell-size_mb="cell">
        <q-td :props="cell">
          {{ wuSizeLabel(cell.value) }}
          <q-tooltip v-if="cell.value != null">
            {{ t('machine.pendingUpdates.sizeTooltip') }}
          </q-tooltip>
        </q-td>
      </template>
      <template #body-cell-is_downloaded="cell">
        <q-td :props="cell">
          <q-icon
            :name="cell.value ? 'download_done' : 'cloud_download'"
            :color="cell.value ? 'positive' : 'grey-6'"
          />
          <q-tooltip>
            {{
              cell.value
                ? t('machine.pendingUpdates.downloaded')
                : t('machine.pendingUpdates.toDownload')
            }}
          </q-tooltip>
        </q-td>
      </template>
      <template #body-cell-first_seen="cell">
        <q-td :props="cell">{{ formatDateTime(cell.value) }}</q-td>
      </template>
    </q-table>
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';
import type { QTableColumn } from 'quasar';
import type { MachineDetail, PendingUpdate } from 'src/services/machines';
import {
  formatDateTime,
  wuSeverityColor,
  wuSeverityLabel,
  wuSizeLabel,
  wuTypeLabel,
} from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail; loading: boolean }>();

const updates = computed<PendingUpdate[]>(() => props.machine.pending_updates ?? []);

// A computed: the headers follow the language when it changes.
const columns = computed<QTableColumn<PendingUpdate>[]>(() => [
  {
    name: 'kb',
    label: t('machine.pendingUpdates.columns.kb'),
    field: 'kb',
    align: 'left',
    format: (v: string | null) => v ?? '—',
  },
  {
    name: 'title',
    label: t('machine.pendingUpdates.columns.title'),
    field: 'title',
    align: 'left',
  },
  // Sortable, but the server already returns them critical-first: MSRC's own
  // vocabulary sorts alphabetically as critical < important < low < moderate,
  // which is worse than useless, so the default order is the one to trust.
  {
    name: 'severity',
    label: t('machine.pendingUpdates.columns.severity'),
    field: 'severity',
    align: 'left',
  },
  {
    name: 'type',
    label: t('machine.pendingUpdates.columns.type'),
    field: 'type',
    align: 'left',
    sortable: true,
  },
  // "max." and not "Taille": WUA reports a ceiling, not a measurement — see
  // wuSizeLabel. The header carries the caveat so the cells do not have to.
  {
    name: 'size_mb',
    label: t('machine.pendingUpdates.columns.size'),
    field: 'size_mb',
    align: 'right',
    sortable: true,
  },
  {
    name: 'is_downloaded',
    label: t('machine.pendingUpdates.columns.downloaded'),
    field: 'is_downloaded',
    align: 'center',
  },
  // How long this machine has been sitting on the update — the column that
  // turns a list of KBs into "this poste has been behind since June".
  {
    name: 'first_seen',
    label: t('machine.pendingUpdates.columns.firstSeen'),
    field: 'first_seen',
    align: 'left',
    sortable: true,
  },
]);
</script>
