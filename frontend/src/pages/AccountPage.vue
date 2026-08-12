<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Mon compte</div>

    <q-card flat bordered class="q-mb-md" style="max-width: 520px">
      <q-card-section class="q-gutter-xs">
        <div class="row items-center">
          <div class="col-4 text-grey-7">E-mail</div>
          <div class="col">{{ auth.user?.email ?? '—' }}</div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-grey-7">Nom</div>
          <div class="col">{{ auth.user?.full_name || '—' }}</div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-grey-7">Rôle</div>
          <div class="col">
            <q-badge :color="auth.isAdmin ? 'primary' : 'grey-7'">
              {{ auth.isAdmin ? 'Administrateur' : 'Lecture seule' }}
            </q-badge>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <q-card flat bordered style="max-width: 520px">
      <q-card-section class="text-subtitle1">Changer mon mot de passe</q-card-section>

      <q-form @submit="onSubmit">
        <q-card-section class="q-gutter-md q-pt-none">
          <q-input
            v-model="currentPassword"
            type="password"
            label="Mot de passe actuel"
            outlined
            dense
            autocomplete="current-password"
            :rules="[required]"
          />
          <q-input
            v-model="newPassword"
            type="password"
            label="Nouveau mot de passe"
            outlined
            dense
            autocomplete="new-password"
            :hint="`${PASSWORD_MIN_LENGTH} caractères minimum`"
            :rules="[required, longEnough]"
          />
          <q-input
            v-model="confirmation"
            type="password"
            label="Confirmer le nouveau mot de passe"
            outlined
            dense
            autocomplete="new-password"
            :rules="[required, matches]"
          />
          <q-banner dense class="bg-blue-1 text-blue-9">
            <template #avatar><q-icon name="info" /></template>
            Toutes vos sessions seront fermées : vous devrez vous reconnecter.
          </q-banner>
        </q-card-section>

        <q-card-actions class="q-px-md q-pb-md">
          <q-btn type="submit" color="primary" label="Changer le mot de passe" :loading="loading" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { changePassword } from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { PASSWORD_MIN_LENGTH } from 'src/services/users';
import { useAuthStore } from 'src/stores/auth';

const $q = useQuasar();
const auth = useAuthStore();
const router = useRouter();

const currentPassword = ref('');
const newPassword = ref('');
const confirmation = ref('');
const loading = ref(false);

const required = (v: string) => !!v || 'Requis';
const longEnough = (v: string) =>
  v.length >= PASSWORD_MIN_LENGTH || `${PASSWORD_MIN_LENGTH} caractères minimum`;
const matches = (v: string) => v === newPassword.value || 'Les mots de passe ne correspondent pas';

async function onSubmit() {
  loading.value = true;
  try {
    await changePassword(currentPassword.value, newPassword.value);
    // The backend invalidates every token issued before the change, including
    // the one that authenticated this request — so log out deliberately rather
    // than letting the next call fail with a confusing 401.
    auth.logout();
    $q.notify({
      type: 'positive',
      message: 'Mot de passe changé. Reconnectez-vous.',
    });
    await router.push({ name: 'login' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Changement impossible') });
  } finally {
    loading.value = false;
  }
}
</script>
