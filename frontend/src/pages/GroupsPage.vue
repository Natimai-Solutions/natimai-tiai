<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <h1 class="text-h5 q-my-none col-auto">{{ t('groups.page.title') }}</h1>
      <q-space />
      <q-btn
        v-if="auth.can('user', 'write')"
        color="primary"
        icon="group_add"
        :label="t('groups.page.create')"
        @click="openCreate"
      />
    </div>

    <div class="text-body2 text-muted q-mb-md" style="max-width: 720px">
      {{ t('groups.page.intro') }}
    </div>

    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="reload" />

    <q-table
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :no-data-label="loadError ? t('groups.page.notLoaded') : t('groups.page.empty')"
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
              <q-tooltip v-if="props.row.builtin_key">{{ t('groups.row.builtin') }}</q-tooltip>
            </q-icon>
            <div>
              <div>{{ groupName(props.row, rows) }}</div>
              <div v-if="props.row.description" class="text-caption text-muted">
                {{ groupDescription(props.row) }}
              </div>
            </div>
          </div>
        </q-td>
      </template>

      <template #body-cell-permissions="props">
        <!-- Wrapping, unlike a table cell's default: a group carries a dozen
             chips, and a single line would push the actions off the screen. -->
        <q-td :props="props" style="white-space: normal; max-width: 720px">
          <span v-if="props.row.is_admin" class="text-weight-medium">{{
            t('groups.row.allPermissions')
          }}</span>
          <span v-else-if="!props.row.permissions.length" class="text-muted">{{
            t('groups.row.noPermission')
          }}</span>
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
          <span v-if="props.row.is_admin || !props.row.scope" class="text-muted">{{
            t('groups.row.wholeFleet')
          }}</span>
          <template v-else>
            <q-chip
              v-for="(label, i) in scopeLabels(props.row)"
              :key="`${i}-${label}`"
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
            :aria-label="t('groups.row.actionsFor', { name: props.row.name })"
            @click="rememberTrigger"
          >
            <q-menu>
              <q-list style="min-width: 200px">
                <!-- A group granting more than the caller holds: the server
                     refuses to edit or delete it (item 4). -->
                <q-item v-if="beyondMe(props.row)" dense class="text-caption text-muted">
                  <q-item-section avatar><q-icon name="lock" size="xs" /></q-item-section>
                  <q-item-section>{{ moreRightsGroup() }}</q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  :disable="beyondMe(props.row)"
                  @click="openEdit(props.row)"
                >
                  <q-item-section avatar><q-icon name="edit" /></q-item-section>
                  <q-item-section>{{ t('groups.row.edit') }}</q-item-section>
                </q-item>
                <q-separator />
                <q-item
                  v-close-popup
                  clickable
                  class="text-negative"
                  :disable="props.row.builtin_key !== null || beyondMe(props.row)"
                  @click="confirmDelete(props.row)"
                >
                  <q-item-section avatar><q-icon name="delete" /></q-item-section>
                  <q-item-section>{{ t('groups.row.delete') }}</q-item-section>
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
    <q-dialog v-model="formOpen" @hide="restoreFocus">
      <q-card style="width: 640px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{ editing ? t('groups.form.editTitle') : t('groups.form.createTitle') }}
        </q-card-section>

        <q-form @submit="submitForm">
          <q-card-section class="q-gutter-md">
            <q-input
              v-model="form.name"
              :label="t('groups.form.name')"
              outlined
              dense
              autofocus
              maxlength="100"
              reactive-rules
              :rules="[required]"
            />
            <q-input
              v-model="form.description"
              :label="t('groups.form.description')"
              outlined
              dense
              maxlength="500"
              autogrow
            />

            <div>
              <div class="text-subtitle2 q-mb-xs">{{ t('groups.form.permissions') }}</div>
              <q-banner v-if="editing?.is_admin" dense class="surface-blue q-mb-sm">
                {{ t('groups.form.adminBanner') }}
              </q-banner>
              <div class="text-caption text-muted q-mb-xs">
                {{ t('groups.form.dependencies') }}
              </div>
              <q-list dense bordered separator>
                <q-item v-for="row in permissionRows()" :key="row.resource">
                  <q-item-section side top style="min-width: 160px">
                    <div class="text-weight-medium q-pt-xs">{{ row.resourceLabel }}</div>
                  </q-item-section>
                  <q-item-section>
                    <div v-for="entry in row.entries" :key="entry.key">
                      <q-checkbox
                        :model-value="form.permissions"
                        :val="entry.key"
                        :label="entry.label"
                        dense
                        :disable="editing?.is_admin === true || cannotGrant(entry.key)"
                        @update:model-value="onPermissions"
                      >
                        <q-tooltip v-if="cannotGrant(entry.key)">
                          {{ t('groups.form.cannotGrant') }}
                        </q-tooltip>
                      </q-checkbox>
                      <div v-if="entry.hint" class="text-caption text-muted q-ml-lg q-mb-xs">
                        {{ entry.hint }}
                      </div>
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
              <div v-if="riskyWithoutEveryday" class="text-caption text-warn q-mt-xs">
                {{ t('groups.form.riskyWithoutEveryday') }}
              </div>
            </div>

            <div v-if="!editing?.is_admin">
              <div class="text-subtitle2 q-mb-xs">{{ t('groups.form.scope') }}</div>
              <div class="text-caption text-muted q-mb-sm">
                {{ t('groups.form.scopeHint') }}
              </div>
              <div class="q-gutter-sm">
                <q-select
                  v-model="form.scope.locations"
                  :options="locationOptions"
                  :label="t('groups.form.locations')"
                  outlined
                  dense
                  multiple
                  use-chips
                  use-input
                  new-value-mode="add-unique"
                  :hint="t('groups.form.locationsHint')"
                  :input-debounce="0"
                  @input-value="locationTyping = $event"
                  @blur="commitTypedLocation"
                />
                <q-select
                  v-model="form.scope.buildings"
                  :options="buildingOptions"
                  :label="t('groups.form.buildings')"
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
                  :label="t('groups.form.rooms')"
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
            <q-btn v-close-popup flat :label="t('groups.form.cancel')" />
            <q-btn type="submit" color="primary" :label="t('groups.form.save')" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { groupDescription, groupName } from 'src/utils/groupText';
import { computed, onMounted, reactive, ref } from 'vue';
import { useFocusReturn } from 'src/composables/useFocusReturn';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import { callerAuthority, exceeds, groupsAuthority, moreRightsGroup } from 'src/utils/authority';
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
import { applyPermissionChange, permissionLabel, permissionRows } from 'src/utils/permissions';
import { liveDialog } from 'src/utils/liveDialog';

const $q = useQuasar();
const auth = useAuthStore();
// Back to the row's menu button when a dialog opened from it closes (item 12).
const { remember: rememberTrigger, restore: restoreFocus } = useFocusReturn();

const rows = ref<Group[]>([]);
const loading = ref(false);
// What the last load failed with; null once one succeeds (item 2).
const loadError = ref<unknown>(null);

// What the caller holds: groups granting more are not offered for editing,
// permissions it lacks are not offered for granting (item 4). Null when it
// cannot be told — the server decides then.
const me = computed(() => callerAuthority(auth.user, rows.value));
function beyondMe(group: Group): boolean {
  return me.value !== null && exceeds(me.value, groupsAuthority([group]));
}
function cannotGrant(key: string): boolean {
  return me.value !== null && !me.value.isAdmin && !me.value.permissions.has(key);
}

/** A box ticked or unticked: what it needs follows, and what needs it goes (item 4). */
function onPermissions(next: string[]) {
  form.permissions = applyPermissionChange(form.permissions, next);
}
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
/** A deleted building or room, wherever its id is still named (C6). */
function deletedPlace(): string {
  return t('groups.deleted.place');
}

/**
 * The scope entries of the group being edited, as the server names them: an
 * entry the listings do not hold — deleted, or not readable without
 * room:read — keeps a name in its picker (and stays removable) instead of
 * showing its raw id.
 */
function editedLabels(kind: 'building' | 'room'): { label: string; value: string }[] {
  return (editing.value?.scope_labels ?? [])
    .filter((l) => l.kind === kind)
    .map((l) => ({ label: l.exists ? l.label : deletedPlace(), value: l.id }));
}

function withEdited(
  listed: { label: string; value: string }[],
  kind: 'building' | 'room',
): { label: string; value: string }[] {
  const extra = editedLabels(kind).filter((e) => !listed.some((o) => o.value === e.value));
  return [...listed, ...extra];
}

const buildingOptions = computed(() =>
  withEdited(
    buildings.value.map((b) => ({
      label: b.location ? `${b.name} (${b.location})` : b.name,
      value: b.id,
    })),
    'building',
  ),
);
const roomOptions = computed(() =>
  withEdited(
    rooms.value.map((r) => ({
      label: r.building ? `${r.name} — ${r.building.name}` : r.name,
      value: r.id,
    })),
    'room',
  ),
);

function scopeLabels(group: Group): string[] {
  if (!group.scope) return [];
  // Named by the server when it can (C6): right for an account without
  // room:read, which cannot list the rooms, and for a deleted place.
  if (group.scope_labels) {
    return group.scope_labels.map((l) => (l.exists ? l.label : deletedPlace()));
  }
  const building = new Map(buildingOptions.value.map((o) => [o.value, o.label]));
  const room = new Map(roomOptions.value.map((o) => [o.value, o.label]));
  return [
    ...group.scope.locations,
    // An id that names nothing any more matches no poste: shown as such so
    // that an administrator can tidy it, never silently dropped.
    ...group.scope.buildings.map((id) => building.get(id) ?? t('groups.deleted.building')),
    ...group.scope.rooms.map((id) => room.get(id) ?? t('groups.deleted.room')),
  ];
}

// A computed: the labels follow the language, which can change on the page.
const columns = computed<QTableColumn<Group>[]>(() => [
  { name: 'name', label: t('groups.columns.name'), field: 'name', align: 'left' },
  {
    name: 'permissions',
    label: t('groups.columns.permissions'),
    field: 'permissions',
    align: 'left',
  },
  { name: 'scope', label: t('groups.columns.scope'), field: 'scope', align: 'left' },
  {
    name: 'member_count',
    label: t('groups.columns.members'),
    field: 'member_count',
    align: 'center',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

const required = (v: string) => !!v.trim() || t('groups.form.required');

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
    // Not asked of an account the server would refuse (item 4).
    const canReadRooms = auth.can('room', 'read');
    const canReadMachines = auth.can('machine', 'read');
    const [groups, sites, bs, rs] = await Promise.all([
      listGroups(),
      canReadMachines ? listLocations().catch(() => []) : Promise.resolve([]),
      canReadRooms ? listBuildings().catch(() => []) : Promise.resolve([]),
      canReadRooms ? listRooms().catch(() => []) : Promise.resolve([]),
    ]);
    rows.value = groups;
    locations.value = sites.map((v) => v.name);
    buildings.value = bs;
    rooms.value = rs;
    loadError.value = null;
  } catch (e) {
    // A banner that stays, with « Réessayer », rather than a toast over an
    // empty table that would read as « aucun groupe » (item 2).
    loadError.value = e;
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
    liveDialog($q, () => ({
      title: t('groups.wholeFleet.title'),
      message: t('groups.wholeFleet.message'),
      cancel: { flat: true, noCaps: true, label: t('groups.wholeFleet.back') },
      ok: { unelevated: true, noCaps: true, label: t('groups.wholeFleet.confirm') },
      persistent: true,
    }))
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
      $q.notify({ type: 'positive', message: t('groups.notify.updated') });
    } else {
      await createGroup({
        name: form.name.trim(),
        description: form.description.trim() || null,
        permissions: form.permissions,
        scope: scopeOrNull(form.scope),
      });
      $q.notify({ type: 'positive', message: t('groups.notify.created') });
    }
    formOpen.value = false;
    await reload();
    // One's own rights may just have changed: the menus follow the profile.
    await auth.fetchMe();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('groups.notify.saveFailed')) });
  } finally {
    saving.value = false;
  }
}

function confirmDelete(group: Group) {
  liveDialog($q, () => ({
    title: t('groups.delete.title'),
    message:
      `${t('groups.delete.question', { name: `<b>${escapeHtml(groupName(group, rows.value))}</b>` })}<br>` +
      t('groups.delete.members', { count: group.member_count }, group.member_count),
    html: true,
    cancel: true,
    ok: { label: t('groups.delete.ok'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteGroup(group.id);
        $q.notify({ type: 'positive', message: t('groups.notify.deleted') });
        await reload();
        await auth.fetchMe();
      } catch (e) {
        $q.notify({
          type: 'negative',
          message: apiErrorMessage(e, t('groups.notify.deleteFailed')),
        });
      }
    })();
  });
}

onMounted(reload);
</script>
