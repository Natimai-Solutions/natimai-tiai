<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn flat dense round icon="arrow_back" aria-label="Retour" :to="{ name: 'rooms' }" />
      <div class="text-h5 q-ml-sm">
        <template v-if="room">
          <span v-if="room.building" class="text-grey-7">{{ room.building.name }} › </span
          >{{ room.name }}
        </template>
        <span v-else>Salle</span>
      </div>
      <q-space />
      <template v-if="room && canWrite">
        <q-btn
          v-if="canPlace"
          flat
          dense
          color="primary"
          icon="playlist_add"
          label="Ajouter des postes"
          class="q-mr-sm"
          @click="openAdd"
        />
        <q-btn flat dense icon="edit" label="Modifier" class="q-mr-sm" @click="formOpen = true" />
      </template>
    </div>

    <q-card v-if="room" flat bordered class="q-mb-md" style="max-width: 640px">
      <q-card-section class="q-gutter-xs">
        <div class="row items-center">
          <div class="col-4 text-grey-7">Emplacement</div>
          <div class="col">
            {{ room.effective_location ?? '—' }}
            <span v-if="room.building && room.effective_location" class="text-caption text-grey">
              (hérité du bâtiment)
            </span>
          </div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-grey-7">Postes</div>
          <div class="col">
            {{ room.machine_count }}
            <q-badge v-if="room.mismatch_count" color="orange" class="q-ml-sm">
              {{ room.mismatch_count }} divergent(s)
            </q-badge>
          </div>
        </div>
        <div v-if="room.ad_key" class="row items-center">
          <div class="col-4 text-grey-7">Annuaire</div>
          <div class="col text-caption">{{ room.ad_key }}</div>
        </div>
        <div v-if="room.notes" class="row">
          <div class="col-4 text-grey-7">Notes</div>
          <div class="col" style="white-space: pre-line">{{ room.notes }}</div>
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
      @row-click="(_evt, row) => goMachine(row)"
    >
      <template #body-cell-hostname="props">
        <q-td :props="props">
          <q-icon
            :name="onlineIcon(props.row.is_online)"
            :color="onlineColor(props.row.is_online)"
            size="16px"
            class="q-mr-xs"
          />
          {{ props.value || props.row.machine_uuid }}
        </q-td>
      </template>
      <template #body-cell-location="props">
        <q-td :props="props">
          {{ props.value ?? '—' }}
          <q-icon
            v-if="props.row.location_mismatch"
            name="wrong_location"
            color="orange"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>L'agent déclare un autre emplacement que la salle</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-last_seen="props">
        <q-td :props="props">{{ timeAgoLabel(props.value) }}</q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right" @click.stop>
          <q-btn
            v-if="canPlace"
            flat
            dense
            round
            icon="remove_circle_outline"
            :aria-label="`Retirer ${props.row.hostname ?? ''} de la salle`"
            @click="remove(props.row)"
          >
            <q-tooltip>Retirer de la salle</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Adding postes: a search over the parc, multi-select. The room-less
         ones come first, but a poste of another room can be moved here too. -->
    <q-dialog v-model="addOpen">
      <q-card style="width: 560px; max-width: 95vw">
        <q-card-section class="text-h6">Ajouter des postes</q-card-section>
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
            label="Rechercher un poste (nom, IP, utilisateur…)"
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
                    {{ scope.opt.location ?? 'sans emplacement' }}
                    <span v-if="scope.opt.room_name"> · déjà en {{ scope.opt.room_name }}</span>
                    <span v-if="scope.opt.session_username">
                      · {{ scope.opt.session_username }}</span
                    >
                  </q-item-label>
                </q-item-section>
              </q-item>
            </template>
          </q-select>
          <div v-if="pickedMismatch.length" class="text-caption text-orange-9 q-mt-sm">
            {{ pickedMismatch.length }} poste(s) sélectionné(s) déclarent un autre emplacement que
            la salle ({{ room?.effective_location }}) : ils seront affectés et signalés.
          </div>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat label="Annuler" />
          <q-btn
            color="primary"
            label="Ajouter"
            :disable="!picked.length"
            :loading="adding"
            @click="addPicked"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

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
import { useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import RoomFormDialog from 'src/components/room/RoomFormDialog.vue';
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
import { onlineColor, onlineIcon, timeAgoLabel } from 'src/utils/format';

const props = defineProps<{ id: string }>();

const $q = useQuasar();
const router = useRouter();
const auth = useAuthStore();

const room = ref<Room | null>(null);
const machines = ref<Machine[]>([]);
const buildings = ref<Building[]>([]);
const locations = ref<string[]>([]);
const loading = ref(false);
const formOpen = ref(false);

const canWrite = computed(() => auth.can('room', 'write'));
// Moving postes by hand: the permission, and a server not in a directory mode.
const manualMode = ref(true);
const canPlace = computed(() => canWrite.value && manualMode.value);

const columns: QTableColumn<Machine>[] = [
  { name: 'hostname', label: 'Nom', field: 'hostname', align: 'left', sortable: true },
  { name: 'location', label: 'Emplacement (agent)', field: 'location', align: 'left' },
  {
    name: 'ip_address',
    label: 'Adresse IP',
    field: 'ip_address',
    align: 'left',
    format: (v: string | null) => v ?? '—',
  },
  {
    name: 'session',
    label: 'Session',
    field: 'session_username',
    align: 'left',
    format: (v: string | null) => v ?? '—',
  },
  { name: 'last_seen', label: 'Vu', field: 'last_seen', align: 'left', sortable: true },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

async function load() {
  loading.value = true;
  try {
    const [r, list] = await Promise.all([
      getRoom(props.id),
      listMachines({ room_id: props.id, sort_by: 'hostname', sort_desc: false, page_size: 200 }),
    ]);
    room.value = r;
    machines.value = list.items;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
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

function goMachine(m: Machine) {
  void router.push({ name: 'machine-detail', params: { id: m.id } });
}

async function remove(m: Machine) {
  try {
    await unassignMachines([m.id]);
    $q.notify({ type: 'positive', message: `${m.hostname ?? 'Poste'} retiré de la salle` });
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Retrait impossible') });
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
    $q.notify(placementNotification(res));
    addOpen.value = false;
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Affectation impossible') });
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

onMounted(() => {
  void load();
  void loadRefs();
});
</script>
