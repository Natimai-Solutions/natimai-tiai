<template>
  <q-layout view="hHh lpR fFf">
    <!-- First stop of the Tab key: past the toolbar and the drawer's ten links. -->
    <a class="skip-link" href="#main-content" @click.prevent="skipToContent">Aller au contenu</a>
    <q-header elevated>
      <q-toolbar>
        <q-btn flat dense round icon="menu" aria-label="Menu" @click="drawer = !drawer" />
        <q-toolbar-title>
          <q-icon name="shield" class="q-mr-sm" />
          Tia'i — Console
        </q-toolbar-title>
        <!-- Not on a phone: it pushed the title down to « Tia'i … » (U29). -->
        <div v-if="auth.user" class="text-caption q-mr-sm gt-xs">{{ auth.user.email }}</div>
        <q-btn
          flat
          dense
          round
          icon="account_circle"
          aria-label="Mon compte"
          :to="{ name: 'account' }"
        />
        <q-btn
          flat
          dense
          round
          icon="logout"
          aria-label="Déconnexion"
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
          <q-item-section>Tableau de bord</q-item-section>
        </q-item>
        <q-item v-if="canReadMachines" v-ripple clickable :to="{ name: 'machines' }">
          <q-item-section avatar><q-icon name="devices" /></q-item-section>
          <q-item-section>Postes</q-item-section>
        </q-item>
        <q-item v-if="canReadMachines" v-ripple clickable :to="{ name: 'software' }">
          <q-item-section avatar><q-icon name="inventory_2" /></q-item-section>
          <q-item-section>Logiciels</q-item-section>
        </q-item>
        <q-item v-if="auth.can('package', 'read')" v-ripple clickable :to="{ name: 'packages' }">
          <q-item-section avatar><q-icon name="install_desktop" /></q-item-section>
          <q-item-section>Paquets</q-item-section>
        </q-item>
        <q-item
          v-if="auth.can('check', 'read') || auth.can('maintenance', 'read')"
          v-ripple
          clickable
          :to="{ name: 'tasks' }"
        >
          <q-item-section avatar><q-icon name="task_alt" /></q-item-section>
          <q-item-section>Mes tâches</q-item-section>
          <!-- Two counts, two colours: the checks given to me, and the postes of
               mine overdue for maintenance (audit U19). -->
          <q-item-section v-if="myTasks || myOverdue" side>
            <div class="row no-wrap q-gutter-xs">
              <q-badge v-if="myTasks" color="primary" :label="myTasks">
                <q-tooltip>Vérifications qui vous sont affectées</q-tooltip>
              </q-badge>
              <q-badge v-if="myOverdue" color="negative" :label="myOverdue">
                <q-tooltip>Postes en retard de maintenance dont vous êtes responsable</q-tooltip>
              </q-badge>
            </div>
          </q-item-section>
        </q-item>
        <q-item v-if="auth.can('room', 'read')" v-ripple clickable :to="{ name: 'rooms' }">
          <q-item-section avatar><q-icon name="meeting_room" /></q-item-section>
          <q-item-section>Salles</q-item-section>
        </q-item>
        <q-item v-if="auth.canManageUsers" v-ripple clickable :to="{ name: 'users' }">
          <q-item-section avatar><q-icon name="person" /></q-item-section>
          <q-item-section>Utilisateurs</q-item-section>
        </q-item>
        <q-item v-if="auth.canManageUsers" v-ripple clickable :to="{ name: 'groups' }">
          <q-item-section avatar><q-icon name="group" /></q-item-section>
          <q-item-section>Groupes</q-item-section>
        </q-item>
        <q-item v-if="auth.can('settings', 'read')" v-ripple clickable :to="{ name: 'settings' }">
          <q-item-section avatar><q-icon name="settings" /></q-item-section>
          <q-item-section>Paramètres</q-item-section>
        </q-item>
        <q-item v-if="auth.can('audit', 'read')" v-ripple clickable :to="{ name: 'audit' }">
          <q-item-section avatar><q-icon name="history_edu" /></q-item-section>
          <q-item-section>Journal d'audit</q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <!-- The profile could not be read: the menus and the pages' buttons
           depend on it, and a console silently missing half of them would
           read as an account without rights. -->
      <div v-if="auth.profileError && !auth.user" class="q-pa-md q-pb-none">
        <LoadErrorBanner
          :error="auth.profileError"
          :loading="profileLoading"
          fallback="Impossible de charger votre profil : les menus et les actions sont incomplets."
          @retry="retryProfile"
        />
      </div>
      <main id="main-content" ref="mainEl" tabindex="-1" class="main-content">
        <router-view />
      </main>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { canOpen, firstReadablePage } from 'src/router/access';
import { PROFILE_REFRESH_MS, useAuthStore } from 'src/stores/auth';
import { listChecks } from 'src/services/checks';
import { getDue } from 'src/services/maintenance';
import { tasksVersion } from 'src/composables/useTasksBadge';

const drawer = ref(false);
const auth = useAuthStore();
const router = useRouter();

// The badge on « Mes tâches »: how many verifications are assigned to me.
// Read once the profile is known, and again on each navigation — cheap (one
// count) and enough for a number that changes a few times a day.
const myTasks = ref(0);
const myOverdue = ref(0);
async function countMyTasks() {
  if (!auth.can('check', 'read')) return;
  try {
    const [checks, due] = await Promise.all([
      listChecks({ open: true, assigned_to: 'me', page_size: 1 }),
      auth.can('maintenance', 'read') ? getDue('me') : Promise.resolve(null),
    ]);
    myTasks.value = checks.total;
    myOverdue.value = due?.overdue ?? 0;
  } catch {
    // The badge is a hint; the page says the truth.
  }
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
let profileTimer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  // Restore the user profile after a page reload: the router's silent refresh
  // has put an access token back, the profile is still to fetch. A failure is
  // shown by the banner above, not left as an unhandled rejection.
  if (auth.isAuthenticated && !auth.user) void retryProfile();
  profileTimer = setInterval(() => void auth.refreshProfile(), PROFILE_REFRESH_MS);
});
onUnmounted(() => {
  if (profileTimer !== null) clearInterval(profileTimer);
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
watch(
  () => auth.user?.id,
  () => void countMyTasks(),
  { immediate: true },
);
watch(
  () => router.currentRoute.value.fullPath,
  () => void countMyTasks(),
);
// A check closed or a visit recorded where the route does not change.
watch(tasksVersion, () => void countMyTasks());

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
