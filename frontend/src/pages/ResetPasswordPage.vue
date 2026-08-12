<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center bg-grey-2">
        <q-card style="width: 380px; max-width: 90vw">
          <q-card-section class="text-center">
            <q-icon name="lock_reset" size="48px" color="primary" />
            <div class="text-h6 q-mt-sm">Nouveau mot de passe</div>
          </q-card-section>

          <q-card-section v-if="!token" class="q-pt-none">
            <q-banner dense class="bg-red-1 text-red-9">
              <template #avatar><q-icon name="error" /></template>
              Lien incomplet : il ne contient pas de jeton de réinitialisation.
            </q-banner>
          </q-card-section>

          <q-form v-else @submit="onSubmit">
            <q-card-section class="q-pt-none q-gutter-md">
              <q-input
                v-model="password"
                type="password"
                label="Nouveau mot de passe"
                outlined
                dense
                autofocus
                autocomplete="new-password"
                :hint="`${PASSWORD_MIN_LENGTH} caractères minimum`"
                :rules="[required, longEnough]"
              />
              <q-input
                v-model="confirmation"
                type="password"
                label="Confirmer le mot de passe"
                outlined
                dense
                autocomplete="new-password"
                :rules="[required, matches]"
              />
            </q-card-section>

            <q-card-actions class="q-px-md q-pb-md">
              <q-btn
                type="submit"
                color="primary"
                class="full-width"
                label="Définir le mot de passe"
                :loading="loading"
              />
            </q-card-actions>
          </q-form>

          <q-card-actions class="q-px-md q-pb-md">
            <q-btn flat class="full-width" label="Retour à la connexion" :to="{ name: 'login' }" />
          </q-card-actions>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { confirmPasswordReset } from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { PASSWORD_MIN_LENGTH } from 'src/services/users';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''));
const password = ref('');
const confirmation = ref('');
const loading = ref(false);

const required = (v: string) => !!v || 'Requis';
const longEnough = (v: string) =>
  v.length >= PASSWORD_MIN_LENGTH || `${PASSWORD_MIN_LENGTH} caractères minimum`;
const matches = (v: string) => v === password.value || 'Les mots de passe ne correspondent pas';

async function onSubmit() {
  loading.value = true;
  try {
    await confirmPasswordReset(token.value, password.value);
    $q.notify({ type: 'positive', message: 'Mot de passe défini. Vous pouvez vous connecter.' });
    await router.push({ name: 'login' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Réinitialisation impossible') });
  } finally {
    loading.value = false;
  }
}
</script>
