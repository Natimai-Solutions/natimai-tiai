<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn
        :aria-label="t('machine.page.backAria')"
        flat
        dense
        round
        icon="arrow_back"
        :to="{ name: 'machines', query: backQuery }"
        class="q-mr-sm"
      >
        <q-tooltip>
          {{ fromSearch ? t('machine.page.backToResults') : t('machine.page.backToComputers') }}
        </q-tooltip>
      </q-btn>
      <h1 class="text-h5 q-my-none row items-center no-wrap break-anywhere" style="min-width: 0">
        <!-- Leading, same dot as the list: the fiche answers « allumé ? » at a glance too. -->
        <q-icon
          v-if="machine"
          :name="onlineIcon(machine.is_online)"
          :color="onlineColor(machine.is_online)"
          size="14px"
          class="q-mr-sm"
        >
          <q-tooltip>
            {{
              t('machine.page.onlineTooltip', {
                state: onlineLabel(machine.is_online),
                ago: timeAgoLabel(machine.last_seen),
              })
            }}
          </q-tooltip>
        </q-icon>
        <span class="break-anywhere" style="min-width: 0">{{ title }}</span>
      </h1>
      <!-- Only when the fiche was opened from a list query: elsewhere there is
           no search to walk, and dead arrows would be worse than none. -->
      <template v-if="fromSearch">
        <q-btn
          :aria-label="t('machine.page.previousAria')"
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
                ? t('machine.page.previous', {
                    name: previousMachine.hostname || previousMachine.machine_uuid,
                  })
                : t('machine.page.firstResult')
            }}
          </q-tooltip>
        </q-btn>
        <q-btn
          :aria-label="t('machine.page.nextAria')"
          flat
          dense
          round
          icon="chevron_right"
          :disable="!nextMachine"
          @click="goNext"
        >
          <q-tooltip>
            {{
              nextMachine
                ? t('machine.page.next', { name: nextMachine.hostname || nextMachine.machine_uuid })
                : t('machine.page.lastResult')
            }}
          </q-tooltip>
        </q-btn>
        <div v-if="positionLabel" class="text-caption text-muted q-ml-sm">
          {{ positionLabel }}
        </div>
      </template>
      <q-space />
      <div v-if="lastRefreshedAt && machine" class="text-caption text-muted q-mr-sm">
        {{ t('machine.page.refreshedAt', { time: lastRefreshLabel }) }}
      </div>
      <q-btn
        :aria-label="t('machine.page.refresh')"
        flat
        dense
        round
        icon="refresh"
        :loading="loading"
        class="q-mr-sm"
        @click="load"
      >
        <q-tooltip>{{ autoRefreshHint }}</q-tooltip>
      </q-btn>
      <!-- The poste's own actions only once it is known: under « Poste
           introuvable » they could only fail. -->
      <template v-if="machine">
        <!-- Wrapped: a disabled button shows no tooltip of its own, and the
             one saying why it is disabled needs an element to hang on. -->
        <div v-if="actionGroups.length" class="inline-block" data-test="action-menu">
          <q-btn-dropdown
            color="primary"
            dense
            :label="t('machine.page.actionMenu')"
            icon="bolt"
            :disable="!!machine.token_revoked"
          >
            <q-list>
              <template v-for="section in actionGroups" :key="section.group">
                <q-item-label header class="q-py-xs">{{ section.label }}</q-item-label>
                <q-item
                  v-for="action in section.actions"
                  :key="action.type"
                  v-close-popup
                  clickable
                  :disable="sending"
                  @click="runOne(action)"
                >
                  <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
                  <q-item-section>{{ action.label }}</q-item-section>
                </q-item>
              </template>
            </q-list>
          </q-btn-dropdown>
          <q-tooltip v-if="machine.token_revoked">
            {{ t('machine.page.revokedTooltip') }}
          </q-tooltip>
        </div>
        <q-btn
          v-if="canDeploy"
          flat
          dense
          no-caps
          color="primary"
          icon="install_desktop"
          :label="t('machine.page.software')"
          class="q-ml-sm"
          :disable="!machine"
          @click="deployOpen = true"
        >
          <q-tooltip>{{ t('machine.page.softwareTooltip') }}</q-tooltip>
        </q-btn>
        <!-- check:write: ask somebody to go and look. One open at a time, so
           the button reads as the state. -->
        <q-btn
          v-if="auth.can('check', 'write') && machine && !machine.check_open"
          flat
          dense
          color="primary"
          icon="fact_check"
          :label="t('machine.page.requestCheck')"
          class="q-ml-sm"
          @click="askOpen = true"
        />
        <!-- room:write: where the console files the poste. -->
        <q-btn
          v-if="canPlace"
          flat
          dense
          color="primary"
          icon="meeting_room"
          :label="machine?.room_name ? t('machine.page.changeRoom') : t('machine.page.assignRoom')"
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
          :label="t('machine.page.allowReenroll')"
          class="q-ml-sm"
          @click="confirmAllowReenroll"
        />
        <q-btn
          v-else-if="canManage"
          flat
          dense
          color="negative"
          icon="key_off"
          :label="t('machine.page.revokeToken')"
          class="q-ml-sm"
          @click="confirmRevoke"
        />
      </template>
    </div>

    <!-- Also after an earlier success: walking to the next poste empties the
         page first, and a failure there must not leave it blank (audit U01). -->
    <!-- An id nobody knows (or outside this account's places, which the
         server answers alike): no « Réessayer », which could only fail again. -->
    <q-banner v-if="notFound && !machine" role="alert" class="surface-orange q-mb-md" rounded>
      <template #avatar><q-icon name="search_off" /></template>
      {{ t('machine.page.notFound') }}
      <template #action>
        <q-btn flat no-caps :label="t('machine.page.backToComputers')" :to="{ name: 'machines' }" />
      </template>
    </q-banner>
    <LoadErrorBanner
      v-else-if="lastError && (!lastRefreshedAt || !machine)"
      :error="lastError"
      :loading="loading"
      @retry="load"
    />
    <div v-else-if="!machine" class="row justify-center q-pa-xl">
      <q-spinner size="lg" color="primary" :aria-label="t('machine.page.loadingAria')" />
    </div>

    <q-banner v-if="machine?.token_revoked" class="surface-red q-mb-md" rounded>
      <template #avatar><q-icon name="key_off" color="negative" /></template>
      {{ t('machine.page.revokedBanner') }}
      <template #action>
        <q-btn
          v-if="canManage"
          flat
          dense
          :label="t('machine.page.allowReenroll')"
          @click="confirmAllowReenroll"
        />
      </template>
    </q-banner>

    <!-- The fleet secret was presented for this poste while it still had a
         live token: a reinstall, or someone claiming its identity. Nothing was
         issued; the decision is the administrator's, with the date and source
         address to make it on. -->
    <q-banner
      v-if="machine?.reenroll_requested_at && !machine.token_revoked"
      class="surface-orange q-mb-md"
      rounded
    >
      <template #avatar><q-icon name="key" color="orange" /></template>
      {{
        t('machine.page.reenrollRequested', {
          date: formatDateTime(machine.reenroll_requested_at),
        })
      }}
      <template v-if="machine.reenroll_requested_ip">
        {{ t('machine.page.reenrollFrom', { ip: machine.reenroll_requested_ip }) }}</template>{{
        t('machine.page.reenrollWarning')
      }}
      <template #action>
        <q-btn
          v-if="canManage"
          flat
          dense
          no-caps
          :label="t('machine.page.allowReenroll')"
          @click="confirmAllowReenroll"
        />
      </template>
    </q-banner>

    <q-banner v-if="machine?.needs_verification" class="surface-orange q-mb-md" rounded>
      <template #avatar><q-icon name="warning" color="orange" /></template>
      {{ t('machine.page.fingerprintMismatch') }}
      <template #action>
        <q-btn
          v-if="canManage"
          flat
          dense
          no-caps
          :label="t('machine.page.confirmIdentity')"
          :loading="confirmingIdentity"
          @click="askConfirmIdentity"
        />
        <q-btn
          v-if="canManage"
          flat
          dense
          :label="t('machine.page.mergeDuplicate')"
          @click="openMerge"
        />
      </template>
    </q-banner>

    <q-banner v-if="machine?.open_check" class="surface-blue q-mb-md" rounded>
      <template #avatar><q-icon name="fact_check" color="primary" /></template>
      <div>
        <span class="text-weight-medium">{{ t('machine.check.requested') }}</span>
        {{
          t('machine.check.by', {
            name: machine.open_check.requested_by,
            ago: timeAgoLabel(machine.open_check.created_at),
          })
        }}
        <template
          v-if="
            machine.open_check.assigned_to_name && machine.open_check.assignee_reachable !== false
          "
        >
          {{ t('machine.check.assignedTo', { name: machine.open_check.assigned_to_name }) }}
        </template>
        <template v-else-if="machine.open_check.assigned_to_name">
          {{ t('machine.check.unreachable', { name: machine.open_check.assigned_to_name }) }}
        </template>
        <template v-else>{{ t('machine.check.open') }}</template>
      </div>
      <div v-if="machine.open_check.instructions" class="q-mt-xs" style="white-space: pre-line">
        {{ checkInstructionsText(machine.open_check) }}
      </div>
      <template v-if="auth.can('check', 'write')" #action>
        <q-btn flat dense :label="t('machine.check.edit')" @click="editCheckOpen = true" />
        <q-btn
          flat
          dense
          color="primary"
          :label="t('machine.check.close')"
          @click="closeCheckOpen = true"
        />
      </template>
    </q-banner>

    <CheckRequestDialog
      v-model="askOpen"
      :check="null"
      :machine-id="props.id"
      :subtitle="machine?.hostname ?? undefined"
      :save="askCheck"
    />
    <CheckRequestDialog
      v-model="editCheckOpen"
      :check="openCheckAsCheck"
      :subtitle="machine?.hostname ?? undefined"
      :save="editCheck"
    />
    <CheckCloseDialog
      v-model="closeCheckOpen"
      :check="machine?.open_check ?? null"
      @closed="onCheckClosed"
    />

    <q-banner v-if="machine?.location_mismatch" class="surface-orange q-mb-md" rounded>
      <template #avatar><q-icon name="wrong_location" color="orange" /></template>
      {{
        t('machine.page.locationMismatch', {
          location: machine.location,
          room: machine.room_name,
          roomLocation: machine.room_location,
        })
      }}
    </q-banner>

    <!-- Placing the poste: one room, or none. -->
    <q-dialog v-model="placeOpen">
      <q-card style="width: 420px; max-width: 90vw">
        <q-card-section class="text-h6">{{ t('machine.place.title') }}</q-card-section>
        <q-card-section>
          <q-select
            v-model="placeRoomId"
            :options="placeRoomOptions"
            emit-value
            map-options
            :label="t('machine.place.room')"
            outlined
            dense
            autofocus
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat :label="t('machine.place.cancel')" />
          <q-btn
            color="primary"
            :label="t('machine.place.save')"
            :loading="placing"
            @click="savePlace"
          />
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
      :threats-failed="threatsFailed"
      :low-disk-percent="lowDiskPercent"
      class="q-mb-md"
      @open-tab="tab = $event"
      @retry="load"
    />
    <MachineAlertsCard v-if="machine" :machine-id="machine.id" :refresh-key="machine.last_seen" />

    <template v-if="machine">
      <q-tabs
        v-model="tab"
        dense
        no-caps
        align="left"
        class="text-muted"
        active-color="primary"
        indicator-color="primary"
      >
        <q-tab name="identity" icon="badge" :label="t('machine.tabs.identity')" />
        <q-tab name="antivirus" icon="shield" :label="t('machine.tabs.antivirus')">
          <q-badge v-if="activeThreats" color="negative" floating>{{ activeThreats }}</q-badge>
        </q-tab>
        <q-tab name="windows_update" icon="system_update" :label="t('machine.tabs.windowsUpdate')">
          <q-badge v-if="machine.wu_pending_count" color="orange" floating>
            {{ machine.wu_pending_count }}
          </q-badge>
        </q-tab>
        <q-tab name="hardware" icon="memory" :label="t('machine.tabs.hardware')" />
        <q-tab name="software" icon="apps" :label="t('machine.tabs.software')">
          <!-- « 212+ » : a partial list is not counted as a whole one. -->
          <q-badge v-if="machine.software.length" color="grey-7" floating>
            {{ machine.software.length }}{{ machine.software_truncated ? '+' : '' }}
          </q-badge>
        </q-tab>
        <q-tab name="compliance" icon="verified_user" :label="t('compliance.card.title')">
          <q-badge
            v-if="complianceFailed"
            color="negative"
            floating
            :aria-label="t('compliance.state.fail')"
          >
            {{ complianceFailed }}
          </q-badge>
        </q-tab>
        <q-tab
          v-if="canReadCommands"
          name="commands"
          icon="history"
          :label="t('machine.tabs.commands')"
        />
        <q-tab
          v-if="canSeeHistory"
          name="history"
          icon="handyman"
          :label="t('machine.tabs.history')"
        >
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
            <MachineUsageCard :machine="machine" />
            <MachineAssetCard v-if="auth.can('asset', 'read')" :machine-id="machine.id" />
            <MachineDirectoryCard :machine="machine" @changed="load" />
          </div>
        </q-tab-panel>

        <q-tab-panel name="antivirus" class="q-px-none">
          <div class="row q-col-gutter-md">
            <MachineDefenderCard :machine="machine" />
            <MachineAntivirusCard :machine="machine" />
          </div>
          <MachineThreatsCard
            v-if="canReadThreats"
            v-model:pagination="threatPagination"
            :threats="threats"
            :loading="loading"
            :failed="threatsFailed"
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
            <MachineStorageCard :machine="machine" :low-disk-percent="lowDiskPercent" />
            <MachineMemoryCard :machine="machine" />
            <MachineGpuCard :machine="machine" />
            <MachineWindows11Card :machine="machine" />
          </div>
        </q-tab-panel>

        <q-tab-panel name="software" class="q-px-none">
          <MachineSoftwareCard :machine="machine" :loading="loading" />
        </q-tab-panel>

        <q-tab-panel name="compliance" class="q-px-none">
          <MachineComplianceCard :machine="machine" />
        </q-tab-panel>

        <!-- Each card under its own right, and the tab only when one of them
             shows: an account that reads neither was told « Aucune
             intervention enregistrée » about a journal nobody had asked for. -->
        <q-tab-panel v-if="canSeeHistory" name="history" class="q-px-none">
          <MachineMaintenanceCard
            v-if="auth.can('maintenance', 'read')"
            :machine-id="props.id"
            :hostname="machine.hostname ?? machine.machine_uuid"
            :can-write="auth.can('maintenance', 'write')"
            @changed="onMaintenanceChanged"
          />
          <MachineHistoryCard
            v-if="canReadInterventions || canWriteInterventions"
            :machine-id="props.id"
            :items="interventions"
            :total="interventionTotal"
            :loading="interventionsLoading"
            :failed="interventionsFailed"
            :can-read="canReadInterventions"
            :can-write="canWriteInterventions"
            @changed="loadInterventions(1)"
            @more="loadInterventions(interventionPage + 1)"
            @retry="loadInterventions(1)"
          />
        </q-tab-panel>

        <q-tab-panel v-if="canReadCommands" name="commands" class="q-px-none">
          <MachineCommandsCard
            v-model:pagination="commandPagination"
            :commands="commands"
            :loading="loading"
            :failed="commandsFailed"
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
      @merged="onCheckClosed"
    />

    <CommandOutputDialog v-model="detailOpen" :command="detailCommand" :kind="detailKind" />

    <PackageDeployDialog v-model="deployOpen" :machine-ids="[id]" @sent="load" />
  </q-page>
</template>

<script setup lang="ts">
import { intlTag, t } from 'src/i18n';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { AUTO_REFRESH_INTERVAL_MS, useAutoRefresh } from 'src/composables/useAutoRefresh';
import { useMachineNavigation } from 'src/composables/useMachineNavigation';
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import CommandOutputDialog from 'src/components/machine/CommandOutputDialog.vue';
import MachineAlertsCard from 'src/components/machine/MachineAlertsCard.vue';
import MachineAssetCard from 'src/components/machine/MachineAssetCard.vue';
import MachineWindows11Card from 'src/components/machine/MachineWindows11Card.vue';
import MachineComplianceCard from 'src/components/machine/MachineComplianceCard.vue';
import MachineDirectoryCard from 'src/components/machine/MachineDirectoryCard.vue';
import MachineAntivirusCard from 'src/components/machine/MachineAntivirusCard.vue';
import MachineCommandsCard from 'src/components/machine/MachineCommandsCard.vue';
import MachineDefenderCard from 'src/components/machine/MachineDefenderCard.vue';
import MachineGpuCard from 'src/components/machine/MachineGpuCard.vue';
import MachineHardwareCard from 'src/components/machine/MachineHardwareCard.vue';
import MachineHistoryCard from 'src/components/machine/MachineHistoryCard.vue';
import MachineMaintenanceCard from 'src/components/machine/MachineMaintenanceCard.vue';
import CheckCloseDialog from 'src/components/check/CheckCloseDialog.vue';
import CheckRequestDialog from 'src/components/check/CheckRequestDialog.vue';
import { createCheck, updateCheck, type Check, type CheckPayload } from 'src/services/checks';
import { checkInstructionsText } from 'src/services/alerts';
import MachineIdentityCard from 'src/components/machine/MachineIdentityCard.vue';
import MachineMemoryCard from 'src/components/machine/MachineMemoryCard.vue';
import MachineMergeDialog from 'src/components/machine/MachineMergeDialog.vue';
import PackageDeployDialog from 'src/components/package/PackageDeployDialog.vue';
import MachineNetworkCard from 'src/components/machine/MachineNetworkCard.vue';
import MachineUsageCard from 'src/components/machine/MachineUsageCard.vue';
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
  confirmIdentity,
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
  commandConfirm,
  createCommands,
  listCommands,
  singleSendNotification,
  type Command,
  type CommandAction,
} from 'src/services/commands';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
import { useFleetThresholds } from 'src/composables/useFleetThresholds';
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
import {
  documentTitle,
  formatDateTime,
  onlineColor,
  onlineIcon,
  onlineLabel,
  timeAgoLabel,
} from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

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
// The compliance tab's badge: the checks failed, live.
const complianceFailed = computed(
  () => machine.value?.compliance?.filter((c) => c.state === 'fail').length ?? 0,
);

// The poste needs machine:read alone; its threats and its commands each ask
// for their own permission, and a group may grant machine:read without them
// (audit B02). What the account may not read is not asked for.
const canReadThreats = computed(() => auth.can('threat', 'read'));
const canReadCommands = computed(() => auth.can('command', 'read'));
// « Historique » holds the journal of interventions and the maintenance card,
// each behind its own right; the tab is offered when either can show. The
// write alone (a group made through the API) still adds a line.
const canReadInterventions = computed(() => auth.can('intervention', 'read'));
const canWriteInterventions = computed(() => auth.can('intervention', 'write'));
const canSeeHistory = computed(
  () =>
    canReadInterventions.value || canWriteInterventions.value || auth.can('maintenance', 'read'),
);

/**
 * The open tab, kept in the URL so a link to « the Windows Update tab of this
 * poste » is a link, and so a reload comes back where the reader was. The
 * default tab stays out of the URL, as the list keeps its own defaults out.
 */
const tab = computed<MachineTab>({
  get: () => {
    const raw = queryValue(route.query.tab);
    if (!raw || !(MACHINE_TABS as readonly string[]).includes(raw)) return DEFAULT_MACHINE_TAB;
    // A link to the commands tab opened by an account that may not read them:
    // the tab is not rendered, and selecting it would leave an empty panel
    // under no selected tab (audit T14).
    if (raw === 'commands' && !canReadCommands.value) return DEFAULT_MACHINE_TAB;
    if (raw === 'history' && !canSeeHistory.value) return DEFAULT_MACHINE_TAB;
    return raw as MachineTab;
  },
  set: (value) => {
    const query = { ...route.query };
    if (value === DEFAULT_MACHINE_TAB) delete query.tab;
    else query.tab = value;
    void router.replace({ query });
  },
});
const commands = ref<Command[]>([]);
// The last read of either list failed: its card says so, and no « aucune
// menace » / « aucune alerte » is claimed off a list nobody could read.
const threatsFailed = ref(false);
const commandsFailed = ref(false);
const { lowDiskPercent } = useFleetThresholds();
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
const deployOpen = ref(false);
const canDeploy = computed(
  () =>
    auth.can('package', 'read') &&
    auth.can('command', 'execute') &&
    auth.can('risky_command', 'execute'),
);
// Revoke, re-enroll, merge: the machine:write half of the fiche.
const canManage = computed(() => auth.can('machine', 'write'));

// --- Verification requests: ask, reassign, close. The fiche reloads after
// each, since the banner and the journal both change.
const askOpen = ref(false);
const editCheckOpen = ref(false);
const closeCheckOpen = ref(false);
// The dialog edits a Check; the fiche carries a lighter shape of the open
// one. Bridged here rather than by a second payload on the API.
const openCheckAsCheck = computed<Check | null>(() => {
  const c = machine.value?.open_check;
  if (!c || !machine.value) return null;
  return {
    id: c.id,
    machine_id: machine.value.id,
    requested_by: c.requested_by,
    assigned_to:
      c.assigned_to_id && c.assigned_to_name
        ? {
            id: c.assigned_to_id,
            name: c.assigned_to_name,
            ...(c.assignee_reachable === false ? { reachable: false } : {}),
          }
        : null,
    instructions: c.instructions,
    instructions_code: c.instructions_code ?? null,
    instructions_params: c.instructions_params ?? null,
    created_at: c.created_at,
    updated_at: c.created_at,
    closed_at: null,
    closed_by: null,
    closing_note: null,
    machine: null,
  };
});
// A check asked for or handed to somebody changes what « Mes tâches » counts:
// the menu badge reads again (audit U19).
async function askCheck(payload: CheckPayload) {
  await createCheck(props.id, payload);
  notifyTasksChanged();
  notify($q, () => ({ type: 'positive', message: t('machine.check.requestedNotify') }));
  await load();
}
async function editCheck(payload: CheckPayload) {
  if (!machine.value?.open_check) return;
  await updateCheck(machine.value.open_check.id, payload);
  notifyTasksChanged();
  notify($q, () => ({ type: 'positive', message: t('machine.check.updatedNotify') }));
  await load();
}
async function onMaintenanceChanged() {
  await load();
  await loadInterventions(1);
}

/** The fiche and its journal: closing a check or merging a duplicate writes to both (audit B19). */
async function onCheckClosed() {
  await load();
  await loadInterventions(1);
}

// --- The journal. Loaded with the fiche and paged by « Afficher plus »:
// a poste's journal is a few dozen lines at most, read top to bottom.
const interventions = ref<Intervention[]>([]);
const interventionTotal = ref(0);
const interventionPage = ref(1);
const interventionsLoading = ref(false);
// The last read of the journal failed: the card says so, and does not claim
// « aucune intervention » off a journal nobody could read.
const interventionsFailed = ref(false);
const INTERVENTION_PAGE_SIZE = 25;

async function loadInterventions(page: number) {
  if (!canReadInterventions.value) return;
  interventionsLoading.value = true;
  const id = props.id;
  try {
    const res = await listInterventions(id, { page, page_size: INTERVENTION_PAGE_SIZE });
    if (id !== props.id) return;
    interventions.value = page === 1 ? res.items : [...interventions.value, ...res.items];
    interventionTotal.value = res.total;
    interventionPage.value = page;
    interventionsFailed.value = false;
  } catch {
    // Said by the card, with « Réessayer », for as long as it is true — a
    // toast was gone in five seconds and left the empty-journal sentence.
    // (A poste that does not exist shows no card: the page says « Poste
    // introuvable » once.)
    if (id === props.id) interventionsFailed.value = true;
  } finally {
    interventionsLoading.value = false;
  }
}

// --- Placement: the room the console files the poste in. By hand only
// when the server is not in a directory mode.
const manualMode = ref(true);
const canPlace = computed(() => auth.can('room', 'write') && manualMode.value);
// Asked only of an account that may place postes and read the rooms: without
// room:write the answer changes nothing, and without room:read the server
// refuses it — a group may hold the write alone, and got a 403 on every fiche.
watch(
  () => auth.can('room', 'write') && auth.can('room', 'read'),
  (allowed) => {
    if (!allowed) return;
    void getRoomConfig()
      .then((c) => {
        manualMode.value = c.manual;
      })
      .catch(() => {
        // Assumed manual: the worst case is a 409 the notification explains.
      });
  },
  { immediate: true },
);
const ROOM_NONE = 'none';
const placeOpen = ref(false);
const placing = ref(false);
const placeRoomId = ref<string | null>(null);
const rooms = ref<Room[]>([]);
const placeRoomOptions = computed(() => [
  { label: t('machine.place.none'), value: ROOM_NONE },
  ...rooms.value.map((r) => ({ label: roomLabel(r), value: r.id })),
]);

async function openPlace() {
  placeRoomId.value = machine.value?.room_id ?? ROOM_NONE;
  placeOpen.value = true;
  try {
    rooms.value = await listRooms();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('machine.place.roomsUnavailable')),
    }));
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
    // The poste now follows another room's maintenance owner and cycle, which
    // moves it in or out of somebody's « Mes tâches » (audit U19).
    notifyTasksChanged();
    notify($q, () => placementNotification(res));
    placeOpen.value = false;
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('machine.place.failed')),
    }));
  } finally {
    placing.value = false;
  }
}

const title = computed(
  () => machine.value?.hostname || machine.value?.machine_uuid || t('machine.page.title'),
);
// The tab says which poste, once known — the router could only say « Poste ».
watch(title, (value) => {
  document.title = documentTitle(value);
});

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
  // The poste this request is for. The counter alone is not enough: a walk to
  // the next poste waits out the fetch already in flight (refreshNow), and that
  // fetch, still the latest one when it answers, would write the poste being
  // left into a fiche whose URL already names the next one (audit T20).
  const machineId = props.id;
  const tp = threatPagination.value;
  const cp = commandPagination.value;
  const noPage = Promise.resolve(null);
  // The poste decides whether the page can show; the lists beside it only
  // fill their own card — one of them failing must not blank the fiche.
  const [m, t, active, c] = await Promise.allSettled([
    getMachine(machineId),
    canReadThreats.value
      ? listThreats({ machine_id: machineId, page: tp.page, page_size: tp.rowsPerPage })
      : noPage,
    // One row is enough: only the total is read.
    canReadThreats.value
      ? listThreats({ machine_id: machineId, status: 'active', page: 1, page_size: 1 })
      : noPage,
    canReadCommands.value
      ? listCommands({ machine_id: machineId, page: cp.page, page_size: cp.rowsPerPage })
      : noPage,
  ]);
  // Dropped without a word: the walk that changed the id has its own load
  // queued behind this one, and that load decides what the page shows.
  if (id !== requestId || machineId !== props.id) return;
  if (m.status === 'rejected') throw m.reason;
  machine.value = m.value;
  if (t.status === 'fulfilled' && t.value) {
    threats.value = t.value.items;
    // Merged into the current value, not the snapshot: a page turned while
    // this request was in the air must not be undone by its answer.
    threatPagination.value = { ...threatPagination.value, rowsNumber: t.value.total };
  }
  if (active.status === 'fulfilled' && active.value) activeThreats.value = active.value.total;
  // Either threat read failing leaves the count unknown: said on the card and
  // on the head of the fiche, never read as zero (an all-clear).
  threatsFailed.value = t.status === 'rejected' || active.status === 'rejected';
  if (c.status === 'fulfilled' && c.value) {
    commands.value = c.value.items;
    commandPagination.value = { ...commandPagination.value, rowsNumber: c.value.total };
  }
  commandsFailed.value = c.status === 'rejected';
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
const { lastRefreshedAt, lastError, refreshNow } = useAutoRefresh(fetchAll, {
  paused: () => detailOpen.value || mergeOpen.value,
});

/**
 * The manual load: this one shows the spinner, the automatic ones do not —
 * and says when it failed over a page already shown, which a background
 * refresh keeps quiet about (audit B04).
 */
async function load() {
  loading.value = true;
  try {
    await refreshNow();
  } finally {
    loading.value = false;
  }
  const error = lastError.value;
  if (error && machine.value) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(error, t('machine.actions.refreshFailed')),
      caption: t('machine.actions.refreshFailedCaption'),
    }));
  }
}

/**
 * The poste does not exist for this account: an unknown id (404), or one that
 * is not even an id (422 on a mistyped link). Retrying cannot change either.
 */
const notFound = computed(() => {
  const e = lastError.value as { response?: { status?: number } } | null;
  const status = e?.response?.status;
  return status === 404 || status === 422 || apiErrorCode(lastError.value) === 'machine.not_found';
});

const lastRefreshLabel = computed(() =>
  lastRefreshedAt.value ? lastRefreshedAt.value.toLocaleTimeString(intlTag()) : '',
);

const autoRefreshHint = computed(() =>
  t('machine.page.autoRefreshHint', { seconds: Math.round(AUTO_REFRESH_INTERVAL_MS / 1000) }),
);

// One action at a time: a double click on a menu entry fires its click twice
// before the menu has closed, and used to queue the command twice. Held from
// the click until the server has answered (or the confirmation is dismissed).
const sending = ref(false);

function runOne(action: CommandAction) {
  if (sending.value) return;
  sending.value = true;
  if (!action.confirm) {
    void send(action);
    return;
  }
  liveDialog($q, () => commandConfirm(action, 1, machine.value?.session_user_present ? 1 : 0))
    .onOk(() => {
      void send(action);
    })
    .onCancel(() => {
      sending.value = false;
    });
}

/** A failed send in the console's words: a vanished poste is not « Ressource introuvable ». */
function sendErrorMessage(e: unknown, fallback: string): string {
  const status = (e as { response?: { status?: number } } | null)?.response?.status;
  if (status === 404) return t('machine.actions.notFound');
  return apiErrorMessage(e, fallback);
}

// `sending` is already up while the confirmation is shown, so it cannot tell
// `send` that a send is running: a second « OK » of the same dialog — two
// clicks in the same instant, which the dialog hands over both — queued the
// command twice. This one is up from the first call to the server's answer.
let sendInFlight = false;

async function send(action: CommandAction) {
  if (sendInFlight) return;
  sendInFlight = true;
  sending.value = true;
  try {
    // The wake is not a command: the poste is off, so there is nothing to queue
    // for an agent that is not running. Same menu entry, same confirmation path,
    // a different call.
    if (action.serverSide) {
      await sendWake();
      return;
    }
    try {
      const res = await createCommands({ type: action.type, machine_ids: [props.id] });
      // The server de-duplicates per (poste, type), and says where the
      // standing one is. Saying "envoyée" here would have the administrator
      // watch a history that never grows a row.
      notify($q, () => singleSendNotification(action, res));
    } catch (e) {
      notify($q, () => ({
        type: 'negative',
        message: sendErrorMessage(e, t('machine.actions.sendFailed')),
      }));
      return;
    }
  } finally {
    sending.value = false;
    sendInFlight = false;
  }
  await load();
}

async function sendWake() {
  try {
    const res = await wakeMachines([props.id]);
    notify($q, () => wakeNotification(res));
    // Reloaded for the history, not for the machine's state: the wake is
    // recorded as a command row, while the poste itself will not reappear until
    // its agent reports — a minute or so after it has actually booted.
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: sendErrorMessage(e, t('machine.actions.wakeFailed')),
    }));
  }
}

function confirmRevoke() {
  liveDialog($q, () => ({
    title: t('machine.actions.revokeTitle'),
    message: t('machine.actions.revokeMessage'),
    cancel: { flat: true, noCaps: true, label: t('machine.actions.cancel') },
    ok: { unelevated: true, noCaps: true, label: t('machine.actions.revokeOk'), color: 'negative' },
    persistent: true,
  })).onOk(() => {
    void doRevoke();
  });
}

async function doRevoke() {
  try {
    await revokeToken(props.id);
    notify($q, () => ({ type: 'positive', message: t('machine.actions.revoked') }));
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('machine.actions.revokeFailed')),
    }));
  }
}

function confirmAllowReenroll() {
  liveDialog($q, () => ({
    title: t('machine.actions.allowTitle'),
    message: t('machine.actions.allowMessage'),
    cancel: { flat: true, noCaps: true, label: t('machine.actions.cancel') },
    ok: { unelevated: true, noCaps: true, label: t('machine.actions.allowOk') },
    persistent: true,
  })).onOk(() => {
    void doAllowReenroll();
  });
}

async function doAllowReenroll() {
  try {
    await allowReenroll(props.id);
    notify($q, () => ({ type: 'positive', message: t('machine.actions.allowed') }));
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('machine.actions.allowFailed')),
    }));
  }
}

// --- « Identité à confirmer » lifted by hand (a hardware swap, a re-image):
// nothing merged, the poste keeps its record and its history.
const confirmingIdentity = ref(false);

function askConfirmIdentity() {
  liveDialog($q, () => ({
    title: t('machine.actions.identityTitle'),
    message: t('machine.actions.identityMessage'),
    cancel: { flat: true, noCaps: true, label: t('machine.actions.cancel') },
    ok: { unelevated: true, noCaps: true, label: t('machine.actions.identityOk') },
    persistent: true,
  })).onOk(() => {
    void doConfirmIdentity();
  });
}

async function doConfirmIdentity() {
  confirmingIdentity.value = true;
  try {
    await confirmIdentity(props.id);
    notify($q, () => ({ type: 'positive', message: t('machine.actions.identityConfirmed') }));
    await load();
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('machine.actions.identityFailed')),
    }));
  } finally {
    confirmingIdentity.value = false;
  }
}

// The count in the label, so the button says whether it has anything to offer
// before it is pressed — its silence on that is what made it look broken.
const mergeLabel = computed(() =>
  duplicates.value.length
    ? t('machine.page.mergeCount', { count: duplicates.value.length })
    : t('machine.page.merge'),
);

const mergeHint = computed(() =>
  duplicates.value.length
    ? t('machine.page.mergeHint', { count: duplicates.value.length }, duplicates.value.length)
    : t('machine.page.mergeHintNone'),
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
    interventionsFailed.value = false;
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
watch(canReadInterventions, (allowed) => {
  if (allowed && !interventions.value.length) void loadInterventions(1);
});

onMounted(() => {
  void load();
  void loadInterventions(1);
});
</script>
