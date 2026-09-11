<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-sm">
      <div class="text-h5 col-auto">Postes</div>
      <q-space />
      <q-input
        v-model="search"
        dense
        outlined
        debounce="300"
        placeholder="Nom, IP, MAC, antivirus ou UUID…"
        class="col-auto"
        style="min-width: 260px"
        @update:model-value="pushQuery"
      >
        <template #append><q-icon name="search" /></template>
      </q-input>
      <!-- The two everyday facets stay on the bar: "on right now" and "carrying
           an active threat" are asked on the way to an action, and a toggle
           costs a glance where a dropdown costs a read. -->
      <q-toggle
        v-model="onlineOnly"
        dense
        label="Allumés"
        class="col-auto"
        @update:model-value="pushQuery"
      >
        <q-tooltip>Postes allumés — agent en contact ces dernières minutes</q-tooltip>
      </q-toggle>
      <q-toggle
        v-model="threatsOnly"
        dense
        label="Menaces actives"
        class="col-auto"
        @update:model-value="pushQuery"
      />
      <q-btn
        flat
        dense
        no-caps
        icon="filter_list"
        label="Filtres"
        class="col-auto"
        @click="filtersOpen = !filtersOpen"
      >
        <q-badge v-if="!filtersOpen && filterChips.length" color="primary" floating>
          {{ filterChips.length }}
        </q-badge>
      </q-btn>
      <div v-if="lastRefreshedAt" class="text-caption text-grey col-auto">
        Actualisé à {{ lastRefreshLabel }}
      </div>
      <q-btn flat dense round icon="download" class="col-auto" @click="exportOpen = true">
        <q-tooltip>Exporter le parc filtré (Excel ou CSV, colonnes au choix)</q-tooltip>
      </q-btn>
      <q-btn flat round icon="refresh" :loading="loading" class="col-auto" @click="reload">
        <q-tooltip>{{ autoRefreshHint }}</q-tooltip>
      </q-btn>
    </div>

    <!-- The dropdowns, folded by default: each is reached for now and then, and
         a bar wearing all of them at once buried the search. Two rows, because
         the questions come in two kinds: "is it protected" and "what is it". -->
    <q-slide-transition>
      <div v-show="filtersOpen" class="q-mb-sm">
        <div class="row items-center q-col-gutter-sm q-mb-xs">
          <div class="col-12 col-sm-auto text-caption text-grey filter-row-label">Sécurité</div>
          <q-select
            v-model="antivirus"
            :options="antivirusOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 200px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="status"
            :options="statusOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 190px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="wu"
            :options="wuOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 210px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="scan"
            :options="scanOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 200px"
            @update:model-value="pushQuery"
          />
        </div>
        <div class="row items-center q-col-gutter-sm">
          <div class="col-12 col-sm-auto text-caption text-grey filter-row-label">Poste</div>
          <!-- First on the "what is it" row: on a multi-site parc "where" is the
               facet everything else is asked within. -->
          <q-select
            v-model="location"
            :options="locationOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 220px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="os"
            :options="osOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 200px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="agent"
            :options="agentOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 220px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="manufacturer"
            :options="manufacturerOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 190px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="model"
            :options="modelOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 220px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="processor"
            :options="processorOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 260px"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="chassis"
            :options="chassisOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 170px"
            @update:model-value="pushQuery"
          />
          <!-- Memory as a bound and a figure: "au moins 16 Gio" is how the
               upgrade question is asked, and no closed list holds every parc's
               sizes. The filter applies once both halves are set. -->
          <q-select
            v-model="ramOp"
            :options="ramOpOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 180px"
            @update:model-value="pushQuery"
          />
          <q-input
            v-model="ramGb"
            type="number"
            min="1"
            step="1"
            dense
            outlined
            debounce="400"
            suffix="Gio"
            placeholder="16"
            class="col-auto"
            style="width: 100px"
            :disable="!ramOp"
            @update:model-value="pushQuery"
          />
          <q-select
            v-model="diskFree"
            :options="diskOptions"
            emit-value
            map-options
            dense
            outlined
            class="col-auto"
            style="width: 210px"
            @update:model-value="pushQuery"
          />
        </div>
      </div>
    </q-slide-transition>

    <!-- A folded filter must never narrow the list silently — the dashboard
         cards land here with one already set. Chips name the active ones, and
         removing one clears it without opening the panel. -->
    <div v-if="!filtersOpen && filterChips.length" class="row items-center q-mb-sm">
      <q-chip
        v-for="chip in filterChips"
        :key="chip.key"
        removable
        dense
        color="primary"
        text-color="white"
        @remove="clearFilter(chip.key)"
      >
        {{ chip.label }}
      </q-chip>
    </div>

    <div v-if="selected.length" class="row items-center q-mb-sm">
      <div class="text-caption text-grey q-mr-md">{{ selected.length }} sélectionné(s)</div>
      <q-btn-dropdown color="primary" dense label="Action groupée" icon="bolt">
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
      v-model:pagination="pagination"
      :rows="rows"
      :columns="columns"
      row-key="id"
      selection="multiple"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      binary-state-sort
      @request="onRequest"
      @row-click="(_evt, row, index) => goDetail(row, index)"
    >
      <template #body-cell-hostname="props">
        <q-td :props="props">
          <!-- Leading, so a column of dots reads as one glance down the list. -->
          <q-icon
            :name="onlineIcon(props.row.is_online)"
            :color="onlineColor(props.row.is_online)"
            size="12px"
            class="q-mr-sm"
          >
            <q-tooltip>
              {{ onlineLabel(props.row.is_online) }} — dernier contact
              {{ timeAgoLabel(props.row.last_seen) }}
            </q-tooltip>
          </q-icon>
          {{ props.value || props.row.machine_uuid }}
          <q-icon
            v-if="props.row.needs_verification"
            name="warning"
            color="orange"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>À vérifier — identité du poste à confirmer (doublon possible)</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-agent="props">
        <q-td :props="props">
          <span :class="{ 'text-grey': !props.value }">{{ props.value ?? '—' }}</span>
          <q-icon
            v-if="isAgentOutdated(props.value, agentLatest)"
            name="system_update_alt"
            color="orange"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>Agent obsolète — référence du parc : {{ agentLatest }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-antivirus="props">
        <q-td :props="props">
          <q-badge :color="protectionColor(props.row.is_up_to_date)">
            {{ antivirusLabel(props.row.av_product_name) }}
          </q-badge>
          <q-tooltip>{{ antivirusTooltip(props.row) }}</q-tooltip>
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
      <!-- A bar and not a figure: the reason to scan this column is to spot the
           postes about to run out, and a bar is read without being parsed. The
           percentage is what colours it — 40 Go left on a 4 To disk and on a
           128 Go SSD are not the same news. -->
      <template #body-cell-disk="props">
        <q-td :props="props">
          <template v-if="props.row.system_volume_total_mb">
            <q-linear-progress
              :value="usedRatio(props.row)"
              :color="
                diskColor(
                  freePercent(props.row.system_volume_total_mb, props.row.system_volume_free_mb),
                )
              "
              size="8px"
              rounded
              style="width: 90px"
            />
            <div class="text-caption text-grey">
              {{ sizeLabel(props.row.system_volume_free_mb) }} libres
            </div>
            <q-tooltip>
              {{ sizeLabel(props.row.system_volume_free_mb) }} libres sur
              {{ sizeLabel(props.row.system_volume_total_mb) }}
            </q-tooltip>
          </template>
          <span v-else class="text-grey">—</span>
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

    <MachineExportDialog
      v-model="exportOpen"
      :params="filterParams"
      :count="pagination.rowsNumber"
    />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import { AUTO_REFRESH_INTERVAL_MS, useAutoRefresh } from 'src/composables/useAutoRefresh';
import MachineExportDialog from 'src/components/machine/MachineExportDialog.vue';
import {
  listAgentVersions,
  listAntivirusProducts,
  listChassisTypes,
  listLocations,
  listMachines,
  listManufacturers,
  listModels,
  listOsVersions,
  listProcessors,
  wakeMachines,
  wakeNotification,
  type FleetValue,
  type ListMachinesParams,
  type Machine,
  type MachineSortField,
  type MachineStatus,
  type ScanFilter,
  type WindowsUpdateFilter,
} from 'src/services/machines';
import {
  bulkSendNotification,
  commandActionGroups,
  createCommands,
  type CommandAction,
} from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import {
  CHASSIS_TYPES,
  DEFAULT_PAGE_SIZE,
  MACHINE_STATUSES,
  PAGE_SIZE_OPTIONS,
  SCAN_AGE_DAYS,
  SCAN_FILTERS,
  WU_FILTERS,
  queryInt,
  queryValue,
} from 'src/utils/machineQuery';
import {
  antivirusLabel,
  antivirusStatusLabel,
  diskColor,
  formatDateTime,
  freePercent,
  onlineColor,
  onlineIcon,
  onlineLabel,
  protectionColor,
  protectionLabel,
  sizeLabel,
  sessionColor,
  sessionLabel,
  timeAgoLabel,
  wuPendingColor,
  wuPendingLabel,
} from 'src/utils/format';
import { isAgentOutdated } from 'src/utils/agentVersion';

const $q = useQuasar();
const router = useRouter();
const route = useRoute();

const rows = ref<Machine[]>([]);
const selected = ref<Machine[]>([]);
const loading = ref(false);
const search = ref('');
const domain = ref('');
// The site, exact like the domain: the dropdown feeds it fleet values.
const location = ref<string | null>(null);
const antivirus = ref<string | null>(null);
const os = ref<string | null>(null);
// One dropdown for two questions: "behind the reference" (the sentinel) or one
// exact version. A version is never spelled like the sentinel.
const AGENT_OUTDATED = 'outdated';
const agent = ref<string | null>(null);
// The reference the rows are flagged against, as the list response carries it.
const agentLatest = ref<string | null>(null);
const status = ref<MachineStatus | null>(null);
const wu = ref<WindowsUpdateFilter | null>(null);
// One token "<type>:<days>" (e.g. "quick:7"): the dropdown speaks in one value,
// the URL and the server in a scan type and an age — split at the boundaries.
const scan = ref<string | null>(null);
const threatsOnly = ref(false);
const onlineOnly = ref(false);
// Inventory facets. `model` is a substring like the antivirus one — "OptiPlex"
// has to gather the 7010 and the 7020, which is how a parc is reasoned about.
const model = ref<string | null>(null);
const manufacturer = ref<string | null>(null);
const processor = ref<string | null>(null);
const chassis = ref<string | null>(null);
// Memory in two halves — a bound and a figure in GiB — because "au moins 16"
// is how the upgrade question is asked. Only counts once both are set.
const ramOp = ref<'min' | 'max' | null>(null);
// A string as often as a number: QInput hands back what was typed, whatever
// the `type`, and the URL hands back a parsed integer. `ramGbValue` is the
// one reading the filter uses.
const ramGb = ref<number | string | null>(null);

/** The typed figure as a positive whole number of GiB, or null. */
const ramGbValue = computed<number | null>(() => {
  if (ramGb.value === null || ramGb.value === '') return null;
  const n = Number(ramGb.value);
  return Number.isInteger(n) && n > 0 ? n : null;
});
// A *percentage* of free space and not a size: 40 Go left on a 4 To disk and on
// a 128 Go SSD are not the same news.
const diskFree = ref<number | null>(null);
// Set by a link from the software catalogue or from a fiche; never by a widget
// here, since nobody types a catalogue id. Carried through the URL so the back
// arrow from a fiche comes back to the same filtered list.
const softwareId = ref<number | null>(null);

// UI state, not query state: the panel starts folded even when a filter is
// active — the chips under the bar say what is filtering instead.
const filtersOpen = ref(false);

/** Sortable columns ↔ their API field: the table speaks in column names, the
 * URL and the server in field names. */
const SORT_FIELD_BY_COLUMN: Record<string, MachineSortField> = {
  hostname: 'hostname',
  domain: 'domain',
  location: 'location',
  antivirus: 'av_product_name',
  windows_update: 'wu_pending_count',
  session: 'session_user_present',
  model: 'hw_model',
  disk: 'disk_free_percent',
  last_seen: 'last_seen',
};
const COLUMN_BY_SORT_FIELD = Object.fromEntries(
  Object.entries(SORT_FIELD_BY_COLUMN).map(([column, field]) => [field, column]),
) as Record<string, string>;

/** Server-side pagination state. `rowsNumber` present makes the q-table hand
 * every page/sort interaction to `onRequest` instead of slicing `rows` — the
 * server holds the fleet, the table only ever holds one page of it. */
const pagination = ref({
  sortBy: 'last_seen' as string | null,
  descending: true,
  page: 1,
  rowsPerPage: DEFAULT_PAGE_SIZE,
  rowsNumber: 0,
});

// Filled from the fleet on mount: the products installed are data, not a list
// the console can know in advance. The count sits in the label so the dropdown
// doubles as an inventory of a mixed parc.
const antivirusOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les antivirus', value: null },
]);

// « Antivirus » in the labels, not just « à jour » : since the Windows Update
// filter joined it, this axis has to say which of the two updates it means.
const statusOptions = [
  { label: 'Antivirus : Tous statuts', value: null },
  { label: 'Antivirus à jour', value: 'up_to_date' },
  { label: 'Antivirus périmé', value: 'outdated' },
  { label: 'À vérifier', value: 'needs_verification' },
  { label: 'Inactif', value: 'inactive' },
];

const wuOptions = [
  { label: 'Windows Update : Tous statuts', value: null },
  { label: 'MAJ Windows requises', value: 'pending' },
  { label: 'Redémarrage requis', value: 'reboot_required' },
];

// « > 1 sem. » / « > 1 mois » : the two questions asked of a scan date. A
// never-run scan counts as overdue server-side — those are the postes the
// filter exists to surface.
const scanOptions = [
  { label: 'Scan AV : Tous', value: null },
  { label: 'Scan rapide > 1 sem.', value: 'quick:7' },
  { label: 'Scan rapide > 1 mois', value: 'quick:30' },
  { label: 'Scan complet > 1 sem.', value: 'full:7' },
  { label: 'Scan complet > 1 mois', value: 'full:30' },
  { label: 'Les 2 scans > 1 sem.', value: 'both:7' },
  { label: 'Les 2 scans > 1 mois', value: 'both:30' },
];

// Filled from the fleet like the antivirus list, and for the same reason: the
// versions installed are data. The count doubles as a migration progress bar.
const osOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les OS', value: null },
]);

// Filled from the fleet like the OS list: the versions running are data, and
// the counts are the deployment's progress bar. "Obsolète" first, because it
// is the entry reached for the morning after a push.
const agentOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Agent : toutes versions', value: null },
]);

// Filled from the fleet: the sites are whatever the deployments wrote in
// their agents' configuration, and the counts are a head count per site.
const locationOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les emplacements', value: null },
]);

const modelOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les modèles', value: null },
]);

const manufacturerOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les constructeurs', value: null },
]);

const processorOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les processeurs', value: null },
]);

// The kinds are a closed list the agent normalises to, so the entries are
// known in advance; the fleet only says which of them are present, and how
// many of each.
const chassisOptions = ref<{ label: string; value: string | null }[]>([
  { label: 'Tous les types de poste', value: null },
]);

const ramOpOptions: { label: string; value: 'min' | 'max' | null }[] = [
  { label: 'Mémoire : toutes', value: null },
  { label: 'Mémoire : au moins', value: 'min' },
  { label: 'Mémoire : au plus', value: 'max' },
];

const diskOptions = [
  { label: 'Espace disque : tous', value: null },
  { label: 'Moins de 10 % libres', value: 10 },
  { label: 'Moins de 20 % libres', value: 20 },
];

type FilterKey =
  | 'location'
  | 'antivirus'
  | 'status'
  | 'wu'
  | 'scan'
  | 'os'
  | 'manufacturer'
  | 'model'
  | 'processor'
  | 'chassis'
  | 'ram'
  | 'disk'
  | 'software'
  | 'agent';

/** Whether the memory filter is complete enough to apply. */
const ramActive = computed(() => ramOp.value !== null && ramGbValue.value !== null);

/** The folded filters currently narrowing the list, as chip labels. The label
 * is looked up in the dropdown's own options, so a chip always reads exactly
 * like the entry that set it. */
const filterChips = computed<{ key: FilterKey; label: string }[]>(() => {
  const label = (opts: { label: string; value: string | null }[], v: string) =>
    opts.find((o) => o.value === v)?.label ?? v;
  const chips: { key: FilterKey; label: string }[] = [];
  if (location.value)
    chips.push({ key: 'location', label: label(locationOptions.value, location.value) });
  if (antivirus.value)
    chips.push({ key: 'antivirus', label: label(antivirusOptions.value, antivirus.value) });
  if (status.value) chips.push({ key: 'status', label: label(statusOptions, status.value) });
  if (wu.value) chips.push({ key: 'wu', label: label(wuOptions, wu.value) });
  if (scan.value) chips.push({ key: 'scan', label: label(scanOptions, scan.value) });
  if (os.value) chips.push({ key: 'os', label: label(osOptions.value, os.value) });
  if (agent.value) chips.push({ key: 'agent', label: label(agentOptions.value, agent.value) });
  if (manufacturer.value) {
    chips.push({
      key: 'manufacturer',
      label: label(manufacturerOptions.value, manufacturer.value),
    });
  }
  if (model.value) chips.push({ key: 'model', label: label(modelOptions.value, model.value) });
  if (processor.value) {
    chips.push({ key: 'processor', label: label(processorOptions.value, processor.value) });
  }
  if (chassis.value)
    chips.push({ key: 'chassis', label: label(chassisOptions.value, chassis.value) });
  if (ramActive.value) {
    chips.push({
      key: 'ram',
      label: `Mémoire ${ramOp.value === 'min' ? '≥' : '≤'} ${ramGbValue.value} Gio`,
    });
  }
  if (diskFree.value != null) {
    chips.push({
      key: 'disk',
      label: diskOptions.find((o) => o.value === diskFree.value)?.label ?? 'Espace disque',
    });
  }
  // No option list behind this one: it comes from a link, so the chip is what
  // tells the reader why the list is short — and the only way back out of it.
  if (softwareId.value != null) {
    chips.push({ key: 'software', label: 'Postes portant un logiciel' });
  }
  return chips;
});

function clearFilter(key: FilterKey) {
  if (key === 'ram') {
    ramOp.value = null;
    ramGb.value = null;
  } else {
    const refs = {
      location,
      antivirus,
      status,
      wu,
      scan,
      os,
      manufacturer,
      model,
      processor,
      chassis,
      disk: diskFree,
      software: softwareId,
      agent,
    };
    refs[key].value = null;
  }
  pushQuery();
}

// bulkOnly: the two diagnostics stay on the detail page. Their value is reading
// one machine's output; fired on a selection they queue a report per poste that
// nobody will open.
const actionGroups = commandActionGroups({ bulkOnly: true });

const columns: QTableColumn<Machine>[] = [
  { name: 'hostname', label: 'Nom', field: 'hostname', align: 'left', sortable: true },
  { name: 'domain', label: 'Domaine', field: 'domain', align: 'left', sortable: true },
  // Sortable, and grouping is the point: a multi-site parc is read one site at
  // a time. Empty on a parc whose agents name no site.
  {
    name: 'location',
    label: 'Emplacement',
    field: 'location',
    align: 'left',
    sortable: true,
    format: (val: string | null) => val ?? '—',
  },
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
  // The agent's version, flagged when below the parc's reference. In the list
  // because the question it answers — "lesquels n'ont pas encore la nouvelle
  // version" — is asked of the parc, not of one poste.
  { name: 'agent', label: 'Agent', field: 'agent_version', align: 'left' },
  // name ≠ field like the session column below: the cell renders the product and
  // its state together, while `field` keeps a sensible sort key. Sortable because
  // grouping a mixed parc by product is exactly what this column is for.
  // The badge colour carries the overall state (`is_up_to_date`) and the tooltip
  // the signature detail — one column where there used to be three.
  {
    name: 'antivirus',
    label: 'Antivirus',
    field: 'av_product_name',
    align: 'left',
    sortable: true,
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
  // The two inventory columns the list is scanned for. The rest of the twenty-five
  // is one machine's business and stays on the fiche.
  { name: 'model', label: 'Modèle', field: 'hw_model', align: 'left', sortable: true },
  // Sortable, and the sort is the point: "montre-moi les postes qui n'ont plus
  // de place" is the question this column exists for. The bar carries the
  // percentage, because that is the figure that means something.
  {
    name: 'disk',
    label: 'Disque',
    field: 'system_volume_free_mb',
    align: 'left',
    sortable: true,
  },
  { name: 'last_seen', label: 'Vu le', field: 'last_seen', align: 'left', sortable: true },
];

/** Open a poste, carrying the whole list query plus the row's absolute rank in
 * it (`i`). The detail page uses the query to come back to this exact search,
 * and the rank to walk to the previous/next result of it. */
function goDetail(row: Machine, rowIndex: number) {
  const p = pagination.value;
  const i = (p.page - 1) * p.rowsPerPage + rowIndex;
  void router.push({
    name: 'machine-detail',
    params: { id: row.id },
    query: { ...buildQuery(), i: String(i) },
  });
}

/** One line: overall state, what the Security Center says of the product, and
 * the signature version — the detail the badge colour compresses. */
function antivirusTooltip(m: Machine): string {
  const parts = [
    protectionLabel(m.is_up_to_date),
    antivirusStatusLabel(
      m.av_product_name,
      m.av_product_enabled,
      m.av_product_signatures_up_to_date,
    ),
  ];
  if (m.signature_version) parts.push(`signatures ${m.signature_version}`);
  return parts.join(' · ');
}

/** Read the filters, sort and page from the URL — the dashboard cards land
 * here with one set, and the detail page's back arrow with another. */
function applyQuery() {
  const q = route.query;
  search.value = queryValue(q.search) ?? '';
  domain.value = queryValue(q.domain) ?? '';
  location.value = queryValue(q.location);
  antivirus.value = queryValue(q.antivirus);
  os.value = queryValue(q.os_version);
  agent.value =
    queryValue(q.agent_outdated) === 'true' ? AGENT_OUTDATED : queryValue(q.agent_version);
  const s = queryValue(q.status);
  status.value = s && MACHINE_STATUSES.includes(s) ? (s as MachineStatus) : null;
  const w = queryValue(q.wu_status);
  wu.value = w && WU_FILTERS.includes(w) ? (w as WindowsUpdateFilter) : null;
  const scanType = queryValue(q.scan_type);
  const scanDays = Number(queryValue(q.scan_days));
  scan.value =
    scanType && SCAN_FILTERS.includes(scanType)
      ? `${scanType}:${SCAN_AGE_DAYS.includes(scanDays) ? scanDays : SCAN_AGE_DAYS[0]}`
      : null;
  threatsOnly.value = queryValue(q.with_active_threats) === 'true';
  onlineOnly.value = queryValue(q.online) === 'true';
  model.value = queryValue(q.hw_model);
  manufacturer.value = queryValue(q.hw_manufacturer);
  processor.value = queryValue(q.cpu_model);
  const kind = queryValue(q.hw_chassis_type);
  chassis.value = kind && CHASSIS_TYPES.some((c) => c.value === kind) ? kind : null;
  // One bound at a time on screen: a URL carrying both keeps the lower one,
  // which is the upgrade question and the more common of the two.
  const ramMin = queryInt(q.ram_min_gb);
  const ramMax = queryInt(q.ram_max_gb);
  if (ramMin !== null) {
    ramOp.value = 'min';
    ramGb.value = ramMin;
  } else if (ramMax !== null) {
    ramOp.value = 'max';
    ramGb.value = ramMax;
  } else {
    ramOp.value = null;
    ramGb.value = null;
  }
  const below = Number(queryValue(q.disk_free_below));
  diskFree.value = diskOptions.some((o) => o.value === below) ? below : null;
  const software = Number(queryValue(q.software_id));
  softwareId.value = Number.isInteger(software) && software > 0 ? software : null;

  const sortField = queryValue(q.sort_by);
  const sortColumn = sortField ? COLUMN_BY_SORT_FIELD[sortField] : undefined;
  const page = Number(queryValue(q.page) ?? '1');
  const pageSize = Number(queryValue(q.page_size) ?? String(DEFAULT_PAGE_SIZE));
  pagination.value = {
    ...pagination.value,
    // No sort in the URL = the server's default order, freshest first — shown
    // as such rather than as "unsorted".
    sortBy: sortColumn ?? 'last_seen',
    descending: sortColumn ? queryValue(q.sort_desc) !== 'false' : true,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    rowsPerPage: PAGE_SIZE_OPTIONS.includes(pageSize) ? pageSize : DEFAULT_PAGE_SIZE,
  };
}

/** The whole list state as URL query params, defaults omitted so the common
 * URL stays short. Shared by the address bar and the links into a fiche. */
function buildQuery(): Record<string, string> {
  const query: Record<string, string> = {};
  if (search.value) query.search = search.value;
  if (domain.value) query.domain = domain.value;
  if (location.value) query.location = location.value;
  if (antivirus.value) query.antivirus = antivirus.value;
  if (os.value) query.os_version = os.value;
  if (agent.value === AGENT_OUTDATED) query.agent_outdated = 'true';
  else if (agent.value) query.agent_version = agent.value;
  if (status.value) query.status = status.value;
  if (wu.value) query.wu_status = wu.value;
  if (scan.value) {
    const [scanType, scanDays] = scan.value.split(':');
    query.scan_type = scanType!;
    query.scan_days = scanDays!;
  }
  if (threatsOnly.value) query.with_active_threats = 'true';
  if (onlineOnly.value) query.online = 'true';
  if (model.value) query.hw_model = model.value;
  if (manufacturer.value) query.hw_manufacturer = manufacturer.value;
  if (processor.value) query.cpu_model = processor.value;
  if (chassis.value) query.hw_chassis_type = chassis.value;
  if (ramActive.value) {
    query[ramOp.value === 'min' ? 'ram_min_gb' : 'ram_max_gb'] = String(ramGbValue.value);
  }
  if (diskFree.value != null) query.disk_free_below = String(diskFree.value);
  if (softwareId.value != null) query.software_id = String(softwareId.value);
  const p = pagination.value;
  const field = p.sortBy ? SORT_FIELD_BY_COLUMN[p.sortBy] : undefined;
  if (field && !(field === 'last_seen' && p.descending)) {
    query.sort_by = field;
    query.sort_desc = String(p.descending);
  }
  if (p.page > 1) query.page = String(p.page);
  if (p.rowsPerPage !== DEFAULT_PAGE_SIZE) query.page_size = String(p.rowsPerPage);
  return query;
}

// The URL is the single source of truth for the list state: widgets and the
// table push into it, and the reload happens in the route watcher — so a link
// from the dashboard, a pasted URL, a widget change and a page turn all take
// the same path.
function pushQuery() {
  // A filter change starts a new search: page 1 of it, sort kept.
  pagination.value = { ...pagination.value, page: 1 };
  void router.replace({ query: buildQuery() });
}

/** Every page/sort/page-size interaction of the server-side table lands here. */
function onRequest(evt: {
  pagination: { sortBy?: string | null; descending?: boolean; page?: number; rowsPerPage?: number };
}) {
  const p = evt.pagination;
  pagination.value = {
    sortBy: p.sortBy ?? null,
    descending: p.descending ?? true,
    page: p.page ?? 1,
    rowsPerPage: p.rowsPerPage ?? DEFAULT_PAGE_SIZE,
    rowsNumber: pagination.value.rowsNumber,
  };
  void router.replace({ query: buildQuery() });
}

watch(
  () => route.query,
  () => {
    applyQuery();
    void reload();
  },
);

// Which fetch is the current one. A background refresh started 90 s ago and a
// page turn issued just now are both in flight at once, and whichever answers
// last would otherwise win — putting page 1's rows under a table that says page
// 2, and writing its own stale page number back over the user's.
let requestId = 0;

/**
 * The current filters as API params — every facet, no pagination and no sort.
 * One definition for the list and the export: an export that silently ignored
 * a facet the reader had set would be worse than no export at all.
 */
const filterParams = computed<ListMachinesParams>(() => {
  const params: ListMachinesParams = {};
  if (search.value) params.search = search.value;
  if (domain.value) params.domain = domain.value;
  if (location.value) params.location = location.value;
  if (antivirus.value) params.antivirus = antivirus.value;
  if (os.value) params.os_version = os.value;
  if (agent.value === AGENT_OUTDATED) params.agent_outdated = true;
  else if (agent.value) params.agent_version = agent.value;
  if (status.value) params.status = status.value;
  if (wu.value) params.wu_status = wu.value;
  if (scan.value) {
    const [scanType, scanDays] = scan.value.split(':');
    params.scan_type = scanType as ScanFilter;
    params.scan_older_than_days = Number(scanDays);
  }
  if (threatsOnly.value) params.with_active_threats = true;
  if (onlineOnly.value) params.online = true;
  if (model.value) params.hw_model = model.value;
  if (manufacturer.value) params.hw_manufacturer = manufacturer.value;
  if (processor.value) params.cpu_model = processor.value;
  if (chassis.value) params.hw_chassis_type = chassis.value;
  if (ramActive.value && ramGbValue.value !== null) {
    if (ramOp.value === 'min') params.ram_min_gb = ramGbValue.value;
    else params.ram_max_gb = ramGbValue.value;
  }
  if (diskFree.value != null) params.disk_free_below = diskFree.value;
  if (softwareId.value != null) params.software_id = softwareId.value;
  return params;
});

/** Fetch the current page of the current query. */
async function fetchMachines() {
  const id = ++requestId;
  const p = pagination.value;
  const params: ListMachinesParams = {
    ...filterParams.value,
    page: p.page,
    page_size: p.rowsPerPage,
  };
  const field = p.sortBy ? SORT_FIELD_BY_COLUMN[p.sortBy] : undefined;
  if (field) {
    params.sort_by = field;
    params.sort_desc = p.descending;
  }
  const data = await listMachines(params);
  // Superseded while we waited: these rows answer a question nobody is asking
  // any more, and the fetch that replaced us will write its own.
  if (id !== requestId) return;
  if (!data.items.length && data.total > 0 && p.page > 1) {
    // The page evaporated under us — the fleet shrank, or a filter came from a
    // URL pointing past the end. Fall back on the last page that still exists.
    pagination.value = {
      ...pagination.value,
      page: Math.ceil(data.total / p.rowsPerPage),
      rowsNumber: data.total,
    };
    void router.replace({ query: buildQuery() });
    return;
  }
  rows.value = data.items;
  agentLatest.value = data.agent_latest_version;
  // Merged into the *current* pagination, never the snapshot taken above: the
  // user may have turned the page while this request was in the air, and
  // writing the snapshot back would silently undo it.
  pagination.value = { ...pagination.value, rowsNumber: data.total };
}

// The machine list follows the fleet like the dashboard does: agents report
// every minute, so a page left open shows postes coming online without a
// keypress. Paused while rows are selected — a bulk action being composed must
// not have its rows shuffled underneath it.
const { lastRefreshedAt, refreshNow } = useAutoRefresh(fetchMachines, {
  paused: () => selected.value.length > 0,
});

const lastRefreshLabel = computed(() =>
  lastRefreshedAt.value ? lastRefreshedAt.value.toLocaleTimeString('fr-FR') : '',
);

const autoRefreshHint = `Actualiser — automatique toutes les ${Math.round(
  AUTO_REFRESH_INTERVAL_MS / 1000,
)} s, en pause pendant une sélection`;

/** The user-visible load: spinner on, and the auto-refresh countdown restarts
 * so the next background tick lands a full period away. */
async function reload() {
  loading.value = true;
  try {
    await refreshNow();
  } finally {
    loading.value = false;
  }
}

async function loadAntivirusOptions() {
  try {
    const products = await listAntivirusProducts();
    antivirusOptions.value = [
      { label: 'Tous les antivirus', value: null },
      ...products.map((p) => ({ label: `${p.name} (${p.count})`, value: p.name })),
    ];
  } catch {
    // A filter that failed to populate must not blank the machine list: the
    // dropdown simply keeps its "Tous antivirus" entry.
  }
}

async function loadAgentOptions() {
  try {
    const fleet = await listAgentVersions();
    const behind = fleet.versions.filter((v) => v.outdated).reduce((n, v) => n + v.count, 0);
    agentOptions.value = [
      { label: 'Agent : toutes versions', value: null },
      { label: `Agent obsolète (${behind})`, value: AGENT_OUTDATED },
      ...fleet.versions.map((v) => ({
        label: `Agent ${v.name}${v.name === fleet.latest ? ' · référence' : ''} (${v.count})`,
        value: v.name,
      })),
    ];
  } catch {
    // Same contract as the other dropdowns: degrade to "toutes versions".
  }
}

async function loadOsOptions() {
  try {
    const versions = await listOsVersions();
    osOptions.value = [
      { label: 'Tous les OS', value: null },
      ...versions.map((v) => ({ label: `${v.name} (${v.count})`, value: v.name })),
    ];
  } catch {
    // Same contract as the antivirus dropdown: degrade to "Tous les OS".
  }
}

/**
 * Fill one inventory dropdown from a fleet listing, on the same reasoning as
 * the antivirus and OS ones: what a parc contains is data, and the counts
 * double as an inventory the renewal plan is read off. A listing that failed
 * leaves its "Tous" entry alone — the filter is still typeable in the URL.
 */
async function loadFleetOptions(
  target: { value: { label: string; value: string | null }[] },
  fetch: () => Promise<FleetValue[]>,
  labelOf: (name: string) => string = (name) => name,
) {
  try {
    const values = await fetch();
    const all = target.value[0]!;
    target.value = [
      all,
      ...values.map((v) => ({ label: `${labelOf(v.name)} (${v.count})`, value: v.name })),
    ];
  } catch {
    // See above.
  }
}

/** The chassis kind in the console's words — the fleet reports the raw key. */
function chassisLabelOf(name: string): string {
  return CHASSIS_TYPES.find((c) => c.value === name)?.label ?? name;
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
  // The wake is emitted by the server, not queued for agents that — by
  // definition of the action — are not running. Everything around it is the
  // same: same menu, same selection, same notification slot.
  if (action.serverSide) {
    await wakeBulk(ids);
    return;
  }
  try {
    const res = await createCommands({ type: action.type, machine_ids: ids });
    $q.notify(bulkSendNotification(res));
    selected.value = [];
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, "Échec de l'envoi des commandes") });
  }
}

async function wakeBulk(ids: string[]) {
  try {
    $q.notify(wakeNotification(await wakeMachines(ids)));
    selected.value = [];
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec du réveil') });
  }
}

/** The bar fills with what is *used*: a full disk is a full bar. */
function usedRatio(m: Machine): number {
  const total = m.system_volume_total_mb;
  const free = m.system_volume_free_mb;
  if (!total || free == null) return 0;
  return Math.min(1, Math.max(0, (total - free) / total));
}

// The export dialog: the filtered fleet, columns at the reader's choice. It
// reads `filterParams` live, so opening it after a filter change exports what
// the table shows.
const exportOpen = ref(false);

onMounted(() => {
  applyQuery();
  void reload();
  void loadAntivirusOptions();
  void loadOsOptions();
  void loadAgentOptions();
  void loadFleetOptions(locationOptions, listLocations);
  void loadFleetOptions(modelOptions, listModels);
  void loadFleetOptions(manufacturerOptions, listManufacturers);
  void loadFleetOptions(processorOptions, listProcessors);
  void loadFleetOptions(chassisOptions, listChassisTypes, chassisLabelOf);
});
</script>

<style scoped>
/* The row captions line up with the dropdowns without taking a column. */
.filter-row-label {
  min-width: 64px;
}
</style>
