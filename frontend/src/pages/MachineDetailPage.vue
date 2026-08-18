<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn flat dense round icon="arrow_back" :to="{ name: 'machines' }" class="q-mr-sm" />
      <div class="text-h5">{{ title }}</div>
      <q-space />
      <q-btn-dropdown color="primary" dense label="Action" icon="bolt" :disable="!machine">
        <q-list>
          <template v-for="section in actionGroups" :key="section.group">
            <q-item-label header class="q-py-xs">{{ section.label }}</q-item-label>
            <q-item
              v-for="action in section.actions"
              :key="action.type"
              v-close-popup
              clickable
              @click="runOne(action)"
            >
              <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
              <q-item-section>{{ action.label }}</q-item-section>
            </q-item>
          </template>
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

      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1 row items-center">
            Windows Update
            <q-space />
            <q-badge v-if="machine?.wu_reboot_required" color="orange" class="q-ml-sm">
              Redémarrage requis
            </q-badge>
          </q-card-section>
          <q-separator />
          <q-list dense>
            <q-item v-for="r in windowsUpdateRows" :key="r.label">
              <q-item-section>{{ r.label }}</q-item-section>
              <q-item-section side class="text-black">{{ r.value }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">
            Antivirus enregistré
            <div class="text-caption text-grey">
              Vu par le Security Center de Windows — la seule source qui voit un antivirus tiers.
            </div>
          </q-card-section>
          <q-separator />
          <q-list dense>
            <q-item v-for="r in antivirusRows" :key="r.label">
              <q-item-section>{{ r.label }}</q-item-section>
              <q-item-section side class="text-black">{{ r.value }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>
    </div>

    <q-card v-if="machine?.pending_updates?.length" flat bordered class="q-mt-md">
      <q-card-section class="text-subtitle1">
        Mises à jour en attente
        <div class="text-caption text-grey">
          Relevé au dernier passage de l'agent ({{ formatDateTime(machine.wu_last_search) }}) — «
          Rechercher les mises à jour » force un nouveau relevé.
        </div>
      </q-card-section>
      <q-separator />
      <q-table
        :rows="machine.pending_updates"
        :columns="updateColumns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[10, 25, 50]"
        no-data-label="Aucune mise à jour en attente."
      >
        <template #body-cell-severity="props">
          <q-td :props="props">
            <q-badge :color="wuSeverityColor(props.value)">
              {{ wuSeverityLabel(props.value) }}
            </q-badge>
          </q-td>
        </template>
        <template #body-cell-type="props">
          <q-td :props="props">{{ wuTypeLabel(props.value) }}</q-td>
        </template>
        <template #body-cell-size_mb="props">
          <q-td :props="props">{{ wuSizeLabel(props.value) }}</q-td>
        </template>
        <template #body-cell-is_downloaded="props">
          <q-td :props="props">
            <q-icon
              :name="props.value ? 'download_done' : 'cloud_download'"
              :color="props.value ? 'positive' : 'grey-6'"
            />
            <q-tooltip>
              {{ props.value ? 'Déjà téléchargée sur le poste' : 'Reste à télécharger' }}
            </q-tooltip>
          </q-td>
        </template>
        <template #body-cell-first_seen="props">
          <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
        </template>
      </q-table>
    </q-card>

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
        <template #body-cell-severity="props">
          <q-td :props="props">
            <q-badge :color="threatSeverityColor(props.value)">
              {{ threatSeverityLabel(props.value) }}
            </q-badge>
          </q-td>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge :color="threatStatusColor(props.value)">
              {{ threatStatusLabel(props.value) }}
            </q-badge>
          </q-td>
        </template>
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
        <template #body-cell-type="props">
          <q-td :props="props">{{ commandTypeLabel(props.value) }}</q-td>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge :color="statusColor(props.value)">{{ statusLabel(props.value) }}</q-badge>
            <q-btn
              v-if="props.row.result_output"
              flat
              dense
              round
              size="sm"
              icon="search"
              color="primary"
              class="q-ml-xs"
              @click="showDetail(props.row, 'output')"
            >
              <q-tooltip>Voir le résultat</q-tooltip>
            </q-btn>
            <q-btn
              v-if="props.row.error"
              flat
              dense
              round
              size="sm"
              icon="error_outline"
              color="negative"
              class="q-ml-xs"
              @click="showDetail(props.row, 'error')"
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

    <q-dialog v-model="detailOpen">
      <q-card style="min-width: 480px; max-width: 90vw">
        <q-card-section class="text-h6">
          {{ detailKind === 'error' ? "Détail de l'erreur" : 'Résultat de la commande' }}
        </q-card-section>
        <q-card-section v-if="detailCommand" class="q-pt-none text-caption text-grey">
          {{ commandTypeLabel(detailCommand.type) }} — terminée le
          {{ formatDateTime(detailCommand.finished_at) }}
        </q-card-section>
        <q-separator />
        <q-card-section>
          <pre class="command-output">{{ detailText }}</pre>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat icon="content_copy" label="Copier" @click="copyDetail" />
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
  type PendingUpdate,
} from 'src/services/machines';
import { listThreats, type Threat } from 'src/services/threats';
import {
  commandActionGroups,
  commandTypeLabel,
  createCommands,
  listCommands,
  type Command,
  type CommandAction,
} from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import {
  antivirusLabel,
  boolLabel,
  formatDateTime,
  onlineLabel,
  runningModeLabel,
  sessionLabel,
  sessionTypeLabel,
  threatSeverityColor,
  threatSeverityLabel,
  threatStatusColor,
  threatStatusLabel,
  timeAgoLabel,
  wuPendingLabel,
  wuSeverityColor,
  wuSeverityLabel,
  wuSizeLabel,
  wuTypeLabel,
} from 'src/utils/format';

const props = defineProps<{ id: string }>();
const $q = useQuasar();

const machine = ref<MachineDetail | null>(null);
const threats = ref<Threat[]>([]);
const commands = ref<Command[]>([]);
const loading = ref(false);
const mergeOpen = ref(false);
const duplicates = ref<Machine[]>([]);
const detailOpen = ref(false);
const detailCommand = ref<Command | null>(null);
const detailKind = ref<'output' | 'error'>('output');

// The whole catalogue here, diagnostics included: reading one machine's
// gpresult or ipconfig is exactly what this page is for.
const actionGroups = commandActionGroups();

const detailText = computed(() =>
  detailKind.value === 'error'
    ? (detailCommand.value?.error ?? '')
    : (detailCommand.value?.result_output ?? ''),
);

const title = computed(() => machine.value?.hostname || machine.value?.machine_uuid || 'Poste');

const identityRows = computed(() =>
  machine.value
    ? [
        { label: 'Nom', value: machine.value.hostname ?? '—' },
        { label: 'UUID machine', value: machine.value.machine_uuid },
        { label: 'Domaine', value: machine.value.domain ?? '—' },
        { label: 'Adresse IP', value: machine.value.ip_address ?? '—' },
        { label: 'OS', value: machine.value.os_version ?? '—' },
        { label: 'Version agent', value: machine.value.agent_version ?? '—' },
        { label: 'SMBIOS UUID', value: machine.value.smbios_uuid ?? '—' },
        { label: 'MachineGuid', value: machine.value.machine_guid ?? '—' },
        {
          label: 'Session',
          value: sessionLabel(machine.value.session_user_present, machine.value.session_username),
        },
        {
          label: 'Type de session',
          value: sessionTypeLabel(machine.value.session_state, machine.value.session_is_remote),
        },
        // Kept adjacent to the two rows above: the session is only as fresh as
        // the last heartbeat, and this is the timestamp that says how fresh.
        // The presence rides along rather than taking a row of its own — it is
        // read from this very timestamp, and it is what says whether a command
        // queued here will be picked up now or at the poste's next boot.
        {
          label: 'Vu le',
          value: `${formatDateTime(machine.value.last_seen)} (${timeAgoLabel(
            machine.value.last_seen,
          )}) — ${onlineLabel(machine.value.is_online)}`,
        },
      ]
    : [],
);

const defenderRows = computed(() =>
  machine.value
    ? [
        { label: 'Defender actif', value: boolLabel(machine.value.av_enabled) },
        { label: 'Protection temps réel', value: boolLabel(machine.value.rtp_enabled) },
        // Placed right under the two flags above: this is the row that explains
        // them reading "Non" on a machine that is in fact protected, a
        // third-party antivirus having pushed Defender into passive mode.
        { label: "Mode d'exécution", value: runningModeLabel(machine.value.running_mode) },
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

const antivirusRows = computed(() =>
  machine.value
    ? [
        { label: 'Produit', value: antivirusLabel(machine.value.av_product_name) },
        { label: 'Protection active', value: boolLabel(machine.value.av_product_enabled) },
        // The Security Center exposes a freshness bit and nothing else — no
        // version, no date, which is why this card carries no scan or update
        // action for a third-party product.
        {
          label: 'Signatures à jour',
          value: boolLabel(machine.value.av_product_signatures_up_to_date),
        },
        { label: 'Est Defender', value: boolLabel(machine.value.av_product_is_defender) },
      ]
    : [],
);

const windowsUpdateRows = computed(() =>
  machine.value
    ? [
        { label: 'Mises à jour en attente', value: wuPendingLabel(machine.value.wu_pending_count) },
        { label: 'Redémarrage requis', value: boolLabel(machine.value.wu_reboot_required) },
        // Windows' own timestamps, not the agent's: they say when the machine
        // last managed to talk to its update source, which is what distinguishes
        // "nothing to install" from "has not checked since March".
        { label: 'Dernière recherche', value: formatDateTime(machine.value.wu_last_search) },
        { label: 'Dernière installation', value: formatDateTime(machine.value.wu_last_install) },
      ]
    : [],
);

const updateColumns: QTableColumn<PendingUpdate>[] = [
  { name: 'kb', label: 'KB', field: 'kb', align: 'left', format: (v: string | null) => v ?? '—' },
  { name: 'title', label: 'Titre', field: 'title', align: 'left' },
  // Sortable, but the server already returns them critical-first: MSRC's own
  // vocabulary sorts alphabetically as critical < important < low < moderate,
  // which is worse than useless, so the default order is the one to trust.
  { name: 'severity', label: 'Sévérité', field: 'severity', align: 'left' },
  { name: 'type', label: 'Type', field: 'type', align: 'left', sortable: true },
  { name: 'size_mb', label: 'Taille', field: 'size_mb', align: 'right', sortable: true },
  { name: 'is_downloaded', label: 'Téléchargée', field: 'is_downloaded', align: 'center' },
  // How long this machine has been sitting on the update — the column that
  // turns a list of KBs into "this poste has been behind since June".
  {
    name: 'first_seen',
    label: 'En attente depuis',
    field: 'first_seen',
    align: 'left',
    sortable: true,
  },
];

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

function showDetail(cmd: Command, kind: 'output' | 'error') {
  detailCommand.value = cmd;
  detailKind.value = kind;
  detailOpen.value = true;
}

// An ipconfig /all or a gpresult dump is meant to be pasted into a ticket, and
// selecting it out of a scrolling <pre> is a chore.
async function copyDetail() {
  try {
    await navigator.clipboard.writeText(detailText.value);
    $q.notify({ type: 'positive', message: 'Copié dans le presse-papiers' });
  } catch {
    $q.notify({ type: 'negative', message: 'Copie impossible' });
  }
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

function runOne(action: CommandAction) {
  if (!action.confirm) {
    void send(action);
    return;
  }
  $q.dialog({
    title: action.label,
    message: [`Lancer « ${action.label} » sur ce poste ?`, action.hint].filter(Boolean).join(' '),
    cancel: true,
    persistent: true,
  }).onOk(() => {
    void send(action);
  });
}

async function send(action: CommandAction) {
  try {
    await createCommands({ type: action.type, machine_ids: [props.id] });
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
.command-output {
  margin: 0;
  max-height: 50vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
</style>
