<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-sm">
      <h1 class="text-h5 q-my-none col-auto">{{ t('schedules.title') }}</h1>
      <q-space />
      <div v-if="canWrite" class="col-auto">
        <q-btn
          outline
          no-caps
          color="primary"
          icon="add"
          :label="t('schedules.newSchedule')"
          @click="openNew()"
        />
      </div>
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          :aria-label="t('schedules.refresh')"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>
    <div class="text-caption text-muted q-mb-md">
      {{ t('schedules.subtitle', { zone: timezone }) }}
    </div>

    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />

    <q-card flat bordered>
      <q-table
        :rows="items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        flat
        :grid="$q.screen.lt.sm"
        :rows-per-page-options="[0]"
        :no-data-label="loadError ? t('schedules.empty.loadFailed') : t('schedules.empty.none')"
      >
        <template #body-cell-name="props">
          <q-td :props="props" style="white-space: normal">
            <div class="text-weight-medium">{{ props.row.name }}</div>
            <div class="text-caption text-muted">{{ props.row.created_by }}</div>
          </q-td>
        </template>
        <template #body-cell-action="props">
          <q-td :props="props" style="white-space: normal">
            {{ actionText(props.row) }}
            <div v-if="optionsText(props.row)" class="text-caption text-muted">
              {{ optionsText(props.row) }}
            </div>
          </q-td>
        </template>
        <template #body-cell-state="props">
          <q-td :props="props" style="white-space: normal; max-width: 260px">
            <q-badge :color="stateColor(props.row.state)">{{
              stateLabel(props.row.state)
            }}</q-badge>
            <div v-if="props.row.state === 'suspended'" class="text-caption text-negative">
              {{ suspendedText(props.row.suspended_code, suspendedParams(props.row)) }}
            </div>
          </q-td>
        </template>
        <template #body-cell-last="props">
          <q-td :props="props" style="white-space: normal; max-width: 280px">
            <template v-if="props.row.last_run">
              <q-badge outline :color="runColor(props.row.last_run.status)">
                {{ runStatusLabel(props.row.last_run.status) }}
              </q-badge>
              <span class="q-ml-xs text-caption">
                {{ runStarted(props.row.last_run) }}
              </span>
              <div class="text-caption text-muted">
                {{ runCauseText(props.row.last_run) || runSummary(props.row.last_run) }}
              </div>
            </template>
            <span v-else>—</span>
          </q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props" auto-width>
            <q-btn
              flat
              dense
              round
              size="sm"
              icon="history"
              :aria-label="t('schedules.actions.runs')"
              @click="openRuns(props.row)"
            />
            <template v-if="canWrite">
              <q-btn
                flat
                dense
                round
                size="sm"
                icon="edit"
                :aria-label="t('schedules.actions.edit')"
                @click="openEdit(props.row)"
              />
              <q-btn
                v-if="props.row.state === 'active'"
                flat
                dense
                round
                size="sm"
                icon="pause"
                :aria-label="t('schedules.actions.disable')"
                @click="toggle(props.row, false)"
              />
              <q-btn
                v-else-if="props.row.state !== 'done'"
                flat
                dense
                round
                size="sm"
                icon="play_arrow"
                :aria-label="t('schedules.actions.enable')"
                @click="toggle(props.row, true)"
              >
                <q-tooltip v-if="props.row.state === 'suspended'">
                  {{ t('schedules.suspended.reenable') }}
                </q-tooltip>
              </q-btn>
              <q-btn
                flat
                dense
                round
                size="sm"
                icon="delete"
                color="negative"
                :aria-label="t('schedules.actions.delete')"
                @click="remove(props.row)"
              />
            </template>
          </q-td>
        </template>
      </q-table>
    </q-card>

    <ScheduleDialog
      v-model="editing"
      :schedule="current"
      :initial-target="initialTarget"
      :timezone="timezone"
      :forbidden-windows="forbiddenWindows"
      @saved="onSaved"
    />

    <q-dialog v-model="runsOpen">
      <q-card style="width: 720px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{ t('schedules.runs.title', { name: current?.name ?? '' }) }}
        </q-card-section>
        <q-card-section v-if="!runs.length" class="text-muted">
          {{ t('schedules.runs.none') }}
        </q-card-section>
        <q-list v-else separator>
          <q-item v-for="run in runs" :key="run.id">
            <q-item-section>
              <q-item-label>
                <q-badge outline :color="runColor(run.status)">{{
                  runStatusLabel(run.status)
                }}</q-badge>
                <span class="q-ml-sm">{{ runStarted(run) }}</span>
                <span v-if="current?.rings" class="q-ml-sm text-caption text-muted">
                  {{ t('schedules.runs.stage', { n: run.stage + 1 }) }}
                </span>
              </q-item-label>
              <q-item-label caption>{{ runSummary(run) }}</q-item-label>
              <q-item-label v-if="runCauseText(run)" caption class="text-negative">
                {{ runCauseText(run) }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
        <q-card-actions align="right">
          <q-btn v-close-popup flat no-caps :label="t('schedules.actions.cancel')" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import ScheduleDialog from 'src/components/schedule/ScheduleDialog.vue';
import { t } from 'src/i18n';
import { commandTypeLabel } from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import {
  deleteSchedule,
  listScheduleRuns,
  listSchedules,
  localText,
  runCauseText,
  runStatusLabel,
  runSummary,
  setScheduleEnabled,
  stateLabel,
  suspendedText,
  targetText,
  whenText,
  type ForbiddenWindow,
  type Schedule,
  type ScheduleRun,
  type ScheduleTargetIn,
} from 'src/services/schedules';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { queryValue } from 'src/utils/machineQuery';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const canWrite = computed(() => auth.can('schedule', 'write'));

/** When a run started, in the console's zone as the schedules are planned;
 * the browser's only for a server that does not send it. */
function runStarted(run: { started_at: string; started_local?: string | null }): string {
  return run.started_local ? localText(run.started_local) : formatDateTime(run.started_at);
}

const items = ref<Schedule[]>([]);
const timezone = ref('UTC');
const forbiddenWindows = ref<ForbiddenWindow[]>([]);
const loading = ref(false);
const loadError = ref<unknown>(null);
const editing = ref(false);
const current = ref<Schedule | null>(null);
const initialTarget = ref<ScheduleTargetIn | null>(null);
const runsOpen = ref(false);
const runs = ref<ScheduleRun[]>([]);

const columns = computed<QTableColumn<Schedule>[]>(() => [
  { name: 'name', label: t('schedules.columns.name'), field: 'name', align: 'left' },
  { name: 'action', label: t('schedules.columns.action'), field: 'command_type', align: 'left' },
  {
    name: 'target',
    label: t('schedules.columns.target'),
    field: (row) => targetText(row.target),
    align: 'left',
    style: 'white-space: normal',
  },
  {
    name: 'when',
    label: t('schedules.columns.when'),
    field: (row) => whenText(row),
    align: 'left',
  },
  {
    name: 'next',
    label: t('schedules.columns.next'),
    field: (row) => localText(row.next_run_local),
    align: 'left',
  },
  { name: 'last', label: t('schedules.columns.last'), field: 'last_run_at', align: 'left' },
  { name: 'state', label: t('schedules.columns.state'), field: 'state', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

function actionText(s: Schedule): string {
  const label = commandTypeLabel(s.command_type);
  return s.package_name ? `${label} — ${s.package_name}` : label;
}

function optionsText(s: Schedule): string {
  const parts: string[] = [];
  if (s.wake_first) parts.push(t('schedules.options.wakeFirst'));
  if (s.shutdown_after) parts.push(t('schedules.options.shutdownAfter'));
  if (s.rings) parts.push(t('schedules.options.rings', { count: s.rings.length }));
  return parts.join(' · ');
}

function suspendedParams(s: Schedule): Record<string, unknown> {
  return s.last_run?.status === 'suspended' ? (s.last_run.result_params ?? {}) : {};
}

function stateColor(state: string): string {
  return state === 'active' ? 'positive' : state === 'suspended' ? 'negative' : 'grey-7';
}

function runColor(status: string): string {
  if (status === 'done') return 'positive';
  if (status === 'running') return 'primary';
  return 'negative';
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const res = await listSchedules({ page_size: 200 });
    items.value = res.items;
    timezone.value = res.timezone;
    forbiddenWindows.value = res.forbidden_windows;
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  } finally {
    loading.value = false;
  }
}

function openNew(target: ScheduleTargetIn | null = null): void {
  current.value = null;
  initialTarget.value = target;
  editing.value = true;
}

function openEdit(s: Schedule): void {
  current.value = s;
  initialTarget.value = null;
  editing.value = true;
}

async function openRuns(s: Schedule): Promise<void> {
  current.value = s;
  runs.value = [];
  runsOpen.value = true;
  try {
    runs.value = (await listScheduleRuns(s.id, { page_size: 50 })).items;
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('schedules.actions.failed')),
    }));
  }
}

async function toggle(s: Schedule, enabled: boolean): Promise<void> {
  try {
    await setScheduleEnabled(s.id, enabled);
    notify($q, () => ({
      type: 'positive',
      message: enabled ? t('schedules.actions.enabled') : t('schedules.actions.disabled'),
    }));
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('schedules.actions.failed')),
    }));
  }
}

function remove(s: Schedule): void {
  liveDialog($q, () => ({
    message: t('schedules.actions.deleteConfirm', { name: s.name }),
    cancel: { flat: true, noCaps: true, label: t('schedules.actions.cancel') },
    ok: { color: 'negative', noCaps: true, label: t('schedules.actions.delete') },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteSchedule(s.id);
        notify($q, () => ({ type: 'positive', message: t('schedules.actions.deleted') }));
        await load();
      } catch (e) {
        notify($q, () => ({
          type: 'negative',
          message: apiErrorMessage(e, t('schedules.actions.failed')),
        }));
      }
    })();
  });
}

async function onSaved(): Promise<void> {
  await load();
}

onMounted(async () => {
  await load();
  // Opened from a room or a selection: « Planifier » goes straight to the
  // form, aimed at it. The address is cleaned so a reload does not reopen it — before
  // the form opens, which a change of route would close.
  const room = queryValue(route.query.room);
  const machines = queryValue(route.query.machines);
  if (canWrite.value && (room || machines)) {
    // The address first: a dialog open when the route changes is closed by
    // Quasar (`no-route-dismiss`).
    await router.replace({ query: {} });
    openNew(
      room
        ? { kind: 'room', value: room }
        : { kind: 'machines', machine_ids: (machines ?? '').split(',').filter(Boolean) },
    );
  }
});
</script>
