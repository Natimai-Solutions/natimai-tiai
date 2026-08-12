<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <div class="text-h5 col-auto">Utilisateurs</div>
      <q-space />
      <q-input
        v-model="search"
        dense
        outlined
        debounce="300"
        placeholder="E-mail ou nom…"
        class="col-auto"
        style="min-width: 220px"
        @update:model-value="reload"
      >
        <template #append><q-icon name="search" /></template>
      </q-input>
      <q-btn color="primary" icon="person_add" label="Nouveau compte" @click="openCreate" />
    </div>

    <q-table
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
    >
      <template #body-cell-role="props">
        <q-td :props="props">
          <q-badge :color="props.value === 'admin' ? 'primary' : 'grey-7'">
            {{ roleLabel(props.value) }}
          </q-badge>
        </q-td>
      </template>

      <template #body-cell-is_active="props">
        <q-td :props="props">
          <q-badge :color="props.value ? 'positive' : 'negative'">
            {{ props.value ? 'Actif' : 'Désactivé' }}
          </q-badge>
        </q-td>
      </template>

      <template #body-cell-created_at="props">
        <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-btn flat dense round icon="more_vert" :aria-label="`Actions pour ${props.row.email}`">
            <q-menu>
              <q-list style="min-width: 220px">
                <q-item v-close-popup clickable @click="openEdit(props.row)">
                  <q-item-section avatar><q-icon name="edit" /></q-item-section>
                  <q-item-section>Modifier</q-item-section>
                </q-item>
                <q-item v-close-popup clickable @click="openReset(props.row)">
                  <q-item-section avatar><q-icon name="lock_reset" /></q-item-section>
                  <q-item-section>Réinitialiser le mot de passe</q-item-section>
                </q-item>

                <q-separator />

                <!-- Self-protection: the backend refuses these on one's own
                     account, so they are hidden rather than shown failing. -->
                <q-item
                  v-close-popup
                  clickable
                  :disable="isSelf(props.row)"
                  @click="toggleActive(props.row)"
                >
                  <q-item-section avatar>
                    <q-icon :name="props.row.is_active ? 'block' : 'check_circle'" />
                  </q-item-section>
                  <q-item-section>
                    {{ props.row.is_active ? 'Désactiver' : 'Réactiver' }}
                  </q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  class="text-negative"
                  :disable="isSelf(props.row)"
                  @click="confirmDelete(props.row)"
                >
                  <q-item-section avatar><q-icon name="delete" /></q-item-section>
                  <q-item-section>Supprimer</q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Création / modification : même formulaire, le mot de passe n'apparaît
         qu'à la création (ensuite c'est la réinitialisation qui s'en charge). -->
    <q-dialog v-model="formOpen">
      <q-card style="width: 420px; max-width: 90vw">
        <q-card-section class="text-h6">
          {{ editing ? 'Modifier le compte' : 'Nouveau compte' }}
        </q-card-section>

        <q-form @submit="submitForm">
          <q-card-section class="q-gutter-md">
            <q-input
              v-model="form.email"
              type="email"
              label="E-mail"
              outlined
              dense
              autofocus
              :rules="[required]"
            />
            <q-input v-model="form.full_name" label="Nom complet" outlined dense />
            <q-select
              v-model="form.role"
              :options="roleOptions"
              emit-value
              map-options
              label="Rôle"
              outlined
              dense
            />
            <q-input
              v-if="!editing"
              v-model="form.password"
              type="password"
              label="Mot de passe"
              outlined
              dense
              :hint="`${PASSWORD_MIN_LENGTH} caractères minimum`"
              :rules="[required, longEnough]"
            />
          </q-card-section>

          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup flat label="Annuler" />
            <q-btn type="submit" color="primary" label="Enregistrer" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <!-- Réinitialisation : mot de passe généré ou choisi, affiché une seule fois. -->
    <q-dialog v-model="resetOpen" @hide="resetResult = null">
      <q-card style="width: 460px; max-width: 90vw">
        <q-card-section class="text-h6">Réinitialiser le mot de passe</q-card-section>
        <q-card-section class="q-pt-none text-body2 text-grey-8">
          {{ resetTarget?.email }}
        </q-card-section>

        <template v-if="resetResult === null">
          <q-form @submit="submitReset">
            <q-card-section class="q-gutter-sm">
              <q-option-group v-model="resetMode" :options="resetModes" />
              <q-input
                v-if="resetMode === 'manual'"
                v-model="resetPassword"
                type="password"
                label="Nouveau mot de passe"
                outlined
                dense
                :hint="`${PASSWORD_MIN_LENGTH} caractères minimum`"
                :rules="[required, longEnough]"
              />
              <q-banner dense class="bg-orange-1 text-orange-9">
                <template #avatar><q-icon name="warning" /></template>
                Les sessions ouvertes de ce compte seront fermées.
              </q-banner>
            </q-card-section>

            <q-card-actions align="right" class="q-px-md q-pb-md">
              <q-btn v-close-popup flat label="Annuler" />
              <q-btn type="submit" color="primary" label="Réinitialiser" :loading="saving" />
            </q-card-actions>
          </q-form>
        </template>

        <template v-else>
          <q-card-section class="q-gutter-sm">
            <div class="text-body2">
              Mot de passe défini. Il n'est plus consultable ensuite — transmettez-le maintenant,
              par un canal distinct de l'e-mail du compte.
            </div>
            <q-input :model-value="resetResult" readonly outlined dense class="text-weight-medium">
              <template #append>
                <q-btn
                  flat
                  dense
                  round
                  icon="content_copy"
                  aria-label="Copier"
                  @click="copyResult"
                />
              </template>
            </q-input>
          </q-card-section>
          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup color="primary" flat label="Fermer" />
          </q-card-actions>
        </template>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar';
import {
  createUser,
  deleteUser,
  listUsers,
  PASSWORD_MIN_LENGTH,
  resetUserPassword,
  updateUser,
  type ConsoleUser,
  type Role,
} from 'src/services/users';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';

const $q = useQuasar();
const auth = useAuthStore();

const rows = ref<ConsoleUser[]>([]);
const loading = ref(false);
const saving = ref(false);
const search = ref('');

const formOpen = ref(false);
const editing = ref<ConsoleUser | null>(null);
const form = reactive({ email: '', full_name: '', role: 'readonly' as Role, password: '' });

const resetOpen = ref(false);
const resetTarget = ref<ConsoleUser | null>(null);
const resetMode = ref<'generate' | 'manual'>('generate');
const resetPassword = ref('');
const resetResult = ref<string | null>(null);

const roleOptions = [
  { label: 'Administrateur', value: 'admin' },
  { label: 'Lecture seule', value: 'readonly' },
];

const resetModes = [
  { label: 'Générer un mot de passe', value: 'generate' },
  { label: 'Saisir un mot de passe', value: 'manual' },
];

const columns: QTableColumn<ConsoleUser>[] = [
  { name: 'email', label: 'E-mail', field: 'email', align: 'left', sortable: true },
  { name: 'full_name', label: 'Nom', field: 'full_name', align: 'left', sortable: true },
  { name: 'role', label: 'Rôle', field: 'role', align: 'center' },
  { name: 'is_active', label: 'État', field: 'is_active', align: 'center' },
  { name: 'created_at', label: 'Créé le', field: 'created_at', align: 'left', sortable: true },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

const required = (v: string) => !!v || 'Requis';
const longEnough = (v: string) =>
  v.length >= PASSWORD_MIN_LENGTH || `${PASSWORD_MIN_LENGTH} caractères minimum`;

function roleLabel(role: Role) {
  return role === 'admin' ? 'Administrateur' : 'Lecture seule';
}

function isSelf(user: ConsoleUser) {
  return user.id === auth.user?.id;
}

async function reload() {
  loading.value = true;
  try {
    const params: Parameters<typeof listUsers>[0] = {};
    if (search.value) params.search = search.value;
    rows.value = (await listUsers(params)).items;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  Object.assign(form, { email: '', full_name: '', role: 'readonly', password: '' });
  formOpen.value = true;
}

function openEdit(user: ConsoleUser) {
  editing.value = user;
  Object.assign(form, {
    email: user.email,
    full_name: user.full_name ?? '',
    role: user.role,
    password: '',
  });
  formOpen.value = true;
}

async function submitForm() {
  saving.value = true;
  try {
    if (editing.value) {
      await updateUser(editing.value.id, {
        email: form.email,
        full_name: form.full_name || null,
        role: form.role,
      });
      $q.notify({ type: 'positive', message: 'Compte mis à jour' });
    } else {
      await createUser({
        email: form.email,
        password: form.password,
        full_name: form.full_name || null,
        role: form.role,
      });
      $q.notify({ type: 'positive', message: 'Compte créé' });
    }
    formOpen.value = false;
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}

function openReset(user: ConsoleUser) {
  resetTarget.value = user;
  resetMode.value = 'generate';
  resetPassword.value = '';
  resetResult.value = null;
  resetOpen.value = true;
}

async function submitReset() {
  if (!resetTarget.value) return;
  saving.value = true;
  try {
    resetResult.value = await resetUserPassword(
      resetTarget.value.id,
      resetMode.value === 'manual' ? resetPassword.value : undefined,
    );
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Réinitialisation impossible') });
  } finally {
    saving.value = false;
  }
}

async function copyResult() {
  if (!resetResult.value) return;
  await copyToClipboard(resetResult.value);
  $q.notify({ type: 'positive', message: 'Copié' });
}

async function toggleActive(user: ConsoleUser) {
  try {
    await updateUser(user.id, { is_active: !user.is_active });
    $q.notify({
      type: 'positive',
      message: user.is_active ? 'Compte désactivé' : 'Compte réactivé',
    });
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Modification impossible') });
  }
}

function confirmDelete(user: ConsoleUser) {
  $q.dialog({
    title: 'Supprimer le compte',
    message:
      `Supprimer définitivement <b>${user.email}</b> ?<br>` +
      'La désactivation est préférable si vous voulez garder la trace du compte.',
    html: true,
    cancel: true,
    ok: { label: 'Supprimer', color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        await deleteUser(user.id);
        $q.notify({ type: 'positive', message: 'Compte supprimé' });
        await reload();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Suppression impossible') });
      }
    })();
  });
}

onMounted(reload);
</script>
