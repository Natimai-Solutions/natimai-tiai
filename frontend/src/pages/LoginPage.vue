<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center bg-grey-2">
        <q-card style="width: 360px; max-width: 90vw">
          <q-card-section class="text-center">
            <q-icon name="shield" size="48px" color="primary" />
            <div class="text-h6 q-mt-sm">Tiai — Console</div>
            <div class="text-caption text-grey">Supervision du parc</div>
          </q-card-section>

          <q-form @submit="onSubmit">
            <q-card-section class="q-gutter-md">
              <q-input
                v-model="email"
                type="email"
                label="E-mail"
                outlined
                dense
                autofocus
                :rules="[required]"
              />
              <q-input
                v-model="password"
                type="password"
                label="Mot de passe"
                outlined
                dense
                :rules="[required]"
              />
            </q-card-section>

            <q-card-actions class="q-px-md q-pb-md column q-gutter-sm">
              <q-btn
                type="submit"
                color="primary"
                class="full-width"
                label="Se connecter"
                :loading="loading"
              />
              <q-btn
                flat
                dense
                class="full-width"
                label="Mot de passe oublié ?"
                :to="{ name: 'forgot-password' }"
              />
            </q-card-actions>
          </q-form>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { useAuthStore } from 'src/stores/auth';
import { apiErrorMessage } from 'src/services/errors';

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();
const $q = useQuasar();

const email = ref('');
const password = ref('');
const loading = ref(false);

const required = (v: string) => !!v || 'Requis';

async function onSubmit() {
  loading.value = true;
  try {
    await auth.login(email.value, password.value);
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/';
    await router.push(redirect);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Identifiants invalides') });
  } finally {
    loading.value = false;
  }
}
</script>
