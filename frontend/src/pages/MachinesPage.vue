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
        placeholder="Nom, IP, antivirus ou UUID…"
        class="col-auto"
        style="min-width: 260px"
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
        v-model="antivirus"
        :options="antivirusOptions"
        emit-value
        map-options
        dense
        outlined
        class="col-auto"
        style="width: 200px"
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
          <template v-for="section in actionGroups" :key="section.group">
            <q-item-label header class="q-py-xs">{{ section.label }}</q-item-label>
            <q-item
              v-for="action in section.actions"
              :key="action.type"
              v-close-popup
              clickable
              @click="runBulk(action)"
            >
              <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
              <q-item-section>{{ action.label }}</q-item-section>
            </q-item>
          </template>
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
      <template #body-cell-antivirus="props">
        <q-td :props="props">
          <q-badge :color="antivirusColor(props.row.av_product_name, props.row.av_product_enabled)">
            {{ antivirusLabel(props.row.av_product_name) }}
          </q-badge>
          <q-tooltip>
            {{
              antivirusStatusLabel(
                props.row.av_product_name,
                props.row.av_product_enabled,
                props.row.av_product_signatures_up_to_date,
              )
            }}
          </q-tooltip>
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
import {
  listAntivirusProducts,
  listMachines,
  type Machine,
  type MachineStatus,
} from 'src/services/machines';
import { commandActionGroups, createCommands, type CommandAction } from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import {
  antivirusColor,
  antivirusLabel,
  antivirusStatusLabel,
  formatDateTime,
  sessionColor,
  sessionLabel,
  wuPendingColor,
  wuPendingLabel,
} from 'src/utils/format';

const $q = useQuasar();
const router = useRouter();

const rows = ref<Machine[]>([]);
const selected = ref<Machine[]>([]);
const loading = ref(false);
const search = ref('');
const domain = ref('');
const antivirus = ref<string | null>(null);
const status = ref<MachineStatus | null>(null);

// Filled from the fleet on mount: the products installed are data, not a list
// the console can know in advance. The count sits in the label so the dropdown
// doubles as an inventory of a mixed parc.
const antivirusOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous antivirus', value: null },
]);

const statusOptions = [
  { label: 'Tous statuts', value: null },
  { label: 'À jour', value: 'up_to_date' },
  { label: 'Non à jour', value: 'outdated' },
  { label: 'À vérifier', value: 'needs_verification' },
  { label: 'Inactif', value: 'inactive' },
];

// bulkOnly: the two diagnostics stay on the detail page. Their value is reading
// one machine's output; fired on a selection they queue a report per poste that
// nobody will open.
const actionGroups = commandActionGroups({ bulkOnly: true });

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
  // name ≠ field like the session column below: the cell renders the product and
  // its state together, while `field` keeps a sensible sort key. Sortable because
  // grouping a mixed parc by product is exactly what this column is for.
  {
    name: 'antivirus',
    label: 'Antivirus',
    field: 'av_product_name',
    align: 'left',
    sortable: true,
  },
  { name: 'signature_version', label: 'Signatures', field: 'signature_version', align: 'left' },
  { name: 'is_up_to_date', label: 'État', field: 'is_up_to_date', align: 'center' },
  {
    name: 'needs_verification',
    label: 'Vérif.',
    field: 'needs_verification',
    align: 'center',
  },
  // Sortable, and it is the sort that matters: "show me the postes furthest
  // behind" is the whole point of the column. A null count (never reported)
  // sorts apart from a zero, which is the distinction the badge makes too.
  {
    name: 'windows_update',
    label: 'MAJ Windows',
    field: 'wu_pending_count',
    align: 'center',
    sortable: true,
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
    if (antivirus.value) params.antivirus = antivirus.value;
    if (status.value) params.status = status.value;
    const data = await listMachines(params);
    rows.value = data.items;
  } finally {
    loading.value = false;
  }
}

async function loadAntivirusOptions() {
  try {
    const products = await listAntivirusProducts();
    antivirusOptions.value = [
      { label: 'Tous antivirus', value: null },
      ...products.map((p) => ({ label: `${p.name} (${p.count})`, value: p.name })),
    ];
  } catch {
    // A filter that failed to populate must not blank the machine list: the
    // dropdown simply keeps its "Tous antivirus" entry.
  }
}

function runBulk(action: CommandAction) {
  const ids = selected.value.map((m) => m.id);
  if (!ids.length) return;
  if (!action.confirm) {
    void sendBulk(action, ids);
    return;
  }
  // The count is the whole point of the confirmation here: "sfc sur 1 poste" and
  // "sfc sur 340 postes" are very different decisions.
  $q.dialog({
    title: action.label,
    message: [`Lancer « ${action.label} » sur ${ids.length} poste(s) ?`, action.hint]
      .filter(Boolean)
      .join(' '),
    cancel: true,
    persistent: true,
  }).onOk(() => {
    void sendBulk(action, ids);
  });
}

async function sendBulk(action: CommandAction, ids: string[]) {
  try {
    const res = await createCommands({ type: action.type, machine_ids: ids });
    $q.notify({ type: 'positive', message: `${res.count} commande(s) envoyée(s)` });
    selected.value = [];
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'envoi des commandes") });
  }
}

onMounted(() => {
  void reload();
  void loadAntivirusOptions();
});
</script>
