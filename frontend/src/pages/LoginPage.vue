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
          <!-- Back from the directory with a refusal (C7): said in words. -->
          <q-banner
            v-if="ssoError"
            class="surface-orange q-mx-md q-mt-sm"
            rounded
            dense
            role="alert"
            data-test="sso-error"
          >
            <template #avatar><q-icon name="error_outline" /></template>
            {{ ssoError }}
          </q-banner>

          <!-- The second step (C7): the password was right, the code is asked. -->
          <q-form v-if="challenge" data-test="second-factor-step" @submit="onCode">
            <q-card-section class="q-gutter-md">
              <div class="text-subtitle1">{{ t('secondFactor.login.title') }}</div>
              <div class="text-caption text-muted">
                {{
                  useBackup ? t('secondFactor.login.backupIntro') : t('secondFactor.login.intro')
                }}
              </div>
              <q-input
                v-model="code"
                :label="
                  useBackup ? t('secondFactor.login.backupCode') : t('secondFactor.login.code')
                "
                autocomplete="one-time-code"
                :inputmode="useBackup ? 'text' : 'numeric'"
                :maxlength="useBackup ? 11 : 7"
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
                :label="t('secondFactor.login.submit')"
                :loading="loading"
              />
              <q-btn
                flat
                dense
                no-caps
                class="full-width"
                :label="
                  useBackup ? t('secondFactor.login.useApp') : t('secondFactor.login.useBackup')
                "
                @click="toggleBackup"
              />
              <q-btn
                flat
                dense
                no-caps
                class="full-width"
                :label="t('secondFactor.login.back')"
                @click="startOver"
              />
            </q-card-actions>
          </q-form>

          <q-form v-else @submit="onSubmit">
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
              <!-- Sign-in through the directory (C7): a navigation, the
                   provider's page taking the whole window. -->
              <template v-if="methods?.oidc_enabled">
                <div class="text-center text-caption text-muted">
                  {{ t('secondFactor.directory.or') }}
                </div>
                <q-btn
                  outline
                  color="primary"
                  no-caps
                  class="full-width"
                  icon="badge"
                  :label="t('secondFactor.directory.signIn', { label: methods.oidc_label })"
                  data-test="sso-button"
                  @click="directorySignIn"
                />
              </template>
            </q-card-actions>
          </q-form>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { useAuthStore } from 'src/stores/auth';
import { apiErrorMessage } from 'src/services/errors';
import { directorySignInUrl, getAuthMethods, type AuthMethods } from 'src/services/auth';
import { errorCodeMessage } from 'src/i18n';
import { safeRedirect } from 'src/router/access';
import { notify } from 'src/utils/notify';

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();
const $q = useQuasar();

const email = ref('');
const password = ref('');
const loading = ref(false);
/** The challenge a right password bought, for an account with a second factor. */
const challenge = ref<string | null>(null);
const code = ref('');
const useBackup = ref(false);

const required = (v: string) => !!v || t('auth.required');
const sessionEnded = computed(() => route.query.ended === '1');

/** Back from the directory with a refusal: its code, worded; an unknown one generically. */
const ssoError = computed(() => {
  const code = route.query.sso_error;
  if (typeof code !== 'string' || !code) return null;
  return errorCodeMessage(code) ?? t('secondFactor.directory.failed');
});

const methods = ref<AuthMethods | null>(null);
onMounted(async () => {
  try {
    methods.value = await getAuthMethods();
  } catch {
    // An older server, or none reachable: the password form alone.
    methods.value = null;
  }
});

function directorySignIn() {
  window.location.assign(directorySignInUrl(safeRedirect(route.query.redirect) ?? null));
}

async function onSubmit() {
  loading.value = true;
  try {
    const asked = await auth.login(email.value, password.value);
    if (asked) {
      // The password is no longer needed, nor kept.
      password.value = '';
      code.value = '';
      useBackup.value = false;
      challenge.value = asked.challenge;
      return;
    }
    await router.push(safeRedirect(route.query.redirect) ?? '/');
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e, t('auth.login.failed')) }));
  } finally {
    loading.value = false;
  }
}

async function onCode() {
  if (!challenge.value) return;
  loading.value = true;
  try {
    await auth.verifySecondFactor(challenge.value, code.value.trim());
    challenge.value = null;
    await router.push(safeRedirect(route.query.redirect) ?? '/');
  } catch (e) {
    code.value = '';
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('secondFactor.login.failed')),
    }));
  } finally {
    loading.value = false;
  }
}

function toggleBackup() {
  useBackup.value = !useBackup.value;
  code.value = '';
}

function startOver() {
  challenge.value = null;
  code.value = '';
}
</script>
