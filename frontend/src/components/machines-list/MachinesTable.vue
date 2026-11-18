<template>
  <q-table
    v-model:selected="selected"
    v-model:pagination="pagination"
    class="machines-table"
    :rows="rows"
    :columns="columns"
    row-key="id"
    :selection="selectable ? 'multiple' : 'none'"
    :loading="loading"
    :rows-per-page-options="[25, 50, 100]"
    binary-state-sort
    @request="(evt) => emit('request', evt)"
  >
    <template #body-cell-hostname="props">
      <q-td :props="props">
        <!-- A flex row: only the name gives way to the 260 px cap of the
             sticky column, with an ellipsis; the dot before it and the icons
             after it stay in sight however long the name (audit U25). -->
        <div class="machine-name">
          <!-- Leading, so a column of dots reads as one glance down the list. -->
          <q-icon
            :name="onlineIcon(props.row.is_online)"
            :color="onlineColor(props.row.is_online)"
            size="12px"
            class="q-mr-sm"
          >
            <q-tooltip>
              {{
                t('machines.table.onlineHint', {
                  state: onlineLabel(props.row.is_online),
                  ago: timeAgoLabel(props.row.last_seen),
                })
              }}
            </q-tooltip>
          </q-icon>
          <!-- The name is the way into the fiche, and the only one: a link,
               reached with Tab and Enter, opened in a new tab on demand. The
               rest of the row is text to read and to copy (see the script). -->
          <router-link
            v-if="detailRoute"
            :to="detailRoute(props.row, props.pageIndex)"
            class="machine-name__text machine-name__link"
            :title="props.value || props.row.machine_uuid"
          >
            {{ props.value || props.row.machine_uuid }}
          </router-link>
          <span v-else class="machine-name__text" :title="props.value || props.row.machine_uuid">{{
            props.value || props.row.machine_uuid
          }}</span>
          <q-icon
            v-if="props.row.check_open"
            name="fact_check"
            color="primary"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>
              {{
                props.row.check_assigned_to
                  ? t('machines.table.checkAssigned', { name: props.row.check_assigned_to })
                  : t('machines.table.checkUnassigned')
              }}
            </q-tooltip>
          </q-icon>
          <!-- Enrolment needing a decision: a reinstalled poste asking back in,
               or a revoked one (C2). -->
          <q-icon
            v-if="props.row.token_revoked"
            name="key_off"
            color="negative"
            size="16px"
            class="q-ml-xs"
            data-test="token-revoked"
          >
            <q-tooltip>{{ t('machines.table.tokenRevoked') }}</q-tooltip>
          </q-icon>
          <q-icon
            v-else-if="props.row.reenroll_requested"
            name="key"
            color="orange"
            size="16px"
            class="q-ml-xs"
            data-test="reenroll-requested"
          >
            <q-tooltip>{{ t('machines.table.reenrollRequested') }}</q-tooltip>
          </q-icon>
          <q-icon
            v-if="props.row.needs_verification"
            name="warning"
            color="orange"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>{{ t('machines.table.needsVerification') }}</q-tooltip>
          </q-icon>
        </div>
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
                ? t('machines.table.maintenanceDue', {
                    date: dueDate(props.row.maintenance_due_at),
                  })
                : t('machines.table.maintenanceExcluded')
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
            {{
              t('machines.table.locationMismatch', {
                agent: props.row.location,
                room: props.row.room_location,
              })
            }}
          </q-tooltip>
        </q-icon>
      </q-td>
    </template>
    <template #body-cell-agent="props">
      <q-td :props="props">
        <span :class="{ 'text-muted': !props.value }">{{ props.value ?? '—' }}</span>
        <q-icon
          v-if="isAgentOutdated(props.value, agentLatest)"
          name="system_update_alt"
          color="orange"
          size="16px"
          class="q-ml-xs"
        >
          <q-tooltip>{{ t('machines.table.agentOutdated', { version: agentLatest }) }}</q-tooltip>
        </q-icon>
      </q-td>
    </template>
    <template #body-cell-antivirus="props">
      <q-td :props="props">
        <q-badge :color="antivirusBadgeColor(props.row.av_product_name, props.row.is_up_to_date)">
          {{
            protectionBadgeLabel(antivirusLabel(props.row.av_product_name), props.row.is_up_to_date)
          }}
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
          <q-tooltip>{{ t('machines.table.rebootRequired') }}</q-tooltip>
        </q-icon>
        <q-tooltip>
          {{
            props.row.wu_pending_count === null
              ? t('machines.table.wuNever')
              : t(
                  'machines.table.wuPending',
                  { count: props.row.wu_pending_count },
                  props.row.wu_pending_count,
                )
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
                lowDiskPercent,
              )
            "
            size="8px"
            rounded
            style="width: 90px"
          />
          <div class="text-caption text-muted">
            {{ t('machines.table.diskFree', { free: sizeLabel(props.row.system_volume_free_mb) }) }}
          </div>
          <q-tooltip>
            {{
              t('machines.table.diskFreeOf', {
                free: sizeLabel(props.row.system_volume_free_mb),
                total: sizeLabel(props.row.system_volume_total_mb),
              })
            }}
          </q-tooltip>
        </template>
        <span v-else class="text-muted">—</span>
      </q-td>
    </template>
    <template #body-cell-session="props">
      <q-td :props="props">
        <q-badge :color="sessionColor(props.row.session_user_present)">
          {{ sessionLabel(props.row.session_user_present, props.row.session_username) }}
        </q-badge>
        <q-tooltip>
          {{ t('machines.table.sessionAt', { date: formatDateTime(props.row.last_seen) }) }}
        </q-tooltip>
      </q-td>
    </template>
    <template #body-cell-usage="props">
      <q-td :props="props">
        <span v-if="props.row.usage_hours === null" class="text-muted">
          {{ t('machines.table.usageRecent') }}
        </span>
        <span v-else :class="{ 'text-muted': props.row.usage_hours === 0 }">
          {{ hoursLabel(props.row.usage_hours) }}
        </span>
        <q-tooltip>
          {{
            props.row.usage_hours === null
              ? t('machines.table.usageRecentHint', { days: usageWindowDays })
              : t('machines.table.usageHint', {
                  hours: hoursLabel(props.row.usage_hours),
                  days: usageWindowDays,
                })
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
import type { RouteLocationRaw } from 'vue-router';
import { t } from 'src/i18n';
import type { Machine } from 'src/services/machines';
import { dueDate, maintenanceStateColor, maintenanceStateLabel } from 'src/services/maintenance';
import { isAgentOutdated } from 'src/utils/agentVersion';
import {
  antivirusBadgeColor,
  antivirusLabel,
  diskColor,
  formatDateTime,
  freePercent,
  onlineColor,
  onlineIcon,
  onlineLabel,
  protectionBadgeLabel,
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
 *
 * A row does not open on click: the name does, as a link. Rows that opened on
 * click could not let a word be selected by double-click — its first click is
 * a plain click, the fiche was open before any selection existed to tell the
 * two apart, and holding every click back for the length of a double-click
 * would have slowed the plain ones. So the row is text (hostname apart), with
 * nothing to guess: select it, copy it, Ctrl+A it.
 */
withDefaults(
  defineProps<{
    rows: Machine[];
    /** The visible columns, in the reader's order. */
    columns: QTableColumn<Machine>[];
    loading: boolean;
    /** The agent version rows are flagged against, as the list response carries it. */
    agentLatest: string | null;
    /** The usage window the server answered with, in days. */
    usageWindowDays: number;
    /** Where a row's name links to (its fiche); without it, the name is text. */
    detailRoute?: ((row: Machine, index: number) => RouteLocationRaw) | undefined;
    /**
     * Whether rows can be ticked. Only when a bulk action is on offer: a
     * read-only account's checkboxes did nothing but pause the auto-refresh.
     */
    selectable?: boolean;
    /** The parc's « disque presque plein » threshold, for the bars' colour. */
    lowDiskPercent?: number | undefined;
  }>(),
  { selectable: true, lowDiskPercent: undefined, detailRoute: undefined },
);

const selected = defineModel<Machine[]>('selected', { required: true });
const pagination = defineModel<MachineListPagination>('pagination', { required: true });

const emit = defineEmits<{
  request: [evt: Parameters<NonNullable<QTableProps['onRequest']>>[0]];
}>();
</script>

<style scoped>
/* The one thing in the row that opens something: it looks like it. Underlined
   rather than coloured — the primary colour falls short of 4.5:1 on a dark
   card, and the text colour is right in both modes. */
.machine-name__link {
  color: inherit;
  font-weight: 500;
  text-decoration: underline;
  text-underline-offset: 2px;
}
/* On a touch screen, a taller target than the 20 px of the text: the padding
   takes the tap and the negative margin gives the room back, so nothing moves.
   Not a stretched ::after as for .row-link: the name is cut (overflow: hidden)
   and would clip it. */
@media (pointer: coarse) {
  .machine-name__link {
    padding-block: 12px;
    margin-block: -12px;
  }
}
</style>
