<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <q-btn flat round dense icon="arrow_back" :to="{ name: 'packages' }" aria-label="Retour" />
      <h1 class="text-h5 q-my-none col-auto break-anywhere">
        {{ pkg ? `${pkg.name}${pkg.version ? ' ' + pkg.version : ''}` : 'Paquet' }}
      </h1>
      <q-chip v-if="pkg" dense :color="trustColor" text-color="white">
        {{ trustLabels[method] }}
      </q-chip>
      <q-chip v-if="pkg?.retired_at" dense>Retiré</q-chip>
      <q-space />
      <template v-if="pkg">
        <q-btn
          v-if="canDeploy"
          color="primary"
          icon="install_desktop"
          label="Déployer"
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
          label="Désinstaller"
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
          :label="pkg.retired_at ? 'Remettre au catalogue' : 'Retirer'"
          @click="toggleRetired"
        />
      </template>
    </div>

    <LoadErrorBanner v-if="loadError" :error="loadError" @retry="load" />

    <div v-if="pkg" class="row q-col-gutter-md">
      <!-- Definition -->
      <div class="col-12 col-lg-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">Définition</q-card-section>
          <q-form ref="formRef" @submit="save">
            <q-card-section class="q-gutter-sm">
              <q-input
                v-model="form.name"
                label="Nom"
                outlined
                dense
                :maxlength="LIMITS.name"
                :rules="[rules.name]"
                :readonly="!canWrite"
              />
              <q-input
                v-model="form.version"
                label="Version"
                outlined
                dense
                :maxlength="LIMITS.version"
                :readonly="!canWrite"
              />
              <template v-if="pkg.kind === 'winget'">
                <q-input
                  v-model="form.winget_id"
                  label="Identifiant winget"
                  outlined
                  dense
                  :maxlength="LIMITS.winget_id"
                  :rules="[rules.wingetId]"
                  :readonly="!canWrite"
                />
                <q-input
                  v-model="form.winget_version"
                  label="Version winget (vide = la plus récente)"
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
                  label="Fichier à lancer pour installer"
                  outlined
                  dense
                  clearable
                  :readonly="!canWrite"
                />
                <q-input
                  v-model="form.install_args"
                  label="Arguments d'installation"
                  outlined
                  dense
                  :rules="[(v: string) => rules.msiexecArgs(form.install_run, v)]"
                  :readonly="!canWrite"
                  hint='Ex. -s -f1"{dir}\ClientPRONOTE.iss" — {dir} = dossier des fichiers sur le poste'
                />
                <q-select
                  v-model="form.uninstall_run"
                  :options="['msiexec', ...fileNames]"
                  label="Désinstallation : fichier à lancer (facultatif)"
                  outlined
                  dense
                  clearable
                  :readonly="!canWrite"
                />
                <q-input
                  v-model="form.uninstall_args"
                  label="Arguments de désinstallation"
                  outlined
                  dense
                  :rules="[(v: string) => rules.msiexecArgs(form.uninstall_run, v)]"
                  :readonly="!canWrite"
                  hint="Avec msiexec : /x {code produit} /qn"
                />
                <q-input
                  v-model="form.success_codes"
                  label="Codes de sortie acceptés"
                  outlined
                  dense
                  :rules="[rules.successCodes]"
                  :readonly="!canWrite"
                  hint="Séparés par des virgules. 3010 et 1641 = redémarrage requis."
                />
              </template>
              <q-input
                v-model="form.detect_name"
                label="Nom dans l'inventaire"
                outlined
                dense
                :maxlength="LIMITS.detect_name"
                :readonly="!canWrite"
                hint="Tel qu'il apparaît dans « Applications et fonctionnalités » ; sert à compter les postes équipés"
              />
              <q-input
                v-model="form.notes"
                label="Notes"
                outlined
                dense
                :maxlength="LIMITS.notes"
                autogrow
                :readonly="!canWrite"
              />
            </q-card-section>
            <q-card-actions v-if="canWrite" align="right" class="q-px-md q-pb-md">
              <span v-if="pkg.signed" class="text-caption text-muted q-mr-md">
                Modifier la ligne de commande annule la signature.
              </span>
              <span v-if="dirty" class="text-caption text-warn q-mr-md">
                Modifications non enregistrées
              </span>
              <q-btn type="submit" color="primary" no-caps label="Enregistrer" :loading="saving" />
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
            {{ pkg.problems.length ? 'Pas encore déployable' : 'Aucun poste ne l’installera' }}
          </div>
          <ul class="q-my-xs q-pl-md">
            <li v-for="m in pkg.install_blockers" :key="m">{{ m }}</li>
          </ul>
        </q-banner>

        <!-- Files -->
        <q-card v-if="pkg.kind === 'files'" flat bordered>
          <q-card-section class="row items-center">
            <div class="text-subtitle1">Fichiers</div>
            <q-space />
            <template v-if="canWrite">
              <q-file
                v-model="toUpload"
                multiple
                dense
                outlined
                label="Choisir des fichiers"
                style="min-width: 220px"
                class="q-mr-sm"
              />
              <q-btn
                color="primary"
                no-caps
                icon="upload"
                label="Déposer"
                :disable="!toUpload?.length"
                :loading="uploading"
                @click="upload"
              />
            </template>
          </q-card-section>
          <div v-if="uploading" class="row items-center no-wrap q-px-md q-pb-sm">
            <q-linear-progress :value="uploadProgress" color="primary" class="col" />
            <q-btn flat dense no-caps label="Annuler" class="q-ml-sm" @click="cancelUpload" />
          </div>
          <q-list separator>
            <q-item v-for="f in files" :key="f.name">
              <q-item-section>
                <q-item-label class="break-anywhere">
                  {{ f.name }}
                  <q-badge v-if="f.name === pkg.install_run" color="primary" class="q-ml-xs">
                    lancé
                  </q-badge>
                </q-item-label>
                <q-item-label caption>
                  {{ formatSize(f.size) }} · SHA-256 {{ f.sha256.slice(0, 16) }}…
                  <template v-if="f.publisher_name">
                    · signé par <b>{{ f.publisher_name }}</b>
                  </template>
                </q-item-label>
              </q-item-section>
              <q-item-section v-if="canWrite" side>
                <q-btn
                  flat
                  round
                  dense
                  icon="delete"
                  :aria-label="`Retirer ${f.name}`"
                  @click="removeFile(f.name)"
                />
              </q-item-section>
            </q-item>
            <q-item v-if="!pkg.files.length">
              <q-item-section class="text-muted">
                Aucun fichier. Pour Pronote : l'installateur et le fichier de réponses .iss.
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>

        <!-- Trust -->
        <q-card flat bordered>
          <q-card-section class="text-subtitle1">Confiance des postes</q-card-section>
          <q-card-section v-if="pkg.kind === 'winget'" class="text-body2">
            Les postes l'installent si leur GPO active winget (<code>DeployWinget</code> = 1) et,
            quand elle est posée, si <code>{{ pkg.winget_id }}</code> figure dans
            <code>DeployWingetAllow</code>. winget télécharge l'installateur et vérifie son
            empreinte.
          </q-card-section>
          <template v-else>
            <q-card-section class="text-body2">
              <div class="text-weight-medium q-mb-xs">
                Méthode B — signature de l'administrateur
              </div>
              <template v-if="pkg.signed">
                Signé par <b>{{ pkg.signer_subject }}</b> le {{ formatDateTime(pkg.signed_at) }} ({{
                  pkg.signed_by
                }}). Les postes l'exécutent si la GPO liste l'empreinte de ce certificat dans
                <code>DeploySigners</code> :
                <div class="q-mt-xs">
                  <code style="word-break: break-all">{{ pkg.signer_thumbprint }}</code>
                </div>
              </template>
              <template v-else>
                Non signé. Téléchargez le manifeste, signez-le sur votre poste avec
                <code>Sign-TiaiPackage.ps1</code>, puis déposez le fichier de signature produit.
              </template>
              <div v-if="canWrite" class="q-mt-sm row q-gutter-sm">
                <q-btn
                  outline
                  no-caps
                  color="primary"
                  icon="download"
                  label="Télécharger le manifeste"
                  :disable="pkg.problems.length > 0"
                  @click="getManifest"
                />
                <q-file
                  v-model="signatureFile"
                  dense
                  outlined
                  accept=".json"
                  label="Déposer la signature (.sig.json)"
                  style="min-width: 240px"
                  :disable="pkg.problems.length > 0"
                  @update:model-value="sendSignature"
                />
                <q-btn
                  v-if="pkg.signed"
                  flat
                  no-caps
                  color="negative"
                  label="Retirer la signature"
                  @click="unsign"
                />
              </div>
            </q-card-section>
            <q-separator />
            <q-card-section class="text-body2">
              <div class="text-weight-medium q-mb-xs">Méthode A — éditeur approuvé (repli)</div>
              <template v-if="tooLargeForMethodA(pkg, 'install')">
                Indisponible : les fichiers pèsent plus de
                {{ methodAMaxLabel(pkg) }} au total, ce que les postes refusent de télécharger pour
                un paquet non signé. Signez le paquet (méthode B).
              </template>
              <template v-else-if="method === 'publisher'">
                Le fichier lancé est signé par <b>{{ pkg.publisher_name }}</b>. Sans signature de
                l'administrateur, les postes l'exécutent si la GPO liste ce nom dans
                <code>DeployPublishers</code>.
              </template>
              <template v-else-if="pkg.signed">Inutile : le paquet est signé.</template>
              <template v-else-if="pkg.publisher_name && besideRun.length">
                <span class="break-anywhere">
                  Indisponible : le fichier lancé est signé par <b>{{ pkg.publisher_name }}</b>,
                  mais {{ quoted(besideRun) }} {{ besideRun.length > 1 ? 'sont' : 'est' }} à côté,
                  et les postes refusent sous la méthode A tout fichier que Windows pourrait charger
                  ou lancer (.dll, .exe, .msi, scripts…) à côté de l'exécutable. Retirez
                  {{ besideRun.length > 1 ? 'ces fichiers' : 'ce fichier' }} du paquet, ou signez-le
                  (méthode B).
                </span>
              </template>
              <template v-else>
                Indisponible : le fichier lancé n'est pas un exécutable (.exe) signé par un éditeur.
              </template>
            </q-card-section>
          </template>
          <q-card-section v-if="pkg.installed_count !== null" class="text-body2">
            Présent d'après l'inventaire sur <b>{{ pkg.installed_count }}</b> poste(s).
          </q-card-section>
        </q-card>
      </div>

      <!-- Deployments -->
      <div class="col-12">
        <q-card flat bordered>
          <q-card-section class="row items-center">
            <div class="text-subtitle1">Déploiements</div>
            <q-space />
            <q-btn
              flat
              round
              dense
              icon="refresh"
              aria-label="Actualiser les déploiements"
              :loading="loadingCommands"
              @click="loadCommands"
            />
          </q-card-section>
          <!-- Each poste's latest deployment, counted over all of them: the
               table below pages, this does not (audit B14). A chip filters. -->
          <q-card-section v-if="summary && summary.postes" class="q-pt-none">
            <div class="text-body2 q-mb-xs">
              {{ summary.postes }} poste{{ summary.postes > 1 ? 's' : '' }} visé{{
                summary.postes > 1 ? 's' : ''
              }}
              — dernier déploiement de chacun ; un état filtre le tableau sur ces postes :
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
              {{ STATUS_LABELS[status] ?? status }} : {{ n }}
            </q-chip>
          </q-card-section>
          <div class="text-caption text-muted q-px-md">
            {{
              statusFilter
                ? `Dernier déploiement de chaque poste, ${(STATUS_LABELS[statusFilter] ?? statusFilter).toLowerCase()}`
                : 'Historique : tous les envois, du plus récent au plus ancien'
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
            :no-data-label="statusFilter ? 'Aucun déploiement dans cet état' : 'Jamais déployé'"
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
                  {{ STATUS_LABELS[cell.row.status] ?? cell.row.status }}
                </q-badge>
              </q-td>
            </template>
            <template #body-cell-result="cell">
              <q-td
                :props="cell"
                class="break-anywhere"
                style="white-space: normal; max-width: 520px"
              >
                {{ cell.row.error || cell.row.result_output || '' }}
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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { isCancel } from 'axios';
import { useQuasar, type QForm, type QTableColumn } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import PackageDeployDialog from 'src/components/package/PackageDeployDialog.vue';
import { commandTypeLabel, type Command } from 'src/services/commands';
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
  trustLabels,
  trustMethod,
  uninstallable,
  updatePackage,
  uploadPackageFiles,
  type Package,
  type PackageSummary,
} from 'src/services/packages';
import { useAuthStore } from 'src/stores/auth';
import { downloadBlob, formatDateTime } from 'src/utils/format';

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
  return names.map((n) => `« ${n} »`).join(', ');
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
const STATUS_LABELS: Record<string, string> = {
  pending: 'En attente',
  delivered: 'Transmise',
  running: 'En cours',
  succeeded: 'Réussie',
  failed: 'Échec',
  expired: 'Expirée',
};
const commandColumns: QTableColumn<Command>[] = [
  { name: 'machine', label: 'Poste', field: 'machine_id', align: 'left' },
  { name: 'type', label: 'Action', field: (c) => commandTypeLabel(c.type), align: 'left' },
  { name: 'status', label: 'Statut', field: 'status', align: 'left' },
  { name: 'created_by', label: 'Par', field: 'created_by', align: 'left' },
  { name: 'created_at', label: 'Le', field: (c) => formatDateTime(c.created_at), align: 'left' },
  { name: 'result', label: 'Résultat', field: 'id', align: 'left' },
];

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
  const what = [
    uploading.value
      ? 'Un dépôt de fichiers est en cours : quitter la page l’interrompt (les fichiers déjà envoyés sont gardés).'
      : '',
    dirty.value ? 'La définition du paquet a été modifiée sans être enregistrée.' : '',
  ].filter(Boolean);
  return new Promise<boolean>((resolve) => {
    $q.dialog({
      title: uploading.value ? 'Dépôt en cours' : 'Modifications non enregistrées',
      message: `${what.join(' ')} Quitter la page ?`,
      cancel: { flat: true, noCaps: true, label: 'Rester' },
      ok: {
        flat: true,
        noCaps: true,
        label: uploading.value ? 'Quitter et interrompre' : 'Quitter sans enregistrer',
        color: 'negative',
      },
      persistent: true,
    })
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
  name: (v: string) => !!v.trim() || 'Nom requis',
  wingetId: (v: string) =>
    /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/.test(v.trim()) ||
    'Identifiant winget invalide (ex. Mozilla.Firefox)',
  msiexecArgs: (run: string | null, v: string) =>
    run !== 'msiexec' ||
    splitArgs(v).length > 0 ||
    'Avec msiexec, indiquer les arguments (ex. /i "{dir}\\app.msi" /qn)',
  successCodes: (v: string) => {
    const parts = v.split(/[,;\s]+/).filter(Boolean);
    if (!parts.length) return 'Au moins un code (ex. 0, 3010, 1641)';
    if (parts.length > 32) return '32 codes au plus';
    return parts.every((p) => /^-?\d+$/.test(p)) || 'Des nombres entiers, séparés par des virgules';
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
          ? 'Enregistré — le manifeste a changé : la signature est à refaire'
          : 'Enregistré',
    });
    return true;
  } catch (e) {
    notifyError(e, 'Enregistrement impossible');
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
      message: `Trop volumineux : ${tooBig.map((f) => f.name).join(', ')}`,
      caption: `Limite de ce serveur : ${formatSize(pkg.value.file_max_bytes)} par fichier.`,
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
      message: files.length > 1 ? 'Fichiers déposés' : 'Fichier déposé',
      ...(dirty.value ? { caption: 'Pensez à enregistrer la définition.' } : {}),
    });
  } catch (e) {
    const notSent = files.slice(kept.length).map((f) => f.name);
    const caption =
      files.length > 1
        ? [
            kept.length ? `Déposé${kept.length > 1 ? 's' : ''} : ${kept.join(', ')}.` : '',
            `Non envoyé${notSent.length > 1 ? 's' : ''} : ${notSent.join(', ')}.`,
          ]
            .filter(Boolean)
            .join(' ')
        : undefined;
    if (isCancel(e)) {
      $q.notify({
        type: 'info',
        message: sent ? 'Dépôt interrompu : les fichiers déjà envoyés sont gardés' : 'Dépôt annulé',
        ...(caption ? { caption } : {}),
      });
    } else {
      $q.notify({
        type: 'negative',
        message: apiErrorMessage(e, 'Dépôt impossible'),
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
  $q.dialog({
    title: 'Retirer le fichier',
    message: `Retirer « ${name} » du paquet ?`,
    cancel: true,
    ok: { label: 'Retirer', color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        refresh(await deletePackageFile(id, name));
      } catch (e) {
        notifyError(e, 'Suppression impossible');
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
    notifyError(e, 'Téléchargement impossible');
  }
}

async function sendSignature(file: File | null) {
  if (!pkg.value || !file) return;
  try {
    const document: unknown = JSON.parse(await file.text());
    refresh(await attachSignature(pkg.value.id, document));
    $q.notify({ type: 'positive', message: 'Signature vérifiée et jointe au paquet' });
  } catch (e) {
    notifyError(
      e,
      e instanceof SyntaxError ? 'Ce fichier n’est pas une signature' : 'Signature refusée',
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
    notifyError(e, 'Opération impossible');
  }
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n > 1 ? many : one}`;
}

function confirm(title: string, message: string, ok: string, color: string): Promise<boolean> {
  return new Promise((resolve) => {
    $q.dialog({
      title,
      message,
      cancel: { flat: true, noCaps: true, label: 'Annuler' },
      ok: { unelevated: true, noCaps: true, label: ok, color },
      persistent: true,
    })
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
      'Remettre au catalogue',
      `« ${p.name} » pourra de nouveau être déployé. Les installations annulées lors du retrait ne sont pas relancées : redéployez le paquet sur les postes voulus.`,
      'Remettre au catalogue',
      'primary',
    );
    if (!ok) return;
    try {
      refresh(await restorePackage(p.id));
      $q.notify({
        type: 'positive',
        message: 'Paquet remis au catalogue',
        caption: 'Les installations annulées au retrait ne sont pas relancées.',
      });
    } catch (e) {
      notifyError(e, 'Opération impossible');
    }
    void loadCommands();
    return;
  }
  // Counted now, not from the tally on screen, which may be minutes old.
  const tally = await getPackageSummary(p.id).catch(() => summary.value);
  if (tally) summary.value = tally;
  const pending = tally?.pending_installs ?? null;
  const cancelled =
    pending === null
      ? 'Les installations en attente (pas encore reçues par leur poste) seront annulées.'
      : pending > 0
        ? `${plural(pending, 'installation en attente', 'installations en attente')} (pas encore ${pending > 1 ? 'reçues' : 'reçue'} par ${pending > 1 ? 'leur poste' : 'son poste'}) ${pending > 1 ? 'seront annulées' : 'sera annulée'}.`
        : 'Aucune installation n’est en attente.';
  const ok = await confirm(
    'Retirer le paquet',
    `${cancelled} Celles déjà transmises vont à leur terme ; les désinstallations ne sont pas touchées. Le paquet ne sera plus proposé au déploiement, et le remettre au catalogue ne relancera pas les installations annulées.`,
    'Retirer',
    'negative',
  );
  if (!ok) return;
  try {
    refresh(await retirePackage(p.id));
    $q.notify({
      type: 'positive',
      message: 'Paquet retiré',
      ...(pending
        ? {
            caption: `${plural(pending, 'installation en attente annulée', 'installations en attente annulées')}.`,
          }
        : {}),
    });
  } catch (e) {
    notifyError(e, 'Opération impossible');
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
      'Modifications non enregistrées',
      'La définition du paquet a été modifiée sans être enregistrée : le déploiement enverrait la version enregistrée, sans ces modifications.',
      'Enregistrer puis déployer',
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
