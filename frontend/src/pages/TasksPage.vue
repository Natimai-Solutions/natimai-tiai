<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <div class="text-h5 col-auto">Mes tâches</div>
      <q-space />
      <q-btn-toggle
        v-model="scope"
        dense
        no-caps
        toggle-color="primary"
        :options="scopeOptions"
        @update:model-value="reload"
      />
    </div>

    <div class="text-body2 text-grey-8 q-mb-md" style="max-width: 760px">
      Les vérifications demandées sur des postes et les maintenances à faire : les vôtres, celles
      que personne n'a encore prises, ou toutes.
    </div>
    <div class="text-h6 q-mb-sm">Vérifications</div>

    <q-table
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[0]"
      hide-pagination
      flat
      bordered
      no-data-label="Rien à faire."
      @row-click="(_evt, row) => goMachine(row)"
    >
      <template #body-cell-machine="props">
        <q-td :props="props">
          <div>{{ props.row.machine?.hostname ?? '—' }}</div>
          <div class="text-caption text-grey">
            {{ placeLabel(props.row.machine) }}
          </div>
        </q-td>
      </template>
      <template #body-cell-instructions="props">
        <q-td :props="props" style="white-space: pre-line; max-width: 420px">
          {{ props.value || '—' }}
        </q-td>
      </template>
      <template #body-cell-assigned_to="props">
        <q-td :props="props">
          <span v-if="props.row.assigned_to">{{ props.row.assigned_to.name }}</span>
          <q-badge v-else color="grey-6">à prendre</q-badge>
        </q-td>
      </template>
      <template #body-cell-created_at="props">
        <q-td :props="props">
          {{ timeAgoLabel(props.value) }}
          <div class="text-caption text-grey">par {{ props.row.requested_by }}</div>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right" @click.stop>
          <template v-if="canWrite">
            <q-btn
              flat
              dense
              color="primary"
              label="Clore"
              icon="task_alt"
              class="q-mr-xs"
              @click="openClose(props.row)"
            />
            <q-btn flat dense round icon="more_vert" aria-label="Autres actions">
              <q-menu>
                <q-list style="min-width: 200px">
                  <q-item
                    v-if="!props.row.assigned_to || props.row.assigned_to.id !== auth.user?.id"
                    v-close-popup
                    clickable
                    @click="takeOver(props.row)"
                  >
                    <q-item-section avatar><q-icon name="person" /></q-item-section>
                    <q-item-section>Me l'affecter</q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable @click="openEdit(props.row)">
                    <q-item-section avatar><q-icon name="edit" /></q-item-section>
                    <q-item-section>Réaffecter / modifier</q-item-section>
                  </q-item>
                </q-list>
              </q-menu>
            </q-btn>
          </template>
        </q-td>
      </template>
    </q-table>

    <!-- Maintenance: rooms with something due, then the loose postes. -->
    <div v-if="auth.can('maintenance', 'read')" class="q-mt-xl">
      <div class="row items-center q-mb-sm">
        <div class="text-h6">Maintenances à faire</div>
        <q-space />
        <div v-if="due" class="text-caption text-grey">
          {{ due.overdue }} en retard · {{ due.due_soon }} à échéance
        </div>
      </div>
      <q-list v-if="due && (due.rooms.length || due.machines.length)" bordered separator>
        <q-expansion-item
          v-for="r in due.rooms"
          :key="r.id"
          :label="r.name"
          group="rooms"
          expand-separator
        >
          <template #header>
            <q-item-section>
              <q-item-label>
                <span v-if="r.building_name" class="text-grey-7">{{ r.building_name }} › </span
                >{{ r.name }}
              </q-item-label>
              <q-item-label caption>
                {{ r.total }} poste(s) · cycle {{ r.cycle_days }} jours ·
                {{ r.owner ? r.owner.name : 'sans responsable' }}
                {{ r.next_due_at ? ` · prochaine échéance ${formatDateTime(r.next_due_at)}` : '' }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <div>
                <q-badge v-if="r.overdue" color="negative" class="q-mr-xs"
                  >{{ r.overdue }} en retard</q-badge
                >
                <q-badge v-if="r.due_soon" color="orange" class="q-mr-xs"
                  >{{ r.due_soon }} à échéance</q-badge
                >
                <q-badge v-if="!r.overdue && !r.due_soon" color="positive">à jour</q-badge>
              </div>
            </q-item-section>
          </template>
          <q-card>
            <q-card-section class="q-pt-none">
              <div class="row q-mb-sm">
                <q-space />
                <q-btn
                  flat
                  dense
                  icon="meeting_room"
                  label="Voir la salle"
                  class="q-mr-sm"
                  :to="{ name: 'room-detail', params: { id: r.id } }"
                />
                <q-btn
                  v-if="canMaintain"
                  dense
                  color="primary"
                  icon="build"
                  label="Effectuer la maintenance"
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
          v-for="m in due.machines"
          :key="m.id"
          clickable
          :to="{ name: 'machine-detail', params: { id: m.id } }"
        >
          <q-item-section>
            <q-item-label>{{ m.hostname ?? m.id }}</q-item-label>
            <q-item-label caption
              >sans salle · {{ m.owner ? m.owner.name : 'sans responsable' }}</q-item-label
            >
          </q-item-section>
          <q-item-section side>
            <q-badge :color="maintenanceStateColor(m.state)" :label="stateWithDate(m)" />
          </q-item-section>
        </q-item>
      </q-list>
      <div v-else-if="due" class="text-grey">Rien à faire.</div>
    </div>

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
import { useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import CheckCloseDialog from 'src/components/check/CheckCloseDialog.vue';
import CheckRequestDialog from 'src/components/check/CheckRequestDialog.vue';
import MaintenanceSessionDialog from 'src/components/maintenance/MaintenanceSessionDialog.vue';
import {
  getDue,
  maintenanceStateColor,
  maintenanceStateLabel,
  type Due,
  type DueMachine,
  type DueRoom,
} from 'src/services/maintenance';
import {
  listChecks,
  updateCheck,
  type Check,
  type CheckMachineRef,
  type CheckPayload,
} from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime, timeAgoLabel } from 'src/utils/format';

const $q = useQuasar();
const router = useRouter();
const auth = useAuthStore();

const scope = ref<'me' | 'none' | 'all'>('me');
const scopeOptions = [
  { label: 'Les miennes', value: 'me' },
  { label: 'À prendre', value: 'none' },
  { label: 'Toutes', value: 'all' },
];
const rows = ref<Check[]>([]);
const loading = ref(false);
const canWrite = computed(() => auth.can('check', 'write'));

const columns: QTableColumn<Check>[] = [
  { name: 'machine', label: 'Poste', field: (r) => r.machine?.hostname ?? '', align: 'left' },
  { name: 'instructions', label: 'Consignes', field: 'instructions', align: 'left' },
  {
    name: 'assigned_to',
    label: 'Affectée à',
    field: (r) => r.assigned_to?.name ?? '',
    align: 'left',
  },
  { name: 'created_at', label: 'Demandée', field: 'created_at', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

function placeLabel(m: CheckMachineRef | null): string {
  if (!m) return '';
  const parts = [m.building_name, m.room_name].filter(Boolean);
  const place = parts.join(' › ');
  if (place && m.location) return `${place} · ${m.location}`;
  return place || m.location || 'sans salle';
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
  })),
);

function stateWithDate(m: DueMachine): string {
  const label = maintenanceStateLabel(m.state);
  return m.due_at ? `${label} · ${formatDateTime(m.due_at)}` : label;
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
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Maintenances indisponibles') });
  }
}

async function reload() {
  loading.value = true;
  void loadDue();
  try {
    const res = await listChecks({
      open: true,
      ...(scope.value === 'all' ? {} : { assigned_to: scope.value }),
      page_size: 200,
    });
    rows.value = res.items;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
  } finally {
    loading.value = false;
  }
}

function goMachine(check: Check) {
  void router.push({ name: 'machine-detail', params: { id: check.machine_id } });
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
  $q.notify({ type: 'positive', message: 'Demande mise à jour' });
  await reload();
}
async function takeOver(check: Check) {
  if (!auth.user) return;
  try {
    await updateCheck(check.id, { assigned_to_id: auth.user.id });
    $q.notify({ type: 'positive', message: 'Vérification affectée à vous' });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Affectation impossible') });
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
