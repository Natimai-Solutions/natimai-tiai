<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <h1 class="text-h5 q-my-none col-auto">Paquets</h1>
      <q-space />
      <q-toggle v-model="showRetired" label="Paquets retirés" dense class="q-mr-md" />
      <q-btn
        v-if="auth.can('package', 'write')"
        color="primary"
        icon="add"
        label="Nouveau paquet"
        no-caps
        @click="openCreate"
      />
    </div>

    <div class="text-body2 text-muted q-mb-md" style="max-width: 760px">
      Ce que la console sait installer. Un paquet <b>winget</b> désigne un logiciel du dépôt
      Microsoft ; un paquet de <b>fichiers</b> embarque son installateur et sa ligne de commande.
      Chaque poste décide de l'exécuter d'après ce que sa GPO approuve : winget, la signature de
      l'administrateur (méthode B) ou l'éditeur de l'exécutable (méthode A).
    </div>

    <q-table
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[0]"
      hide-pagination
      flat
      bordered
      no-data-label="Aucun paquet pour l'instant"
      @row-click="(_evt, row) => open(row)"
    >
      <template #body-cell-name="props">
        <q-td :props="props">
          <div class="text-weight-medium">{{ props.row.name }}</div>
          <div class="text-caption text-muted">
            {{ props.row.kind === 'winget' ? props.row.winget_id : fileSummary(props.row) }}
          </div>
        </q-td>
      </template>
      <template #body-cell-trust="props">
        <q-td :props="props">
          <q-chip dense size="sm" :color="trustColor(props.row)" text-color="white">
            {{ trustLabels[trustMethod(props.row)] }}
          </q-chip>
        </q-td>
      </template>
      <template #body-cell-state="props">
        <q-td :props="props">
          <span v-if="props.row.retired_at" class="text-muted">Retiré</span>
          <span v-else-if="props.row.problems.length" class="text-warn">
            {{ props.row.problems[0].message }}
          </span>
          <span v-else class="text-ok">Prêt</span>
        </q-td>
      </template>
      <template #body-cell-installed="props">
        <q-td :props="props">
          {{ props.row.installed_count ?? '—' }}
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="createOpen">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="text-h6">Nouveau paquet</q-card-section>
        <q-form @submit="submitCreate">
          <q-card-section class="q-gutter-md">
            <q-btn-toggle
              v-model="form.kind"
              no-caps
              unelevated
              toggle-color="primary"
              :options="[
                { label: 'winget', value: 'winget' },
                { label: 'Fichiers (.exe, .msi…)', value: 'files' },
              ]"
            />
            <q-input
              v-model="form.name"
              label="Nom"
              outlined
              dense
              autofocus
              :rules="[(v: string) => !!v.trim() || 'Requis']"
            />
            <q-input v-model="form.version" label="Version" outlined dense />
            <template v-if="form.kind === 'winget'">
              <q-input
                v-model="form.winget_id"
                label="Identifiant winget"
                outlined
                dense
                hint="Exact, tel que « winget search » l'affiche : Mozilla.Firefox, 7zip.7zip…"
                :rules="[
                  (v: string) =>
                    /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/.test(v) || 'Identifiant invalide',
                ]"
              />
            </template>
            <div v-else class="text-caption text-muted">
              Les fichiers et la ligne de commande se renseignent sur la page du paquet, une fois
              créé.
            </div>
          </q-card-section>
          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup flat no-caps label="Annuler" />
            <q-btn type="submit" color="primary" no-caps label="Créer" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import { apiErrorMessage } from 'src/services/errors';
import {
  createPackage,
  listPackages,
  trustLabels,
  trustMethod,
  type Package,
  type PackageKind,
} from 'src/services/packages';
import { useAuthStore } from 'src/stores/auth';

const $q = useQuasar();
const router = useRouter();
const auth = useAuthStore();

const rows = ref<Package[]>([]);
const loading = ref(false);
const showRetired = ref(false);
const createOpen = ref(false);
const saving = ref(false);
const form = reactive({ kind: 'winget' as PackageKind, name: '', version: '', winget_id: '' });

const columns: QTableColumn<Package>[] = [
  { name: 'name', label: 'Paquet', field: 'name', align: 'left', sortable: true },
  { name: 'version', label: 'Version', field: (p) => p.version ?? '', align: 'left' },
  { name: 'trust', label: 'Confiance', field: 'kind', align: 'left' },
  { name: 'state', label: 'État', field: 'id', align: 'left' },
  { name: 'installed', label: 'Postes équipés', field: 'installed_count', align: 'center' },
];

function fileSummary(p: Package): string {
  if (!p.files.length) return 'Aucun fichier';
  return p.install_run ?? `${p.files.length} fichier(s)`;
}

function trustColor(p: Package): string {
  return { winget: 'primary', signed: 'positive', publisher: 'teal', none: 'grey-7' }[
    trustMethod(p)
  ];
}

async function reload() {
  loading.value = true;
  try {
    rows.value = await listPackages(showRetired.value);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
  } finally {
    loading.value = false;
  }
}

function open(p: Package) {
  void router.push({ name: 'package-detail', params: { id: p.id } });
}

function openCreate() {
  Object.assign(form, { kind: 'winget', name: '', version: '', winget_id: '' });
  createOpen.value = true;
}

async function submitCreate() {
  saving.value = true;
  try {
    const created = await createPackage({
      kind: form.kind,
      name: form.name.trim(),
      version: form.version.trim() || null,
      ...(form.kind === 'winget' ? { winget_id: form.winget_id.trim() } : {}),
    });
    createOpen.value = false;
    open(created);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Création impossible') });
  } finally {
    saving.value = false;
  }
}

watch(showRetired, reload);
onMounted(reload);
</script>
