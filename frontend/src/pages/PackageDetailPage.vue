<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <q-btn flat round dense icon="arrow_back" :to="{ name: 'packages' }" aria-label="Retour" />
      <h1 class="text-h5 q-my-none col-auto">
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
          <q-form @submit="save">
            <q-card-section class="q-gutter-sm">
              <q-input v-model="form.name" label="Nom" outlined dense :readonly="!canWrite" />
              <q-input
                v-model="form.version"
                label="Version"
                outlined
                dense
                :readonly="!canWrite"
              />
              <template v-if="pkg.kind === 'winget'">
                <q-input
                  v-model="form.winget_id"
                  label="Identifiant winget"
                  outlined
                  dense
                  :readonly="!canWrite"
                />
                <q-input
                  v-model="form.winget_version"
                  label="Version winget (vide = la plus récente)"
                  outlined
                  dense
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
                  :readonly="!canWrite"
                  hint="Avec msiexec : /x {code produit} /qn"
                />
                <q-input
                  v-model="form.success_codes"
                  label="Codes de sortie acceptés"
                  outlined
                  dense
                  :readonly="!canWrite"
                  hint="Séparés par des virgules. 3010 et 1641 = redémarrage requis."
                />
              </template>
              <q-input
                v-model="form.detect_name"
                label="Nom dans l'inventaire"
                outlined
                dense
                :readonly="!canWrite"
                hint="Tel qu'il apparaît dans « Applications et fonctionnalités » ; sert à compter les postes équipés"
              />
              <q-input
                v-model="form.notes"
                label="Notes"
                outlined
                dense
                autogrow
                :readonly="!canWrite"
              />
            </q-card-section>
            <q-card-actions v-if="canWrite" align="right" class="q-px-md q-pb-md">
              <span v-if="pkg.signed" class="text-caption text-muted q-mr-md">
                Modifier la ligne de commande annule la signature.
              </span>
              <span v-if="dirty" class="text-caption text-warning q-mr-md">
                Modifications non enregistrées
              </span>
              <q-btn type="submit" color="primary" no-caps label="Enregistrer" :loading="saving" />
            </q-card-actions>
          </q-form>
        </q-card>
      </div>

      <div class="col-12 col-lg-6 q-gutter-y-md">
        <!-- Problems -->
        <q-banner v-if="pkg.problems.length" class="surface-orange">
          <div class="text-weight-medium">Pas encore déployable</div>
          <ul class="q-my-xs q-pl-md">
            <li v-for="p in pkg.problems" :key="p.code">{{ p.message }}</li>
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
            <q-item v-for="f in pkg.files" :key="f.name">
              <q-item-section>
                <q-item-label>
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
              <template v-if="method === 'publisher' || (!pkg.signed && pkg.publisher_name)">
                Le fichier lancé est signé par <b>{{ pkg.publisher_name }}</b
                >. Sans signature de l'administrateur, les postes l'exécutent si la GPO liste ce nom
                dans <code>DeployPublishers</code>.
              </template>
              <template v-else-if="pkg.signed">Inutile : le paquet est signé.</template>
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
          <q-table
            :rows="commands"
            :columns="commandColumns"
            row-key="id"
            flat
            :loading="loadingCommands"
            :rows-per-page-options="[0]"
            hide-pagination
            no-data-label="Jamais déployé"
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
              <q-td :props="cell" style="white-space: normal; max-width: 520px">
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
import { useQuasar, type QTableColumn } from 'quasar';
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
  PACKAGE_FILE_MAX_BYTES,
  joinArgs,
  listPackageCommands,
  removeSignature,
  restorePackage,
  retirePackage,
  splitArgs,
  trustLabels,
  trustMethod,
  updatePackage,
  uploadPackageFiles,
  type Package,
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
const fileNames = computed(() => pkg.value?.files.map((f) => f.name) ?? []);
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
  if (!dirty.value) return true;
  return new Promise<boolean>((resolve) => {
    $q.dialog({
      title: 'Modifications non enregistrées',
      message: 'La définition du paquet a été modifiée sans être enregistrée. Quitter la page ?',
      cancel: { flat: true, noCaps: true, label: 'Rester' },
      ok: { flat: true, noCaps: true, label: 'Quitter sans enregistrer', color: 'negative' },
      persistent: true,
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false));
  });
});

async function load() {
  loadError.value = null;
  try {
    fill(await getPackage(props.id));
  } catch (e) {
    loadError.value = e;
  }
  void loadCommands();
}

async function loadCommands() {
  loadingCommands.value = true;
  try {
    commands.value = (await listPackageCommands(props.id)).items;
  } catch {
    commands.value = [];
  } finally {
    loadingCommands.value = false;
  }
}

function notifyError(e: unknown, fallback: string) {
  $q.notify({ type: 'negative', message: apiErrorMessage(e, fallback) });
}

async function save() {
  if (!pkg.value) return;
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
  } catch (e) {
    notifyError(e, 'Enregistrement impossible');
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
  const tooBig = files.filter((f) => f.size > PACKAGE_FILE_MAX_BYTES);
  if (tooBig.length) {
    $q.notify({
      type: 'negative',
      message: `Trop volumineux : ${tooBig.map((f) => f.name).join(', ')}`,
      caption: `Limite : ${formatSize(PACKAGE_FILE_MAX_BYTES)} par fichier.`,
    });
    return;
  }
  const total = files.reduce((n, f) => n + f.size, 0) || 1;
  uploading.value = true;
  uploadProgress.value = 0;
  uploadAbort = new AbortController();
  let sent = 0;
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
    if (isCancel(e)) {
      $q.notify({
        type: 'info',
        message: sent ? 'Dépôt interrompu : les fichiers déjà envoyés sont gardés' : 'Dépôt annulé',
      });
    } else {
      notifyError(e, 'Dépôt impossible');
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
    const base = `${pkg.value.name}-${pkg.value.version ?? ''}`.replace(/[^A-Za-z0-9._-]+/g, '-');
    downloadBlob(blob, `${base.replace(/^-+|-+$/g, '')}.tiai-manifest.json`);
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

async function toggleRetired() {
  if (!pkg.value) return;
  try {
    refresh(
      pkg.value.retired_at ? await restorePackage(pkg.value.id) : await retirePackage(pkg.value.id),
    );
  } catch (e) {
    notifyError(e, 'Opération impossible');
  }
}

function openDeploy(action: 'install' | 'uninstall') {
  deployAction.value = action;
  deployOpen.value = true;
}

onMounted(load);
</script>
