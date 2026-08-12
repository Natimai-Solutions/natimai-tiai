<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn flat dense round icon="arrow_back" :to="{ name: 'machines' }" class="q-mr-sm" />
      <div class="text-h5">{{ title }}</div>
      <q-space />
      <q-btn-dropdown color="primary" dense label="Action" icon="bolt" :disable="!machine">
        <q-list>
          <q-item
            v-for="action in actions"
            :key="action.type"
            v-close-popup
            clickable
            @click="runOne(action.type)"
          >
            <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
            <q-item-section>{{ action.label }}</q-item-section>
          </q-item>
        </q-list>
      </q-btn-dropdown>
      <q-btn
        flat
        dense
        color="primary"
        icon="merge"
        label="Fusionner"
        class="q-ml-sm"
        :disable="!machine"
        @click="openMerge"
      />
      <q-btn
        flat
        dense
        color="negative"
        icon="key_off"
        label="Révoquer le token"
        class="q-ml-sm"
        :disable="!machine"
        @click="confirmRevoke"
      />
    </div>

    <q-banner v-if="machine?.needs_verification" class="bg-orange-2 q-mb-md" rounded>
      <template #avatar><q-icon name="warning" color="orange" /></template>
      Empreinte divergente : ce poste nécessite une vérification manuelle (clone, swap matériel ou
      ré-image).
      <template #action>
        <q-btn flat dense label="Fusionner un doublon" @click="openMerge" />
      </template>
    </q-banner>

    <div class="row q-col-gutter-md">
      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">Identité</q-card-section>
          <q-separator />
          <q-list dense>
            <q-item v-for="r in identityRows" :key="r.label">
              <q-item-section>{{ r.label }}</q-item-section>
              <q-item-section side class="text-black">{{ r.value }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">État Defender</q-card-section>
          <q-separator />
          <q-list dense>
            <q-item v-for="r in defenderRows" :key="r.label">
              <q-item-section>{{ r.label }}</q-item-section>
              <q-item-section side class="text-black">{{ r.value }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>
    </div>

    <q-card flat bordered class="q-mt-md">
      <q-card-section class="text-subtitle1">Historique des menaces</q-card-section>
      <q-separator />
      <q-table
        :rows="threats"
        :columns="threatColumns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[10, 25, 50]"
        no-data-label="Aucune menace détectée."
      >
        <template #body-cell-detected_at="props">
          <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
        </template>
      </q-table>
    </q-card>

    <q-card flat bordered class="q-mt-md">
      <q-card-section class="text-subtitle1">Dernières commandes</q-card-section>
      <q-separator />
      <q-table
        :rows="commands"
        :columns="commandColumns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[10, 25, 50]"
        no-data-label="Aucune commande."
      >
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge :color="statusColor(props.value)">{{ statusLabel(props.value) }}</q-badge>
            <q-btn
              v-if="props.row.error"
              flat
              dense
              round
              size="sm"
              icon="error_outline"
              color="negative"
              class="q-ml-xs"
              @click="showError(props.row)"
            >
              <q-tooltip>Voir l'erreur</q-tooltip>
            </q-btn>
          </q-td>
        </template>
        <template #body-cell-created_at="props">
          <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
        </template>
        <template #body-cell-finished_at="props">
          <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
        </template>
      </q-table>
    </q-card>

    <q-dialog v-model="mergeOpen">
      <q-card style="min-width: 420px; max-width: 90vw">
        <q-card-section class="text-h6">Fusionner un doublon</q-card-section>
        <q-card-section class="q-pt-none text-caption text-grey">
          Le poste choisi sera fusionné dans <b>{{ title }}</b> (conservé) : ses menaces et
          commandes y seront rattachées, puis il sera supprimé.
        </q-card-section>
        <q-separator />
        <q-list separator>
          <q-item v-for="d in duplicates" :key="d.id">
            <q-item-section>
              <q-item-label>{{ d.hostname || d.machine_uuid }}</q-item-label>
              <q-item-label caption>Vu le {{ formatDateTime(d.last_seen) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn dense color="primary" label="Fusionner ici" @click="doMerge(d)" />
            </q-item-section>
          </q-item>
          <q-item v-if="!duplicates.length">
            <q-item-section class="text-grey">
              Aucun doublon détecté (même SMBIOS UUID).
            </q-item-section>
          </q-item>
        </q-list>
        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Fermer" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="errorOpen">
      <q-card style="min-width: 420px; max-width: 90vw">
        <q-card-section class="text-h6">Détail de l'erreur</q-card-section>
        <q-card-section v-if="errorCommand" class="q-pt-none text-caption text-grey">
          {{ errorCommand.type }} — terminée le {{ formatDateTime(errorCommand.finished_at) }}
        </q-card-section>
        <q-separator />
        <q-card-section>
          <pre class="command-error">{{ errorCommand?.error }}</pre>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Fermer" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import {
  getDuplicates,
  getMachine,
  mergeMachines,
  revokeToken,
  type Machine,
  type MachineDetail,
} from 'src/services/machines';
import { listThreats, type Threat } from 'src/services/threats';
import {
  createCommands,
  listCommands,
  type Command,
  type CommandType,
} from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import { boolLabel, formatDateTime } from 'src/utils/format';

const props = defineProps<{ id: string }>();
const $q = useQuasar();

const machine = ref<MachineDetail | null>(null);
const threats = ref<Threat[]>([]);
const commands = ref<Command[]>([]);
const loading = ref(false);
const mergeOpen = ref(false);
const duplicates = ref<Machine[]>([]);
const errorOpen = ref(false);
const errorCommand = ref<Command | null>(null);

const actions: { type: CommandType; label: string; icon: string }[] = [
  { type: 'quick_scan', label: 'Scan rapide', icon: 'bolt' },
  { type: 'full_scan', label: 'Scan complet', icon: 'travel_explore' },
  { type: 'update_signatures', label: 'Mise à jour signatures', icon: 'sync' },
];

const title = computed(() => machine.value?.hostname || machine.value?.machine_uuid || 'Poste');

const identityRows = computed(() =>
  machine.value
    ? [
        { label: 'Nom', value: machine.value.hostname ?? '—' },
        { label: 'UUID machine', value: machine.value.machine_uuid },
        { label: 'Domaine', value: machine.value.domain ?? '—' },
        { label: 'OS', value: machine.value.os_version ?? '—' },
        { label: 'Version agent', value: machine.value.agent_version ?? '—' },
        { label: 'SMBIOS UUID', value: machine.value.smbios_uuid ?? '—' },
        { label: 'MachineGuid', value: machine.value.machine_guid ?? '—' },
        { label: 'Vu le', value: formatDateTime(machine.value.last_seen) },
      ]
    : [],
);

const defenderRows = computed(() =>
  machine.value
    ? [
        { label: 'Antivirus actif', value: boolLabel(machine.value.av_enabled) },
        { label: 'Protection temps réel', value: boolLabel(machine.value.rtp_enabled) },
        { label: 'À jour', value: boolLabel(machine.value.is_up_to_date) },
        { label: 'Version signatures', value: machine.value.signature_version ?? '—' },
        {
          label: 'Signatures à jour le',
          value: formatDateTime(machine.value.signature_last_updated),
        },
        { label: 'Âge signatures (j)', value: machine.value.signature_age_days ?? '—' },
        { label: 'Dernier scan rapide', value: formatDateTime(machine.value.last_quick_scan) },
        { label: 'Dernier scan complet', value: formatDateTime(machine.value.last_full_scan) },
      ]
    : [],
);

const threatColumns: QTableColumn<Threat>[] = [
  { name: 'threat_name', label: 'Menace', field: 'threat_name', align: 'left' },
  { name: 'severity', label: 'Sévérité', field: 'severity', align: 'left' },
  { name: 'status', label: 'Statut', field: 'status', align: 'left' },
  { name: 'detected_at', label: 'Détectée le', field: 'detected_at', align: 'left' },
];

const commandStatusColors: Record<string, string> = {
  pending: 'grey-7',
  delivered: 'blue-7',
  running: 'blue-7',
  succeeded: 'positive',
  failed: 'negative',
  expired: 'orange',
};

const commandStatusLabels: Record<string, string> = {
  pending: 'En attente',
  delivered: 'Transmise',
  running: 'En cours',
  succeeded: 'Réussie',
  failed: 'Échec',
  expired: 'Expirée',
};

function statusColor(status: string): string {
  return commandStatusColors[status] ?? 'grey-7';
}

function statusLabel(status: string): string {
  return commandStatusLabels[status] ?? status;
}

function showError(cmd: Command) {
  errorCommand.value = cmd;
  errorOpen.value = true;
}

const commandColumns: QTableColumn<Command>[] = [
  { name: 'type', label: 'Type', field: 'type', align: 'left' },
  { name: 'status', label: 'Statut', field: 'status', align: 'left' },
  { name: 'created_by', label: 'Par', field: 'created_by', align: 'left' },
  { name: 'created_at', label: 'Créée le', field: 'created_at', align: 'left' },
  { name: 'finished_at', label: 'Terminée le', field: 'finished_at', align: 'left' },
];

async function load() {
  loading.value = true;
  try {
    const [m, t, c] = await Promise.all([
      getMachine(props.id),
      listThreats({ machine_id: props.id }),
      listCommands({ machine_id: props.id }),
    ]);
    machine.value = m;
    threats.value = t.items;
    commands.value = c.items;
  } finally {
    loading.value = false;
  }
}

async function runOne(type: CommandType) {
  try {
    await createCommands({ type, machine_ids: [props.id] });
    $q.notify({ type: 'positive', message: 'Commande envoyée' });
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'envoi de la commande") });
  }
}

function confirmRevoke() {
  $q.dialog({
    title: 'Révoquer le token',
    message: 'Le poste devra se ré-enrôler. Continuer ?',
    cancel: true,
    persistent: true,
  }).onOk(() => {
    void doRevoke();
  });
}

async function doRevoke() {
  try {
    await revokeToken(props.id);
    $q.notify({ type: 'positive', message: 'Token révoqué' });
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec de la révocation') });
  }
}

async function openMerge() {
  try {
    duplicates.value = await getDuplicates(props.id);
    mergeOpen.value = true;
  } catch (e) {
    $q.notify({
      type: 'negative',
      message: apiErrorMessage(e, 'Échec du chargement des doublons'),
    });
  }
}

function doMerge(source: Machine) {
  $q.dialog({
    title: 'Fusionner les postes',
    message: `Fusionner « ${source.hostname || source.machine_uuid} » dans ce poste ? Cette action est irréversible.`,
    cancel: true,
    persistent: true,
  }).onOk(() => {
    void runMerge(source.id);
  });
}

async function runMerge(sourceId: string) {
  try {
    await mergeMachines(props.id, sourceId);
    $q.notify({ type: 'positive', message: 'Postes fusionnés' });
    mergeOpen.value = false;
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec de la fusion') });
  }
}

onMounted(load);
</script>

<style scoped>
.command-error {
  margin: 0;
  max-height: 50vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
</style>
