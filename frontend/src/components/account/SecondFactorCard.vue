<template>
  <q-card flat bordered class="q-mt-md" style="max-width: 520px" data-test="second-factor-card">
    <q-card-section class="text-subtitle1 row items-center">
      {{ t('secondFactor.card.title') }}
      <q-space />
      <q-badge
        :color="enabled ? 'positive' : 'grey-7'"
        :outline="!enabled"
        data-test="second-factor-state"
      >
        {{ enabled ? t('secondFactor.card.on') : t('secondFactor.card.off') }}
      </q-badge>
    </q-card-section>
    <q-card-section class="q-pt-none text-caption text-muted">
      {{ t('secondFactor.card.caption') }}
      <div v-if="required" class="q-mt-xs">{{ t('secondFactor.card.required') }}</div>
      <div v-if="enabled" class="q-mt-xs">
        {{ t('secondFactor.card.codesLeft', { n: auth.user?.backup_codes_left ?? 0 }) }}
      </div>
    </q-card-section>

    <!-- Enrolment: the QR code, the key as text, the first code. -->
    <q-card-section v-if="setup" class="q-pt-none" data-test="second-factor-setup">
      <div class="q-mb-sm">{{ t('secondFactor.setup.scan') }}</div>
      <svg
        :viewBox="`-2 -2 ${qr.size + 4} ${qr.size + 4}`"
        width="180"
        height="180"
        role="img"
        :aria-label="t('secondFactor.setup.qrLabel')"
        class="qr"
      >
        <rect x="-2" y="-2" :width="qr.size + 4" :height="qr.size + 4" fill="#fff" />
        <path :d="qr.path" fill="#000" />
      </svg>
      <div class="text-caption q-mt-sm">{{ t('secondFactor.setup.manual') }}</div>
      <code class="secret" data-test="second-factor-secret">{{ groupedSecret }}</code>
      <q-form class="q-mt-md" @submit="confirm">
        <q-input
          v-model="code"
          :label="t('secondFactor.setup.code')"
          outlined
          dense
          autocomplete="one-time-code"
          inputmode="numeric"
          maxlength="7"
          reactive-rules
          :rules="[sixDigits]"
        />
        <div class="row q-gutter-sm q-mt-sm">
          <q-btn
            type="submit"
            color="primary"
            no-caps
            unelevated
            :label="t('secondFactor.setup.confirm')"
            :loading="busy"
          />
          <q-btn
            flat
            no-caps
            :label="t('secondFactor.setup.cancel')"
            :disable="busy"
            @click="setup = null"
          />
        </div>
      </q-form>
    </q-card-section>

    <q-card-actions v-if="!setup" class="q-px-md q-pb-md">
      <q-btn
        v-if="!enabled"
        color="primary"
        no-caps
        unelevated
        :label="t('secondFactor.card.enable')"
        :loading="busy"
        data-test="second-factor-enable"
        @click="startOpen = true"
      />
      <template v-else>
        <q-btn
          outline
          no-caps
          color="primary"
          :label="t('secondFactor.card.regenerate')"
          @click="regenerateOpen = true"
        />
        <q-btn
          v-if="!required"
          flat
          no-caps
          color="negative"
          :label="t('secondFactor.card.disable')"
          @click="disableOpen = true"
        />
      </template>
    </q-card-actions>

    <!-- The backup codes, shown once. -->
    <q-dialog v-model="codesOpen" persistent>
      <q-card style="width: 420px; max-width: 95vw" data-test="backup-codes">
        <q-card-section class="text-h6">{{ t('secondFactor.codes.title') }}</q-card-section>
        <q-card-section class="q-pt-none">
          <div class="q-mb-md">{{ t('secondFactor.codes.intro') }}</div>
          <div class="codes">
            <code v-for="c in backupCodes" :key="c">{{ c }}</code>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            no-caps
            icon="content_copy"
            :label="t('secondFactor.codes.copy')"
            @click="copy"
          />
          <q-btn
            flat
            no-caps
            icon="download"
            :label="t('secondFactor.codes.download')"
            @click="download"
          />
          <q-btn
            color="primary"
            no-caps
            unelevated
            :label="t('secondFactor.codes.done')"
            @click="codesOpen = false"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- The password again before a secret is made: a stolen session must
         not put a second factor of its own on the account. -->
    <q-dialog v-model="startOpen">
      <q-card style="width: 420px; max-width: 95vw">
        <q-card-section class="text-h6">{{ t('secondFactor.card.enable') }}</q-card-section>
        <q-form @submit="start">
          <q-card-section class="q-pt-none">
            <q-input
              v-model="password"
              type="password"
              autocomplete="current-password"
              :label="t('secondFactor.disable.password')"
              outlined
              dense
              autofocus
              reactive-rules
              :rules="[(v: string) => !!v || t('account.password.required')]"
              data-test="second-factor-password"
            />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat no-caps :label="t('secondFactor.setup.cancel')" />
            <q-btn
              type="submit"
              color="primary"
              no-caps
              unelevated
              :label="t('secondFactor.setup.continue')"
              :loading="busy"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="disableOpen">
      <q-card style="width: 420px; max-width: 95vw">
        <q-card-section class="text-h6">{{ t('secondFactor.disable.title') }}</q-card-section>
        <q-form @submit="disable">
          <q-card-section class="q-gutter-md q-pt-none">
            <q-input
              v-model="password"
              type="password"
              autocomplete="current-password"
              :label="t('secondFactor.disable.password')"
              outlined
              dense
              reactive-rules
              :rules="[(v: string) => !!v || t('account.password.required')]"
            />
            <q-input
              v-model="code"
              :label="t('secondFactor.disable.code')"
              autocomplete="one-time-code"
              outlined
              dense
              reactive-rules
              :rules="[(v: string) => !!v.trim() || t('account.password.required')]"
            />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat no-caps :label="t('secondFactor.disable.cancel')" />
            <q-btn
              type="submit"
              color="negative"
              no-caps
              unelevated
              :label="t('secondFactor.disable.submit')"
              :loading="busy"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="regenerateOpen">
      <q-card style="width: 420px; max-width: 95vw">
        <q-card-section class="text-h6">{{ t('secondFactor.regenerate.title') }}</q-card-section>
        <q-form @submit="regenerate">
          <q-card-section class="q-pt-none">
            <div class="q-mb-md">{{ t('secondFactor.regenerate.intro') }}</div>
            <q-input
              v-model="code"
              :label="t('secondFactor.regenerate.code')"
              autocomplete="one-time-code"
              inputmode="numeric"
              maxlength="7"
              outlined
              dense
              reactive-rules
              :rules="[sixDigits]"
            />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat no-caps :label="t('secondFactor.regenerate.cancel')" />
            <q-btn
              type="submit"
              color="primary"
              no-caps
              unelevated
              :label="t('secondFactor.regenerate.submit')"
              :loading="busy"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { qrPath } from 'src/services/assets';
import { regenerateBackupCodes, totpConfirm, totpDisable, totpSetup } from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { downloadBlob } from 'src/utils/format';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();

const enabled = computed(() => auth.user?.second_factor_enabled === true);
const required = computed(() => auth.user?.second_factor_required === true);

const setup = ref<{ secret: string; otpauth_uri: string } | null>(null);
const code = ref('');
const password = ref('');
const busy = ref(false);
const backupCodes = ref<string[]>([]);
const codesOpen = ref(false);
const startOpen = ref(false);
const disableOpen = ref(false);
const regenerateOpen = ref(false);

const qr = computed(() => qrPath(setup.value?.otpauth_uri ?? ''));
/** The key in groups of four, as authenticator apps print theirs. */
const groupedSecret = computed(() => (setup.value?.secret ?? '').replace(/(.{4})/g, '$1 ').trim());

const sixDigits = (v: string) =>
  /^\d{6}$/.test(v.replace(/\s/g, '')) || t('secondFactor.codeFormat');

// Each dialog starts empty: a code typed for one action is not sent with another.
watch([disableOpen, regenerateOpen, startOpen], () => {
  code.value = '';
  password.value = '';
});

function fail(e: unknown): void {
  notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
}

async function start(): Promise<void> {
  busy.value = true;
  try {
    setup.value = await totpSetup(password.value);
    startOpen.value = false;
    password.value = '';
    code.value = '';
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}

function showCodes(codes: string[]): void {
  backupCodes.value = codes;
  codesOpen.value = true;
}

async function confirm(): Promise<void> {
  busy.value = true;
  try {
    const codes = await totpConfirm(code.value.replace(/\s/g, ''));
    setup.value = null;
    code.value = '';
    await auth.refreshProfile();
    notify($q, () => ({ type: 'positive', message: t('secondFactor.enabled') }));
    showCodes(codes);
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}

async function disable(): Promise<void> {
  busy.value = true;
  try {
    await totpDisable(password.value, code.value.trim());
    disableOpen.value = false;
    await auth.refreshProfile();
    notify($q, () => ({ type: 'positive', message: t('secondFactor.disable.done') }));
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}

async function regenerate(): Promise<void> {
  busy.value = true;
  try {
    const codes = await regenerateBackupCodes(code.value.replace(/\s/g, ''));
    regenerateOpen.value = false;
    await auth.refreshProfile();
    showCodes(codes);
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(backupCodes.value.join('\n'));
    notify($q, () => ({ type: 'positive', message: t('secondFactor.codes.copied') }));
  } catch (e) {
    fail(e);
  }
}

function download(): void {
  const text = [
    t('secondFactor.codes.title'),
    auth.user?.email ?? '',
    '',
    ...backupCodes.value,
  ].join('\n');
  downloadBlob(new Blob([text + '\n'], { type: 'text/plain' }), t('secondFactor.codes.fileName'));
}
</script>

<style scoped>
.qr {
  display: block;
}
.secret {
  display: inline-block;
  margin-top: 4px;
  font-size: 1rem;
  letter-spacing: 0.05em;
  word-break: break-all;
}
.codes {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px 16px;
  font-size: 1rem;
}
</style>
