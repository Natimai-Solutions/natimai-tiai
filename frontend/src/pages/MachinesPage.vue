<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <div class="text-h5 col-auto">Postes</div>
      <q-space />
      <q-input
        v-model="search"
        dense
        outlined
        debounce="300"
        placeholder="Nom, IP ou UUID…"
        class="col-auto"
        style="min-width: 220px"
        @update:model-value="reload"
      >
        <template #append><q-icon name="search" /></template>
      </q-input>
      <q-input
        v-model="domain"
        dense
        outlined
        debounce="300"
        placeholder="Domaine"
        class="col-auto"
        style="width: 160px"
        @update:model-value="reload"
      />
      <q-select
        v-model="status"
        :options="statusOptions"
        emit-value
        map-options
        dense
        outlined
        class="col-auto"
        style="width: 160px"
        @update:model-value="reload"
      />
    </div>

    <div v-if="selected.length" class="row items-center q-mb-sm">
      <div class="text-caption text-grey q-mr-md">{{ selected.length }} sélectionné(s)</div>
      <q-btn-dropdown color="primary" dense label="Actions de masse" icon="bolt">
        <q-list>
          <q-item
            v-for="action in actions"
            :key="action.type"
            v-close-popup
            clickable
            @click="runBulk(action.type)"
          >
            <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
            <q-item-section>{{ action.label }}</q-item-section>
          </q-item>
        </q-list>
      </q-btn-dropdown>
    </div>

    <q-table
      v-model:selected="selected"
      :rows="rows"
      :columns="columns"
      row-key="id"
      selection="multiple"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      @row-click="(_evt, row) => goDetail(row)"
    >
      <template #body-cell-is_up_to_date="props">
        <q-td :props="props">
          <q-badge :color="props.value ? 'positive' : 'negative'">
            {{ props.value ? 'À jour' : 'Non à jour' }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-needs_verification="props">
        <q-td :props="props">
          <q-badge v-if="props.value" color="orange">À vérifier</q-badge>
          <span v-else>—</span>
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
      <template #body-cell-last_seen="props">
        <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import { listMachines, type Machine, type MachineStatus } from 'src/services/machines';
import { createCommands, type CommandType } from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import { formatDateTime, sessionColor, sessionLabel } from 'src/utils/format';

const $q = useQuasar();
const router = useRouter();

const rows = ref<Machine[]>([]);
const selected = ref<Machine[]>([]);
const loading = ref(false);
const search = ref('');
const domain = ref('');
const status = ref<MachineStatus | null>(null);

const statusOptions = [
  { label: 'Tous statuts', value: null },
  { label: 'À jour', value: 'up_to_date' },
  { label: 'Non à jour', value: 'outdated' },
  { label: 'À vérifier', value: 'needs_verification' },
  { label: 'Inactif', value: 'inactive' },
];

const actions: { type: CommandType; label: string; icon: string }[] = [
  { type: 'quick_scan', label: 'Scan rapide', icon: 'bolt' },
  { type: 'full_scan', label: 'Scan complet', icon: 'travel_explore' },
  { type: 'update_signatures', label: 'Mise à jour signatures', icon: 'sync' },
];

const columns: QTableColumn<Machine>[] = [
  { name: 'hostname', label: 'Nom', field: 'hostname', align: 'left', sortable: true },
  { name: 'domain', label: 'Domaine', field: 'domain', align: 'left', sortable: true },
  // Not sortable: a string sort would put 192.168.1.10 before 192.168.1.9, and
  // an octet-aware comparator is not worth it on a column people search, not sort.
  {
    name: 'ip_address',
    label: 'Adresse IP',
    field: 'ip_address',
    align: 'left',
    format: (val: string | null) => val ?? '—',
  },
  { name: 'os_version', label: 'OS', field: 'os_version', align: 'left' },
  { name: 'signature_version', label: 'Signatures', field: 'signature_version', align: 'left' },
  { name: 'is_up_to_date', label: 'État', field: 'is_up_to_date', align: 'center' },
  {
    name: 'needs_verification',
    label: 'Vérif.',
    field: 'needs_verification',
    align: 'center',
  },
  // name ≠ field on purpose: the cell renders presence *and* username, while
  // `field` still gives the sort a sensible key (present / absent / unknown).
  {
    name: 'session',
    label: 'Session',
    field: 'session_user_present',
    align: 'center',
    sortable: true,
  },
  { name: 'last_seen', label: 'Vu le', field: 'last_seen', align: 'left', sortable: true },
];

function goDetail(row: Machine) {
  void router.push({ name: 'machine-detail', params: { id: row.id } });
}

async function reload() {
  loading.value = true;
  try {
    const params: Parameters<typeof listMachines>[0] = {};
    if (search.value) params.search = search.value;
    if (domain.value) params.domain = domain.value;
    if (status.value) params.status = status.value;
    const data = await listMachines(params);
    rows.value = data.items;
  } finally {
    loading.value = false;
  }
}

async function runBulk(type: CommandType) {
  const ids = selected.value.map((m) => m.id);
  if (!ids.length) return;
  try {
    const res = await createCommands({ type, machine_ids: ids });
    $q.notify({ type: 'positive', message: `${res.count} commande(s) envoyée(s)` });
    selected.value = [];
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'envoi des commandes") });
  }
}

onMounted(reload);
</script>
