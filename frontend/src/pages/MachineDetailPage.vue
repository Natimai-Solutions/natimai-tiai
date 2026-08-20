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
      <div class="text-h5">{{ title }}</div>
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
      <!-- Admin only: the merge endpoint requires machine:write, so for a
           read-only operator the button could only ever open a dialog and 403.
           The count rides in the label — "Fusionner" said nothing about whether
           there was anything to fuse, which is what made it look inert. -->
      <q-btn
        v-if="auth.isAdmin"
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
      <q-btn
        v-if="auth.isAdmin"
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
        <q-btn v-if="auth.isAdmin" flat dense label="Fusionner un doublon" @click="openMerge" />
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
          <q-card-section class="text-subtitle1">
            État Defender
            <div v-if="machine?.av_product_is_defender" class="text-caption text-grey">
              Defender est l'antivirus enregistré au Security Center de Windows.
            </div>
          </q-card-section>
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

      <div v-if="showAVProductCard" class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">
            Antivirus enregistré
            <div class="text-caption text-grey">
              Vu par le Security Center de Windows — un produit tiers, ou aucun.
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section v-if="avProductUnread" class="text-caption text-grey">
            Jamais relevé sur ce poste : son agent est antérieur à la lecture du Security Center, ou
            l'hôte n'en a pas — un SKU Windows Server n'en embarque aucun. C'est ce que dit « Non
            relevé » dans la liste des postes : non pas que le poste soit sans antivirus, mais que
            ce relevé-là manque. L'état Defender ci-dessus, lui, est bien à jour.
          </q-card-section>
          <q-list v-else dense>
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
          <q-td :props="props">
            {{ wuSizeLabel(props.value) }}
            <q-tooltip v-if="props.value != null">
              Majorant relevé par Windows Update : la somme de toutes les charges utiles que la mise
              à jour pourrait avoir à récupérer, alors qu'une seule sera téléchargée. Exact sur un
              pilote, surestimé sur un correctif cumulatif.
            </q-tooltip>
          </q-td>
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
        v-model:pagination="threatPagination"
        :rows="threats"
        :columns="threatColumns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[10, 25, 50]"
        no-data-label="Aucune menace détectée."
        @request="onThreatRequest"
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
        v-model:pagination="commandPagination"
        :rows="commands"
        :columns="commandColumns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[10, 25, 50]"
        no-data-label="Aucune commande."
        @request="onCommandRequest"
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
      <q-card style="min-width: 560px; max-width: 90vw">
        <q-card-section class="text-h6">Fusionner un doublon</q-card-section>

        <!-- Which record is kept, said with the UUID and not only the hostname:
             two records of one poste carry the *same* hostname, and naming both
             sides "PC-042" is what made the dialog read as a merge with itself. -->
        <q-card-section class="q-pt-none">
          <div class="text-caption text-grey">Poste conservé (celui-ci)</div>
          <div class="text-body2 text-weight-medium">{{ title }}</div>
          <div class="text-caption text-grey merge-uuid">{{ machine?.machine_uuid }}</div>
          <div class="text-caption text-grey q-mt-xs">
            Enrôlé le {{ formatDateTime(machine?.first_seen) }} — vu le
            {{ formatDateTime(machine?.last_seen) }}
          </div>
          <div class="text-caption text-grey q-mt-sm">
            Le poste choisi ci-dessous sera supprimé : ses menaces et commandes seront rattachées à
            l'enregistrement conservé. Action irréversible.
          </div>
        </q-card-section>

        <q-separator />
        <q-list separator>
          <q-item v-for="d in duplicates" :key="d.id">
            <q-item-section>
              <q-item-label>
                {{ d.hostname || d.machine_uuid }}
                <q-badge
                  :color="matchReasonColor(d.match_reason)"
                  class="q-ml-sm"
                  :label="matchReasonLabel(d.match_reason)"
                />
              </q-item-label>
              <!-- The three lines that distinguish two records of one poste:
                   its own UUID, when it was enrolled, when it last reported. -->
              <q-item-label caption class="merge-uuid">{{ d.machine_uuid }}</q-item-label>
              <q-item-label caption>
                Enrôlé le {{ formatDateTime(d.first_seen) }} — vu le
                {{ formatDateTime(d.last_seen) }} ({{ timeAgoLabel(d.last_seen) }})
              </q-item-label>
              <q-item-label caption>{{ matchReasonHint(d.match_reason) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn dense color="primary" label="Fusionner ici" @click="doMerge(d)" />
            </q-item-section>
          </q-item>
          <q-item v-if="!duplicates.length">
            <q-item-section class="text-grey">
              Aucun doublon détecté : aucun autre poste ne partage l'ancre matérielle (SMBIOS ou
              TPM) ni le nom de celui-ci. Un doublon dont le nom a changé se cherche ci-dessous.
            </q-item-section>
          </q-item>
        </q-list>

        <q-separator />
        <!-- Manual search, because detection cannot cover the case that most
             needs merging: when the anchor itself drifted, the two records have
             nothing left in common for the server to match on. -->
        <q-card-section>
          <div class="text-caption text-grey q-mb-sm">
            Chercher un autre poste à fusionner dans celui-ci — vérifiez l'UUID avant de
            confirmer&nbsp;: rien ne garantit qu'il s'agisse du même matériel.
          </div>
          <q-input
            v-model="mergeSearch"
            dense
            outlined
            clearable
            debounce="300"
            placeholder="Nom, IP ou UUID du poste à fusionner…"
            :loading="mergeSearching"
            @update:model-value="runMergeSearch"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <q-list v-if="mergeResults.length" separator dense class="q-mt-sm">
            <q-item v-for="m in mergeResults" :key="m.id">
              <q-item-section>
                <q-item-label>{{ m.hostname || m.machine_uuid }}</q-item-label>
                <q-item-label caption class="merge-uuid">{{ m.machine_uuid }}</q-item-label>
                <q-item-label caption>Vu le {{ formatDateTime(m.last_seen) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn dense flat color="primary" label="Fusionner ici" @click="doMerge(m)" />
              </q-item-section>
            </q-item>
          </q-list>
          <div v-else-if="mergeSearch && !mergeSearching" class="text-caption text-grey q-mt-sm">
            Aucun autre poste ne correspond.
          </div>
        </q-card-section>

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
import { computed, onMounted, ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { AUTO_REFRESH_INTERVAL_MS, useAutoRefresh } from 'src/composables/useAutoRefresh';
import { useMachineNavigation } from 'src/composables/useMachineNavigation';
import {
  getDuplicates,
  getMachine,
  listMachines,
  mergeMachines,
  revokeToken,
  wakeMachines,
  wakeNotification,
  type DuplicateCandidate,
  type Machine,
  type MachineDetail,
  type MatchReason,
  type PendingUpdate,
} from 'src/services/machines';
import { useAuthStore } from 'src/stores/auth';
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
  ipAddressLabel,
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
const auth = useAuthStore();

const machine = ref<MachineDetail | null>(null);
const threats = ref<Threat[]>([]);
const commands = ref<Command[]>([]);
const loading = ref(false);
const mergeOpen = ref(false);
const duplicates = ref<DuplicateCandidate[]>([]);
const mergeSearch = ref('');
const mergeResults = ref<Machine[]>([]);
const mergeSearching = ref(false);
const detailOpen = ref(false);
const detailCommand = ref<Command | null>(null);
const detailKind = ref<'output' | 'error'>('output');

// Previous/next through the search this fiche was opened from, and the back
// arrow's return query. Empty when the fiche was reached any other way.
const { fromSearch, previousMachine, nextMachine, positionLabel, backQuery, goPrevious, goNext } =
  useMachineNavigation();

// Both histories are paginated by the server: a poste that has been running for
// a year holds far more than a page of either, and the old behaviour silently
// showed the first fifty rows as if they were all of it.
const THREAT_PAGE_SIZE = 10;
const COMMAND_PAGE_SIZE = 10;
const threatPagination = ref({ page: 1, rowsPerPage: THREAT_PAGE_SIZE, rowsNumber: 0 });
const commandPagination = ref({ page: 1, rowsPerPage: COMMAND_PAGE_SIZE, rowsNumber: 0 });

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
        {
          label: 'Adresse IP',
          value: ipAddressLabel(machine.value.ip_address, machine.value.ip_prefix_length),
        },
        // Right under the address it was elected with, and for two reasons: it
        // is the wake target — a dash here means « Réveiller le poste » has
        // nothing to aim at — and it is what an admin compares against the
        // switch when a wake did not work.
        { label: 'Adresse MAC', value: machine.value.mac_address ?? '—' },
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

/**
 * Whether the Security Center deserves a card of its own.
 *
 * Not when the product it names is Defender: every row it would carry is already
 * in the Defender card, and two panels stating the same protection twice read as
 * a display bug rather than as corroboration. It stays for a third-party product
 * — the case Defender's own WMI class cannot describe — for "no antivirus
 * registered at all", and for the case where nothing was ever read, which is the
 * one an administrator most needs spelled out.
 */
const showAVProductCard = computed(
  () => machine.value != null && machine.value.av_product_is_defender !== true,
);

/**
 * No Security Center reading at all, as opposed to one that found nothing. The
 * card then explains itself instead of printing four rows of "Inconnu" beside a
 * Defender card that is plainly alive — the contradiction that reading invites.
 */
const avProductUnread = computed(
  () => machine.value != null && machine.value.av_product_name == null,
);

const antivirusRows = computed(() => {
  const m = machine.value;
  // Never read: the card shows its explanation instead, not a table of dashes.
  if (!m || m.av_product_name == null) return [];
  const rows = [{ label: 'Produit', value: antivirusLabel(m.av_product_name) }];
  // Both bits below describe a *product*. With none registered they would only
  // add two "Inconnu" under a "Aucun" that has already said everything.
  if (m.av_product_name !== '') {
    rows.push(
      { label: 'Protection active', value: boolLabel(m.av_product_enabled) },
      // The Security Center exposes a freshness bit and nothing else — no
      // version, no date, which is why this card carries no scan or update
      // action for a third-party product.
      {
        label: 'Signatures à jour',
        value: boolLabel(m.av_product_signatures_up_to_date),
      },
    );
  }
  // No "Est Defender" row: the card being here at all is that answer, and the
  // Defender card says so in words on the machines where it is Defender.
  return rows;
});

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
  // "max." and not "Taille": WUA reports a ceiling, not a measurement — see
  // wuSizeLabel. The header carries the caveat so the cells do not have to.
  { name: 'size_mb', label: 'Taille max.', field: 'size_mb', align: 'right', sortable: true },
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

// Which fetch is the current one. The 90 s background refresh, a page turn on
// either history, and a walk to the next poste can all be in flight together;
// without this the slowest answer would win and write its own stale page
// numbers back over whatever the reader has since asked for.
let requestId = 0;

async function fetchAll() {
  const id = ++requestId;
  const tp = threatPagination.value;
  const cp = commandPagination.value;
  const [m, t, c] = await Promise.all([
    getMachine(props.id),
    listThreats({ machine_id: props.id, page: tp.page, page_size: tp.rowsPerPage }),
    listCommands({ machine_id: props.id, page: cp.page, page_size: cp.rowsPerPage }),
  ]);
  if (id !== requestId) return;
  machine.value = m;
  threats.value = t.items;
  // Merged into the current value, not the snapshot: a page turned while this
  // request was in the air must not be undone by its answer.
  threatPagination.value = { ...threatPagination.value, rowsNumber: t.total };
  commands.value = c.items;
  commandPagination.value = { ...commandPagination.value, rowsNumber: c.total };
  // Not awaited with the rest: the count on the merge button is worth showing,
  // but never worth holding the page for.
  void fetchDuplicates();
}

/** Turn a page of the threat history (server-side). */
function onThreatRequest(evt: { pagination: { page?: number; rowsPerPage?: number } }) {
  threatPagination.value = {
    ...threatPagination.value,
    page: evt.pagination.page ?? 1,
    rowsPerPage: evt.pagination.rowsPerPage ?? THREAT_PAGE_SIZE,
  };
  void load();
}

/** Turn a page of the command history (server-side). */
function onCommandRequest(evt: { pagination: { page?: number; rowsPerPage?: number } }) {
  commandPagination.value = {
    ...commandPagination.value,
    page: evt.pagination.page ?? 1,
    rowsPerPage: evt.pagination.rowsPerPage ?? COMMAND_PAGE_SIZE,
  };
  void load();
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

const MATCH_REASON_LABELS: Record<MatchReason, string> = {
  smbios_uuid: 'Même carte mère',
  tpm_ek_hash: 'Même TPM',
  hostname: 'Même nom',
};

const MATCH_REASON_HINTS: Record<MatchReason, string> = {
  smbios_uuid: 'Ancre matérielle identique (SMBIOS UUID) : très probablement le même poste.',
  tpm_ek_hash: 'Même clé TPM : très probablement le même poste.',
  hostname:
    'Seul le nom correspond — cela peut aussi être un poste remplacé qui a repris le nom de l’ancien. À vérifier avant de fusionner.',
};

function matchReasonLabel(reason: MatchReason): string {
  return MATCH_REASON_LABELS[reason];
}

function matchReasonHint(reason: MatchReason): string {
  return MATCH_REASON_HINTS[reason];
}

/** Hardware evidence in the accent colour, a name match in a warning one: the
 * badge has to say at a glance which of the two decisions this is. */
function matchReasonColor(reason: MatchReason): string {
  return reason === 'hostname' ? 'orange' : 'primary';
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

/** Candidates for the button's count, refreshed with the page. Admin-only: the
 * merge itself is, and a read-only console has no use for the list. */
async function fetchDuplicates() {
  if (!auth.isAdmin) return;
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
  mergeSearch.value = '';
  mergeResults.value = [];
  mergeOpen.value = true;
  void fetchDuplicates();
}

/** Free search over the fleet for a poste to merge in, current one excluded. */
async function runMergeSearch() {
  const term = (mergeSearch.value ?? '').trim();
  if (!term) {
    mergeResults.value = [];
    return;
  }
  mergeSearching.value = true;
  try {
    const data = await listMachines({ search: term, page_size: 10 });
    mergeResults.value = data.items.filter((m) => m.id !== props.id);
  } catch (e) {
    mergeResults.value = [];
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec de la recherche') });
  } finally {
    mergeSearching.value = false;
  }
}

function doMerge(source: Machine) {
  // Both UUIDs in the confirmation: on two records of one poste the hostnames
  // are identical, and a confirmation naming the same string twice is exactly
  // the one an administrator clicks through without reading.
  const kept = machine.value?.machine_uuid ?? title.value;
  const removed = source.hostname
    ? `${escapeHtml(source.machine_uuid)} (${escapeHtml(source.hostname)})`
    : escapeHtml(source.machine_uuid);
  $q.dialog({
    title: 'Fusionner les postes',
    message:
      `<div>Supprimer l'enregistrement <b>${removed}</b> et rattacher son historique à ` +
      `<b>${escapeHtml(kept)}</b> ?</div>` +
      `<div class="q-mt-sm">Cette action est irréversible.</div>`,
    html: true,
    cancel: true,
    persistent: true,
  }).onOk(() => {
    void runMerge(source.id);
  });
}

/** Escape interpolated machine-reported text before it goes into the dialog's
 * HTML: a hostname comes from a poste, not from this console. */
function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
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
    threats.value = [];
    commands.value = [];
    duplicates.value = [];
    threatPagination.value = { page: 1, rowsPerPage: THREAT_PAGE_SIZE, rowsNumber: 0 };
    commandPagination.value = { page: 1, rowsPerPage: COMMAND_PAGE_SIZE, rowsNumber: 0 };
    void load();
  },
);

// The profile is fetched by the layout without being awaited, so on a hard
// reload of this page `isAdmin` is still false when the first load runs and the
// admin-only candidate lookup is skipped. The buttons appear on their own once
// it resolves; the count behind them would not, and a merge button reading
// "aucun doublon" on a poste that has one is the very thing this change set out
// to fix.
watch(
  () => auth.isAdmin,
  (isAdmin) => {
    if (isAdmin) void fetchDuplicates();
  },
);

onMounted(load);
</script>

<style scoped>
/* The UUID is read character by character when two records have to be told
   apart — the one place in this page where a monospace face earns its keep. */
.merge-uuid {
  font-family: monospace;
  font-size: 11px;
}

.command-output {
  margin: 0;
  max-height: 50vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
</style>
