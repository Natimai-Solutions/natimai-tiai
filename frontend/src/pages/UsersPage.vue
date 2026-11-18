<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-sm q-mb-md">
      <h1 class="text-h5 q-my-none col-auto">{{ t('users.page.title') }}</h1>
      <q-space />
      <q-input
        v-model="search"
        :aria-label="t('users.page.search')"
        dense
        outlined
        debounce="300"
        :placeholder="t('users.page.searchPlaceholder')"
        class="col-auto"
        style="min-width: 220px"
        @update:model-value="searchAgain"
      >
        <template #append><q-icon name="search" /></template>
      </q-input>
      <!-- In its own column: the gutter pads every direct child of the row,
           and on a bare button that padding landed inside the button, which
           sat a few pixels low and flush against the search box. -->
      <div v-if="auth.can('user', 'write')" class="col-auto">
        <q-btn
          color="primary"
          icon="person_add"
          :label="t('users.page.create')"
          @click="openCreate"
        />
      </div>
    </div>

    <!-- Persistent, unlike a toast: an empty table under a search that could
         not be run would read as « aucun compte » (item 2). -->
    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="reload" />

    <q-table
      v-model:pagination="pagination"
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      :no-data-label="loadError ? t('users.page.notLoaded') : t('users.page.empty')"
      class="users-table"
      @request="onRequest"
    >
      <template #body-cell-groups="props">
        <q-td :props="props">
          <template v-if="props.row.groups.length">
            <q-chip
              v-for="group in props.row.groups"
              :key="group.id"
              dense
              size="sm"
              color="primary"
              text-color="white"
              class="q-ml-none"
            >
              {{ groupName(group) }}
            </q-chip>
          </template>
          <span v-else class="text-muted">{{ t('users.row.noGroup') }}</span>
        </q-td>
      </template>

      <template #body-cell-is_active="props">
        <q-td :props="props">
          <q-badge :color="props.value ? 'positive' : 'negative'">
            {{ props.value ? t('users.row.active') : t('users.row.disabled') }}
          </q-badge>
          <!-- A lock lifts by itself; until then the way out is a password
               reset, from the menu of the row. -->
          <q-badge v-if="isLocked(props.row)" color="warning" class="q-ml-xs">
            {{ t('users.row.locked') }}
            <q-tooltip>
              {{ t('users.row.lockedTooltip', { until: formatDateTime(props.row.locked_until) }) }}
            </q-tooltip>
          </q-badge>
        </q-td>
      </template>

      <template #body-cell-email_preference="props">
        <q-td :props="props">
          <span :class="props.value === 'none' ? 'text-muted' : ''">
            {{ emailPreferenceLabel(props.value) }}
          </span>
        </q-td>
      </template>

      <template #body-cell-created_at="props">
        <q-td :props="props">{{ formatDateTime(props.value) }}</q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="text-right">
          <q-btn
            v-if="auth.can('user', 'write')"
            flat
            dense
            round
            icon="more_vert"
            :aria-label="t('users.row.actionsFor', { email: props.row.email })"
            @click="rememberTrigger"
          >
            <q-menu>
              <q-list style="min-width: 220px">
                <!-- An account holding more rights than the caller: the server
                     refuses every action on it, so none is offered (item 4). -->
                <q-item v-if="beyondMe(props.row)" dense class="text-caption text-muted">
                  <q-item-section avatar><q-icon name="lock" size="xs" /></q-item-section>
                  <q-item-section>{{ moreRightsAccount() }}</q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  :disable="beyondMe(props.row)"
                  @click="openEdit(props.row)"
                >
                  <q-item-section avatar><q-icon name="edit" /></q-item-section>
                  <q-item-section>{{ t('users.row.edit') }}</q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  :disable="beyondMe(props.row)"
                  @click="openReset(props.row)"
                >
                  <q-item-section avatar><q-icon name="lock_reset" /></q-item-section>
                  <q-item-section>{{ t('users.row.resetPassword') }}</q-item-section>
                </q-item>

                <q-separator />

                <!-- Self-protection: the backend refuses these on one's own
                     account, so they are hidden rather than shown failing. -->
                <q-item
                  v-close-popup
                  clickable
                  :disable="isSelf(props.row) || beyondMe(props.row)"
                  @click="toggleActive(props.row)"
                >
                  <q-item-section avatar>
                    <q-icon :name="props.row.is_active ? 'block' : 'check_circle'" />
                  </q-item-section>
                  <q-item-section>
                    {{
                      props.row.is_active ? t('users.row.deactivate') : t('users.row.reactivate')
                    }}
                  </q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  class="text-negative"
                  :disable="isSelf(props.row) || beyondMe(props.row)"
                  @click="confirmDelete(props.row)"
                >
                  <q-item-section avatar><q-icon name="delete" /></q-item-section>
                  <q-item-section>{{ t('users.row.delete') }}</q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Création / modification : même formulaire, le mot de passe n'apparaît
         qu'à la création (ensuite c'est la réinitialisation qui s'en charge). -->
    <q-dialog v-model="formOpen" @hide="restoreFocus">
      <q-card style="width: 420px; max-width: 90vw">
        <q-card-section class="text-h6">
          {{ editing ? t('users.form.editTitle') : t('users.form.createTitle') }}
        </q-card-section>

        <q-form @submit="submitForm">
          <q-card-section class="q-gutter-md">
            <q-input
              v-model="form.email"
              type="email"
              :label="t('users.form.email')"
              autocomplete="off"
              outlined
              dense
              autofocus
              :rules="[required]"
            />
            <q-input v-model="form.full_name" :label="t('users.form.fullName')" outlined dense />
            <!-- Memberships, not a role: what the account may do is the union
                 of its groups' grants (page « Groupes »). One's own groups are
                 not editable — the backend refuses it — so the field is locked
                 rather than shown failing. -->
            <q-select
              v-model="form.group_ids"
              :options="grantableGroupOptions"
              emit-value
              map-options
              multiple
              use-chips
              :label="t('users.form.groups')"
              outlined
              dense
              :disable="editing !== null && isSelf(editing)"
              :hint="
                editing !== null && isSelf(editing)
                  ? t('users.form.ownGroupsHint')
                  : grantableGroupOptions.some((o) => o.disable)
                    ? t('users.form.greyedHint')
                    : t('users.form.noGroupHint')
              "
            />
            <!-- Only when editing: a new account starts on the default cadence
                 (résumé quotidien), and its holder changes it from « Mon
                 compte ». Here it is the lever for the opposite case — an
                 account left on « aucun e-mail » on a parc nobody is watching. -->
            <q-select
              v-if="editing"
              v-model="form.email_preference"
              :options="preferenceOptions"
              emit-value
              map-options
              :label="t('users.form.emailPreference')"
              outlined
              dense
            />
            <q-input
              v-if="!editing"
              v-model="form.password"
              type="password"
              autocomplete="new-password"
              :label="t('users.form.password')"
              outlined
              dense
              :hint="t('users.form.minLength', { count: passwordMin })"
              :rules="[required, longEnough]"
            />
          </q-card-section>

          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup flat :label="t('users.form.cancel')" />
            <q-btn type="submit" color="primary" :label="t('users.form.save')" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <!-- Réinitialisation : mot de passe généré ou choisi, affiché une seule fois. -->
    <!-- Persistent once the password is shown: it is applied already and
         shown only here, so only « Fermer » may take it away (audit U13).
         Persistent while the request is in flight too: the server may have
         applied a generated password that nobody would ever see. -->
    <q-dialog
      v-model="resetOpen"
      :persistent="resetting || resetResult !== null"
      @hide="onResetHide"
    >
      <q-card style="width: 460px; max-width: 90vw">
        <q-card-section class="text-h6">{{ t('users.reset.title') }}</q-card-section>
        <q-card-section class="q-pt-none text-body2 text-muted">
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
                autocomplete="new-password"
                :label="t('users.reset.newPassword')"
                outlined
                dense
                :hint="t('users.form.minLength', { count: passwordMin })"
                :rules="[required, longEnough]"
              />
              <q-banner dense class="surface-orange">
                <template #avatar><q-icon name="warning" /></template>
                {{ t('users.reset.sessionsClosed') }}
              </q-banner>
            </q-card-section>

            <q-card-actions align="right" class="q-px-md q-pb-md">
              <q-btn v-close-popup flat :label="t('users.reset.cancel')" :disable="resetting" />
              <q-btn
                type="submit"
                color="primary"
                :label="t('users.reset.submit')"
                :loading="resetting"
              />
            </q-card-actions>
          </q-form>
        </template>

        <template v-else>
          <q-card-section class="q-gutter-sm">
            <div class="text-body2">
              {{ t('users.reset.done') }}
            </div>
            <q-input
              :aria-label="t('users.reset.result')"
              :model-value="resetResult"
              readonly
              outlined
              dense
              class="text-weight-medium"
            >
              <template #append>
                <q-btn
                  flat
                  dense
                  round
                  icon="content_copy"
                  :aria-label="t('users.reset.copy')"
                  @click="copyResult"
                />
              </template>
            </q-input>
          </q-card-section>
          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup color="primary" flat :label="t('users.reset.close')" />
          </q-card-actions>
        </template>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { groupName } from 'src/utils/groupText';
import { usePasswordPolicy } from 'src/composables/usePasswordPolicy';
import { t } from 'src/i18n';
import { escapeHtml } from 'src/utils/html';
import { computed, onMounted, reactive, ref } from 'vue';
import { useFocusReturn } from 'src/composables/useFocusReturn';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { copyToClipboard, useQuasar, type QTableColumn } from 'quasar';
import {
  createUser,
  deleteUser,
  listUsers,
  resetUserPassword,
  updateUser,
  type ConsoleUser,
} from 'src/services/users';
import { listGroups, type Group } from 'src/services/groups';
import {
  callerAuthority,
  exceeds,
  groupsAuthority,
  groupsByIds,
  moreRightsAccount,
} from 'src/utils/authority';
import { apiErrorMessage } from 'src/services/errors';
import type { EmailPreference } from 'src/services/auth';
import { useAuthStore } from 'src/stores/auth';
import { EMAIL_PREFERENCE_OPTIONS, emailPreferenceLabel, formatDateTime } from 'src/utils/format';

const { passwordMin } = usePasswordPolicy();

/** Locked now — `locked_until` stays set after it has passed, until the next login. */
function isLocked(user: ConsoleUser): boolean {
  return !!user.locked_until && Date.parse(user.locked_until) > Date.now();
}

const $q = useQuasar();
const auth = useAuthStore();
// Back to the row's menu button when a dialog opened from it closes (item 12).
const { remember: rememberTrigger, restore: restoreFocus } = useFocusReturn();

const rows = ref<ConsoleUser[]>([]);
const loading = ref(false);
// What the last load failed with; null once one succeeds.
const loadError = ref<unknown>(null);
const saving = ref(false);
const search = ref('');

// Server-side pagination: `rowsNumber` is what makes the q-table ask the server
// for each page instead of slicing whatever it was handed first.
const DEFAULT_PAGE_SIZE = 25;
const pagination = ref({ page: 1, rowsPerPage: DEFAULT_PAGE_SIZE, rowsNumber: 0 });

const formOpen = ref(false);
const editing = ref<ConsoleUser | null>(null);
const form = reactive({
  email: '',
  full_name: '',
  group_ids: [] as string[],
  password: '',
  email_preference: 'digest_daily' as EmailPreference,
});

// Loaded once with the page: the list is short and changes on another page.
const groups = ref<Group[]>([]);
async function loadGroups() {
  try {
    groups.value = await listGroups();
  } catch (e) {
    $q.notify({
      type: 'negative',
      message: apiErrorMessage(e, t('users.notify.groupsUnavailable')),
    });
  }
}

// What the caller holds, from its profile and its groups: what the server
// would refuse is not offered (item 4). Null when it cannot be told.
const me = computed(() => callerAuthority(auth.user, groups.value));

/** Whether acting on `user` reaches rights the caller does not hold. */
function beyondMe(user: ConsoleUser): boolean {
  if (!me.value || isSelf(user)) return false;
  const theirs = groupsByIds(
    user.groups.map((g) => g.id),
    groups.value,
  );
  return theirs !== null && exceeds(me.value, groupsAuthority(theirs));
}

// The groups the caller may hand out; the others are shown greyed, so the
// form says why they cannot be picked rather than failing on « Enregistrer ».
const grantableGroupOptions = computed(() =>
  groups.value.map((g) => ({
    label: groupName(g),
    value: g.id,
    disable: me.value !== null && exceeds(me.value, groupsAuthority([g])),
  })),
);

// Label + value only: the explanatory sentences belong on « Mon compte », where
// someone is choosing for themselves. Here an admin is reading a list.
const preferenceOptions = computed(() =>
  EMAIL_PREFERENCE_OPTIONS.map((o) => ({
    label: emailPreferenceLabel(o.value),
    value: o.value,
  })),
);

const resetOpen = ref(false);
function onResetHide() {
  resetResult.value = null;
  restoreFocus();
}
const resetTarget = ref<ConsoleUser | null>(null);
const resetMode = ref<'generate' | 'manual'>('generate');
const resetPassword = ref('');
const resetResult = ref<string | null>(null);
// Its own flag, not the user form's `saving`: it also holds the dialog open.
const resetting = ref(false);

const resetModes = computed(() => [
  { label: t('users.reset.generate'), value: 'generate' },
  { label: t('users.reset.manual'), value: 'manual' },
]);

// A computed: the labels follow the language, which can change on the page.
const columns = computed<QTableColumn<ConsoleUser>[]>(() => [
  { name: 'email', label: t('users.columns.email'), field: 'email', align: 'left' },
  { name: 'full_name', label: t('users.columns.name'), field: 'full_name', align: 'left' },
  { name: 'groups', label: t('users.columns.groups'), field: 'groups', align: 'left' },
  { name: 'is_active', label: t('users.columns.state'), field: 'is_active', align: 'center' },
  // Not sortable, like the columns above: the rows are a server page now, and
  // a client-side sort would only reorder the page in view.
  {
    name: 'email_preference',
    label: t('users.columns.emails'),
    field: 'email_preference',
    align: 'left',
  },
  { name: 'created_at', label: t('users.columns.createdAt'), field: 'created_at', align: 'left' },
  // Sticky on the right: on a phone the table scrolls sideways, and the menu
  // of each row was six columns away, out of reach (item 12).
  {
    name: 'actions',
    label: '',
    field: 'id',
    align: 'right',
    classes: 'users-actions-cell',
    headerClasses: 'users-actions-cell',
  },
]);

const required = (v: string) => !!v || t('users.form.required');
const longEnough = (v: string) =>
  v.length >= passwordMin.value || t('users.form.minLength', { count: passwordMin.value });

function isSelf(user: ConsoleUser) {
  return user.id === auth.user?.id;
}

// Which fetch is the current one: a debounced search and a page turn can be in
// flight together, and the slower answer must not paint its rows over the newer
// question — nor write its own page number back over the current one.
let requestId = 0;

async function reload() {
  loading.value = true;
  const id = ++requestId;
  try {
    const p = pagination.value;
    const params: Parameters<typeof listUsers>[0] = {
      page: p.page,
      page_size: p.rowsPerPage,
    };
    if (search.value) params.search = search.value;
    const data = await listUsers(params);
    if (id !== requestId) return;
    if (!data.items.length && data.total > 0 && p.page > 1) {
      // The last account of the last page went (a deletion): fall back on
      // the last page that still exists, as the journal does (audit B26).
      pagination.value = {
        ...pagination.value,
        page: Math.ceil(data.total / p.rowsPerPage),
        rowsNumber: data.total,
      };
      void reload();
      return;
    }
    rows.value = data.items;
    pagination.value = { ...pagination.value, rowsNumber: data.total };
    loadError.value = null;
  } catch (e) {
    if (id !== requestId) return;
    // The rows of the previous search go: left under the new text, they would
    // read as its results (item 2). The banner says why the table is empty.
    rows.value = [];
    pagination.value = { ...pagination.value, rowsNumber: 0 };
    loadError.value = e;
  } finally {
    // Only the current fetch may clear the spinner: a superseded one finishing
    // first would take it down while the newer request is still running.
    if (id === requestId) loading.value = false;
  }
}

/** A new search starts at its first page, not at the page of the previous one. */
function searchAgain() {
  pagination.value = { ...pagination.value, page: 1 };
  void reload();
}

/** Page turns and page-size changes go back to the server. */
function onRequest(evt: { pagination: { page?: number; rowsPerPage?: number } }) {
  pagination.value = {
    ...pagination.value,
    page: evt.pagination.page ?? 1,
    rowsPerPage: evt.pagination.rowsPerPage ?? DEFAULT_PAGE_SIZE,
  };
  void reload();
}

function openCreate() {
  editing.value = null;
  Object.assign(form, {
    email: '',
    full_name: '',
    group_ids: [],
    password: '',
    email_preference: 'digest_daily',
  });
  formOpen.value = true;
}

function openEdit(user: ConsoleUser) {
  editing.value = user;
  Object.assign(form, {
    email: user.email,
    full_name: user.full_name ?? '',
    group_ids: user.groups.map((g) => g.id),
    password: '',
    email_preference: user.email_preference,
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
        // Left out on one's own account: the backend refuses it, and the
        // field was locked for that reason.
        ...(isSelf(editing.value) ? {} : { group_ids: form.group_ids }),
        email_preference: form.email_preference,
      });
      $q.notify({ type: 'positive', message: t('users.notify.updated') });
    } else {
      await createUser({
        email: form.email,
        password: form.password,
        full_name: form.full_name || null,
        group_ids: form.group_ids,
      });
      $q.notify({ type: 'positive', message: t('users.notify.created') });
    }
    formOpen.value = false;
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('users.notify.saveFailed')) });
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
  if (!resetTarget.value || resetting.value) return;
  resetting.value = true;
  try {
    const password = await resetUserPassword(
      resetTarget.value.id,
      resetMode.value === 'manual' ? resetPassword.value : undefined,
    );
    // Shown whatever happened to the dialog meanwhile: the server has applied
    // it, and this is the only place it can be read (audit U13).
    resetResult.value = password;
    // A reset lifts the lock: the row says so now, not at the next reload (item 13).
    const targetId = resetTarget.value?.id;
    rows.value = rows.value.map((u) => (u.id === targetId ? { ...u, locked_until: null } : u));
    resetOpen.value = true;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('users.notify.resetFailed')) });
  } finally {
    resetting.value = false;
  }
}

async function copyResult() {
  if (!resetResult.value) return;
  try {
    await copyToClipboard(resetResult.value);
    $q.notify({ type: 'positive', message: t('users.notify.copied') });
  } catch {
    $q.notify({
      type: 'negative',
      message: t('users.notify.copyFailed'),
    });
  }
}

async function toggleActive(user: ConsoleUser) {
  try {
    await updateUser(user.id, { is_active: !user.is_active });
    $q.notify(
      user.is_active
        ? {
            type: 'positive',
            message: t('users.notify.deactivated'),
            // What a deactivated owner leaves behind is nobody's until it comes back.
            caption: t('users.notify.deactivatedCaption'),
          }
        : { type: 'positive', message: t('users.notify.reactivated') },
    );
    await reload();
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('users.notify.editFailed')) });
  }
}

function confirmDelete(user: ConsoleUser) {
  $q.dialog({
    title: t('users.delete.title'),
    message:
      `${t('users.delete.question', { email: `<b>${escapeHtml(user.email)}</b>` })}<br>` +
      t('users.delete.advice'),
    html: true,
    cancel: true,
    ok: { label: t('users.delete.ok'), color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        await deleteUser(user.id);
        $q.notify({ type: 'positive', message: t('users.notify.deleted') });
        await reload();
      } catch (e) {
        $q.notify({
          type: 'negative',
          message: apiErrorMessage(e, t('users.notify.deleteFailed')),
        });
      }
    })();
  });
}

onMounted(() => {
  void reload();
  void loadGroups();
});
</script>

<style scoped>
.users-table :deep(.users-actions-cell) {
  position: sticky;
  right: 0;
  z-index: 1;
  background: var(--q-users-sticky-bg, #fff);
}
.body--dark .users-table {
  --q-users-sticky-bg: var(--q-dark);
}
</style>
