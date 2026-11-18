<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <h1 class="text-h5 q-my-none col-auto">{{ t('rooms.list.title') }}</h1>
      <q-space />
      <!-- Each only where the account's scope lets it create: one confined
           to rooms creates neither, one confined to buildings no building. -->
      <q-btn
        v-if="canWrite && creation.buildings"
        flat
        color="primary"
        icon="apartment"
        :label="t('rooms.list.newBuilding')"
        @click="openBuildingForm(null)"
      />
      <q-btn
        v-if="canWrite && creation.rooms"
        color="primary"
        icon="meeting_room"
        :label="t('rooms.list.newRoom')"
        @click="openRoomForm(null)"
      />
    </div>

    <!-- A directory mode: the membership is the directory's, and a sync is
         how a setting switched on the server reaches the whole parc at once. -->
    <q-banner v-if="config && !config.manual" class="surface-blue q-mb-md" rounded>
      <template #avatar><q-icon name="account_tree" color="primary" /></template>
      {{ t('rooms.list.directoryBefore', { source: sourceLabel }) }} (<code
        >ROOM_SOURCE={{ config.source }}</code
      >){{ t('rooms.list.directoryAfter') }}
      <template v-if="canWrite" #action>
        <q-btn flat dense :label="t('rooms.list.resync')" :loading="syncing" @click="sync" />
      </template>
    </q-banner>

    <q-tabs v-model="tab" dense align="left" class="text-muted q-mb-sm" active-color="primary">
      <q-tab name="rooms" icon="meeting_room" :label="t('rooms.list.tabRooms')" />
      <q-tab name="buildings" icon="apartment" :label="t('rooms.list.tabBuildings')" />
    </q-tabs>

    <q-tab-panels v-model="tab" animated>
      <q-tab-panel name="rooms" class="q-px-none">
        <div class="text-body2 text-muted q-mb-sm" style="max-width: 760px">
          {{ t('rooms.list.roomsIntro') }}
        </div>
        <q-table
          :rows="rooms"
          :columns="roomColumns"
          row-key="id"
          :loading="loading"
          :rows-per-page-options="[0]"
          hide-pagination
          flat
          bordered
          :grid="small"
          card-container-class="q-col-gutter-sm"
        >
          <!-- On a phone, a card per room — its name, place, postes and
               maintenance in sight, its actions as buttons — rather than a
               table to scroll sideways (audit U23). -->
          <template #item="props">
            <div class="col-12" :data-test="`room-card-${props.row.id}`">
              <q-card flat bordered>
                <q-card-section class="q-pb-xs">
                  <router-link
                    :to="{ name: 'room-detail', params: { id: props.row.id } }"
                    class="row-link text-weight-medium"
                    style="overflow-wrap: anywhere"
                  >
                    {{ props.row.name }}
                  </router-link>
                  <q-icon
                    v-if="props.row.ad_key"
                    name="account_tree"
                    size="16px"
                    class="q-ml-xs text-muted"
                    :aria-label="t('rooms.list.fromDirectory', { key: props.row.ad_key })"
                  />
                  <div class="text-caption text-muted" style="overflow-wrap: anywhere">
                    {{
                      [props.row.building?.name, props.row.effective_location]
                        .filter(Boolean)
                        .join(' · ') || t('rooms.list.noBuildingNorLocation')
                    }}
                  </div>
                  <div
                    v-if="props.row.notes"
                    class="text-caption text-muted ellipsis-2-lines"
                    style="overflow-wrap: anywhere"
                  >
                    {{ props.row.notes }}
                  </div>
                  <div class="q-mt-xs">
                    {{
                      t(
                        'rooms.list.machines',
                        { count: props.row.machine_count },
                        props.row.machine_count,
                      )
                    }}
                    <q-badge v-if="props.row.mismatch_count" color="orange" class="q-ml-xs">
                      {{ t('rooms.list.mismatched', { count: props.row.mismatch_count }) }}
                    </q-badge>
                  </div>
                  <div class="q-mt-xs">
                    <q-badge v-if="props.row.maintenance_overdue" color="negative" class="q-mr-xs">
                      {{ t('rooms.list.overdue', { count: props.row.maintenance_overdue }) }}
                    </q-badge>
                    <q-badge v-if="props.row.maintenance_due_soon" color="orange" class="q-mr-xs">
                      {{ t('rooms.list.dueSoon', { count: props.row.maintenance_due_soon }) }}
                    </q-badge>
                    <!-- Leading space: the badges and « Maintenance : » stay
                         separate words, as the literal text kept them. -->
                    <span class="text-caption text-muted">
                      {{ ' ' + t('rooms.list.maintenance') }}
                      {{ cycleText(props.row) }}
                      {{
                        props.row.effective_owner_name ? `· ${props.row.effective_owner_name}` : ''
                      }}
                    </span>
                  </div>
                </q-card-section>
                <q-card-actions v-if="canWrite" align="right">
                  <q-btn
                    flat
                    no-caps
                    icon="edit"
                    :label="t('rooms.actions.edit')"
                    @click="openRoomForm(props.row)"
                  />
                  <q-btn
                    flat
                    no-caps
                    color="negative"
                    icon="delete"
                    :label="t('rooms.actions.delete')"
                    @click="confirmDeleteRoom(props.row)"
                  />
                </q-card-actions>
              </q-card>
            </div>
          </template>
          <template #body-cell-name="props">
            <q-td :props="props">
              <div>
                <router-link
                  :to="{ name: 'room-detail', params: { id: props.row.id } }"
                  class="row-link"
                >
                  {{ props.row.name }}
                </router-link>
                <q-icon
                  v-if="props.row.ad_key"
                  name="account_tree"
                  size="16px"
                  class="q-ml-xs text-muted"
                >
                  <q-tooltip>{{
                    t('rooms.list.fromDirectory', { key: props.row.ad_key })
                  }}</q-tooltip>
                </q-icon>
              </div>
              <div
                v-if="props.row.notes"
                class="text-caption text-muted ellipsis"
                style="max-width: 320px"
              >
                {{ props.row.notes }}
              </div>
            </q-td>
          </template>
          <template #body-cell-building="props">
            <q-td :props="props">{{ props.row.building?.name ?? '—' }}</q-td>
          </template>
          <template #body-cell-effective_location="props">
            <q-td :props="props">{{ props.value ?? '—' }}</q-td>
          </template>
          <template #body-cell-maintenance="props">
            <q-td :props="props">
              <q-badge v-if="props.row.maintenance_overdue" color="negative" class="q-mr-xs">
                {{ t('rooms.list.overdue', { count: props.row.maintenance_overdue }) }}
              </q-badge>
              <q-badge v-if="props.row.maintenance_due_soon" color="orange">
                {{ t('rooms.list.dueSoon', { count: props.row.maintenance_due_soon }) }}
              </q-badge>
              <span
                v-if="!props.row.maintenance_overdue && !props.row.maintenance_due_soon"
                class="text-muted"
                >—</span
              >
              <div class="text-caption text-muted">
                {{ cycleText(props.row) }}
                {{ props.row.effective_owner_name ? `· ${props.row.effective_owner_name}` : '' }}
              </div>
            </q-td>
          </template>
          <template #body-cell-mismatch_count="props">
            <q-td :props="props">
              <q-badge v-if="props.value" color="orange" :label="props.value">
                <q-tooltip>
                  {{ t('rooms.list.mismatchTooltip', { count: props.value }, props.value) }}
                </q-tooltip>
              </q-badge>
              <span v-else class="text-muted">—</span>
            </q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props" class="text-right" @click.stop>
              <q-btn
                v-if="canWrite"
                flat
                dense
                round
                icon="more_vert"
                :aria-label="t('rooms.list.actionsFor', { name: props.row.name })"
              >
                <q-menu>
                  <q-list style="min-width: 200px">
                    <q-item v-close-popup clickable @click="openRoomForm(props.row)">
                      <q-item-section avatar><q-icon name="edit" /></q-item-section>
                      <q-item-section>{{ t('rooms.actions.edit') }}</q-item-section>
                    </q-item>
                    <q-separator />
                    <q-item
                      v-close-popup
                      clickable
                      class="text-negative"
                      @click="confirmDeleteRoom(props.row)"
                    >
                      <q-item-section avatar><q-icon name="delete" /></q-item-section>
                      <q-item-section>{{ t('rooms.actions.delete') }}</q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <q-tab-panel name="buildings" class="q-px-none">
        <div class="text-body2 text-muted q-mb-sm" style="max-width: 760px">
          {{ t('rooms.list.buildingsIntro') }}
        </div>
        <q-table
          :rows="buildings"
          :columns="buildingColumns"
          row-key="id"
          :loading="loading"
          :rows-per-page-options="[0]"
          hide-pagination
          flat
          bordered
          :grid="small"
          card-container-class="q-col-gutter-sm"
        >
          <template #item="props">
            <div class="col-12" :data-test="`building-card-${props.row.id}`">
              <q-card flat bordered>
                <q-card-section class="q-pb-xs">
                  <div class="text-weight-medium" style="overflow-wrap: anywhere">
                    {{ props.row.name }}
                  </div>
                  <div class="text-caption text-muted" style="overflow-wrap: anywhere">
                    {{ props.row.location ?? t('rooms.list.noLocation') }}
                  </div>
                  <div class="q-mt-xs">
                    {{
                      t('rooms.list.roomsAndMachines', {
                        rooms: props.row.room_count,
                        machines: props.row.machine_count,
                      })
                    }}
                  </div>
                </q-card-section>
                <q-card-actions v-if="canWrite" align="right">
                  <q-btn
                    flat
                    no-caps
                    icon="edit"
                    :label="t('rooms.actions.edit')"
                    @click="openBuildingForm(props.row)"
                  />
                  <q-btn
                    flat
                    no-caps
                    color="negative"
                    icon="delete"
                    :label="t('rooms.actions.delete')"
                    @click="confirmDeleteBuilding(props.row)"
                  />
                </q-card-actions>
              </q-card>
            </div>
          </template>
          <template #body-cell-location="props">
            <q-td :props="props">{{ props.value ?? '—' }}</q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props" class="text-right">
              <q-btn
                v-if="canWrite"
                flat
                dense
                round
                icon="more_vert"
                :aria-label="t('rooms.list.actionsFor', { name: props.row.name })"
              >
                <q-menu>
                  <q-list style="min-width: 200px">
                    <q-item v-close-popup clickable @click="openBuildingForm(props.row)">
                      <q-item-section avatar><q-icon name="edit" /></q-item-section>
                      <q-item-section>{{ t('rooms.actions.edit') }}</q-item-section>
                    </q-item>
                    <q-separator />
                    <q-item
                      v-close-popup
                      clickable
                      class="text-negative"
                      @click="confirmDeleteBuilding(props.row)"
                    >
                      <q-item-section avatar><q-icon name="delete" /></q-item-section>
                      <q-item-section>{{ t('rooms.actions.delete') }}</q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <RoomFormDialog
      v-model="roomFormOpen"
      :room="editingRoom"
      :buildings="buildings"
      :locations="locations"
      @saved="reload"
    />
    <BuildingFormDialog
      v-model="buildingFormOpen"
      :building="editingBuilding"
      :locations="locations"
      @saved="reload"
    />
  </q-page>
</template>

<script setup lang="ts">
import { escapeHtml } from 'src/utils/html';
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import BuildingFormDialog from 'src/components/room/BuildingFormDialog.vue';
import RoomFormDialog from 'src/components/room/RoomFormDialog.vue';
import { listLocations } from 'src/services/machines';
import {
  deleteBuilding,
  deleteRoom,
  getRoomConfig,
  getRoomCreation,
  listBuildings,
  listRooms,
  roomSourceLabel,
  syncDirectory,
  syncNotification,
  syncPreviewMessage,
  type Building,
  type Room,
  type RoomConfig,
  type RoomCreation,
  type SyncResult,
} from 'src/services/rooms';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { t } from 'src/i18n';
import { liveDialog, liveNotify } from 'src/utils/liveDialog';

const $q = useQuasar();
// A phone: cards rather than tables (audit U23).
const small = computed(() => $q.screen.lt.sm);
const auth = useAuthStore();

const tab = ref<'rooms' | 'buildings'>('rooms');
const rooms = ref<Room[]>([]);
const buildings = ref<Building[]>([]);
// The sites the agents report, offered as choices when placing a building
// or a loose room — so the words match and no poste reads as divergent for
// a typo.
const locations = ref<string[]>([]);
const loading = ref(false);

const canWrite = computed(() => auth.can('room', 'write'));
// What the scope lets create; both until the server says, which only ever
// shows a button the server then refuses.
const creation = ref<RoomCreation>({ rooms: true, buildings: true });

async function loadCreation() {
  try {
    creation.value = await getRoomCreation();
  } catch {
    // Kept as is: the routes still refuse what the scope does not allow.
  }
}

const config = ref<RoomConfig | null>(null);
const syncing = ref(false);
const sourceLabel = computed(() => (config.value ? roomSourceLabel(config.value.source) : ''));

/** « 90 j », or « exclue » for a room out of the maintenance. */
function cycleText(room: Room): string {
  return room.effective_cycle_days > 0
    ? t('rooms.list.cycleDays', { days: room.effective_cycle_days })
    : t('rooms.list.excluded');
}

async function loadConfig() {
  try {
    config.value = await getRoomConfig();
  } catch {
    // Without it the page assumes manual, which only ever shows a 409.
  }
}

/**
 * The re-sync, never in one click: its dry run first — how many postes leave
 * their room, how many rooms appear — and the real run only once confirmed.
 * A first run on a parc filed by hand used to empty it.
 */
async function sync() {
  syncing.value = true;
  let preview: SyncResult;
  try {
    preview = await syncDirectory(true);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('rooms.list.resyncFailed')) });
    syncing.value = false;
    return;
  }
  liveDialog($q, () => ({
    title: t('rooms.list.resync'),
    message: syncPreviewMessage(preview),
    cancel: { flat: true, label: t('rooms.actions.cancel') },
    ok: { label: t('rooms.list.resyncConfirm'), color: 'primary' },
    persistent: true,
  }))
    .onOk(() => void runSync())
    .onCancel(() => {
      syncing.value = false;
    });
}

async function runSync() {
  try {
    const res = await syncDirectory();
    // The warning stays until read: its words follow a change of language.
    const notice = syncNotification(res);
    if (notice.timeout === 0)
      liveNotify(
        (options) => $q.notify(options),
        () => syncNotification(res),
      );
    else $q.notify(notice);
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('rooms.list.resyncFailed')) });
  } finally {
    syncing.value = false;
  }
}

const roomFormOpen = ref(false);
const editingRoom = ref<Room | null>(null);
const buildingFormOpen = ref(false);
const editingBuilding = ref<Building | null>(null);

const roomColumns = computed<QTableColumn<Room>[]>(() => [
  { name: 'name', label: t('rooms.list.columns.room'), field: 'name', align: 'left' },
  {
    name: 'building',
    label: t('rooms.list.columns.building'),
    field: (r) => r.building?.name ?? '',
    align: 'left',
  },
  {
    name: 'effective_location',
    label: t('rooms.list.columns.location'),
    field: 'effective_location',
    align: 'left',
  },
  {
    name: 'machine_count',
    label: t('rooms.list.columns.machines'),
    field: 'machine_count',
    align: 'center',
  },
  {
    name: 'mismatch_count',
    label: t('rooms.list.columns.mismatched'),
    field: 'mismatch_count',
    align: 'center',
  },
  {
    name: 'maintenance',
    label: t('rooms.list.columns.maintenance'),
    field: 'maintenance_overdue',
    align: 'left',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

const buildingColumns = computed<QTableColumn<Building>[]>(() => [
  { name: 'name', label: t('rooms.list.columns.building'), field: 'name', align: 'left' },
  { name: 'location', label: t('rooms.list.columns.location'), field: 'location', align: 'left' },
  {
    name: 'room_count',
    label: t('rooms.list.columns.rooms'),
    field: 'room_count',
    align: 'center',
  },
  {
    name: 'machine_count',
    label: t('rooms.list.columns.machines'),
    field: 'machine_count',
    align: 'center',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

async function reload() {
  loading.value = true;
  try {
    [rooms.value, buildings.value] = await Promise.all([listRooms(), listBuildings()]);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('rooms.list.loadFailed')) });
  } finally {
    loading.value = false;
  }
}

async function loadLocations() {
  try {
    locations.value = (await listLocations()).map((l) => l.name);
  } catch {
    // Free entry still works without the suggestions.
  }
}

function openRoomForm(room: Room | null) {
  editingRoom.value = room;
  roomFormOpen.value = true;
}

function openBuildingForm(building: Building | null) {
  editingBuilding.value = building;
  buildingFormOpen.value = true;
}

function confirmDeleteRoom(room: Room) {
  liveDialog($q, () => ({
    title: t('rooms.list.deleteRoomTitle'),
    message:
      t('rooms.list.deleteAsk', { name: `<b>${escapeHtml(room.name)}</b>` }) +
      '<br>' +
      t('rooms.list.deleteRoomBody', { count: room.machine_count }, room.machine_count),
    html: true,
    cancel: true,
    ok: { label: t('rooms.actions.delete'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteRoom(room.id);
        $q.notify({ type: 'positive', message: t('rooms.list.roomDeleted') });
        await reload();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, t('rooms.list.deleteFailed')) });
      }
    })();
  });
}

function confirmDeleteBuilding(building: Building) {
  liveDialog($q, () => ({
    title: t('rooms.list.deleteBuildingTitle'),
    message:
      t('rooms.list.deleteAsk', { name: `<b>${escapeHtml(building.name)}</b>` }) +
      '<br>' +
      t('rooms.list.deleteBuildingBody', { count: building.room_count }, building.room_count),
    html: true,
    cancel: true,
    ok: { label: t('rooms.actions.delete'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteBuilding(building.id);
        $q.notify({ type: 'positive', message: t('rooms.list.buildingDeleted') });
        await reload();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, t('rooms.list.deleteFailed')) });
      }
    })();
  });
}

onMounted(() => {
  void reload();
  void loadLocations();
  void loadConfig();
  void loadCreation();
});
</script>
