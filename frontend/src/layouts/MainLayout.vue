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
        <q-item v-if="auth.isAdmin" v-ripple clickable :to="{ name: 'users' }">
          <q-item-section avatar><q-icon name="group" /></q-item-section>
          <q-item-section>Utilisateurs</q-item-section>
        </q-item>
      </q-list>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from 'src/stores/auth';

const drawer = ref(false);
const auth = useAuthStore();
const router = useRouter();

onMounted(() => {
  // Restore the user profile after a page reload if a token is present.
  if (auth.isAuthenticated && !auth.user) {
    void auth.fetchMe();
  }
});

function onLogout() {
  auth.logout();
  void router.push({ name: 'login' });
}
</script>
