<template>
  <q-layout view="hHh lpR fFf">
    <q-header elevated>
      <q-toolbar>
        <q-btn flat dense round icon="menu" aria-label="Menu" @click="drawer = !drawer" />
        <q-toolbar-title>
          <q-icon name="shield" class="q-mr-sm" />
          Tia'i — Console
        </q-toolbar-title>
        <div v-if="auth.user" class="text-caption q-mr-sm">{{ auth.user.email }}</div>
        <q-btn
          flat
          dense
          round
          icon="account_circle"
          aria-label="Mon compte"
          :to="{ name: 'account' }"
        />
        <q-btn flat dense round icon="logout" aria-label="Déconnexion" @click="onLogout" />
      </q-toolbar>
    </q-header>

    <q-drawer v-model="drawer" show-if-above bordered>
      <q-list>
        <q-item v-ripple clickable exact :to="{ name: 'dashboard' }">
          <q-item-section avatar><q-icon name="dashboard" /></q-item-section>
          <q-item-section>Tableau de bord</q-item-section>
        </q-item>
        <q-item v-ripple clickable :to="{ name: 'machines' }">
          <q-item-section avatar><q-icon name="devices" /></q-item-section>
          <q-item-section>Postes</q-item-section>
        </q-item>
        <q-item v-ripple clickable :to="{ name: 'software' }">
          <q-item-section avatar><q-icon name="inventory_2" /></q-item-section>
          <q-item-section>Logiciels</q-item-section>
        </q-item>
        <q-item v-if="auth.can('check', 'read')" v-ripple clickable :to="{ name: 'tasks' }">
          <q-item-section avatar><q-icon name="task_alt" /></q-item-section>
          <q-item-section>Mes tâches</q-item-section>
          <q-item-section v-if="myTasks" side>
            <q-badge color="primary" :label="myTasks" />
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
      </q-list>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from 'src/stores/auth';
import { listChecks } from 'src/services/checks';

const drawer = ref(false);
const auth = useAuthStore();
const router = useRouter();

// The badge on « Mes tâches »: how many verifications are assigned to me.
// Read once the profile is known, and again on each navigation — cheap (one
// count) and enough for a number that changes a few times a day.
const myTasks = ref(0);
async function countMyTasks() {
  if (!auth.can('check', 'read')) return;
  try {
    myTasks.value = (await listChecks({ open: true, assigned_to: 'me', page_size: 1 })).total;
  } catch {
    // The badge is a hint; the page says the truth.
  }
}

onMounted(() => {
  // Restore the user profile after a page reload if a token is present.
  if (auth.isAuthenticated && !auth.user) {
    void auth.fetchMe();
  }
});
watch(
  () => auth.user?.id,
  () => void countMyTasks(),
  { immediate: true },
);
watch(
  () => router.currentRoute.value.fullPath,
  () => void countMyTasks(),
);

function onLogout() {
  auth.logout();
  void router.push({ name: 'login' });
}
</script>
