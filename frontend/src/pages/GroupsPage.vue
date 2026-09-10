<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <div class="text-h5 col-auto">Groupes</div>
      <q-space />
      <q-btn
        v-if="auth.can('user', 'write')"
        color="primary"
        icon="group_add"
        label="Nouveau groupe"
        @click="openCreate"
      />
    </div>

    <div class="text-body2 text-grey-8 q-mb-md" style="max-width: 720px">
      Un compte peut ce que ses groupes lui accordent, tous groupes confondus. Les trois groupes
      intégrés se renomment et, sauf les administrateurs, se modifient comme les autres ; ils ne se
      suppriment pas.
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
    >
      <template #body-cell-name="props">
        <q-td :props="props">
          <div class="row items-center no-wrap">
            <q-icon
              :name="props.row.is_admin ? 'shield' : props.row.builtin_key ? 'lock' : 'group'"
              size="18px"
              class="q-mr-sm text-grey-7"
            >
              <q-tooltip v-if="props.row.builtin_key">Groupe intégré</q-tooltip>
            </q-icon>
            <div>
              <div>{{ props.row.name }}</div>
              <div v-if="props.row.description" class="text-caption text-grey">
                {{ props.row.description }}
              </div>
            </div>
          </div>
        </q-td>
      </template>

      <template #body-cell-permissions="props">
        <q-td :props="props">
          <span v-if="props.row.is_admin" class="text-weight-medium">Tous les droits</span>
          <span v-else-if="!props.row.permissions.length" class="text-grey">Aucun</span>
          <template v-else>
            <q-chip
              v-for="key in props.row.permissions"
              :key="key"
              dense
              size="sm"
              outline
              color="primary"
              class="q-ml-none"
            >
              {{ permissionLabel(key) }}
            </q-chip>
          </template>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-btn
            v-if="auth.can('user', 'write')"
            flat
            dense
            round
            icon="more_vert"
            :aria-label="`Actions pour ${props.row.name}`"
          >
            <q-menu>
              <q-list style="min-width: 200px">
                <q-item v-close-popup clickable @click="openEdit(props.row)">
                  <q-item-section avatar><q-icon name="edit" /></q-item-section>
                  <q-item-section>Modifier</q-item-section>
                </q-item>
                <q-separator />
                <q-item
                  v-close-popup
                  clickable
                  class="text-negative"
                  :disable="props.row.builtin_key !== null"
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

    <!-- Création / modification : même formulaire. La grille des droits est
         l'objet de la page ; pour les administrateurs elle est affichée cochée
         et verrouillée, leurs droits étant implicites. -->
    <q-dialog v-model="formOpen">
      <q-card style="width: 640px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{ editing ? 'Modifier le groupe' : 'Nouveau groupe' }}
        </q-card-section>

        <q-form @submit="submitForm">
          <q-card-section class="q-gutter-md">
            <q-input
              v-model="form.name"
              label="Nom"
              outlined
              dense
              autofocus
              maxlength="100"
              :rules="[required]"
            />
            <q-input
              v-model="form.description"
              label="Description"
              outlined
              dense
              maxlength="500"
              autogrow
            />

            <div>
              <div class="text-subtitle2 q-mb-xs">Droits</div>
              <q-banner v-if="editing?.is_admin" dense class="bg-blue-1 text-blue-9 q-mb-sm">
                Les administrateurs ont tous les droits, y compris ceux des ressources à venir.
                Cette grille n'est pas modifiable.
              </q-banner>
              <q-list dense bordered separator>
                <q-item v-for="row in permissionRows()" :key="row.resource">
                  <q-item-section side top style="min-width: 160px">
                    <div class="text-weight-medium q-pt-xs">{{ row.resourceLabel }}</div>
                  </q-item-section>
                  <q-item-section>
                    <div v-for="entry in row.entries" :key="entry.key">
                      <q-checkbox
                        v-model="form.permissions"
                        :val="entry.key"
                        :label="entry.label"
                        dense
                        :disable="editing?.is_admin === true"
                      />
                      <div v-if="entry.hint" class="text-caption text-grey q-ml-lg q-mb-xs">
                        {{ entry.hint }}
                      </div>
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
              <div v-if="riskyWithoutEveryday" class="text-caption text-orange-9 q-mt-xs">
                Les commandes à risque ne s'exécutent pas sans les commandes courantes : ce droit
                seul n'ouvre rien.
              </div>
            </div>
          </q-card-section>

          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup flat label="Annuler" />
            <q-btn type="submit" color="primary" label="Enregistrer" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { createGroup, deleteGroup, listGroups, updateGroup, type Group } from 'src/services/groups';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { permissionLabel, permissionRows } from 'src/utils/permissions';

const $q = useQuasar();
const auth = useAuthStore();

const rows = ref<Group[]>([]);
const loading = ref(false);
const saving = ref(false);

const formOpen = ref(false);
const editing = ref<Group | null>(null);
const form = reactive({
  name: '',
  description: '',
  permissions: [] as string[],
});

const columns: QTableColumn<Group>[] = [
  { name: 'name', label: 'Groupe', field: 'name', align: 'left' },
  { name: 'permissions', label: 'Droits', field: 'permissions', align: 'left' },
  { name: 'member_count', label: 'Comptes', field: 'member_count', align: 'center' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

const required = (v: string) => !!v.trim() || 'Requis';

// The one combination the grid lets you tick that grants nothing: said in the
// form rather than discovered on the first 403.
const riskyWithoutEveryday = computed(
  () =>
    form.permissions.includes('risky_command:execute') &&
    !form.permissions.includes('command:execute'),
);

async function reload() {
  loading.value = true;
  try {
    rows.value = await listGroups();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  Object.assign(form, { name: '', description: '', permissions: [] });
  formOpen.value = true;
}

function openEdit(group: Group) {
  editing.value = group;
  Object.assign(form, {
    name: group.name,
    description: group.description ?? '',
    permissions: [...group.permissions],
  });
  formOpen.value = true;
}

async function submitForm() {
  saving.value = true;
  try {
    if (editing.value) {
      await updateGroup(editing.value.id, {
        name: form.name.trim(),
        description: form.description.trim() || null,
        // Implicit for the administrators: sending them would be refused.
        ...(editing.value.is_admin ? {} : { permissions: form.permissions }),
      });
      $q.notify({ type: 'positive', message: 'Groupe mis à jour' });
    } else {
      await createGroup({
        name: form.name.trim(),
        description: form.description.trim() || null,
        permissions: form.permissions,
      });
      $q.notify({ type: 'positive', message: 'Groupe créé' });
    }
    formOpen.value = false;
    await reload();
    // One's own rights may just have changed: the menus follow the profile.
    await auth.fetchMe();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}

function confirmDelete(group: Group) {
  $q.dialog({
    title: 'Supprimer le groupe',
    message:
      `Supprimer <b>${group.name}</b> ?<br>` +
      `Les ${group.member_count} compte(s) qui en font partie perdent ce qu'il leur accordait.`,
    html: true,
    cancel: true,
    ok: { label: 'Supprimer', color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        await deleteGroup(group.id);
        $q.notify({ type: 'positive', message: 'Groupe supprimé' });
        await reload();
        await auth.fetchMe();
      } catch (e) {
        $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Suppression impossible') });
      }
    })();
  });
}

onMounted(reload);
</script>
