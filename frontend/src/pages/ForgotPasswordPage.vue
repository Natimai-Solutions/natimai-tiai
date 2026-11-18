<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center surface-grey">
        <q-card style="width: 380px; max-width: 90vw">
          <q-card-section class="text-center">
            <q-icon name="lock_reset" size="48px" color="primary" />
            <div class="text-h6 q-mt-sm">{{ t('auth.forgot.title') }}</div>
          </q-card-section>

          <template v-if="!sent">
            <q-card-section class="q-pt-none text-body2 text-muted">
              {{ t('auth.forgot.intro') }}
            </q-card-section>

            <q-form @submit="onSubmit">
              <q-card-section class="q-pt-none">
                <q-input
                  v-model="email"
                  autocomplete="email"
                  type="email"
                  :label="t('auth.email')"
                  outlined
                  dense
                  autofocus
                  reactive-rules
                  :rules="[required]"
                />
              </q-card-section>

              <q-card-actions class="q-px-md q-pb-md column q-gutter-sm">
                <q-btn
                  type="submit"
                  color="primary"
                  class="full-width"
                  :label="t('auth.forgot.submit')"
                  :loading="loading"
                />
                <q-btn
                  flat
                  class="full-width"
                  :label="t('auth.backToLogin')"
                  :to="{ name: 'login' }"
                />
              </q-card-actions>
            </q-form>
          </template>

          <template v-else>
            <!-- Same wording whether or not the address has an account: the API
                 answers alike so the console must not leak the difference. -->
            <q-card-section class="q-pt-none text-body2">
              {{ t('auth.forgot.sentBefore') }} <b>{{ email }}</b>{{
                t('auth.forgot.sentAfter', { expiry: resetExpiry })
              }}
            </q-card-section>
            <q-card-actions class="q-px-md q-pb-md">
              <q-btn
                color="primary"
                class="full-width"
                :label="t('auth.backToLogin')"
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
import { usePasswordPolicy } from 'src/composables/usePasswordPolicy';
import { ref } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { requestPasswordReset } from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { notify } from 'src/utils/notify';

const { resetExpiry } = usePasswordPolicy();

const $q = useQuasar();

const email = ref('');
const loading = ref(false);
const sent = ref(false);

const required = (v: string) => !!v || t('auth.required');

async function onSubmit() {
  loading.value = true;
  try {
    await requestPasswordReset(email.value);
    sent.value = true;
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('auth.forgot.failed')) }));
  } finally {
    loading.value = false;
  }
}
</script>
