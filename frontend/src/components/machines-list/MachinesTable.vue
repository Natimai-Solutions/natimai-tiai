<template>
  <q-table
    v-model:selected="selected"
    v-model:pagination="pagination"
    :rows="rows"
    :columns="columns"
    row-key="id"
    selection="multiple"
    :loading="loading"
    :rows-per-page-options="[25, 50, 100]"
    binary-state-sort
    @request="(evt) => emit('request', evt)"
    @row-click="(_evt, row, index) => emit('open', row, index)"
  >
    <template #body-cell-hostname="props">
      <q-td :props="props">
        <!-- Leading, so a column of dots reads as one glance down the list. -->
        <q-icon
          :name="onlineIcon(props.row.is_online)"
          :color="onlineColor(props.row.is_online)"
          size="12px"
          class="q-mr-sm"
        >
          <q-tooltip>
            {{ onlineLabel(props.row.is_online) }} — dernier contact
            {{ timeAgoLabel(props.row.last_seen) }}
          </q-tooltip>
        </q-icon>
        {{ props.value || props.row.machine_uuid }}
        <q-icon
          v-if="props.row.check_open"
          name="fact_check"
          color="primary"
          size="16px"
          class="q-ml-xs"
        >
          <q-tooltip>
            Vérification demandée{{
              props.row.check_assigned_to
                ? `, affectée à ${props.row.check_assigned_to}`
                : ', à prendre'
            }}
          </q-tooltip>
        </q-icon>
        <q-icon
          v-if="props.row.needs_verification"
          name="warning"
          color="orange"
          size="16px"
          class="q-ml-xs"
        >
          <q-tooltip
            >Identité à confirmer — empreinte matérielle divergente (doublon possible)</q-tooltip
          >
        </q-icon>
      </q-td>
    </template>
    <template #body-cell-maintenance="props">
      <q-td :props="props">
        <q-badge
          v-if="props.row.maintenance_state"
          :color="maintenanceStateColor(props.row.maintenance_state)"
          :label="maintenanceStateLabel(props.row.maintenance_state)"
        >
          <q-tooltip>
            {{
              props.row.maintenance_due_at
                ? `Due le ${formatDateTime(props.row.maintenance_due_at)}`
                : 'Exclu de la maintenance'
            }}
            {{ props.row.maintenance_owner ? ` · ${props.row.maintenance_owner}` : '' }}
          </q-tooltip>
        </q-badge>
      </q-td>
    </template>
    <template #body-cell-room="props">
      <q-td :props="props">
        {{ props.value || '—' }}
        <q-icon
          v-if="props.row.location_mismatch"
          name="wrong_location"
          color="orange"
          size="16px"
          class="q-ml-xs"
        >
          <q-tooltip>
            Emplacement divergent : l'agent déclare « {{ props.row.location }} », la salle est à «
            {{ props.row.room_location }} »
          </q-tooltip>
        </q-icon>
      </q-td>
    </template>
    <template #body-cell-agent="props">
      <q-td :props="props">
        <span :class="{ 'text-grey': !props.value }">{{ props.value ?? '—' }}</span>
        <q-icon
          v-if="isAgentOutdated(props.value, agentLatest)"
          name="system_update_alt"
          color="orange"
          size="16px"
          class="q-ml-xs"
        >
          <q-tooltip>Agent obsolète — référence du parc : {{ agentLatest }}</q-tooltip>
        </q-icon>
      </q-td>
    </template>
    <template #body-cell-antivirus="props">
      <q-td :props="props">
        <q-badge :color="protectionColor(props.row.is_up_to_date)">
          {{ antivirusLabel(props.row.av_product_name) }}
        </q-badge>
        <q-tooltip>{{ antivirusTooltip(props.row) }}</q-tooltip>
      </q-td>
    </template>
    <template #body-cell-windows_update="props">
      <q-td :props="props">
        <q-badge :color="wuPendingColor(props.row.wu_pending_count)">
          {{ wuPendingLabel(props.row.wu_pending_count) }}
        </q-badge>
        <q-icon
          v-if="props.row.wu_reboot_required"
          name="restart_alt"
          color="orange"
          size="18px"
          class="q-ml-xs"
        >
          <q-tooltip>Redémarrage requis</q-tooltip>
        </q-icon>
        <q-tooltip>
          {{
            props.row.wu_pending_count === null
              ? 'Windows Update jamais remonté par l’agent'
              : `${props.row.wu_pending_count} mise(s) à jour en attente`
          }}
        </q-tooltip>
      </q-td>
    </template>
    <!-- A bar and not a figure: the reason to scan this column is to spot the
         postes about to run out, and a bar is read without being parsed. The
         percentage is what colours it — 40 Go left on a 4 To disk and on a
         128 Go SSD are not the same news. -->
    <template #body-cell-disk="props">
      <q-td :props="props">
        <template v-if="props.row.system_volume_total_mb">
          <q-linear-progress
            :value="usedRatio(props.row)"
            :color="
              diskColor(
                freePercent(props.row.system_volume_total_mb, props.row.system_volume_free_mb),
              )
            "
            size="8px"
            rounded
            style="width: 90px"
          />
          <div class="text-caption text-grey">
            {{ sizeLabel(props.row.system_volume_free_mb) }} libres
          </div>
          <q-tooltip>
            {{ sizeLabel(props.row.system_volume_free_mb) }} libres sur
            {{ sizeLabel(props.row.system_volume_total_mb) }}
          </q-tooltip>
        </template>
        <span v-else class="text-grey">—</span>
      </q-td>
    </template>
    <template #body-cell-session="props">
      <q-td :props="props">
        <q-badge :color="sessionColor(props.row.session_user_present)">
          {{ sessionLabel(props.row.session_user_present, props.row.session_username) }}
        </q-badge>
        <q-tooltip>Au dernier contact : {{ formatDateTime(props.row.last_seen) }}</q-tooltip>
      </q-td>
    </template>
    <template #body-cell-usage="props">
      <q-td :props="props">
        <span v-if="props.row.usage_hours === null" class="text-grey">récent</span>
        <span v-else :class="{ 'text-grey': props.row.usage_hours === 0 }">
          {{ hoursLabel(props.row.usage_hours) }}
        </span>
        <q-tooltip>
          {{
            props.row.usage_hours === null
              ? `Enrôlé il y a moins de ${usageWindowDays} jours : pas encore de fenêtre complète`
              : `Allumé ${hoursLabel(props.row.usage_hours)} sur les ${usageWindowDays} derniers jours`
          }}
        </q-tooltip>
      </q-td>
    </template>
    <template #body-cell-last_seen="props">
      <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import type { QTableColumn, QTableProps } from 'quasar';
import type { Machine } from 'src/services/machines';
import { maintenanceStateColor, maintenanceStateLabel } from 'src/services/maintenance';
import { isAgentOutdated } from 'src/utils/agentVersion';
import {
  antivirusLabel,
  diskColor,
  formatDateTime,
  freePercent,
  onlineColor,
  onlineIcon,
  onlineLabel,
  protectionColor,
  sessionColor,
  sessionLabel,
  sizeLabel,
  timeAgoLabel,
  wuPendingColor,
  wuPendingLabel,
} from 'src/utils/format';
import {
  antivirusTooltip,
  usedRatio,
  type MachineListPagination,
} from 'src/utils/machineListTable';
import { hoursLabel } from 'src/utils/usageFilter';

/**
 * The machine list's table: one page of the fleet, a cell per column the
 * reader chose. Sorting and paging are the server's — every interaction comes
 * out as `request`, and the page writes it into the URL.
 */
defineProps<{
  rows: Machine[];
  /** The visible columns, in the reader's order. */
  columns: QTableColumn<Machine>[];
  loading: boolean;
  /** The agent version rows are flagged against, as the list response carries it. */
  agentLatest: string | null;
  /** The usage window the server answered with, in days. */
  usageWindowDays: number;
}>();

const selected = defineModel<Machine[]>('selected', { required: true });
const pagination = defineModel<MachineListPagination>('pagination', { required: true });

const emit = defineEmits<{
  request: [evt: Parameters<NonNullable<QTableProps['onRequest']>>[0]];
  /** A row clicked, with its index on the current page. */
  open: [row: Machine, index: number];
}>();
</script>
