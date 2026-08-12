<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center bg-grey-2">
        <q-card style="width: 380px; max-width: 90vw">
          <q-card-section class="text-center">
            <q-icon name="lock_reset" size="48px" color="primary" />
            <div class="text-h6 q-mt-sm">Mot de passe oublié</div>
          </q-card-section>

          <template v-if="!sent">
            <q-card-section class="q-pt-none text-body2 text-grey-8">
              Indiquez l'adresse de votre compte : un lien de réinitialisation vous sera envoyé.
            </q-card-section>

            <q-form @submit="onSubmit">
              <q-card-section class="q-pt-none">
                <q-input
                  v-model="email"
                  type="email"
                  label="E-mail"
                  outlined
                  dense
                  autofocus
                  :rules="[required]"
                />
              </q-card-section>

              <q-card-actions class="q-px-md q-pb-md column q-gutter-sm">
                <q-btn
                  type="submit"
                  color="primary"
                  class="full-width"
                  label="Envoyer le lien"
                  :loading="loading"
                />
                <q-btn
                  flat
                  class="full-width"
                  label="Retour à la connexion"
                  :to="{ name: 'login' }"
                />
              </q-card-actions>
            </q-form>
          </template>

          <template v-else>
            <!-- Same wording whether or not the address has an account: the API
                 answers alike so the console must not leak the difference. -->
            <q-card-section class="q-pt-none text-body2">
              Si un compte existe pour <b>{{ email }}</b
              >, un lien de réinitialisation vient d'être envoyé. Il expire dans une heure.
            </q-card-section>
            <q-card-actions class="q-px-md q-pb-md">
              <q-btn
                color="primary"
                class="full-width"
                label="Retour à la connexion"
                :to="{ name: 'login' }"
              />
            </q-card-actions>
          </template>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useQuasar } from 'quasar';
import { requestPasswordReset } from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';

const $q = useQuasar();

const email = ref('');
const loading = ref(false);
const sent = ref(false);

const required = (v: string) => !!v || 'Requis';

async function onSubmit() {
  loading.value = true;
  try {
    await requestPasswordReset(email.value);
    sent.value = true;
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Envoi impossible') });
  } finally {
    loading.value = false;
  }
}
</script>
