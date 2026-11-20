<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <h1 class="text-h5 q-my-none col-auto">{{ t('tasks.title') }}</h1>
      <q-space />
      <!-- Wrapped in its own column: the gutter pads every direct child of the
           row, and on a toggle that padding showed as a white band inside the
           frame, so the selected button never filled it. -->
      <div class="col-auto">
        <q-btn-toggle
          v-model="scope"
          dense
          no-caps
          unelevated
          toggle-color="primary"
          :options="scopeOptions"
          @update:model-value="reload"
        />
      </div>
    </div>

    <div class="text-body2 text-muted q-mb-md" style="max-width: 760px">
      {{ t('tasks.intro') }}
    </div>
    <!-- Each section for who may read it: an account that only holds the
         maintenance (no check:read) is sent here by its reminders too. -->
    <div v-if="canReadChecks" class="row items-center q-mb-sm">
      <div class="text-h6">{{ t('tasks.checks.title') }}</div>
      <q-space />
      <div v-if="!loading" class="text-caption text-muted" data-test="checks-total">
        {{ t('tasks.checks.total', { count: checksTotal }, checksTotal) }}
      </div>
    </div>

    <q-table
      v-if="canReadChecks"
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[0]"
      hide-pagination
      flat
      bordered
      :no-data-label="t('tasks.checks.nothing')"
      :grid="$q.screen.lt.sm"
    >
      <!-- On a phone, a card per check with « Clore » in sight, rather than
           a table to scroll sideways (audit U23). -->
      <template #item="props">
        <div class="col-12 q-pa-xs">
          <q-card flat bordered>
            <q-card-section class="q-pb-xs">
              <router-link
                :to="{ name: 'machine-detail', params: { id: props.row.machine_id } }"
                class="row-link text-weight-medium"
              >
                {{ props.row.machine?.hostname ?? t('tasks.checks.machine') }}
              </router-link>
              <div class="text-caption text-muted">{{ placeLabel(props.row.machine) }}</div>
              <div class="q-mt-xs" style="white-space: pre-line">
                {{ checkInstructionsText(props.row) || '—' }}
              </div>
              <div class="text-caption text-muted q-mt-xs">
                {{
                  effectiveAssignee(props.row.assigned_to)
                    ? props.row.assigned_to!.name
                    : formerAssigneeNote(props.row.assigned_to)
                      ? t('tasks.checks.toTakeWhy', {
                          why: formerAssigneeNote(props.row.assigned_to),
                        })
                      : t('tasks.checks.toTake')
                }}
                ·
                {{ timeAgoLabel(props.row.created_at) }}
              </div>
            </q-card-section>
            <q-card-actions v-if="canWrite" align="right">
              <q-btn
                v-if="!props.row.assigned_to || props.row.assigned_to.id !== auth.user?.id"
                flat
                dense
                no-caps
                :label="t('tasks.checks.takeOver')"
                @click="takeOver(props.row)"
              />
              <q-btn
                flat
                dense
                no-caps
                :label="t('tasks.checks.edit')"
                @click="openEdit(props.row)"
              />
              <q-btn
                unelevated
                dense
                no-caps
                color="primary"
                icon="task_alt"
                :label="t('tasks.checks.close')"
                @click="openClose(props.row)"
              />
            </q-card-actions>
          </q-card>
        </div>
      </template>
      <template #body-cell-machine="props">
        <q-td :props="props">
          <div>
            <router-link
              :to="{ name: 'machine-detail', params: { id: props.row.machine_id } }"
              class="row-link"
            >
              {{ props.row.machine?.hostname ?? t('tasks.checks.machine') }}
            </router-link>
          </div>
          <div class="text-caption text-muted" style="white-space: normal; max-width: 280px">
            {{ placeLabel(props.row.machine) }}
          </div>
        </q-td>
      </template>
      <template #body-cell-instructions="props">
        <q-td :props="props" style="white-space: pre-line; min-width: 280px; max-width: 420px">
          <div class="q-gutter-xs q-mb-xs">
            <q-badge
              v-if="props.row.priority && props.row.priority !== 'normal'"
              :color="priorityColor(props.row.priority)"
            >
              {{ t(`checks.priority.${props.row.priority}`) }}
            </q-badge>
            <q-badge v-if="props.row.category" outline color="primary">
              {{ t(`checks.category.${props.row.category}`) }}
            </q-badge>
            <q-badge
              v-if="props.row.due_date"
              outline
              :color="isOverdue(props.row.due_date) ? 'negative' : 'grey-7'"
            >
              {{
                isOverdue(props.row.due_date)
                  ? t('checks.overdue', { date: formatDate(props.row.due_date) })
                  : t('checks.due', { date: formatDate(props.row.due_date) })
              }}
            </q-badge>
            <q-badge v-if="props.row.report_id" outline color="orange-8">
              {{ t('checks.fromReport') }}
            </q-badge>
          </div>
          {{ props.value || '—' }}
        </q-td>
      </template>
      <template #body-cell-assigned_to="props">
        <q-td :props="props">
          <span v-if="effectiveAssignee(props.row.assigned_to)">
            {{ props.row.assigned_to.name }}
          </span>
          <template v-else>
            <q-badge color="grey-6">{{ t('tasks.checks.toTake') }}</q-badge>
            <div v-if="formerAssigneeNote(props.row.assigned_to)" class="text-caption text-muted">
              {{ formerAssigneeNote(props.row.assigned_to) }}
            </div>
          </template>
        </q-td>
      </template>
      <template #body-cell-created_at="props">
        <q-td :props="props">
          {{ timeAgoLabel(props.value) }}
          <div class="text-caption text-muted">
            {{ t('tasks.checks.by', { name: props.row.requested_by }) }}
          </div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right" @click.stop>
          <template v-if="canWrite">
            <q-btn
              flat
              dense
              color="primary"
              :label="t('tasks.checks.close')"
              icon="task_alt"
              class="q-mr-xs"
              @click="openClose(props.row)"
            />
            <q-btn flat dense round icon="more_vert" :aria-label="t('tasks.checks.moreActions')">
              <q-menu>
                <q-list style="min-width: 200px">
                  <q-item
                    v-if="!props.row.assigned_to || props.row.assigned_to.id !== auth.user?.id"
                    v-close-popup
                    clickable
                    @click="takeOver(props.row)"
                  >
                    <q-item-section avatar><q-icon name="person" /></q-item-section>
                    <q-item-section>{{ t('tasks.checks.takeOver') }}</q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable @click="openEdit(props.row)">
                    <q-item-section avatar><q-icon name="edit" /></q-item-section>
                    <q-item-section>{{ t('tasks.checks.reassign') }}</q-item-section>
                  </q-item>
                </q-list>
              </q-menu>
            </q-btn>
          </template>
        </q-td>
      </template>
    </q-table>

    <!-- Maintenance: rooms with something due, then the loose postes. -->
    <div v-if="auth.can('maintenance', 'read')" :class="canReadChecks ? 'q-mt-xl' : ''">
      <div class="row items-center q-mb-sm">
        <div class="text-h6">{{ t('tasks.maintenance.title') }}</div>
        <q-space />
        <div v-if="due" class="text-caption text-muted">
          {{ t('tasks.maintenance.counts', { overdue: due.overdue, dueSoon: due.due_soon }) }}
        </div>
      </div>
      <q-list v-if="due && (dueRooms.length || dueMachines.length)" bordered separator>
        <q-expansion-item
          v-for="r in dueRooms"
          :key="r.key ?? r.id"
          :label="r.name"
          group="rooms"
          expand-separator
        >
          <template #header>
            <q-item-section>
              <q-item-label>
                <span v-if="r.building_name" class="text-muted">{{ r.building_name }} › </span
                >{{ r.name }}
              </q-item-label>
              <q-item-label caption>
                {{
                  t(
                    'tasks.maintenance.summary',
                    {
                      count: r.total,
                      days: r.cycle_days,
                      owner: r.owner ? r.owner.name : t('tasks.maintenance.noOwner'),
                    },
                    r.total,
                  )
                }}
                {{ r.next_due_at ? ` · ${dueLabel(r.next_due_at)}` : '' }}
              </q-item-label>
              <!-- Postes whose own owner or cycle overrides the room's: their
                   group says what they resolve to, not the room's. -->
              <q-item-label v-if="r.level === 'machine'" caption class="text-italic">
                {{ t('tasks.maintenance.ownSettings') }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <div>
                <q-badge v-if="r.overdue" color="negative" class="q-mr-xs">{{
                  t('tasks.maintenance.overdue', { count: r.overdue })
                }}</q-badge>
                <q-badge v-if="r.due_soon" color="orange" class="q-mr-xs">{{
                  t('tasks.maintenance.dueSoon', { count: r.due_soon })
                }}</q-badge>
                <q-badge v-if="!r.overdue && !r.due_soon" color="positive">{{
                  t('tasks.maintenance.upToDate')
                }}</q-badge>
              </div>
            </q-item-section>
          </template>
          <q-card>
            <q-card-section class="q-pt-none">
              <div class="row q-mb-sm">
                <q-space />
                <!-- Taking a room, or handing it on, from here as for a
                     check (audit U18). -->
                <template v-if="canMaintain">
                  <q-btn
                    v-if="r.owner?.id !== auth.user?.id"
                    flat
                    dense
                    no-caps
                    icon="person"
                    :label="t('tasks.maintenance.takeOver')"
                    class="q-mr-sm"
                    @click="takeRoom(r)"
                  />
                  <q-btn
                    v-if="r.level !== 'machine'"
                    flat
                    dense
                    no-caps
                    icon="forward"
                    :label="t('tasks.maintenance.handOver')"
                    class="q-mr-sm"
                    @click="openHandOver(r)"
                  />
                </template>
                <q-btn
                  flat
                  dense
                  icon="meeting_room"
                  :label="t('tasks.maintenance.viewRoom')"
                  class="q-mr-sm"
                  :to="{ name: 'room-detail', params: { id: r.id } }"
                />
                <q-btn
                  v-if="canMaintain"
                  dense
                  color="primary"
                  icon="build"
                  :label="t('tasks.maintenance.doMaintenance')"
                  @click="openSession(r)"
                />
              </div>
              <q-list dense>
                <q-item
                  v-for="m in r.machines"
                  :key="m.id"
                  clickable
                  :to="{ name: 'machine-detail', params: { id: m.id } }"
                >
                  <q-item-section>{{ m.hostname ?? m.id }}</q-item-section>
                  <q-item-section side>
                    <q-badge :color="maintenanceStateColor(m.state)" :label="stateWithDate(m)" />
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-card>
        </q-expansion-item>
        <q-item
          v-for="m in dueMachines"
          :key="m.id"
          clickable
          :to="{ name: 'machine-detail', params: { id: m.id } }"
        >
          <q-item-section>
            <q-item-label>{{ m.hostname ?? m.id }}</q-item-label>
            <q-item-label caption>{{
              t('tasks.maintenance.noRoom', {
                owner: m.owner ? m.owner.name : t('tasks.maintenance.noOwner'),
              })
            }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-badge :color="maintenanceStateColor(m.state)" :label="stateWithDate(m)" />
          </q-item-section>
        </q-item>
      </q-list>
      <div v-else-if="due" class="text-muted">{{ t('tasks.maintenance.nothing') }}</div>
    </div>

    <MaintenanceSettingsDialog
      v-model="handOverOpen"
      :subject="handOverRoom?.name ?? ''"
      :room-id="handOverRoom?.id ?? null"
      :cycle-days="handOverSettings?.maintenance_cycle_days ?? null"
      :owner-id="handOverSettings?.maintenance_owner?.id ?? null"
      :inherit-hint="t('tasks.maintenance.inheritHint')"
      :save="saveHandOver"
    />
    <MaintenanceSessionDialog
      v-model="sessionOpen"
      :room-id="sessionRoom?.id ?? null"
      :room-name="sessionRoom?.name ?? null"
      :machines="sessionMachines"
      @recorded="reload"
    />

    <CheckCloseDialog v-model="closeOpen" :check="closing" @closed="reload" />
    <CheckRequestDialog
      v-model="editOpen"
      :check="editing"
      :subtitle="editing?.machine?.hostname ?? undefined"
      :save="saveEdit"
    />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import CheckCloseDialog from 'src/components/check/CheckCloseDialog.vue';
import CheckRequestDialog from 'src/components/check/CheckRequestDialog.vue';
import MaintenanceSessionDialog from 'src/components/maintenance/MaintenanceSessionDialog.vue';
import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import {
  dueLabel,
  getDue,
  getRoomMaintenance,
  isDue,
  maintenanceStateColor,
  maintenanceStateLabel,
  updateMachineMaintenance,
  updateRoomMaintenance,
  type MaintenanceSettingsPayload,
  type RoomMaintenance,
  type Due,
  type DueMachine,
  type DueRoom,
} from 'src/services/maintenance';
import {
  effectiveAssignee,
  formerAssigneeNote,
  listAllChecks,
  priorityColor,
  updateCheck,
  type Check,
  type CheckMachineRef,
  type CheckPayload,
} from 'src/services/checks';
import { checkInstructionsText } from 'src/services/alerts';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { formatDate, timeAgoLabel } from 'src/utils/format';
import { t } from 'src/i18n';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();

const scope = ref<'me' | 'none' | 'all'>('me');
const scopeOptions = computed(() =>
  (['me', 'none', 'all'] as const).map((value) => ({ label: t(`tasks.scopes.${value}`), value })),
);
const rows = ref<Check[]>([]);
const checksTotal = ref(0);
const loading = ref(false);
const canWrite = computed(() => auth.can('check', 'write'));
const canReadChecks = computed(() => auth.can('check', 'read'));

const columns = computed<QTableColumn<Check>[]>(() => [
  {
    name: 'machine',
    label: t('tasks.checks.columns.machine'),
    field: (r) => r.machine?.hostname ?? '',
    align: 'left',
  },
  {
    name: 'instructions',
    label: t('tasks.checks.columns.instructions'),
    field: (row: Check) => checkInstructionsText(row),
    align: 'left',
  },
  {
    name: 'assigned_to',
    label: t('tasks.checks.columns.assignedTo'),
    field: (r) => effectiveAssignee(r.assigned_to)?.name ?? '',
    align: 'left',
  },
  {
    name: 'created_at',
    label: t('tasks.checks.columns.requested'),
    field: 'created_at',
    align: 'left',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

/** A due date before today, in the reader's day. */
function isOverdue(due: string): boolean {
  const today = new Date();
  const local = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  return due < local;
}

function placeLabel(m: CheckMachineRef | null): string {
  if (!m) return '';
  const parts = [m.building_name, m.room_name].filter(Boolean);
  const place = parts.join(' › ');
  if (place && m.location) return `${place} · ${m.location}`;
  return place || m.location || t('tasks.checks.noRoom');
}

// --- Maintenance
const due = ref<Due | null>(null);
const canMaintain = computed(() => auth.can('maintenance', 'write'));
const sessionOpen = ref(false);
const sessionRoom = ref<DueRoom | null>(null);
const sessionMachines = computed(() =>
  (sessionRoom.value?.machines ?? []).map((m) => ({
    id: m.id,
    hostname: m.hostname ?? m.id,
    hint: stateWithDate(m),
    // Ticked: what is due. A poste up to date is there to tick by hand.
    preselect: isDue(m.state),
  })),
);

// « À faire » lists what has something to do; a room all up to date is in
// « Salles » (audit B09).
const dueRooms = computed(() =>
  (due.value?.rooms ?? []).filter((r) => r.overdue > 0 || r.due_soon > 0),
);
// The same rule for the postes in no room: the server sends them all, those
// up to date included, and an owner whose postes are all up to date must read
// « Rien à faire », not a list of « À jour » (audit B09).
const dueMachines = computed(() => (due.value?.machines ?? []).filter((m) => isDue(m.state)));

function stateWithDate(m: DueMachine): string {
  const label = maintenanceStateLabel(m.state);
  if (!m.due_at) return label;
  return isDue(m.state) ? `${label} · ${dueLabel(m.due_at)}` : label;
}

async function takeRoom(r: DueRoom) {
  if (!auth.user) return;
  const me = auth.user.id;
  try {
    if (r.level === 'machine') {
      // Postes that override the room: taking them is setting their own
      // owner — the room, and its other postes, stay whose they are.
      for (const m of r.machines) {
        await updateMachineMaintenance(m.id, { maintenance_owner_id: me });
      }
      notify($q, () => ({
        type: 'positive',
        message: t(
          'tasks.maintenance.machinesTaken',
          { count: r.machines.length, room: r.name },
          r.machines.length,
        ),
      }));
    } else {
      await updateRoomMaintenance(r.id, { maintenance_owner_id: me });
      notify($q, () => ({
        type: 'positive',
        message: t('tasks.maintenance.roomTaken', { room: r.name }),
      }));
    }
    notifyTasksChanged();
    await reload();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('tasks.maintenance.takeFailed')),
    }));
  }
}

const handOverOpen = ref(false);
const handOverRoom = ref<DueRoom | null>(null);
const handOverSettings = ref<RoomMaintenance | null>(null);
async function openHandOver(r: DueRoom) {
  try {
    handOverSettings.value = await getRoomMaintenance(r.id);
    handOverRoom.value = r;
    handOverOpen.value = true;
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('tasks.maintenance.roomFailed')),
    }));
  }
}
async function saveHandOver(payload: MaintenanceSettingsPayload) {
  if (!handOverRoom.value) return;
  await updateRoomMaintenance(handOverRoom.value.id, payload);
  notify($q, () => ({ type: 'positive', message: t('tasks.maintenance.handedOver') }));
  notifyTasksChanged();
  await reload();
}

function openSession(r: DueRoom) {
  sessionRoom.value = r;
  sessionOpen.value = true;
}

async function loadDue() {
  if (!auth.can('maintenance', 'read')) return;
  try {
    due.value = await getDue(scope.value === 'all' ? undefined : scope.value);
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('tasks.maintenance.loadFailed')),
    }));
  }
}

async function reload() {
  loading.value = true;
  void loadDue();
  if (!canReadChecks.value) {
    loading.value = false;
    return;
  }
  try {
    // Every page: the list stopped at 200 while the badge said 310.
    const res = await listAllChecks({
      open: true,
      ...(scope.value === 'all' ? {} : { assigned_to: scope.value }),
    });
    rows.value = res.items;
    checksTotal.value = res.total;
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('tasks.checks.loadFailed')),
    }));
  } finally {
    loading.value = false;
  }
}

// --- Closing
const closeOpen = ref(false);
const closing = ref<Check | null>(null);
function openClose(check: Check) {
  closing.value = check;
  closeOpen.value = true;
}

// --- Reassigning
const editOpen = ref(false);
const editing = ref<Check | null>(null);
function openEdit(check: Check) {
  editing.value = check;
  editOpen.value = true;
}
async function saveEdit(payload: CheckPayload) {
  if (!editing.value) return;
  await updateCheck(editing.value.id, payload);
  notify($q, () => ({ type: 'positive', message: t('tasks.checks.updated') }));
  notifyTasksChanged();
  await reload();
}
async function takeOver(check: Check) {
  if (!auth.user) return;
  try {
    await updateCheck(check.id, { assigned_to_id: auth.user.id });
    notify($q, () => ({ type: 'positive', message: t('tasks.checks.taken') }));
    notifyTasksChanged();
    await reload();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('tasks.checks.takeFailed')),
    }));
  }
}

// The profile is fetched by the layout without being awaited: on a hard
// reload the permission checks in `reload` run before it is there, and the
// lists would stay empty. Re-read once it lands.
watch(
  () => auth.user?.id,
  (id) => {
    if (id) void reload();
  },
);

onMounted(reload);
</script>
