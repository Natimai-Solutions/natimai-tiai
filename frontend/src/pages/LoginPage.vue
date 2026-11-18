<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center surface-grey">
        <q-card style="width: 360px; max-width: 90vw">
          <q-card-section class="text-center">
            <q-icon name="shield" size="48px" color="primary" />
            <div class="text-h6 q-mt-sm">Tia'i — Console</div>
            <div class="text-caption text-muted">{{ t('auth.login.subtitle') }}</div>
          </q-card-section>

          <!-- Sent here by a request that found the session over: said once,
               here, whatever the page that hit it managed to show. -->
          <q-banner v-if="sessionEnded" class="surface-orange q-mx-md" rounded dense role="status">
            <template #avatar><q-icon name="schedule" /></template>
            {{ t('auth.login.sessionEnded') }}
          </q-banner>

          <q-form @submit="onSubmit">
            <q-card-section class="q-gutter-md">
              <q-input
                v-model="email"
                autocomplete="username"
                type="email"
                :label="t('auth.email')"
                outlined
                dense
                autofocus
                reactive-rules
                :rules="[required]"
              />
              <q-input
                v-model="password"
                autocomplete="current-password"
                type="password"
                :label="t('auth.login.password')"
                outlined
                dense
                reactive-rules
                :rules="[required]"
              />
            </q-card-section>

            <q-card-actions class="q-px-md q-pb-md column q-gutter-sm">
              <q-btn
                type="submit"
                color="primary"
                class="full-width"
                :label="t('auth.login.submit')"
                :loading="loading"
              />
              <q-btn
                flat
                dense
                class="full-width"
                :label="t('auth.login.forgot')"
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
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { useAuthStore } from 'src/stores/auth';
import { apiErrorMessage } from 'src/services/errors';
import { safeRedirect } from 'src/router/access';

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();
const $q = useQuasar();

const email = ref('');
const password = ref('');
const loading = ref(false);

const required = (v: string) => !!v || t('auth.required');
const sessionEnded = computed(() => route.query.ended === '1');

async function onSubmit() {
  loading.value = true;
  try {
    await auth.login(email.value, password.value);
    await router.push(safeRedirect(route.query.redirect) ?? '/');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('auth.login.failed')) });
  } finally {
    loading.value = false;
  }
}
</script>
