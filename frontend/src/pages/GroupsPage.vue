<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <h1 class="text-h5 q-my-none col-auto">Groupes</h1>
      <q-space />
      <q-btn
        v-if="auth.can('user', 'write')"
        color="primary"
        icon="group_add"
        label="Nouveau groupe"
        @click="openCreate"
      />
    </div>

    <div class="text-body2 text-muted q-mb-md" style="max-width: 720px">
      Un compte peut ce que ses groupes lui accordent, tous groupes confondus. Les trois groupes
      intégrés se renomment et, sauf les administrateurs, se modifient comme les autres ; ils ne se
      suppriment pas. Un groupe peut être limité à des emplacements, bâtiments ou salles : ses
      membres ne voient alors que ces postes — à condition qu'aucun de leurs autres groupes ne soit
      ouvert à tout le parc.
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
              class="q-mr-sm text-muted"
            >
              <q-tooltip v-if="props.row.builtin_key">Groupe intégré</q-tooltip>
            </q-icon>
            <div>
              <div>{{ props.row.name }}</div>
              <div v-if="props.row.description" class="text-caption text-muted">
                {{ props.row.description }}
              </div>
            </div>
          </div>
        </q-td>
      </template>

      <template #body-cell-permissions="props">
        <!-- Wrapping, unlike a table cell's default: a group carries a dozen
             chips, and a single line would push the actions off the screen. -->
        <q-td :props="props" style="white-space: normal; max-width: 720px">
          <span v-if="props.row.is_admin" class="text-weight-medium">Tous les droits</span>
          <span v-else-if="!props.row.permissions.length" class="text-muted">Aucun</span>
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

      <template #body-cell-scope="props">
        <q-td :props="props" style="white-space: normal; max-width: 320px">
          <span v-if="props.row.is_admin || !props.row.scope" class="text-muted">Tout le parc</span>
          <template v-else>
            <q-chip
              v-for="label in scopeLabels(props.row)"
              :key="label"
              dense
              size="sm"
              icon="place"
              class="q-ml-none"
            >
              {{ label }}
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
              <q-banner v-if="editing?.is_admin" dense class="surface-blue q-mb-sm">
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
                      <div v-if="entry.hint" class="text-caption text-muted q-ml-lg q-mb-xs">
                        {{ entry.hint }}
                      </div>
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
              <div v-if="riskyWithoutEveryday" class="text-caption text-warn q-mt-xs">
                Les commandes à risque ne s'exécutent pas sans les commandes courantes : ce droit
                seul n'ouvre rien.
              </div>
            </div>

            <div v-if="!editing?.is_admin">
              <div class="text-subtitle2 q-mb-xs">Postes concernés</div>
              <div class="text-caption text-muted q-mb-sm">
                Rien de coché : tout le parc. Sinon, les postes d'au moins un de ces emplacements,
                bâtiments ou salles — et les salles, vérifications, maintenances et e-mails qui s'y
                rapportent.
              </div>
              <div class="q-gutter-sm">
                <q-select
                  v-model="form.scope.locations"
                  :options="locationOptions"
                  label="Emplacements"
                  outlined
                  dense
                  multiple
                  use-chips
                  use-input
                  new-value-mode="add-unique"
                  hint="Tels que les agents les déclarent ; saisie libre possible"
                  @input-value="locationTyping = $event"
                  @blur="commitTypedLocation"
                />
                <q-select
                  v-model="form.scope.buildings"
                  :options="buildingOptions"
                  label="Bâtiments"
                  outlined
                  dense
                  multiple
                  use-chips
                  emit-value
                  map-options
                />
                <q-select
                  v-model="form.scope.rooms"
                  :options="roomOptions"
                  label="Salles"
                  outlined
                  dense
                  multiple
                  use-chips
                  emit-value
                  map-options
                />
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
import {
  createGroup,
  deleteGroup,
  listGroups,
  scopeOrNull,
  updateGroup,
  type Group,
} from 'src/services/groups';
import { listLocations } from 'src/services/machines';
import { listBuildings, listRooms, type Building, type Room } from 'src/services/rooms';
import { escapeHtml } from 'src/utils/html';
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
  scope: { locations: [] as string[], buildings: [] as string[], rooms: [] as string[] },
});

// What the scope pickers offer, and how a stored id is named in the table.
const locations = ref<string[]>([]);
const buildings = ref<Building[]>([]);
const rooms = ref<Room[]>([]);
const locationOptions = computed(() => locations.value);
const buildingOptions = computed(() =>
  buildings.value.map((b) => ({
    label: b.location ? `${b.name} (${b.location})` : b.name,
    value: b.id,
  })),
);
const roomOptions = computed(() =>
  rooms.value.map((r) => ({
    label: r.building ? `${r.name} — ${r.building.name}` : r.name,
    value: r.id,
  })),
);

function scopeLabels(group: Group): string[] {
  if (!group.scope) return [];
  const building = new Map(buildingOptions.value.map((o) => [o.value, o.label]));
  const room = new Map(roomOptions.value.map((o) => [o.value, o.label]));
  return [
    ...group.scope.locations,
    // An id that names nothing any more matches no poste: shown as such so
    // that an administrator can tidy it, never silently dropped.
    ...group.scope.buildings.map((id) => building.get(id) ?? 'Bâtiment supprimé'),
    ...group.scope.rooms.map((id) => room.get(id) ?? 'Salle supprimée'),
  ];
}

const columns: QTableColumn<Group>[] = [
  { name: 'name', label: 'Groupe', field: 'name', align: 'left' },
  { name: 'permissions', label: 'Droits', field: 'permissions', align: 'left' },
  { name: 'scope', label: 'Postes', field: 'scope', align: 'left' },
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
    // The places only name the scope chips: their failure must not blank
    // the groups, which the page is about.
    const [groups, sites, bs, rs] = await Promise.all([
      listGroups(),
      listLocations().catch(() => []),
      listBuildings().catch(() => []),
      listRooms().catch(() => []),
    ]);
    rows.value = groups;
    locations.value = sites.map((v) => v.name);
    buildings.value = bs;
    rooms.value = rs;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  Object.assign(form, {
    name: '',
    description: '',
    permissions: [],
    scope: { locations: [], buildings: [], rooms: [] },
  });
  formOpen.value = true;
}

function openEdit(group: Group) {
  editing.value = group;
  Object.assign(form, {
    name: group.name,
    description: group.description ?? '',
    permissions: [...group.permissions],
    scope: {
      locations: [...(group.scope?.locations ?? [])],
      buildings: [...(group.scope?.buildings ?? [])],
      rooms: [...(group.scope?.rooms ?? [])],
    },
  });
  formOpen.value = true;
}

// What is typed in « Emplacements » and not yet a chip: Quasar keeps it only
// on Entrée, and drops it when the field loses focus — the group would then
// be saved with no restriction at all (audit U02).
const locationTyping = ref('');

function commitTypedLocation() {
  const typed = locationTyping.value.trim();
  locationTyping.value = '';
  if (typed && !form.scope.locations.includes(typed)) {
    form.scope.locations = [...form.scope.locations, typed];
  }
}

/** Saving a group that reaches the whole parc is said, then confirmed. */
function confirmWholeParc(): Promise<boolean> {
  const restrictedBefore = editing.value ? editing.value.scope !== null : true;
  if (editing.value?.is_admin || scopeOrNull(form.scope) !== null || !restrictedBefore) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    $q.dialog({
      title: 'Tout le parc',
      message:
        'Aucun emplacement, bâtiment ni salle n’est choisi : les membres de ce groupe ' +
        'verront tous les postes et pourront y exercer ses droits. Enregistrer ainsi ?',
      cancel: { flat: true, noCaps: true, label: 'Revenir au formulaire' },
      ok: { unelevated: true, noCaps: true, label: 'Enregistrer pour tout le parc' },
      persistent: true,
    })
      .onOk(() => resolve(true))
      .onCancel(() => resolve(false));
  });
}

async function submitForm() {
  commitTypedLocation();
  if (!(await confirmWholeParc())) return;
  saving.value = true;
  try {
    if (editing.value) {
      await updateGroup(editing.value.id, {
        name: form.name.trim(),
        description: form.description.trim() || null,
        // Implicit for the administrators: sending them would be refused.
        ...(editing.value.is_admin
          ? {}
          : { permissions: form.permissions, scope: scopeOrNull(form.scope) }),
      });
      $q.notify({ type: 'positive', message: 'Groupe mis à jour' });
    } else {
      await createGroup({
        name: form.name.trim(),
        description: form.description.trim() || null,
        permissions: form.permissions,
        scope: scopeOrNull(form.scope),
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
      `Supprimer <b>${escapeHtml(group.name)}</b> ?<br>` +
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
