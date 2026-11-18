<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <q-btn
        flat
        round
        dense
        icon="arrow_back"
        :to="{ name: 'packages' }"
        :aria-label="t('packagePages.detail.back')"
      />
      <h1 class="text-h5 q-my-none col-auto break-anywhere">
        {{
          pkg
            ? `${pkg.name}${pkg.version ? ' ' + pkg.version : ''}`
            : t('packagePages.detail.titleFallback')
        }}
      </h1>
      <q-chip v-if="pkg" dense :color="trustColor" text-color="white">
        {{ trustLabel(method) }}
      </q-chip>
      <q-chip v-if="pkg?.retired_at" dense>{{ t('packagePages.detail.retired') }}</q-chip>
      <q-space />
      <template v-if="pkg">
        <q-btn
          v-if="canDeploy"
          color="primary"
          icon="install_desktop"
          :label="t('packagePages.detail.deploy')"
          no-caps
          :disable="!deployable(pkg)"
          class="q-mr-sm"
          @click="openDeploy('install')"
        />
        <q-btn
          v-if="canDeploy && (pkg.kind === 'winget' || pkg.uninstall_run)"
          outline
          color="negative"
          icon="delete_sweep"
          :label="t('packagePages.detail.uninstall')"
          no-caps
          :disable="!uninstallable(pkg)"
          class="q-mr-sm"
          @click="openDeploy('uninstall')"
        />
        <q-btn
          v-if="canWrite"
          flat
          no-caps
          :icon="pkg.retired_at ? 'unarchive' : 'archive'"
          :label="
            pkg.retired_at ? t('packagePages.detail.restore') : t('packagePages.detail.retire')
          "
          @click="toggleRetired"
        />
      </template>
    </div>

    <LoadErrorBanner v-if="loadError" :error="loadError" @retry="load" />

    <div v-if="pkg" class="row q-col-gutter-md">
      <!-- Definition -->
      <div class="col-12 col-lg-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">{{
            t('packagePages.detail.definition.title')
          }}</q-card-section>
          <q-form ref="formRef" @submit="save">
            <q-card-section class="q-gutter-sm">
              <q-input
                v-model="form.name"
                :label="t('packagePages.detail.definition.name')"
                outlined
                dense
                :maxlength="LIMITS.name"
                reactive-rules
                :rules="[rules.name]"
                :readonly="!canWrite"
              />
              <q-input
                v-model="form.version"
                :label="t('packagePages.detail.definition.version')"
                outlined
                dense
                :maxlength="LIMITS.version"
                :readonly="!canWrite"
              />
              <template v-if="pkg.kind === 'winget'">
                <q-input
                  v-model="form.winget_id"
                  :label="t('packagePages.detail.definition.wingetId')"
                  outlined
                  dense
                  :maxlength="LIMITS.winget_id"
                  reactive-rules
                  :rules="[rules.wingetId]"
                  :readonly="!canWrite"
                />
                <q-input
                  v-model="form.winget_version"
                  :label="t('packagePages.detail.definition.wingetVersion')"
                  outlined
                  dense
                  :maxlength="LIMITS.winget_version"
                  :readonly="!canWrite"
                />
              </template>
              <template v-else>
                <q-select
                  v-model="form.install_run"
                  :options="['msiexec', ...fileNames]"
                  :label="t('packagePages.detail.definition.installRun')"
                  outlined
                  dense
                  clearable
                  :readonly="!canWrite"
                />
                <q-input
                  v-model="form.install_args"
                  :label="t('packagePages.detail.definition.installArgs')"
                  outlined
                  dense
                  reactive-rules
                  :rules="[(v: string) => rules.msiexecArgs(form.install_run, v)]"
                  :readonly="!canWrite"
                  :hint="t('packagePages.detail.definition.installArgsHint')"
                />
                <q-select
                  v-model="form.uninstall_run"
                  :options="['msiexec', ...fileNames]"
                  :label="t('packagePages.detail.definition.uninstallRun')"
                  outlined
                  dense
                  clearable
                  :readonly="!canWrite"
                />
                <q-input
                  v-model="form.uninstall_args"
                  :label="t('packagePages.detail.definition.uninstallArgs')"
                  outlined
                  dense
                  reactive-rules
                  :rules="[(v: string) => rules.msiexecArgs(form.uninstall_run, v)]"
                  :readonly="!canWrite"
                  :hint="t('packagePages.detail.definition.uninstallArgsHint')"
                />
                <q-input
                  v-model="form.success_codes"
                  :label="t('packagePages.detail.definition.successCodes')"
                  outlined
                  dense
                  reactive-rules
                  :rules="[rules.successCodes]"
                  :readonly="!canWrite"
                  :hint="t('packagePages.detail.definition.successCodesHint')"
                />
              </template>
              <q-input
                v-model="form.detect_name"
                :label="t('packagePages.detail.definition.detectName')"
                outlined
                dense
                :maxlength="LIMITS.detect_name"
                :readonly="!canWrite"
                :hint="t('packagePages.detail.definition.detectNameHint')"
              />
              <q-input
                v-model="form.notes"
                :label="t('packagePages.detail.definition.notes')"
                outlined
                dense
                :maxlength="LIMITS.notes"
                autogrow
                :readonly="!canWrite"
              />
            </q-card-section>
            <q-card-actions v-if="canWrite" align="right" class="q-px-md q-pb-md">
              <span v-if="pkg.signed" class="text-caption text-muted q-mr-md">
                {{ t('packagePages.detail.definition.signedEditWarning') }}
              </span>
              <span v-if="dirty" class="text-caption text-warn q-mr-md">
                {{ t('packagePages.detail.definition.unsaved') }}
              </span>
              <q-btn
                type="submit"
                color="primary"
                no-caps
                :label="t('packagePages.detail.definition.save')"
                :loading="saving"
              />
            </q-card-actions>
          </q-form>
        </q-card>
      </div>

      <div class="col-12 col-lg-6 q-gutter-y-md">
        <!-- What every poste would refuse an installation for: the server's
             list, the one its deployment refusal gives (problems first, then
             why neither method B nor method A carries it). -->
        <q-banner v-if="pkg.install_blockers.length" class="surface-orange break-anywhere">
          <div class="text-weight-medium">
            {{
              pkg.problems.length
                ? t('packagePages.detail.blockers.notDeployable')
                : t('packagePages.detail.blockers.noComputer')
            }}
          </div>
          <ul class="q-my-xs q-pl-md">
            <li v-for="m in installBlockerTexts(pkg)" :key="m">{{ m }}</li>
          </ul>
        </q-banner>

        <!-- Files -->
        <q-card v-if="pkg.kind === 'files'" flat bordered>
          <q-card-section class="row items-center">
            <div class="text-subtitle1">{{ t('packagePages.detail.files.title') }}</div>
            <q-space />
            <template v-if="canWrite">
              <q-file
                v-model="toUpload"
                multiple
                dense
                outlined
                :label="t('packagePages.detail.files.choose')"
                style="min-width: 220px"
                class="q-mr-sm"
              />
              <q-btn
                color="primary"
                no-caps
                icon="upload"
                :label="t('packagePages.detail.files.upload')"
                :disable="!toUpload?.length"
                :loading="uploading"
                @click="upload"
              />
            </template>
          </q-card-section>
          <div v-if="uploading" class="row items-center no-wrap q-px-md q-pb-sm">
            <q-linear-progress :value="uploadProgress" color="primary" class="col" />
            <q-btn
              flat
              dense
              no-caps
              :label="t('packagePages.detail.files.cancel')"
              class="q-ml-sm"
              @click="cancelUpload"
            />
          </div>
          <q-list separator>
            <q-item v-for="f in files" :key="f.name">
              <q-item-section>
                <q-item-label class="break-anywhere">
                  {{ f.name }}
                  <q-badge v-if="f.name === pkg.install_run" color="primary" class="q-ml-xs">
                    {{ t('packagePages.detail.files.run') }}
                  </q-badge>
                </q-item-label>
                <q-item-label caption>
                  {{ formatSize(f.size) }} · SHA-256 {{ f.sha256.slice(0, 16) }}…
                  <PackageRichText
                    v-if="f.publisher_name"
                    path="packagePages.detail.files.signedBy"
                    :bold="{ publisher: f.publisher_name }"
                  />
                </q-item-label>
              </q-item-section>
              <q-item-section v-if="canWrite" side>
                <q-btn
                  flat
                  round
                  dense
                  icon="delete"
                  :aria-label="t('packagePages.detail.files.remove', { name: f.name })"
                  @click="removeFile(f.name)"
                />
              </q-item-section>
            </q-item>
            <q-item v-if="!pkg.files.length">
              <q-item-section class="text-muted">
                {{ t('packagePages.detail.files.empty') }}
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>

        <!-- Trust -->
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">{{
            t('packagePages.detail.trust.title')
          }}</q-card-section>
          <q-card-section v-if="pkg.kind === 'winget'" class="text-body2">
            <PackageRichText
              path="packagePages.detail.trust.winget"
              :code="{
                deployWinget: 'DeployWinget',
                id: pkg.winget_id ?? '',
                allow: 'DeployWingetAllow',
              }"
            />
          </q-card-section>
          <template v-else>
            <q-card-section class="text-body2">
              <div class="text-weight-medium q-mb-xs">
                {{ t('packagePages.detail.methodB.title') }}
              </div>
              <template v-if="pkg.signed">
                <PackageRichText
                  path="packagePages.detail.methodB.signed"
                  :named="{ date: formatDateTime(pkg.signed_at), by: pkg.signed_by ?? '' }"
                  :bold="{ subject: pkg.signer_subject ?? '' }"
                  :code="{ signers: 'DeploySigners' }"
                />
                <div class="q-mt-xs">
                  <code style="word-break: break-all">{{ pkg.signer_thumbprint }}</code>
                </div>
              </template>
              <template v-else>
                <PackageRichText
                  path="packagePages.detail.methodB.unsigned"
                  :code="{ script: 'Sign-TiaiPackage.ps1' }"
                />
              </template>
              <div v-if="canWrite" class="q-mt-sm row q-gutter-sm">
                <q-btn
                  outline
                  no-caps
                  color="primary"
                  icon="download"
                  :label="t('packagePages.detail.methodB.downloadManifest')"
                  :disable="pkg.problems.length > 0"
                  @click="getManifest"
                />
                <q-file
                  v-model="signatureFile"
                  dense
                  outlined
                  accept=".json"
                  :label="t('packagePages.detail.methodB.uploadSignature')"
                  style="min-width: 240px"
                  :disable="pkg.problems.length > 0"
                  @update:model-value="sendSignature"
                />
                <q-btn
                  v-if="pkg.signed"
                  flat
                  no-caps
                  color="negative"
                  :label="t('packagePages.detail.methodB.removeSignature')"
                  @click="unsign"
                />
              </div>
            </q-card-section>
            <q-separator />
            <q-card-section class="text-body2">
              <div class="text-weight-medium q-mb-xs">
                {{ t('packagePages.detail.methodA.title') }}
              </div>
              <template v-if="tooLargeForMethodA(pkg, 'install')">
                {{ t('packagePages.detail.methodA.tooLarge', { max: methodAMaxLabel(pkg) }) }}
              </template>
              <template v-else-if="method === 'publisher'">
                <PackageRichText
                  path="packagePages.detail.methodA.publisher"
                  :bold="{ publisher: pkg.publisher_name ?? '' }"
                  :code="{ publishers: 'DeployPublishers' }"
                />
              </template>
              <template v-else-if="pkg.signed">{{
                t('packagePages.detail.methodA.signed')
              }}</template>
              <template v-else-if="pkg.publisher_name && besideRun.length">
                <PackageRichText
                  class="break-anywhere"
                  path="packagePages.detail.methodA.loadable"
                  :named="{ files: quoted(besideRun) }"
                  :bold="{ publisher: pkg.publisher_name }"
                  :plural="besideRun.length"
                />
              </template>
              <template v-else>
                {{ t('packagePages.detail.methodA.notExe') }}
              </template>
            </q-card-section>
          </template>
          <q-card-section v-if="pkg.installed_count !== null" class="text-body2">
            <PackageRichText
              path="packagePages.detail.trust.installed"
              :bold="{ count: String(pkg.installed_count) }"
              :plural="pkg.installed_count"
            />
          </q-card-section>
        </q-card>
      </div>

      <!-- Deployments -->
      <div class="col-12">
        <q-card flat bordered>
          <q-card-section class="row items-center">
            <div class="text-subtitle1">{{ t('packagePages.detail.deployments.title') }}</div>
            <q-space />
            <q-btn
              flat
              round
              dense
              icon="refresh"
              :aria-label="t('packagePages.detail.deployments.refresh')"
              :loading="loadingCommands"
              @click="loadCommands"
            />
          </q-card-section>
          <!-- Each poste's latest deployment, counted over all of them: the
               table below pages, this does not (audit B14). A chip filters. -->
          <q-card-section v-if="summary && summary.postes" class="q-pt-none">
            <div class="text-body2 q-mb-xs">
              {{
                t(
                  'packagePages.detail.deployments.summary',
                  { count: summary.postes },
                  summary.postes,
                )
              }}
            </div>
            <q-chip
              v-for="(n, status) in summary.by_status"
              :key="status"
              clickable
              dense
              :outline="statusFilter !== status"
              :color="STATUS_COLORS[status] ?? 'grey-7'"
              :text-color="statusFilter === status ? 'white' : undefined"
              :aria-pressed="statusFilter === status"
              @click="toggleStatusFilter(status)"
            >
              {{ t('packagePages.detail.deployments.chip', { label: statusLabel(status), n }) }}
            </q-chip>
          </q-card-section>
          <div class="text-caption text-muted q-px-md">
            {{
              statusFilter
                ? t('packagePages.detail.deployments.filtered', {
                    status: statusLabel(statusFilter).toLowerCase(),
                  })
                : t('packagePages.detail.deployments.history')
            }}
          </div>
          <q-table
            v-model:pagination="commandPagination"
            :rows="commands"
            :columns="commandColumns"
            row-key="id"
            flat
            :loading="loadingCommands"
            :rows-per-page-options="[25, 50, 100]"
            :no-data-label="
              statusFilter
                ? t('packagePages.detail.deployments.noDataFiltered')
                : t('packagePages.detail.deployments.noData')
            "
            @request="onCommandsRequest"
          >
            <template #body-cell-machine="cell">
              <q-td :props="cell">
                <router-link :to="{ name: 'machine-detail', params: { id: cell.row.machine_id } }">
                  {{ cell.row.machine_hostname ?? cell.row.machine_id }}
                </router-link>
              </q-td>
            </template>
            <template #body-cell-status="cell">
              <q-td :props="cell">
                <q-badge :color="STATUS_COLORS[cell.row.status] ?? 'grey-7'">
                  {{ statusLabel(cell.row.status) }}
                </q-badge>
              </q-td>
            </template>
            <template #body-cell-result="cell">
              <q-td
                :props="cell"
                class="break-anywhere"
                style="white-space: normal; max-width: 520px"
              >
                {{ commandVerdictText(cell.row) }}
              </q-td>
            </template>
          </q-table>
        </q-card>
      </div>
    </div>

    <PackageDeployDialog
      v-model="deployOpen"
      :package="pkg"
      :initial-action="deployAction"
      @sent="loadCommands"
    />
  </q-page>
</template>

<script setup lang="ts">
import { installBlockerTexts } from 'src/utils/packageText';
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { isCancel } from 'axios';
import { useQuasar, type QForm, type QTableColumn } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import PackageDeployDialog from 'src/components/package/PackageDeployDialog.vue';
import PackageRichText from 'src/components/package/PackageRichText.vue';
import { t } from 'src/i18n';
import { commandTypeLabel, commandVerdictText, type Command } from 'src/services/commands';
import { apiErrorMessage } from 'src/services/errors';
import {
  attachSignature,
  deletePackageFile,
  deployable,
  downloadManifest,
  formatSize,
  getPackage,
  getPackageSummary,
  joinArgs,
  listPackageCommands,
  loadableBeside,
  manifestFileName,
  methodAMaxLabel,
  removeSignature,
  restorePackage,
  retirePackage,
  sortedFiles,
  splitArgs,
  tooLargeFiles,
  tooLargeForMethodA,
  trustLabel,
  trustMethod,
  uninstallable,
  updatePackage,
  uploadPackageFiles,
  type Package,
  type PackageSummary,
} from 'src/services/packages';
import { useAuthStore } from 'src/stores/auth';
import { downloadBlob, formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';

const props = defineProps<{ id: string }>();
const $q = useQuasar();
const auth = useAuthStore();

const pkg = ref<Package | null>(null);
const loadError = ref<unknown>(null);
const saving = ref(false);
const toUpload = ref<File[] | null>(null);
const uploading = ref(false);
const uploadProgress = ref(0);
const signatureFile = ref<File | null>(null);
const commands = ref<Command[]>([]);
const loadingCommands = ref(false);
const deployOpen = ref(false);
const deployAction = ref<'install' | 'uninstall'>('install');

const form = reactive({
  name: '',
  version: '',
  winget_id: '',
  winget_version: '',
  install_run: null as string | null,
  install_args: '',
  uninstall_run: null as string | null,
  uninstall_args: '',
  success_codes: '',
  detect_name: '',
  notes: '',
});

const canWrite = computed(() => auth.can('package', 'write'));
const canDeploy = computed(
  () => auth.can('command', 'execute') && auth.can('risky_command', 'execute'),
);
// In the order a French reader looks for them (case and accents aside).
const files = computed(() => (pkg.value ? sortedFiles(pkg.value) : []));
const fileNames = computed(() => files.value.map((f) => f.name));
// What stands beside the executable and keeps method A from running it.
const besideRun = computed(() => (pkg.value ? loadableBeside(pkg.value, 'install') : []));
const formRef = ref<QForm | null>(null);

// The bounds the server holds the fields to (packages.py _LIMITS, the winget
// patterns): typed past them, its refusal used to arrive in English.
const LIMITS = {
  name: 200,
  version: 100,
  notes: 5000,
  detect_name: 200,
  winget_id: 128,
  winget_version: 64,
};

function quoted(names: string[]): string {
  return names.map((name) => t('packages.quoted', { name })).join(t('packages.listSeparator'));
}
const method = computed(() => (pkg.value ? trustMethod(pkg.value) : 'none'));
const trustColor = computed(
  () =>
    ({ winget: 'primary', signed: 'positive', publisher: 'teal', none: 'grey-7' })[method.value],
);

const STATUS_COLORS: Record<string, string> = {
  pending: 'grey-7',
  delivered: 'blue-7',
  running: 'blue-7',
  succeeded: 'positive',
  failed: 'negative',
  expired: 'orange',
};
const STATUSES = new Set(['pending', 'delivered', 'running', 'succeeded', 'failed', 'expired']);

/** A deployment's state in words; a state this build does not know, as sent. */
function statusLabel(status: string): string {
  return STATUSES.has(status) ? t(`packagePages.status.${status}`) : status;
}

const commandColumns = computed<QTableColumn<Command>[]>(() => [
  {
    name: 'machine',
    label: t('packagePages.detail.deployments.columns.machine'),
    field: 'machine_id',
    align: 'left',
  },
  {
    name: 'type',
    label: t('packagePages.detail.deployments.columns.type'),
    field: (c) => commandTypeLabel(c.type),
    align: 'left',
  },
  {
    name: 'status',
    label: t('packagePages.detail.deployments.columns.status'),
    field: 'status',
    align: 'left',
  },
  {
    name: 'created_by',
    label: t('packagePages.detail.deployments.columns.createdBy'),
    field: 'created_by',
    align: 'left',
  },
  {
    name: 'created_at',
    label: t('packagePages.detail.deployments.columns.createdAt'),
    field: (c) => formatDateTime(c.created_at),
    align: 'left',
  },
  {
    name: 'result',
    label: t('packagePages.detail.deployments.columns.result'),
    field: 'id',
    align: 'left',
  },
]);

type PackageForm = typeof form;

function formOf(p: Package): PackageForm {
  return {
    name: p.name,
    version: p.version ?? '',
    winget_id: p.winget_id ?? '',
    winget_version: p.winget_version ?? '',
    install_run: p.install_run,
    install_args: joinArgs(p.install_args),
    uninstall_run: p.uninstall_run,
    uninstall_args: joinArgs(p.uninstall_args),
    success_codes: p.success_codes.join(', '),
    detect_name: p.detect_name ?? '',
    notes: p.notes ?? '',
  };
}

// The form as last filled from the server: what « modifié » is measured from.
const saved = ref<PackageForm>({ ...form });
const dirty = computed(() =>
  (Object.keys(form) as (keyof PackageForm)[]).some((k) => form[k] !== saved.value[k]),
);

/** The whole form from the server: after a load or a save. */
function fill(p: Package) {
  pkg.value = p;
  const next = formOf(p);
  Object.assign(form, next);
  saved.value = { ...next };
}

/**
 * The package after a side action (a file, a signature, retirement): its
 * files and signature change, the definition the reader is typing stays —
 * only the fields left untouched follow the server (audit U05).
 */
function refresh(p: Package) {
  pkg.value = p;
  const next = formOf(p);
  for (const k of Object.keys(next) as (keyof PackageForm)[]) {
    if (form[k] === saved.value[k]) Object.assign(form, { [k]: next[k] });
  }
  saved.value = { ...next };
}

onBeforeRouteLeave(() => {
  if (!dirty.value && !uploading.value) return true;
  // Leaving cancels an upload under way: said before, not after (the toast
  // « Dépôt annulé » came once the files were lost).
  // As things stand when it asks: the words follow the language, not the upload.
  const wasUploading = uploading.value;
  const wasDirty = dirty.value;
  const what = () =>
    [
      wasUploading ? t('packagePages.detail.leave.uploading') : '',
      wasDirty ? t('packagePages.detail.leave.dirty') : '',
    ].filter(Boolean);
  return new Promise<boolean>((resolve) => {
    liveDialog($q, () => ({
      title: wasUploading
        ? t('packagePages.detail.leave.titleUploading')
        : t('packagePages.detail.leave.titleDirty'),
      message: t('packagePages.detail.leave.question', { what: what().join(' ') }),
      cancel: { flat: true, noCaps: true, label: t('packagePages.detail.leave.stay') },
      ok: {
        flat: true,
        noCaps: true,
        label: wasUploading
          ? t('packagePages.detail.leave.okUploading')
          : t('packagePages.detail.leave.okDirty'),
        color: 'negative',
      },
      persistent: true,
    }))
      .onOk(() => {
        cancelUpload();
        resolve(true);
      })
      .onCancel(() => resolve(false));
  });
});

/**
 * Closing the tab, reloading, typing another address: the browser asks
 * before an upload under way or unsaved changes are lost (its own wording —
 * a page cannot set it).
 */
function guardUnload(e: BeforeUnloadEvent) {
  if (!uploading.value && !dirty.value) return;
  e.preventDefault();
  // Still what some browsers read to ask.
  e.returnValue = '';
}

onMounted(() => window.addEventListener('beforeunload', guardUnload));
onBeforeUnmount(() => window.removeEventListener('beforeunload', guardUnload));

async function load() {
  loadError.value = null;
  try {
    fill(await getPackage(props.id));
  } catch (e) {
    loadError.value = e;
  }
  void loadCommands();
}

const summary = ref<PackageSummary | null>(null);
const statusFilter = ref<string | null>(null);
const commandPagination = ref({ page: 1, rowsPerPage: 25, rowsNumber: 0 });

// Which fetch is the current one: two quick toggles of a status chip must not
// have the first answer, arriving last, shown under the second filter.
let commandsRequestId = 0;

async function loadCommands() {
  const id = ++commandsRequestId;
  loadingCommands.value = true;
  const p = commandPagination.value;
  try {
    const [list, tally] = await Promise.all([
      // A state chosen in the tally lists the rows the tally counts: each
      // poste's latest deployment, not every attempt behind it.
      listPackageCommands(
        props.id,
        p.page,
        p.rowsPerPage,
        statusFilter.value,
        statusFilter.value !== null,
      ),
      getPackageSummary(props.id).catch(() => null),
    ]);
    if (id !== commandsRequestId) return;
    commands.value = list.items;
    commandPagination.value = { ...commandPagination.value, rowsNumber: list.total };
    summary.value = tally;
  } catch {
    if (id !== commandsRequestId) return;
    commands.value = [];
  } finally {
    if (id === commandsRequestId) loadingCommands.value = false;
  }
}

function onCommandsRequest(req: { pagination: { page: number; rowsPerPage: number } }) {
  commandPagination.value = {
    ...commandPagination.value,
    page: req.pagination.page,
    rowsPerPage: req.pagination.rowsPerPage,
  };
  void loadCommands();
}

function toggleStatusFilter(status: string) {
  statusFilter.value = statusFilter.value === status ? null : status;
  commandPagination.value = { ...commandPagination.value, page: 1 };
  void loadCommands();
}

// What the server would refuse, said under the field before sending
// (audit U03) — the same rules as backend/app/api/routes/packages.py.
const rules = {
  name: (v: string) => !!v.trim() || t('packagePages.detail.rules.nameRequired'),
  wingetId: (v: string) =>
    /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/.test(v.trim()) ||
    t('packagePages.detail.rules.wingetIdInvalid'),
  msiexecArgs: (run: string | null, v: string) =>
    run !== 'msiexec' || splitArgs(v).length > 0 || t('packagePages.detail.rules.msiexecArgs'),
  successCodes: (v: string) => {
    const parts = v.split(/[,;\s]+/).filter(Boolean);
    if (!parts.length) return t('packagePages.detail.rules.successCodesNone');
    if (parts.length > 32) return t('packagePages.detail.rules.successCodesMax');
    return (
      parts.every((p) => /^-?\d+$/.test(p)) || t('packagePages.detail.rules.successCodesIntegers')
    );
  },
};

function notifyError(e: unknown, fallback: string) {
  $q.notify({ type: 'negative', message: apiErrorMessage(e, fallback) });
}

/** Saves the definition; whether it was saved. */
async function save(): Promise<boolean> {
  if (!pkg.value) return false;
  saving.value = true;
  try {
    const common = {
      name: form.name.trim(),
      version: form.version.trim() || null,
      detect_name: form.detect_name.trim() || null,
      notes: form.notes.trim() || null,
    };
    const fields =
      pkg.value.kind === 'winget'
        ? {
            ...common,
            winget_id: form.winget_id.trim(),
            winget_version: form.winget_version.trim() || null,
          }
        : {
            ...common,
            install_run: form.install_run,
            install_args: splitArgs(form.install_args),
            uninstall_run: form.uninstall_run,
            uninstall_args: splitArgs(form.uninstall_args),
            success_codes: form.success_codes
              .split(/[,;\s]+/)
              .filter(Boolean)
              .map((v) => Number(v)),
          };
    const wasSigned = pkg.value.signed;
    const updated = await updatePackage(pkg.value.id, fields);
    fill(updated);
    $q.notify({
      type: wasSigned && !updated.signed ? 'warning' : 'positive',
      message:
        wasSigned && !updated.signed
          ? t('packagePages.detail.savedResign')
          : t('packagePages.detail.saved'),
    });
    return true;
  } catch (e) {
    notifyError(e, t('packagePages.detail.saveFailed'));
    return false;
  } finally {
    saving.value = false;
  }
}

// Cancels the upload in progress; null when none is.
let uploadAbort: AbortController | null = null;

/**
 * One request per file, in turn: the proxy bounds a request, the server a
 * file — several large files sent together would be refused after the whole
 * transfer (audit U16, B31). Sizes are checked before anything leaves.
 */
async function upload() {
  if (!pkg.value || !toUpload.value?.length) return;
  const files = [...toUpload.value];
  // Against the server's own bound, as the package reports it.
  const tooBig = tooLargeFiles(pkg.value, files);
  if (tooBig.length) {
    $q.notify({
      type: 'negative',
      message: t('packagePages.detail.upload.tooLarge', {
        files: tooBig.map((f) => f.name).join(t('packages.listSeparator')),
      }),
      caption: t('packagePages.detail.upload.tooLargeCaption', {
        size: formatSize(pkg.value.file_max_bytes),
      }),
    });
    return;
  }
  const total = files.reduce((n, f) => n + f.size, 0) || 1;
  uploading.value = true;
  uploadProgress.value = 0;
  uploadAbort = new AbortController();
  let sent = 0;
  // The files the server took, in order: one request each, so a refusal
  // stops the drop there — the ones before it are kept, the rest not sent.
  const kept: string[] = [];
  try {
    for (const file of files) {
      const updated = await uploadPackageFiles(
        pkg.value.id,
        [file],
        (f) => {
          uploadProgress.value = (sent + f * file.size) / total;
        },
        uploadAbort.signal,
      );
      sent += file.size;
      kept.push(file.name);
      refresh(updated);
    }
    // The first executable dropped is, nine times out of ten, the one to run:
    // proposed, to be saved with the rest of the definition.
    if (pkg.value && !form.install_run) {
      const exe = pkg.value.files.find((f) => /\.(exe|msi)$/i.test(f.name));
      if (exe) form.install_run = exe.name;
    }
    toUpload.value = null;
    $q.notify({
      type: 'positive',
      message: t('packagePages.detail.upload.done', files.length),
      ...(dirty.value ? { caption: t('packagePages.detail.upload.rememberSave') } : {}),
    });
  } catch (e) {
    const notSent = files.slice(kept.length).map((f) => f.name);
    const caption =
      files.length > 1
        ? [
            kept.length
              ? t(
                  'packagePages.detail.upload.kept',
                  { files: kept.join(t('packages.listSeparator')) },
                  kept.length,
                )
              : '',
            t(
              'packagePages.detail.upload.notSent',
              { files: notSent.join(t('packages.listSeparator')) },
              notSent.length,
            ),
          ]
            .filter(Boolean)
            .join(' ')
        : undefined;
    if (isCancel(e)) {
      $q.notify({
        type: 'info',
        message: sent
          ? t('packagePages.detail.upload.interrupted')
          : t('packagePages.detail.upload.cancelled'),
        ...(caption ? { caption } : {}),
      });
    } else {
      $q.notify({
        type: 'negative',
        message: apiErrorMessage(e, t('packagePages.detail.upload.failed')),
        ...(caption ? { caption } : {}),
        ...(files.length > 1 ? { timeout: 10000 } : {}),
      });
    }
  } finally {
    uploading.value = false;
    uploadAbort = null;
  }
}

function cancelUpload() {
  uploadAbort?.abort();
}

onBeforeUnmount(cancelUpload);

function removeFile(name: string) {
  if (!pkg.value) return;
  const id = pkg.value.id;
  liveDialog($q, () => ({
    title: t('packagePages.detail.removeFile.title'),
    message: t('packagePages.detail.removeFile.message', { name }),
    cancel: true,
    ok: { label: t('packagePages.detail.removeFile.ok'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        refresh(await deletePackageFile(id, name));
      } catch (e) {
        notifyError(e, t('packagePages.detail.removeFile.failed'));
      }
    })();
  });
}

async function getManifest() {
  if (!pkg.value) return;
  try {
    const blob = await downloadManifest(pkg.value.id);
    downloadBlob(blob, manifestFileName(pkg.value));
  } catch (e) {
    notifyError(e, t('packagePages.detail.downloadFailed'));
  }
}

async function sendSignature(file: File | null) {
  if (!pkg.value || !file) return;
  try {
    const document: unknown = JSON.parse(await file.text());
    refresh(await attachSignature(pkg.value.id, document));
    $q.notify({ type: 'positive', message: t('packagePages.detail.signature.attached') });
  } catch (e) {
    notifyError(
      e,
      e instanceof SyntaxError
        ? t('packagePages.detail.signature.notSignature')
        : t('packagePages.detail.signature.refused'),
    );
  } finally {
    signatureFile.value = null;
  }
}

async function unsign() {
  if (!pkg.value) return;
  try {
    refresh(await removeSignature(pkg.value.id));
  } catch (e) {
    notifyError(e, t('packagePages.detail.operationFailed'));
  }
}

/** A confirmation; `texts` words it, again on a change of language. */
function confirm(
  texts: () => { title: string; message: string; ok: string },
  color: string,
): Promise<boolean> {
  return new Promise((resolve) => {
    liveDialog($q, () => ({
      title: texts().title,
      message: texts().message,
      cancel: { flat: true, noCaps: true, label: t('packagePages.detail.cancel') },
      ok: { unelevated: true, noCaps: true, label: texts().ok, color },
      persistent: true,
    }))
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false));
  });
}

/**
 * Retiring cancels the installations no poste has received yet — said, with
 * their number, before; and restoring does not bring them back — said too.
 * The deployments card follows either way.
 */
async function toggleRetired() {
  if (!pkg.value) return;
  const p = pkg.value;
  if (p.retired_at) {
    const ok = await confirm(
      () => ({
        title: t('packagePages.detail.restoreConfirm.title'),
        message: t('packagePages.detail.restoreConfirm.message', { name: p.name }),
        ok: t('packagePages.detail.restoreConfirm.ok'),
      }),
      'primary',
    );
    if (!ok) return;
    try {
      refresh(await restorePackage(p.id));
      $q.notify({
        type: 'positive',
        message: t('packagePages.detail.restoreConfirm.done'),
        caption: t('packagePages.detail.restoreConfirm.doneCaption'),
      });
    } catch (e) {
      notifyError(e, t('packagePages.detail.operationFailed'));
    }
    void loadCommands();
    return;
  }
  // Counted now, not from the tally on screen, which may be minutes old.
  const tally = await getPackageSummary(p.id).catch(() => summary.value);
  if (tally) summary.value = tally;
  const pending = tally?.pending_installs ?? null;
  const cancelled = () =>
    pending === null
      ? t('packagePages.detail.retireConfirm.pendingUnknown')
      : pending > 0
        ? t('packagePages.detail.retireConfirm.pending', { count: pending }, pending)
        : t('packagePages.detail.retireConfirm.noPending');
  const ok = await confirm(
    () => ({
      title: t('packagePages.detail.retireConfirm.title'),
      message: t('packagePages.detail.retireConfirm.message', { cancelled: cancelled() }),
      ok: t('packagePages.detail.retireConfirm.ok'),
    }),
    'negative',
  );
  if (!ok) return;
  try {
    refresh(await retirePackage(p.id));
    $q.notify({
      type: 'positive',
      message: t('packagePages.detail.retireConfirm.done'),
      ...(pending
        ? {
            caption: t(
              'packagePages.detail.retireConfirm.doneCaption',
              { count: pending },
              pending,
            ),
          }
        : {}),
    });
  } catch (e) {
    notifyError(e, t('packagePages.detail.operationFailed'));
  }
  void loadCommands();
}

/**
 * The deployment sends the definition as saved: with changes typed and not
 * saved, it would deploy without them, silently. Said, and offered to save
 * first.
 */
async function openDeploy(action: 'install' | 'uninstall') {
  if (dirty.value && canWrite.value) {
    const ok = await confirm(
      () => ({
        title: t('packagePages.detail.unsavedDeploy.title'),
        message: t('packagePages.detail.unsavedDeploy.message'),
        ok: t('packagePages.detail.unsavedDeploy.ok'),
      }),
      'primary',
    );
    if (!ok) return;
    if ((await formRef.value?.validate()) === false) return;
    if (!(await save())) return;
    // Saved, the package may no longer be deployable (a file to run that
    // is not in it): the dialog says so.
  }
  deployAction.value = action;
  deployOpen.value = true;
}

onMounted(load);
</script>

<style scoped>
/* A 255-character file name without a space must wrap, not widen the page. */
.break-anywhere {
  overflow-wrap: anywhere;
  word-break: break-word;
}
</style>
