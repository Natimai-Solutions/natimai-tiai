<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn
        flat
        dense
        round
        icon="arrow_back"
        :to="{ name: 'machines', query: backQuery }"
        class="q-mr-sm"
      >
        <q-tooltip>
          {{ fromSearch ? 'Retour aux résultats de la recherche' : 'Retour aux postes' }}
        </q-tooltip>
      </q-btn>
      <div class="text-h5 row items-center no-wrap">
        <!-- Leading, same dot as the list: the fiche answers « allumé ? » at a glance too. -->
        <q-icon
          v-if="machine"
          :name="onlineIcon(machine.is_online)"
          :color="onlineColor(machine.is_online)"
          size="14px"
          class="q-mr-sm"
        >
          <q-tooltip>
            {{ onlineLabel(machine.is_online) }} — dernier contact
            {{ timeAgoLabel(machine.last_seen) }}
          </q-tooltip>
        </q-icon>
        {{ title }}
      </div>
      <!-- Only when the fiche was opened from a list query: elsewhere there is
           no search to walk, and dead arrows would be worse than none. -->
      <template v-if="fromSearch">
        <q-btn
          flat
          dense
          round
          icon="chevron_left"
          class="q-ml-md"
          :disable="!previousMachine"
          @click="goPrevious"
        >
          <q-tooltip>
            {{
              previousMachine
                ? `Précédent : ${previousMachine.hostname || previousMachine.machine_uuid}`
                : 'Premier résultat'
            }}
          </q-tooltip>
        </q-btn>
        <q-btn flat dense round icon="chevron_right" :disable="!nextMachine" @click="goNext">
          <q-tooltip>
            {{
              nextMachine
                ? `Suivant : ${nextMachine.hostname || nextMachine.machine_uuid}`
                : 'Dernier résultat'
            }}
          </q-tooltip>
        </q-btn>
        <div v-if="positionLabel" class="text-caption text-grey q-ml-sm">
          {{ positionLabel }}
        </div>
      </template>
      <q-space />
      <div v-if="lastRefreshedAt" class="text-caption text-grey q-mr-sm">
        Actualisé à {{ lastRefreshLabel }}
      </div>
      <q-btn flat dense round icon="refresh" :loading="loading" class="q-mr-sm" @click="load">
        <q-tooltip>{{ autoRefreshHint }}</q-tooltip>
      </q-btn>
      <q-btn-dropdown
        v-if="actionGroups.length"
        color="primary"
        dense
        label="Action"
        icon="bolt"
        :disable="!machine"
      >
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
      <!-- room:write: where the console files the poste. -->
      <q-btn
        v-if="canPlace"
        flat
        dense
        color="primary"
        icon="meeting_room"
        :label="machine?.room_name ? 'Changer de salle' : 'Affecter à une salle'"
        class="q-ml-sm"
        :disable="!machine"
        @click="openPlace"
      />
      <!-- machine:write only: the merge endpoint requires it, so for anyone
           else the button could only ever open a dialog and 403.
           The count rides in the label — "Fusionner" said nothing about whether
           there was anything to fuse, which is what made it look inert. -->
      <q-btn
        v-if="canManage"
        flat
        dense
        color="primary"
        icon="merge"
        :label="mergeLabel"
        class="q-ml-sm"
        :disable="!machine"
        @click="openMerge"
      >
        <q-tooltip>{{ mergeHint }}</q-tooltip>
      </q-btn>
      <!-- One slot, two states: revoking and lifting the revocation are the
           two halves of the same kill-switch, and showing both at once would
           read as a choice when only one ever applies. -->
      <q-btn
        v-if="canManage && machine?.token_revoked"
        flat
        dense
        color="positive"
        icon="key"
        label="Autoriser le ré-enrôlement"
        class="q-ml-sm"
        @click="confirmAllowReenroll"
      />
      <q-btn
        v-else-if="canManage"
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

    <q-banner v-if="machine?.token_revoked" class="bg-red-2 q-mb-md" rounded>
      <template #avatar><q-icon name="key_off" color="negative" /></template>
      Token révoqué : le poste est coupé du serveur et ne peut plus se ré-enrôler, même avec le
      secret du parc, tant que le ré-enrôlement n'est pas autorisé ici.
      <template #action>
        <q-btn
          v-if="canManage"
          flat
          dense
          label="Autoriser le ré-enrôlement"
          @click="confirmAllowReenroll"
        />
      </template>
    </q-banner>

    <q-banner v-if="machine?.needs_verification" class="bg-orange-2 q-mb-md" rounded>
      <template #avatar><q-icon name="warning" color="orange" /></template>
      Empreinte divergente : ce poste nécessite une vérification manuelle (clone, swap matériel ou
      ré-image).
      <template #action>
        <q-btn v-if="canManage" flat dense label="Fusionner un doublon" @click="openMerge" />
      </template>
    </q-banner>

    <q-banner v-if="machine?.location_mismatch" class="bg-orange-1 q-mb-md" rounded>
      <template #avatar><q-icon name="wrong_location" color="orange" /></template>
      Emplacement divergent : l'agent déclare « {{ machine.location }} », mais la salle
      {{ machine.room_name }} est à « {{ machine.room_location }} ». Une GPO mal ciblée, ou un poste
      déplacé sans sa salle.
    </q-banner>

    <!-- Placing the poste: one room, or none. -->
    <q-dialog v-model="placeOpen">
      <q-card style="width: 420px; max-width: 90vw">
        <q-card-section class="text-h6">Salle du poste</q-card-section>
        <q-card-section>
          <q-select
            v-model="placeRoomId"
            :options="placeRoomOptions"
            emit-value
            map-options
            label="Salle"
            outlined
            dense
            autofocus
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat label="Annuler" />
          <q-btn color="primary" label="Enregistrer" :loading="placing" @click="savePlace" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- First the state and the findings, then the detail behind them by
         tab: the fiche used to open on eleven cards of facts and leave the
         reader to find the one that mattered. -->
    <MachineStatusCard
      v-if="machine"
      :machine="machine"
      :active-threats="activeThreats"
      class="q-mb-md"
      @open-tab="tab = $event"
    />

    <template v-if="machine">
      <q-tabs
        v-model="tab"
        dense
        no-caps
        align="left"
        class="text-grey"
        active-color="primary"
        indicator-color="primary"
      >
        <q-tab name="identity" icon="badge" label="Identité" />
        <q-tab name="antivirus" icon="shield" label="Antivirus">
          <q-badge v-if="activeThreats" color="negative" floating>{{ activeThreats }}</q-badge>
        </q-tab>
        <q-tab name="windows_update" icon="system_update" label="Windows Update">
          <q-badge v-if="machine.wu_pending_count" color="orange" floating>
            {{ machine.wu_pending_count }}
          </q-badge>
        </q-tab>
        <q-tab name="hardware" icon="memory" label="Matériel" />
        <q-tab name="software" icon="apps" label="Logiciels">
          <q-badge v-if="machine.software.length" color="grey-7" floating>
            {{ machine.software.length }}
          </q-badge>
        </q-tab>
        <q-tab name="commands" icon="history" label="Commandes" />
        <q-tab name="history" icon="handyman" label="Historique">
          <q-badge v-if="interventionTotal" color="grey-7" floating>{{
            interventionTotal
          }}</q-badge>
        </q-tab>
      </q-tabs>
      <q-separator />

      <q-tab-panels v-model="tab" animated class="bg-transparent">
        <q-tab-panel name="identity" class="q-px-none">
          <div class="row q-col-gutter-md">
            <MachineIdentityCard :machine="machine" />
            <MachineNetworkCard :machine="machine" />
          </div>
        </q-tab-panel>

        <q-tab-panel name="antivirus" class="q-px-none">
          <div class="row q-col-gutter-md">
            <MachineDefenderCard :machine="machine" />
            <MachineAntivirusCard :machine="machine" />
          </div>
          <MachineThreatsCard
            v-model:pagination="threatPagination"
            :threats="threats"
            :loading="loading"
            @refresh="load"
          />
        </q-tab-panel>

        <q-tab-panel name="windows_update" class="q-px-none">
          <div class="row q-col-gutter-md">
            <MachineWindowsUpdateCard :machine="machine" />
          </div>
          <MachinePendingUpdatesCard :machine="machine" :loading="loading" />
        </q-tab-panel>

        <q-tab-panel name="hardware" class="q-px-none">
          <div class="row q-col-gutter-md">
            <MachineHardwareCard :machine="machine" />
            <MachineStorageCard :machine="machine" />
            <MachineMemoryCard :machine="machine" />
            <MachineGpuCard :machine="machine" />
          </div>
        </q-tab-panel>

        <q-tab-panel name="software" class="q-px-none">
          <MachineSoftwareCard :machine="machine" :loading="loading" />
        </q-tab-panel>

        <q-tab-panel name="history" class="q-px-none">
          <MachineHistoryCard
            :machine-id="props.id"
            :items="interventions"
            :total="interventionTotal"
            :loading="interventionsLoading"
            :can-write="auth.can('intervention', 'write')"
            @changed="loadInterventions(1)"
            @more="loadInterventions(interventionPage + 1)"
          />
        </q-tab-panel>

        <q-tab-panel name="commands" class="q-px-none">
          <MachineCommandsCard
            v-model:pagination="commandPagination"
            :commands="commands"
            :loading="loading"
            @refresh="load"
            @show-detail="showDetail"
          />
        </q-tab-panel>
      </q-tab-panels>
    </template>

    <MachineMergeDialog
      v-model="mergeOpen"
      :machine="machine"
      :machine-id="id"
      :duplicates="duplicates"
      @merged="load"
    />

    <CommandOutputDialog v-model="detailOpen" :command="detailCommand" :kind="detailKind" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { AUTO_REFRESH_INTERVAL_MS, useAutoRefresh } from 'src/composables/useAutoRefresh';
import { useMachineNavigation } from 'src/composables/useMachineNavigation';
import CommandOutputDialog from 'src/components/machine/CommandOutputDialog.vue';
import MachineAntivirusCard from 'src/components/machine/MachineAntivirusCard.vue';
import MachineCommandsCard from 'src/components/machine/MachineCommandsCard.vue';
import MachineDefenderCard from 'src/components/machine/MachineDefenderCard.vue';
import MachineGpuCard from 'src/components/machine/MachineGpuCard.vue';
import MachineHardwareCard from 'src/components/machine/MachineHardwareCard.vue';
import MachineHistoryCard from 'src/components/machine/MachineHistoryCard.vue';
import MachineIdentityCard from 'src/components/machine/MachineIdentityCard.vue';
import MachineMemoryCard from 'src/components/machine/MachineMemoryCard.vue';
import MachineMergeDialog from 'src/components/machine/MachineMergeDialog.vue';
import MachineNetworkCard from 'src/components/machine/MachineNetworkCard.vue';
import MachinePendingUpdatesCard from 'src/components/machine/MachinePendingUpdatesCard.vue';
import MachineSoftwareCard from 'src/components/machine/MachineSoftwareCard.vue';
import MachineStatusCard from 'src/components/machine/MachineStatusCard.vue';
import MachineStorageCard from 'src/components/machine/MachineStorageCard.vue';
import MachineThreatsCard from 'src/components/machine/MachineThreatsCard.vue';
import MachineWindowsUpdateCard from 'src/components/machine/MachineWindowsUpdateCard.vue';
import {
  DEFAULT_MACHINE_TAB,
  DEFAULT_PAGE_SIZE,
  MACHINE_TABS,
  type MachineTab,
  type TablePagination,
} from 'src/components/machine/types';
import { queryValue } from 'src/utils/machineQuery';
import {
  allowReenroll,
  getDuplicates,
  getMachine,
  revokeToken,
  wakeMachines,
  wakeNotification,
  type DuplicateCandidate,
  type MachineDetail,
} from 'src/services/machines';
import { useAuthStore } from 'src/stores/auth';
import { listThreats, type Threat } from 'src/services/threats';
import {
  commandActionGroups,
  createCommands,
  listCommands,
  type Command,
  type CommandAction,
} from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import { listInterventions, type Intervention } from 'src/services/interventions';
import {
  getRoomConfig,
  listRooms,
  placeMachines,
  placementNotification,
  roomLabel,
  unassignMachines,
  type Room,
} from 'src/services/rooms';
import { onlineColor, onlineIcon, onlineLabel, timeAgoLabel } from 'src/utils/format';

const props = defineProps<{ id: string }>();
const $q = useQuasar();
const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const machine = ref<MachineDetail | null>(null);
const threats = ref<Threat[]>([]);
// Counted by the server over the whole history, not read off the page of it
// shown below: the badge and the alert must say "3" when there are three,
// whichever page the history table is on.
const activeThreats = ref(0);

/**
 * The open tab, kept in the URL so a link to « the Windows Update tab of this
 * poste » is a link, and so a reload comes back where the reader was. The
 * default tab stays out of the URL, as the list keeps its own defaults out.
 */
const tab = computed<MachineTab>({
  get: () => {
    const raw = queryValue(route.query.tab);
    return raw && (MACHINE_TABS as readonly string[]).includes(raw)
      ? (raw as MachineTab)
      : DEFAULT_MACHINE_TAB;
  },
  set: (value) => {
    const query = { ...route.query };
    if (value === DEFAULT_MACHINE_TAB) delete query.tab;
    else query.tab = value;
    void router.replace({ query });
  },
});
const commands = ref<Command[]>([]);
const loading = ref(false);
const mergeOpen = ref(false);
const duplicates = ref<DuplicateCandidate[]>([]);
const detailOpen = ref(false);
const detailCommand = ref<Command | null>(null);
const detailKind = ref<'output' | 'error'>('output');

// Previous/next through the search this fiche was opened from, and the back
// arrow's return query. Empty when the fiche was reached any other way.
const { fromSearch, previousMachine, nextMachine, positionLabel, backQuery, goPrevious, goNext } =
  useMachineNavigation();

// Both histories are paginated by the server: a poste that has been running for
// a year holds far more than a page of either, and the old behaviour silently
// showed the first fifty rows as if they were all of it. The cards own the page
// turning; the page owns the state and the refetch that follows it.
const threatPagination = ref<TablePagination>({
  page: 1,
  rowsPerPage: DEFAULT_PAGE_SIZE,
  rowsNumber: 0,
});
const commandPagination = ref<TablePagination>({
  page: 1,
  rowsPerPage: DEFAULT_PAGE_SIZE,
  rowsNumber: 0,
});

// The whole catalogue here, diagnostics included: reading one machine's
// gpresult or ipconfig is exactly what this page is for.
// What this profile may trigger: the menu never offers what the backend would
// refuse, and goes away entirely for an account that may run nothing.
const actionGroups = computed(() => commandActionGroups({ permissions: auth.permissions }));
// Revoke, re-enroll, merge: the machine:write half of the fiche.
const canManage = computed(() => auth.can('machine', 'write'));

// --- The journal. Loaded with the fiche and paged by « Afficher plus »:
// a poste's journal is a few dozen lines at most, read top to bottom.
const interventions = ref<Intervention[]>([]);
const interventionTotal = ref(0);
const interventionPage = ref(1);
const interventionsLoading = ref(false);
const INTERVENTION_PAGE_SIZE = 25;

async function loadInterventions(page: number) {
  if (!auth.can('intervention', 'read')) return;
  interventionsLoading.value = true;
  try {
    const id = props.id;
    const res = await listInterventions(id, { page, page_size: INTERVENTION_PAGE_SIZE });
    if (id !== props.id) return;
    interventions.value = page === 1 ? res.items : [...interventions.value, ...res.items];
    interventionTotal.value = res.total;
    interventionPage.value = page;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Historique indisponible') });
  } finally {
    interventionsLoading.value = false;
  }
}

// --- Placement: the room the console files the poste in. By hand only
// when the server is not in a directory mode.
const manualMode = ref(true);
const canPlace = computed(() => auth.can('room', 'write') && manualMode.value);
void getRoomConfig()
  .then((c) => {
    manualMode.value = c.manual;
  })
  .catch(() => {
    // Assumed manual: the worst case is a 409 the notification explains.
  });
const ROOM_NONE = 'none';
const placeOpen = ref(false);
const placing = ref(false);
const placeRoomId = ref<string | null>(null);
const rooms = ref<Room[]>([]);
const placeRoomOptions = computed(() => [
  { label: 'Sans salle', value: ROOM_NONE },
  ...rooms.value.map((r) => ({ label: roomLabel(r), value: r.id })),
]);

async function openPlace() {
  placeRoomId.value = machine.value?.room_id ?? ROOM_NONE;
  placeOpen.value = true;
  try {
    rooms.value = await listRooms();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Salles indisponibles') });
  }
}

async function savePlace() {
  if (!machine.value || !placeRoomId.value) return;
  placing.value = true;
  try {
    const res =
      placeRoomId.value === ROOM_NONE
        ? await unassignMachines([machine.value.id])
        : await placeMachines(placeRoomId.value, [machine.value.id]);
    $q.notify(placementNotification(res));
    placeOpen.value = false;
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Affectation impossible') });
  } finally {
    placing.value = false;
  }
}

const title = computed(() => machine.value?.hostname || machine.value?.machine_uuid || 'Poste');

function showDetail(cmd: Command, kind: 'output' | 'error') {
  detailCommand.value = cmd;
  detailKind.value = kind;
  detailOpen.value = true;
}

// Which fetch is the current one. The 90 s background refresh, a page turn on
// either history, and a walk to the next poste can all be in flight together;
// without this the slowest answer would win and write its own stale page
// numbers back over whatever the reader has since asked for.
let requestId = 0;

async function fetchAll() {
  const id = ++requestId;
  const tp = threatPagination.value;
  const cp = commandPagination.value;
  const [m, t, active, c] = await Promise.all([
    getMachine(props.id),
    listThreats({ machine_id: props.id, page: tp.page, page_size: tp.rowsPerPage }),
    // One row is enough: only the total is read.
    listThreats({ machine_id: props.id, status: 'active', page: 1, page_size: 1 }),
    listCommands({ machine_id: props.id, page: cp.page, page_size: cp.rowsPerPage }),
  ]);
  if (id !== requestId) return;
  machine.value = m;
  threats.value = t.items;
  activeThreats.value = active.total;
  // Merged into the current value, not the snapshot: a page turned while this
  // request was in the air must not be undone by its answer.
  threatPagination.value = { ...threatPagination.value, rowsNumber: t.total };
  commands.value = c.items;
  commandPagination.value = { ...commandPagination.value, rowsNumber: c.total };
  // Not awaited with the rest: the count on the merge button is worth showing,
  // but never worth holding the page for.
  void fetchDuplicates();
}

/**
 * This is the page an administrator leaves open after firing a command, so it
 * follows the poste on its own: `pending` → `transmise` → `en cours` →
 * `réussie` arrives without a click.
 *
 * Paused while a dialog is over the page. The result dialog reads a snapshot
 * and would survive a refresh, but the merge dialog would have its duplicate
 * list swapped under the cursor — and either way, pulling the tables around
 * behind a modal is the one moment a background refresh is worse than stale
 * data.
 */
const { lastRefreshedAt, refreshNow } = useAutoRefresh(fetchAll, {
  paused: () => detailOpen.value || mergeOpen.value,
});

/** The manual load: this one shows the spinner, the automatic ones do not. */
async function load() {
  loading.value = true;
  try {
    await refreshNow();
  } finally {
    loading.value = false;
  }
}

const lastRefreshLabel = computed(() =>
  lastRefreshedAt.value ? lastRefreshedAt.value.toLocaleTimeString('fr-FR') : '',
);

const autoRefreshHint = `Actualiser — automatique toutes les ${Math.round(
  AUTO_REFRESH_INTERVAL_MS / 1000,
)} s`;

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
  // The wake is not a command: the poste is off, so there is nothing to queue
  // for an agent that is not running. Same menu entry, same confirmation path,
  // a different call.
  if (action.serverSide) {
    await sendWake();
    return;
  }
  try {
    const res = await createCommands({ type: action.type, machine_ids: [props.id] });
    if (res.count === 0) {
      // The server de-duplicates per (poste, type). Saying "envoyée" here would
      // have the administrator watch a history that never grows a row.
      $q.notify({
        type: 'warning',
        message: `« ${action.label} » est déjà en attente sur ce poste.`,
      });
    } else {
      $q.notify({ type: 'positive', message: 'Commande envoyée' });
    }
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'envoi de la commande") });
  }
}

async function sendWake() {
  try {
    const res = await wakeMachines([props.id]);
    $q.notify(wakeNotification(res));
    // Reloaded for the history, not for the machine's state: the wake is
    // recorded as a command row, while the poste itself will not reappear until
    // its agent reports — a minute or so after it has actually booted.
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec du réveil') });
  }
}

function confirmRevoke() {
  $q.dialog({
    title: 'Révoquer le token',
    message:
      'Le poste sera coupé du serveur et ne pourra pas revenir — même avec le secret du parc — ' +
      'tant que le ré-enrôlement ne sera pas autorisé depuis cette page. Continuer ?',
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

function confirmAllowReenroll() {
  $q.dialog({
    title: 'Autoriser le ré-enrôlement',
    message:
      "L'ancien token reste invalide ; le poste reviendra de lui-même à sa prochaine tentative " +
      "d'enrôlement, dans les minutes qui suivent s'il est allumé. Continuer ?",
    cancel: true,
    persistent: true,
  }).onOk(() => {
    void doAllowReenroll();
  });
}

async function doAllowReenroll() {
  try {
    await allowReenroll(props.id);
    $q.notify({ type: 'positive', message: 'Ré-enrôlement autorisé' });
    await load();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'autorisation") });
  }
}

// The count in the label, so the button says whether it has anything to offer
// before it is pressed — its silence on that is what made it look broken.
const mergeLabel = computed(() =>
  duplicates.value.length ? `Fusionner (${duplicates.value.length})` : 'Fusionner',
);

const mergeHint = computed(() =>
  duplicates.value.length
    ? `${duplicates.value.length} doublon(s) possible(s) détecté(s)`
    : 'Aucun doublon détecté — la recherche manuelle reste possible',
);

/** Candidates for the button's count, refreshed with the page. machine:write
 * only: the merge itself is, and a read-only console has no use for the list. */
async function fetchDuplicates() {
  if (!canManage.value) return;
  try {
    const id = props.id;
    const found = await getDuplicates(id);
    // The reader may have walked to the next poste while this was in the air.
    if (id !== props.id) return;
    duplicates.value = found;
  } catch {
    // A failed candidate lookup must not take the fiche down with it: the
    // button simply falls back to its countless label.
    duplicates.value = [];
  }
}

function openMerge() {
  mergeOpen.value = true;
  void fetchDuplicates();
}

// Walking to the previous/next result changes the route param on the *same*
// component instance — nothing remounts, so the reload has to be watched for.
// Everything on screen belongs to the poste being left, `machine` included:
// held on to, the header, the banners and the merge dialog would spend a round
// trip describing one poste under another one's name. Both histories go back to
// their first page for the same reason.
watch(
  () => props.id,
  () => {
    machine.value = null;
    interventions.value = [];
    interventionTotal.value = 0;
    void loadInterventions(1);
    threats.value = [];
    activeThreats.value = 0;
    commands.value = [];
    duplicates.value = [];
    threatPagination.value = { page: 1, rowsPerPage: DEFAULT_PAGE_SIZE, rowsNumber: 0 };
    commandPagination.value = { page: 1, rowsPerPage: DEFAULT_PAGE_SIZE, rowsNumber: 0 };
    void load();
  },
);

// The profile is fetched by the layout without being awaited, so on a hard
// reload of this page `canManage` is still false when the first load runs and
// the candidate lookup is skipped. The buttons appear on their own once it
// resolves; the count behind them would not, and a merge button reading
// "aucun doublon" on a poste that has one is the very thing this change set out
// to fix.
watch(canManage, (allowed) => {
  if (allowed) void fetchDuplicates();
});

// Same reasoning as the duplicate lookup: on a hard reload the profile is
// not there yet when the first load runs, and the journal would stay empty.
watch(
  () => auth.can('intervention', 'read'),
  (allowed) => {
    if (allowed && !interventions.value.length) void loadInterventions(1);
  },
);

onMounted(() => {
  void load();
  void loadInterventions(1);
});
</script>
