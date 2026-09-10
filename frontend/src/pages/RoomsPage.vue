<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <div class="text-h5 col-auto">Salles</div>
      <q-space />
      <q-btn
        v-if="canWrite"
        flat
        color="primary"
        icon="apartment"
        label="Nouveau bâtiment"
        @click="openBuildingForm(null)"
      />
      <q-btn
        v-if="canWrite"
        color="primary"
        icon="meeting_room"
        label="Nouvelle salle"
        @click="openRoomForm(null)"
      />
    </div>

    <!-- A directory mode: the membership is the directory's, and a sync is
         how a setting switched on the server reaches the whole parc at once. -->
    <q-banner v-if="config && !config.manual" class="bg-blue-1 q-mb-md" rounded>
      <template #avatar><q-icon name="account_tree" color="primary" /></template>
      Les postes sont rangés {{ sourceLabel }} (<code>ROOM_SOURCE={{ config.source }}</code
      >) : les salles se créent toutes seules et le rattachement manuel est désactivé. Nom, bâtiment
      et notes des salles restent modifiables.
      <template v-if="canWrite" #action>
        <q-btn
          flat
          dense
          label="Resynchroniser depuis l'annuaire"
          :loading="syncing"
          @click="sync"
        />
      </template>
    </q-banner>

    <q-tabs v-model="tab" dense align="left" class="text-grey-8 q-mb-sm" active-color="primary">
      <q-tab name="rooms" icon="meeting_room" label="Salles" />
      <q-tab name="buildings" icon="apartment" label="Bâtiments" />
    </q-tabs>

    <q-tab-panels v-model="tab" animated>
      <q-tab-panel name="rooms" class="q-px-none">
        <div class="text-body2 text-grey-8 q-mb-sm" style="max-width: 760px">
          Une salle est où les postes sont, telle que la console les range. Elle hérite
          l'emplacement de son bâtiment ; un poste dont l'agent déclare un autre emplacement est
          signalé, jamais refusé.
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
          @row-click="(_evt, row) => goRoom(row)"
        >
          <template #body-cell-name="props">
            <q-td :props="props">
              <div>
                {{ props.row.name }}
                <q-icon
                  v-if="props.row.ad_key"
                  name="account_tree"
                  size="16px"
                  class="q-ml-xs text-grey-7"
                >
                  <q-tooltip>Créée depuis l'annuaire : {{ props.row.ad_key }}</q-tooltip>
                </q-icon>
              </div>
              <div
                v-if="props.row.notes"
                class="text-caption text-grey ellipsis"
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
          <template #body-cell-mismatch_count="props">
            <q-td :props="props">
              <q-badge v-if="props.value" color="orange" :label="props.value">
                <q-tooltip>
                  {{ props.value }} poste(s) dont l'agent déclare un autre emplacement que la salle
                </q-tooltip>
              </q-badge>
              <span v-else class="text-grey">—</span>
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
                :aria-label="`Actions pour ${props.row.name}`"
              >
                <q-menu>
                  <q-list style="min-width: 200px">
                    <q-item v-close-popup clickable @click="openRoomForm(props.row)">
                      <q-item-section avatar><q-icon name="edit" /></q-item-section>
                      <q-item-section>Modifier</q-item-section>
                    </q-item>
                    <q-separator />
                    <q-item
                      v-close-popup
                      clickable
                      class="text-negative"
                      @click="confirmDeleteRoom(props.row)"
                    >
                      <q-item-section avatar><q-icon name="delete" /></q-item-section>
                      <q-item-section>Supprimer</q-item-section>
                    </q-item>
                  </q-list>
                </q-menu>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-tab-panel>

      <q-tab-panel name="buildings" class="q-px-none">
        <div class="text-body2 text-grey-8 q-mb-sm" style="max-width: 760px">
          Un bâtiment porte l'emplacement — dans les mots que les agents remontent — et regroupe des
          salles. Il n'a ni cycle ni responsable propres.
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
        >
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
                :aria-label="`Actions pour ${props.row.name}`"
              >
                <q-menu>
                  <q-list style="min-width: 200px">
                    <q-item v-close-popup clickable @click="openBuildingForm(props.row)">
                      <q-item-section avatar><q-icon name="edit" /></q-item-section>
                      <q-item-section>Modifier</q-item-section>
                    </q-item>
                    <q-separator />
                    <q-item
                      v-close-popup
                      clickable
                      class="text-negative"
                      @click="confirmDeleteBuilding(props.row)"
                    >
                      <q-item-section avatar><q-icon name="delete" /></q-item-section>
                      <q-item-section>Supprimer</q-item-section>
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
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import BuildingFormDialog from 'src/components/room/BuildingFormDialog.vue';
import RoomFormDialog from 'src/components/room/RoomFormDialog.vue';
import { listLocations } from 'src/services/machines';
import {
  deleteBuilding,
  deleteRoom,
  getRoomConfig,
  listBuildings,
  listRooms,
  ROOM_SOURCE_LABELS,
  syncDirectory,
  type Building,
  type Room,
  type RoomConfig,
} from 'src/services/rooms';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';

const $q = useQuasar();
const router = useRouter();
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

const config = ref<RoomConfig | null>(null);
const syncing = ref(false);
const sourceLabel = computed(() =>
  config.value ? (ROOM_SOURCE_LABELS[config.value.source] ?? config.value.source) : '',
);

async function loadConfig() {
  try {
    config.value = await getRoomConfig();
  } catch {
    // Without it the page assumes manual, which only ever shows a 409.
  }
}

async function sync() {
  syncing.value = true;
  try {
    const res = await syncDirectory();
    $q.notify({
      type: 'positive',
      message: `${res.placed} poste(s) rangé(s), ${res.unplaced} retiré(s), ${res.rooms_created} salle(s) créée(s)`,
    });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Resynchronisation impossible') });
  } finally {
    syncing.value = false;
  }
}

const roomFormOpen = ref(false);
const editingRoom = ref<Room | null>(null);
const buildingFormOpen = ref(false);
const editingBuilding = ref<Building | null>(null);

const roomColumns: QTableColumn<Room>[] = [
  { name: 'name', label: 'Salle', field: 'name', align: 'left' },
  { name: 'building', label: 'Bâtiment', field: (r) => r.building?.name ?? '', align: 'left' },
  {
    name: 'effective_location',
    label: 'Emplacement',
    field: 'effective_location',
    align: 'left',
  },
  { name: 'machine_count', label: 'Postes', field: 'machine_count', align: 'center' },
  { name: 'mismatch_count', label: 'Divergents', field: 'mismatch_count', align: 'center' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

const buildingColumns: QTableColumn<Building>[] = [
  { name: 'name', label: 'Bâtiment', field: 'name', align: 'left' },
  { name: 'location', label: 'Emplacement', field: 'location', align: 'left' },
  { name: 'room_count', label: 'Salles', field: 'room_count', align: 'center' },
  { name: 'machine_count', label: 'Postes', field: 'machine_count', align: 'center' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

async function reload() {
  loading.value = true;
  try {
    [rooms.value, buildings.value] = await Promise.all([listRooms(), listBuildings()]);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
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

function goRoom(room: Room) {
  void router.push({ name: 'room-detail', params: { id: room.id } });
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
  $q.dialog({
    title: 'Supprimer la salle',
    message:
      `Supprimer <b>${room.name}</b> ?<br>` +
      `Ses ${room.machine_count} poste(s) restent dans le parc, sans salle.`,
    html: true,
    cancel: true,
    ok: { label: 'Supprimer', color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        await deleteRoom(room.id);
        $q.notify({ type: 'positive', message: 'Salle supprimée' });
        await reload();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Suppression impossible') });
      }
    })();
  });
}

function confirmDeleteBuilding(building: Building) {
  $q.dialog({
    title: 'Supprimer le bâtiment',
    message:
      `Supprimer <b>${building.name}</b> ?<br>` +
      `Ses ${building.room_count} salle(s) restent, sans bâtiment, et gardent son emplacement.`,
    html: true,
    cancel: true,
    ok: { label: 'Supprimer', color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        await deleteBuilding(building.id);
        $q.notify({ type: 'positive', message: 'Bâtiment supprimé' });
        await reload();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Suppression impossible') });
      }
    })();
  });
}

onMounted(() => {
  void reload();
  void loadLocations();
  void loadConfig();
});
</script>
