<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center surface-grey">
        <q-card style="width: 380px; max-width: 90vw">
          <q-card-section class="text-center">
            <q-icon name="lock_reset" size="48px" color="primary" />
            <div class="text-h6 q-mt-sm">Nouveau mot de passe</div>
          </q-card-section>

          <q-card-section v-if="!token" class="q-pt-none">
            <q-banner dense class="surface-red">
              <template #avatar><q-icon name="error" /></template>
              Lien incomplet : il ne contient pas de jeton de réinitialisation.
            </q-banner>
          </q-card-section>

          <q-card-section v-else-if="linkState === 'checking'" class="row justify-center">
            <q-spinner size="md" color="primary" aria-label="Vérification du lien" />
          </q-card-section>

          <!-- Expired, already used or garbled: said before anything is typed,
               with the way to a fresh link (C7). -->
          <q-card-section v-else-if="linkState === 'invalid'" class="q-pt-none q-gutter-sm">
            <q-banner dense class="surface-orange" role="alert">
              <template #avatar><q-icon name="link_off" /></template>
              Ce lien n'est plus valable : il a expiré, a déjà servi, ou a été coupé en route.
              Demandez-en un nouveau.
            </q-banner>
            <q-btn
              color="primary"
              no-caps
              class="full-width"
              label="Mot de passe oublié"
              :to="{ name: 'forgot-password' }"
            />
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
                :hint="`${passwordMin} caractères minimum`"
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
import { usePasswordPolicy } from 'src/composables/usePasswordPolicy';
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { checkPasswordResetToken, confirmPasswordReset } from 'src/services/auth';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';

const { passwordMin } = usePasswordPolicy();

const $q = useQuasar();
const route = useRoute();
const router = useRouter();

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''));
const password = ref('');
const confirmation = ref('');
const loading = ref(false);
// Whether the link can still be used, asked as the page opens (C7).
const linkState = ref<'checking' | 'valid' | 'invalid' | 'unknown'>('checking');

onMounted(async () => {
  if (!token.value) return;
  linkState.value = await checkPasswordResetToken(token.value);
});

const required = (v: string) => !!v || 'Requis';
const longEnough = (v: string) =>
  v.length >= passwordMin.value || `${passwordMin.value} caractères minimum`;
const matches = (v: string) => v === password.value || 'Les mots de passe ne correspondent pas';

async function onSubmit() {
  loading.value = true;
  try {
    await confirmPasswordReset(token.value, password.value);
    $q.notify({ type: 'positive', message: 'Mot de passe défini. Vous pouvez vous connecter.' });
    await router.push({ name: 'login' });
  } catch (e) {
    // The link died while the form was open (or the check was not available):
    // the page says so, and offers a fresh one.
    if (apiErrorCode(e) === 'password.reset_token.invalid') {
      linkState.value = 'invalid';
      return;
    }
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Réinitialisation impossible') });
  } finally {
    loading.value = false;
  }
}
</script>
