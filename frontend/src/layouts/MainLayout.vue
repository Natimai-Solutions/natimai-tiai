<template>
  <q-layout view="hHh lpR fFf">
    <!-- First stop of the Tab key: past the toolbar and the drawer's ten links. -->
    <a class="skip-link" href="#main-content" @click.prevent="skipToContent">{{
      t('layout.shell.skipToContent')
    }}</a>
    <q-header elevated>
      <q-toolbar>
        <q-btn
          flat
          dense
          round
          icon="menu"
          :aria-label="t('layout.shell.menu')"
          @click="drawer = !drawer"
        />
        <q-toolbar-title>
          <q-icon name="shield" class="q-mr-sm" />
          Tia'i — Console
        </q-toolbar-title>
        <!-- Not on a phone: it pushed the title down to « Tia'i … » (U29). On a
             tablet a long address is cut short, whole in its tooltip: the
             title keeps its room. -->
        <div
          v-if="auth.user"
          class="text-caption q-mr-sm gt-xs ellipsis"
          style="max-width: 40vw"
          :title="auth.user.email"
          data-test="header-email"
        >
          {{ auth.user.email }}
        </div>
        <q-btn
          flat
          dense
          round
          icon="account_circle"
          :aria-label="t('layout.shell.account')"
          :to="{ name: 'account' }"
        />
        <q-btn
          flat
          dense
          round
          icon="logout"
          :aria-label="t('layout.shell.logout')"
          :loading="loggingOut"
          @click="onLogout"
        />
      </q-toolbar>
    </q-header>

    <q-drawer v-model="drawer" show-if-above bordered>
      <q-list>
        <!-- The three pages of the parc need machine:read: an account without it
             would only open 403s there (it lands on its first readable page). -->
        <q-item v-if="canReadMachines" v-ripple clickable exact :to="{ name: 'dashboard' }">
          <q-item-section avatar><q-icon name="dashboard" /></q-item-section>
          <q-item-section>{{ t('layout.pages.dashboard') }}</q-item-section>
        </q-item>
        <q-item v-if="canReadMachines" v-ripple clickable :to="{ name: 'machines' }">
          <q-item-section avatar><q-icon name="devices" /></q-item-section>
          <q-item-section>{{ t('layout.pages.machines') }}</q-item-section>
        </q-item>
        <q-item v-if="canReadMachines" v-ripple clickable :to="{ name: 'alerts' }">
          <q-item-section avatar><q-icon name="notifications_active" /></q-item-section>
          <q-item-section>{{ t('layout.pages.alerts') }}</q-item-section>
        </q-item>
        <q-item v-if="auth.can('asset', 'read')" v-ripple clickable :to="{ name: 'assets' }">
          <q-item-section avatar><q-icon name="devices_other" /></q-item-section>
          <q-item-section>{{ t('layout.pages.assets') }}</q-item-section>
        </q-item>
        <q-item v-if="canReadMachines" v-ripple clickable :to="{ name: 'software' }">
          <q-item-section avatar><q-icon name="inventory_2" /></q-item-section>
          <q-item-section>{{ t('layout.pages.software') }}</q-item-section>
        </q-item>
        <q-item v-if="auth.can('package', 'read')" v-ripple clickable :to="{ name: 'packages' }">
          <q-item-section avatar><q-icon name="install_desktop" /></q-item-section>
          <q-item-section>{{ t('layout.pages.packages') }}</q-item-section>
        </q-item>
        <q-item
          v-if="auth.can('check', 'read') || auth.can('maintenance', 'read')"
          v-ripple
          clickable
          :to="{ name: 'tasks' }"
        >
          <q-item-section avatar><q-icon name="task_alt" /></q-item-section>
          <q-item-section>{{ t('layout.pages.tasks') }}</q-item-section>
          <!-- Two counts, two colours: the checks given to me, and the postes of
               mine overdue for maintenance (audit U19). -->
          <q-item-section v-if="myTasks || myOverdue" side>
            <div class="row no-wrap q-gutter-xs">
              <q-badge v-if="myTasks" color="primary" :label="myTasks">
                <q-tooltip>{{ t('layout.shell.myChecks') }}</q-tooltip>
              </q-badge>
              <q-badge v-if="myOverdue" color="negative" :label="myOverdue">
                <q-tooltip>{{ t('layout.shell.myOverdue') }}</q-tooltip>
              </q-badge>
            </div>
          </q-item-section>
        </q-item>
        <q-item v-if="auth.can('report', 'read')" v-ripple clickable :to="{ name: 'reports' }">
          <q-item-section avatar><q-icon name="campaign" /></q-item-section>
          <q-item-section>{{ t('layout.pages.reports') }}</q-item-section>
          <q-item-section v-if="newReports" side>
            <q-badge color="orange-8" :label="newReports" />
          </q-item-section>
        </q-item>
        <q-item v-if="auth.can('schedule', 'read')" v-ripple clickable :to="{ name: 'schedules' }">
          <q-item-section avatar><q-icon name="event_repeat" /></q-item-section>
          <q-item-section>{{ t('layout.pages.schedules') }}</q-item-section>
        </q-item>
        <q-item v-if="auth.can('room', 'read')" v-ripple clickable :to="{ name: 'rooms' }">
          <q-item-section avatar><q-icon name="meeting_room" /></q-item-section>
          <q-item-section>{{ t('layout.pages.rooms') }}</q-item-section>
        </q-item>
        <q-item v-if="auth.canManageUsers" v-ripple clickable :to="{ name: 'users' }">
          <q-item-section avatar><q-icon name="person" /></q-item-section>
          <q-item-section>{{ t('layout.pages.users') }}</q-item-section>
        </q-item>
        <q-item v-if="auth.canManageUsers" v-ripple clickable :to="{ name: 'groups' }">
          <q-item-section avatar><q-icon name="group" /></q-item-section>
          <q-item-section>{{ t('layout.pages.groups') }}</q-item-section>
        </q-item>
        <q-item v-if="auth.can('settings', 'read')" v-ripple clickable :to="{ name: 'settings' }">
          <q-item-section avatar><q-icon name="settings" /></q-item-section>
          <q-item-section>{{ t('layout.pages.settings') }}</q-item-section>
        </q-item>
        <q-item v-if="auth.can('audit', 'read')" v-ripple clickable :to="{ name: 'audit' }">
          <q-item-section avatar><q-icon name="history_edu" /></q-item-section>
          <q-item-section>{{ t('layout.pages.audit') }}</q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <!-- The profile could not be read: the menus and the pages' buttons
           depend on it, and a console silently missing half of them would
           read as an account without rights. -->
      <div v-if="auth.profileError && !auth.user" class="q-pa-md q-pb-none">
        <!-- The sentence is ours whatever failed: handed over as the text to
             show, not as the fallback of an error that has words of its own. -->
        <LoadErrorBanner
          :error="null"
          :loading="profileLoading"
          :fallback="profileErrorMessage"
          @retry="retryProfile"
        />
      </div>
      <!-- Where « Aller au contenu » lands. Not a `main` itself: every page is
           a `q-page`, which renders the landmark — one per page, not two. -->
      <div id="main-content" ref="mainEl" tabindex="-1" class="main-content">
        <router-view />
      </div>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { t } from 'src/i18n';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { canOpen, firstReadablePage } from 'src/router/access';
import { PROFILE_REFRESH_MS, useAuthStore } from 'src/stores/auth';
import { listChecks } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';
import { getDue } from 'src/services/maintenance';
import { useAutoRefresh } from 'src/composables/useAutoRefresh';
import { tasksVersion } from 'src/composables/useTasksBadge';
import { reportsVersion } from 'src/composables/useReportsBadge';
import { listReports } from 'src/services/reports';

const drawer = ref(false);
const auth = useAuthStore();
const router = useRouter();

// The badges on « Mes tâches »: how many verifications are assigned to me, and
// how many postes of mine are overdue for maintenance. Read once the profile
// is known, and again on each navigation — cheap (two counts) and enough for
// numbers that change a few times a day.
//
// Each count under its own permission, and on its own: the entry is offered
// to an account that only follows maintenance, which has no right to the list
// of checks — and one count that fails says nothing about the other.
const myTasks = ref(0);
const myOverdue = ref(0);
function isForbidden(e: unknown): boolean {
  return (e as { response?: { status?: number } } | null)?.response?.status === 403;
}
async function countMyChecks() {
  // A right withdrawn during the session takes its count with it.
  if (!auth.can('check', 'read')) {
    myTasks.value = 0;
    return;
  }
  try {
    myTasks.value = (await listChecks({ open: true, assigned_to: 'me', page_size: 1 })).total;
  } catch (e) {
    // The badge is a hint; the page says the truth. A 403 is the right
    // withdrawn before the profile says so: the count goes with it.
    if (isForbidden(e)) myTasks.value = 0;
  }
}
async function countMyOverdue() {
  if (!auth.can('maintenance', 'read')) {
    myOverdue.value = 0;
    return;
  }
  try {
    myOverdue.value = (await getDue('me')).overdue;
  } catch (e) {
    // As above.
    if (isForbidden(e)) myOverdue.value = 0;
  }
}
// C4: the reports still to sort, within the reader's scope.
const newReports = ref(0);
async function countReports() {
  if (!auth.can('report', 'read')) {
    newReports.value = 0;
    return;
  }
  try {
    newReports.value = (await listReports({ state: 'new', page_size: 1 })).new;
  } catch (e) {
    if (isForbidden(e)) newReports.value = 0;
  }
}
async function countMyTasks() {
  await Promise.all([countMyChecks(), countMyOverdue(), countReports()]);
}

const canReadMachines = computed(() => auth.can('machine', 'read'));

// The profile, read again on a retry, every few minutes and after a 403
// (`stores/auth`): rights an administrator changed reach the menus without F5.
const profileLoading = ref(false);
async function retryProfile() {
  profileLoading.value = true;
  try {
    await auth.fetchMe();
  } catch {
    // The banner stays, with the new error.
  } finally {
    profileLoading.value = false;
  }
}

// What the banner says: always that the profile is what is missing — the
// reader sees an empty menu, and « Erreur interne du serveur » alone does not
// tell them why — then what the server answered, when it answered.
const profileErrorMessage = computed(() => {
  const reason = apiErrorMessage(auth.profileError, '');
  return reason ? t('layout.shell.profileErrorReason', { reason }) : t('layout.shell.profileError');
});

// The periodic read goes through `useAutoRefresh` for what it does beyond a
// timer: nothing while the tab is hidden, one catch-up when it is shown again.
// A bare interval here asked `/auth/me` from every forgotten background tab,
// and each of those calls renews the access token when it has expired — which
// slides the session: it then lived to its absolute limit (`SESSION_MAX_DAYS`)
// instead of closing after `REFRESH_TOKEN_EXPIRE_DAYS` without use. A tab
// nobody looks at sends nothing at all.
useAutoRefresh(() => auth.refreshProfile(), { intervalMs: PROFILE_REFRESH_MS });

onMounted(() => {
  // Restore the user profile after a page reload: the router's silent refresh
  // has put an access token back, the profile is still to fetch. A failure is
  // shown by the banner above, not left as an unhandled rejection.
  if (auth.isAuthenticated && !auth.user) void retryProfile();
});

// Rights withdrawn while a page is open: leave it for the first page still
// readable, rather than stay on one that now answers 403 to everything.
watch(
  () => auth.user?.permissions,
  (permissions) => {
    if (!permissions) return;
    const current = router.currentRoute.value;
    if (!canOpen(permissions, current.meta.requiresPermission)) {
      void router.replace({ name: firstReadablePage(permissions) });
    }
  },
);

// « Aller au contenu »: focus moves into the page, as the link promises.
const mainEl = ref<HTMLElement | null>(null);
function skipToContent() {
  mainEl.value?.focus();
}
// The account, and its two rights: one withdrawn or given during the session
// (the profile read again) recounts at once, not at the next navigation.
watch(
  [
    () => auth.user?.id,
    () => auth.can('check', 'read'),
    () => auth.can('maintenance', 'read'),
    () => auth.can('report', 'read'),
  ],
  () => void countMyTasks(),
  { immediate: true },
);
watch(
  () => router.currentRoute.value.fullPath,
  () => void countMyTasks(),
);
// A check closed or a visit recorded where the route does not change.
watch(tasksVersion, () => void countMyTasks());
watch(reportsVersion, () => void countReports());

// Logging out is a server call — the session is revoked there, not just
// forgotten here — so the button waits for it rather than racing the router.
const loggingOut = ref(false);
async function onLogout() {
  loggingOut.value = true;
  try {
    await auth.logout();
  } finally {
    loggingOut.value = false;
  }
  await router.push({ name: 'login' });
}
</script>
