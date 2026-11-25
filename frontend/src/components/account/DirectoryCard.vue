<template>
  <!-- A local account and the directory (C7): linked, it signs in either way.
       Shown only when the console offers the directory sign-in. -->
  <q-card
    v-if="methods?.oidc_enabled && local"
    flat
    bordered
    class="q-mt-md"
    style="max-width: 520px"
    data-test="directory-card"
  >
    <q-card-section class="text-subtitle1 row items-center">
      {{ t('secondFactor.directory.cardTitle', { label: methods.oidc_label }) }}
      <q-space />
      <q-badge :color="linked ? 'positive' : 'grey-7'" :outline="!linked">
        {{ linked ? t('secondFactor.directory.linked') : t('secondFactor.directory.notLinked') }}
      </q-badge>
    </q-card-section>
    <q-card-section class="q-pt-none text-caption text-muted">
      {{ t('secondFactor.directory.cardCaption', { label: methods.oidc_label }) }}
    </q-card-section>
    <q-card-actions class="q-px-md q-pb-md">
      <q-btn
        v-if="!linked"
        outline
        no-caps
        color="primary"
        icon="badge"
        :label="t('secondFactor.directory.link', { label: methods.oidc_label })"
        :loading="busy"
        data-test="directory-link"
        @click="openLink"
      />
      <q-btn
        v-else
        flat
        no-caps
        color="negative"
        :label="t('secondFactor.directory.unlink')"
        :loading="busy"
        data-test="directory-unlink"
        @click="unlink"
      />
    </q-card-actions>

    <!-- Proven again before the link: a stolen session must not bind the
         account to a directory identity that signs in without password. -->
    <q-dialog v-model="linkOpen">
      <q-card style="width: 420px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{ t('secondFactor.directory.linkTitle', { label: methods.oidc_label }) }}
        </q-card-section>
        <q-form @submit="link">
          <q-card-section class="q-gutter-md q-pt-none">
            <div>
              {{
                t('secondFactor.directory.linkIntro', {
                  withCode: needsCode ? t('secondFactor.directory.withCode') : '',
                })
              }}
            </div>
            <q-input
              v-model="password"
              type="password"
              autocomplete="current-password"
              :label="t('secondFactor.directory.password')"
              outlined
              dense
              autofocus
              reactive-rules
              :rules="[(v: string) => !!v || t('account.password.required')]"
              data-test="directory-password"
            />
            <q-input
              v-if="needsCode"
              v-model="code"
              :label="t('secondFactor.directory.code')"
              autocomplete="one-time-code"
              outlined
              dense
              reactive-rules
              :rules="[(v: string) => !!v.trim() || t('account.password.required')]"
              data-test="directory-code"
            />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat no-caps :label="t('secondFactor.directory.cancel')" />
            <q-btn
              type="submit"
              color="primary"
              no-caps
              unelevated
              :label="t('secondFactor.directory.continue')"
              :loading="busy"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import { useRoute } from 'vue-router';
import { t } from 'src/i18n';
import {
  getAuthMethods,
  startDirectoryLink,
  unlinkDirectory,
  type AuthMethods,
} from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();
const route = useRoute();

const methods = ref<AuthMethods | null>(null);
const busy = ref(false);
const local = computed(() => (auth.user?.auth_source ?? 'local') === 'local');
const linked = computed(() => auth.user?.directory_linked === true);
const needsCode = computed(() => auth.user?.second_factor_enabled === true);
const linkOpen = ref(false);
const password = ref('');
const code = ref('');

function openLink(): void {
  password.value = '';
  code.value = '';
  linkOpen.value = true;
}

onMounted(async () => {
  // Back from the provider after a link: said once.
  if (route.query.linked === '1') {
    notify($q, () => ({ type: 'positive', message: t('secondFactor.directory.linkedDone') }));
  }
  try {
    methods.value = await getAuthMethods();
  } catch {
    methods.value = null;
  }
});

async function link(): Promise<void> {
  busy.value = true;
  try {
    const url = await startDirectoryLink(
      password.value,
      needsCode.value ? code.value.trim() : null,
    );
    password.value = '';
    window.location.assign(url);
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
    busy.value = false;
  }
}

async function unlink(): Promise<void> {
  busy.value = true;
  try {
    await unlinkDirectory();
    await auth.refreshProfile();
    notify($q, () => ({ type: 'positive', message: t('secondFactor.directory.unlinkedDone') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  } finally {
    busy.value = false;
  }
}
</script>
