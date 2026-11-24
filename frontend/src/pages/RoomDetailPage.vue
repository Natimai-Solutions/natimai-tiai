<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn
        flat
        dense
        round
        icon="arrow_back"
        :aria-label="t('rooms.actions.back')"
        :to="{ name: 'rooms' }"
      />
      <h1 class="text-h5 q-my-none q-ml-sm">
        <template v-if="room">
          <span v-if="room.building" class="text-muted">{{ room.building.name }} › </span
          >{{ room.name }}
        </template>
        <span v-else>{{ t('rooms.detail.room') }}</span>
      </h1>
      <q-space />
      <template v-if="room && canWrite">
        <q-btn
          v-if="canPlace"
          flat
          dense
          color="primary"
          icon="playlist_add"
          :label="t('rooms.detail.addMachines')"
          class="q-mr-sm"
          @click="openAdd"
        />
        <q-btn
          flat
          dense
          icon="edit"
          :label="t('rooms.actions.edit')"
          class="q-mr-sm"
          @click="formOpen = true"
        />
      </template>
      <!-- C3: a command on the room, later or every week. -->
      <q-btn
        v-if="room && canSchedule"
        flat
        dense
        color="primary"
        icon="event_repeat"
        :label="t('rooms.detail.schedule')"
        class="q-mr-sm"
        :to="{ name: 'schedules', query: { room: room.id } }"
      />
      <!-- The room's labels: its equipment and postes, to stick on them. -->
      <q-btn
        v-if="room && canReadAssets"
        flat
        dense
        color="primary"
        icon="qr_code_2"
        :label="t('rooms.detail.labels')"
        class="q-mr-sm"
        :to="{ name: 'asset-labels', query: { room_id: room.id } }"
      />
      <q-btn
        v-if="room && canMaintain && machines.length"
        dense
        color="primary"
        icon="build"
        :label="t('rooms.detail.doMaintenance')"
        @click="sessionOpen = true"
      />
    </div>

    <q-card v-if="room" flat bordered class="q-mb-md" style="max-width: 640px">
      <q-card-section class="q-gutter-xs">
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('rooms.detail.location') }}</div>
          <div class="col">
            {{ room.effective_location ?? '—' }}
            <span v-if="room.building && room.effective_location" class="text-caption text-muted">
              {{ t('rooms.detail.fromBuilding') }}
            </span>
          </div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('rooms.detail.machines') }}</div>
          <div class="col">
            {{ room.machine_count }}
            <q-badge v-if="room.mismatch_count" color="orange" class="q-ml-sm">
              {{ t('rooms.detail.mismatched', { count: room.mismatch_count }) }}
            </q-badge>
          </div>
        </div>
        <div v-if="room.ad_key" class="row items-center">
          <div class="col-4 text-muted">{{ t('rooms.detail.directory') }}</div>
          <div class="col text-caption">{{ room.ad_key }}</div>
        </div>
        <div v-if="room.notes" class="row">
          <div class="col-4 text-muted">{{ t('rooms.detail.notes') }}</div>
          <div class="col" style="white-space: pre-line">{{ room.notes }}</div>
        </div>
      </q-card-section>
    </q-card>

    <q-card v-if="room && maintenance" flat bordered class="q-mb-md" style="max-width: 640px">
      <q-card-section class="row items-center text-subtitle1">
        {{ t('rooms.detail.maintenance') }}
        <q-space />
        <q-btn
          v-if="canMaintain"
          flat
          dense
          icon="tune"
          :label="t('rooms.detail.adjust')"
          @click="maintenanceOpen = true"
        />
      </q-card-section>
      <q-separator />
      <q-card-section class="q-gutter-xs">
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('rooms.detail.cycle') }}</div>
          <div class="col">
            {{
              maintenance.effective_cycle_days > 0
                ? t(
                    'rooms.detail.cycleDays',
                    { days: maintenance.effective_cycle_days },
                    maintenance.effective_cycle_days,
                  )
                : t('rooms.detail.excluded')
            }}
            <span class="text-caption text-muted">
              ({{
                originLabel(
                  maintenance.effective_cycle_origin,
                  maintenance.maintenance_cycle_days !== null,
                )
              }})
            </span>
          </div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('rooms.detail.owner') }}</div>
          <div class="col">
            <!-- The level the resolution took: a room owner deactivated
                 since leaves the parc's default in charge, and says so. -->
            <template v-if="maintenance.effective_owner">
              {{ maintenance.effective_owner.name }}
              <span class="text-caption text-muted" data-test="owner-origin">
                ({{
                  originLabel(
                    maintenance.effective_owner_origin,
                    maintenance.maintenance_owner !== null,
                  )
                }})
              </span>
            </template>
            <span v-else class="text-muted">{{ t('rooms.detail.nobody') }}</span>
            <div
              v-if="
                maintenance.maintenance_owner && maintenance.effective_owner_origin === 'global'
              "
              class="text-caption text-warn"
            >
              {{
                t('rooms.detail.ownerIgnored', {
                  owner: ownerLabel(maintenance.maintenance_owner),
                })
              }}
            </div>
          </div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('rooms.detail.machines') }}</div>
          <div class="col">
            <q-badge v-if="room.maintenance_overdue" color="negative" class="q-mr-xs">
              {{ t('rooms.detail.overdue', { count: room.maintenance_overdue }) }}
            </q-badge>
            <q-badge v-if="room.maintenance_due_soon" color="orange" class="q-mr-xs">
              {{ t('rooms.detail.dueSoon', { count: room.maintenance_due_soon }) }}
            </q-badge>
            <span v-if="!room.maintenance_overdue && !room.maintenance_due_soon" class="text-muted">
              {{ t('rooms.detail.nothingToDo') }}
            </span>
          </div>
        </div>
        <div v-if="sessions.length" class="row">
          <div class="col-4 text-muted">{{ t('rooms.detail.sessions') }}</div>
          <div class="col" data-test="room-sessions">
            <!-- Every visit, newest first, a page at a time; each opens with
                 its global note and its postes. -->
            <div v-for="s in sessions" :key="s.id" class="q-mb-xs">
              <a
                href="#"
                class="row-link"
                :data-test="`session-${s.id}`"
                @click.prevent="openSessionView(s.id)"
              >
                {{ formatDateTime(s.performed_at) }}
              </a>
              · {{ s.performed_by }} ·
              {{ t('rooms.detail.sessionMachines', { count: s.machine_count }, s.machine_count) }}
              <div v-if="s.note" class="text-caption text-muted" style="white-space: pre-line">
                {{ s.note }}
              </div>
            </div>
            <q-btn
              v-if="sessionsTotal > sessions.length"
              flat
              dense
              no-caps
              size="sm"
              :label="t('rooms.detail.showMore', { count: sessionsTotal - sessions.length })"
              @click="loadMoreSessions"
            />
          </div>
        </div>
      </q-card-section>
    </q-card>

    <q-table
      :rows="machines"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[0]"
      hide-pagination
      flat
      bordered
      :grid="small"
      card-container-class="q-col-gutter-sm"
    >
      <!-- On a phone, a card per poste with its link and « Retirer » in
           sight, rather than a table to scroll sideways (audit U23). -->
      <template #item="cell">
        <div class="col-12" :data-test="`machine-card-${cell.row.id}`">
          <q-card flat bordered>
            <q-card-section class="row items-start no-wrap q-py-sm">
              <div class="col" style="min-width: 0">
                <div style="overflow-wrap: anywhere">
                  <q-icon
                    :name="onlineIcon(cell.row.is_online)"
                    :color="onlineColor(cell.row.is_online)"
                    size="16px"
                    class="q-mr-xs"
                  />
                  <router-link
                    :to="{ name: 'machine-detail', params: { id: cell.row.id } }"
                    class="row-link text-weight-medium"
                  >
                    {{ cell.row.hostname || cell.row.machine_uuid }}
                  </router-link>
                </div>
                <div class="text-caption text-muted" style="overflow-wrap: anywhere">
                  {{
                    [cell.row.location ?? t('rooms.detail.noLocation'), cell.row.session_username]
                      .filter(Boolean)
                      .join(' · ')
                  }}
                  <q-icon
                    v-if="cell.row.location_mismatch"
                    name="wrong_location"
                    color="orange"
                    size="16px"
                    :aria-label="t('rooms.detail.mismatch')"
                  />
                </div>
                <div class="q-mt-xs">
                  <q-badge
                    v-if="cell.row.maintenance_state"
                    :color="maintenanceStateColor(cell.row.maintenance_state)"
                    :label="maintenanceStateLabel(cell.row.maintenance_state)"
                    class="q-mr-xs"
                  />
                  <span class="text-caption text-muted">{{
                    cell.row.last_seen
                      ? t('rooms.detail.seen', { ago: timeAgoLabel(cell.row.last_seen) })
                      : t('rooms.detail.neverSeen')
                  }}</span>
                </div>
              </div>
              <q-btn
                v-if="canPlace"
                flat
                round
                icon="remove_circle_outline"
                :aria-label="t('rooms.detail.removeAria', { name: cell.row.hostname ?? '' })"
                @click="confirmRemove(cell.row)"
              />
            </q-card-section>
          </q-card>
        </div>
      </template>
      <template #body-cell-hostname="cell">
        <q-td :props="cell">
          <q-icon
            :name="onlineIcon(cell.row.is_online)"
            :color="onlineColor(cell.row.is_online)"
            size="16px"
            class="q-mr-xs"
          />
          <router-link
            :to="{ name: 'machine-detail', params: { id: cell.row.id } }"
            class="row-link"
          >
            {{ cell.value || cell.row.machine_uuid }}
          </router-link>
        </q-td>
      </template>
      <template #body-cell-location="cell">
        <q-td :props="cell">
          {{ cell.value ?? '—' }}
          <q-icon
            v-if="cell.row.location_mismatch"
            name="wrong_location"
            color="orange"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>{{ t('rooms.detail.mismatch') }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-maintenance="cell">
        <q-td :props="cell">
          <q-badge
            v-if="cell.row.maintenance_state"
            :color="maintenanceStateColor(cell.row.maintenance_state)"
            :label="maintenanceStateLabel(cell.row.maintenance_state)"
          />
        </q-td>
      </template>
      <template #body-cell-last_seen="cell">
        <q-td :props="cell">{{ timeAgoLabel(cell.value) }}</q-td>
      </template>
      <template #body-cell-actions="cell">
        <q-td :props="cell" class="text-right" @click.stop>
          <q-btn
            v-if="canPlace"
            flat
            dense
            round
            icon="remove_circle_outline"
            :aria-label="t('rooms.detail.removeAria', { name: cell.row.hostname ?? '' })"
            @click="confirmRemove(cell.row)"
          >
            <q-tooltip>{{ t('rooms.detail.removeTooltip') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Adding postes: a search over the parc, multi-select. The room-less
         ones come first, but a poste of another room can be moved here too. -->
    <q-dialog v-model="addOpen">
      <q-card style="width: 560px; max-width: 95vw">
        <q-card-section class="text-h6">{{ t('rooms.detail.addMachines') }}</q-card-section>
        <q-card-section class="q-pt-none">
          <q-select
            v-model="picked"
            :options="candidates"
            multiple
            use-chips
            use-input
            input-debounce="300"
            option-value="id"
            :option-label="candidateLabel"
            :label="t('rooms.detail.searchMachine')"
            outlined
            dense
            autofocus
            @filter="searchCandidates"
          >
            <template #option="scope">
              <q-item v-bind="scope.itemProps">
                <q-item-section>
                  <q-item-label>{{ scope.opt.hostname ?? scope.opt.machine_uuid }}</q-item-label>
                  <q-item-label caption>
                    {{ scope.opt.location ?? t('rooms.detail.noLocation') }}
                    <span v-if="scope.opt.room_name">
                      · {{ t('rooms.detail.alreadyIn', { room: scope.opt.room_name }) }}</span
                    >
                    <span v-if="scope.opt.session_username">
                      · {{ scope.opt.session_username }}</span
                    >
                  </q-item-label>
                </q-item-section>
              </q-item>
            </template>
          </q-select>
          <div v-if="pickedMismatch.length" class="text-caption text-warn q-mt-sm">
            {{
              t(
                'rooms.detail.pickedMismatch',
                { count: pickedMismatch.length, site: room?.effective_location ?? '' },
                pickedMismatch.length,
              )
            }}
          </div>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat :label="t('rooms.actions.cancel')" />
          <q-btn
            color="primary"
            :label="t('rooms.actions.add')"
            :disable="!picked.length"
            :loading="adding"
            @click="addPicked"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <MaintenanceSettingsDialog
      v-model="maintenanceOpen"
      :subject="room?.name ?? ''"
      :room-id="props.id"
      :cycle-days="maintenance?.maintenance_cycle_days ?? null"
      :owner-id="maintenance?.maintenance_owner?.id ?? null"
      :owner-label="ownerLabel(maintenance?.maintenance_owner)"
      :inherit-hint="t('rooms.detail.inheritHint')"
      :save="saveMaintenance"
    />
    <MaintenanceSessionViewDialog
      v-model="sessionViewOpen"
      :session-id="sessionViewId"
      @deleted="load"
    />
    <MaintenanceSessionDialog
      v-model="sessionOpen"
      :room-id="props.id"
      :room-name="room?.name ?? null"
      :machines="sessionMachines"
      @recorded="load"
    />

    <RoomFormDialog
      v-model="formOpen"
      :room="room"
      :buildings="buildings"
      :locations="locations"
      @saved="load"
    />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import RoomFormDialog from 'src/components/room/RoomFormDialog.vue';
import MaintenanceSessionDialog from 'src/components/maintenance/MaintenanceSessionDialog.vue';
import MaintenanceSessionViewDialog from 'src/components/maintenance/MaintenanceSessionViewDialog.vue';
import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import {
  dueDate,
  getRoomMaintenance,
  isDue,
  listSessions,
  maintenanceStateColor,
  maintenanceStateLabel,
  ownerLabel,
  updateRoomMaintenance,
  type MaintenanceSession,
  type MaintenanceSettingsPayload,
  type RoomMaintenance,
} from 'src/services/maintenance';
import { listLocations, listMachines, type Machine } from 'src/services/machines';
import {
  getRoom,
  getRoomConfig,
  listBuildings,
  placeMachines,
  placementNotification,
  unassignMachines,
  type Building,
  type Room,
} from 'src/services/rooms';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { t } from 'src/i18n';
import {
  documentTitle,
  formatDateTime,
  onlineColor,
  onlineIcon,
  timeAgoLabel,
} from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const props = defineProps<{ id: string }>();

const $q = useQuasar();
// A phone: a card per poste rather than a table (audit U23).
const small = computed(() => $q.screen.lt.sm);
const auth = useAuthStore();

const room = ref<Room | null>(null);
// The tab says which room, once known — the router could only say « Salle ».
watch(
  () => room.value?.name,
  (name) => {
    if (name) document.title = documentTitle(name);
  },
);
const machines = ref<Machine[]>([]);
const buildings = ref<Building[]>([]);
const locations = ref<string[]>([]);
const loading = ref(false);
const formOpen = ref(false);

const canWrite = computed(() => auth.can('room', 'write'));
// Moving postes by hand: the permission, and a server not in a directory mode.
const manualMode = ref(true);
const canPlace = computed(() => canWrite.value && manualMode.value);

const columns = computed<QTableColumn<Machine>[]>(() => [
  {
    name: 'hostname',
    label: t('rooms.detail.columns.name'),
    field: 'hostname',
    align: 'left',
    sortable: true,
  },
  {
    name: 'location',
    label: t('rooms.detail.columns.location'),
    field: 'location',
    align: 'left',
  },
  {
    name: 'ip_address',
    label: t('rooms.detail.columns.ip'),
    field: 'ip_address',
    align: 'left',
    format: (v: string | null) => v ?? '—',
  },
  {
    name: 'session',
    label: t('rooms.detail.columns.session'),
    field: 'session_username',
    align: 'left',
    format: (v: string | null) => v ?? '—',
  },
  {
    name: 'maintenance',
    label: t('rooms.detail.columns.maintenance'),
    field: 'maintenance_state',
    align: 'center',
  },
  {
    name: 'last_seen',
    label: t('rooms.detail.columns.lastSeen'),
    field: 'last_seen',
    align: 'left',
    sortable: true,
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

// Maintenance of the room: its settings, its last visits, the postes done.
const canMaintain = computed(() => auth.can('maintenance', 'write'));
const canReadAssets = computed(() => auth.can('asset', 'read'));
const canSchedule = computed(() => auth.can('schedule', 'write'));
const maintenance = ref<RoomMaintenance | null>(null);
const sessions = ref<MaintenanceSession[]>([]);
const sessionsTotal = ref(0);
const SESSION_PAGE_SIZE = 5;
const sessionViewOpen = ref(false);
const sessionViewId = ref<string | null>(null);
const maintenanceOpen = ref(false);
const sessionOpen = ref(false);
const sessionMachines = computed(() =>
  machines.value.map((m) => ({
    id: m.id,
    hostname: m.hostname ?? m.machine_uuid,
    hint: `${maintenanceStateLabel(m.maintenance_state)}${
      m.last_maintenance_at
        ? ` · ${t('rooms.detail.lastMaintenance', { date: dueDate(m.last_maintenance_at) })}`
        : ''
    }`,
    // Ticked: what is due; a poste excluded from the cycle never (audit B09).
    preselect: isDue(m.maintenance_state),
  })),
);

async function loadMaintenance() {
  if (!auth.can('maintenance', 'read')) return;
  try {
    const [settings, list] = await Promise.all([
      getRoomMaintenance(props.id),
      listSessions({ room_id: props.id, page: 1, page_size: SESSION_PAGE_SIZE }),
    ]);
    maintenance.value = settings;
    sessions.value = list.items;
    sessionsTotal.value = list.total;
  } catch {
    // The card simply stays absent.
  }
}

/** The next visits, older: none of them is out of reach any more. */
async function loadMoreSessions() {
  try {
    const page = Math.floor(sessions.value.length / SESSION_PAGE_SIZE) + 1;
    const list = await listSessions({ room_id: props.id, page, page_size: SESSION_PAGE_SIZE });
    const known = new Set(sessions.value.map((s) => s.id));
    sessions.value = [...sessions.value, ...list.items.filter((s) => !known.has(s.id))];
    sessionsTotal.value = list.total;
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('rooms.detail.sessionsFailed')),
    }));
  }
}

function openSessionView(id: string) {
  sessionViewId.value = id;
  sessionViewOpen.value = true;
}

/** « défaut du parc » or « propre à la salle », from the level the server resolved. */
function originLabel(origin: 'room' | 'global' | undefined, ownSet: boolean): string {
  const level = origin ?? (ownSet ? 'room' : 'global');
  return level === 'room' ? t('rooms.detail.ownOrigin') : t('rooms.detail.globalOrigin');
}

async function saveMaintenance(payload: MaintenanceSettingsPayload) {
  maintenance.value = await updateRoomMaintenance(props.id, payload);
  // Another owner or cycle moves the room in or out of somebody's « Mes
  // tâches »: the menu badge reads again (audit U19).
  notifyTasksChanged();
  notify($q, () => ({ type: 'positive', message: t('rooms.detail.settingsSaved') }));
  await load();
}

/**
 * Every poste of the room, page after page: the server serves 200 at most per
 * request, and a room beyond that was shown — and maintained — cut short,
 * without a word (audit U24).
 */
async function roomMachines(): Promise<Machine[]> {
  const out: Machine[] = [];
  for (let page = 1; page <= 50; page++) {
    const list = await listMachines({
      room_id: props.id,
      sort_by: 'hostname',
      sort_desc: false,
      page,
      page_size: 200,
    });
    out.push(...list.items);
    if (out.length >= list.total || list.items.length === 0) break;
  }
  return out;
}

async function load() {
  loading.value = true;
  try {
    const [r, all] = await Promise.all([getRoom(props.id), roomMachines()]);
    room.value = r;
    machines.value = all;
    void loadMaintenance();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('rooms.detail.loadFailed')),
    }));
  } finally {
    loading.value = false;
  }
}

async function loadRefs() {
  try {
    [buildings.value, locations.value] = await Promise.all([
      listBuildings(),
      listLocations().then((l) => l.map((x) => x.name)),
    ]);
  } catch {
    // The form still works without them.
  }
  try {
    manualMode.value = (await getRoomConfig()).manual;
  } catch {
    // Assumed manual: the worst case is a 409 the notification explains.
  }
}

/** Taking a poste out of the room changes its owner and cycle: asked first. */
function confirmRemove(m: Machine) {
  liveDialog($q, () => ({
    title: t('rooms.detail.removeTitle'),
    message: t('rooms.detail.removeAsk', {
      name: m.hostname ?? t('rooms.detail.thisMachine'),
      room: room.value?.name ?? '',
    }),
    cancel: true,
    ok: { label: t('rooms.detail.remove'), color: 'negative' },
  })).onOk(() => void remove(m));
}

async function remove(m: Machine) {
  try {
    await unassignMachines([m.id]);
    // Out of the room, the poste leaves its maintenance owner's « Mes tâches »:
    // the menu badge reads again (audit U19).
    notifyTasksChanged();
    notify($q, () => ({
      type: 'positive',
      message: m.hostname
        ? t('rooms.detail.removed', { name: m.hostname })
        : t('rooms.detail.machineRemoved'),
    }));
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('rooms.detail.removeFailed')),
    }));
  }
}

// --- Adding postes ----------------------------------------------------------

const addOpen = ref(false);
const adding = ref(false);
const picked = ref<Machine[]>([]);
const candidates = ref<Machine[]>([]);

const pickedMismatch = computed(() => {
  const site = room.value?.effective_location;
  if (!site) return [];
  return picked.value.filter((m) => m.location && m.location !== site);
});

function candidateLabel(m: Machine): string {
  return m.hostname ?? m.machine_uuid;
}

function openAdd() {
  picked.value = [];
  candidates.value = [];
  addOpen.value = true;
}

function searchCandidates(val: string, update: (fn: () => void) => void) {
  void (async () => {
    try {
      const res = await listMachines({
        ...(val ? { search: val } : {}),
        sort_by: 'hostname',
        sort_desc: false,
        page_size: 50,
      });
      update(() => {
        // Not the ones already here: adding them again would be a no-op.
        candidates.value = res.items.filter((m) => m.room_id !== props.id);
      });
    } catch {
      update(() => {
        candidates.value = [];
      });
    }
  })();
}

async function addPicked() {
  adding.value = true;
  try {
    const res = await placeMachines(
      props.id,
      picked.value.map((m) => m.id),
    );
    // The postes moved here now follow this room's maintenance owner and
    // cycle: « Mes tâches » counts them differently (audit U19).
    notifyTasksChanged();
    notify($q, () => placementNotification(res));
    addOpen.value = false;
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('rooms.detail.placeFailed')),
    }));
  } finally {
    adding.value = false;
  }
}

watch(
  () => props.id,
  () => {
    room.value = null;
    machines.value = [];
    void load();
  },
);

// Same reasoning as the fiche: the profile lands after the first load on a
// hard reload, and the maintenance card is gated on it.
watch(
  () => auth.user?.id,
  (id) => {
    if (id && !maintenance.value) void loadMaintenance();
  },
);

onMounted(() => {
  void load();
  void loadRefs();
});
</script>
