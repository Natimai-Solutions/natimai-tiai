<template>
  <q-page padding>
    <h1 class="text-h5 q-mb-md">{{ t('account.title') }}</h1>

    <!-- A session opened for enrolment only (C7): the rest of the console
         waits for the second factor a group requires. -->
    <q-banner
      v-if="auth.user?.enrolment_only"
      class="surface-orange q-mb-md"
      rounded
      dense
      role="status"
      style="max-width: 520px"
      data-test="enrolment-banner"
    >
      <template #avatar><q-icon name="phonelink_lock" /></template>
      {{ t('secondFactor.card.enrolmentOnly') }}
    </q-banner>

    <q-card flat bordered class="q-mb-md" style="max-width: 520px">
      <q-card-section class="q-gutter-xs">
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('account.profile.email') }}</div>
          <div class="col">{{ auth.user?.email ?? '—' }}</div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('account.profile.name') }}</div>
          <div class="col">{{ auth.user?.full_name || '—' }}</div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-muted">{{ t('account.profile.groups') }}</div>
          <div class="col">
            <template v-if="auth.user?.groups.length">
              <q-chip
                v-for="group in auth.user.groups"
                :key="group.id"
                dense
                color="primary"
                text-color="white"
                class="q-ml-none account-group-chip"
              >
                {{ groupName(group, auth.user.groups) }}
              </q-chip>
            </template>
            <span v-else class="text-muted">{{ t('account.profile.noGroup') }}</span>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <!-- Offered once the console speaks more than French (`ENGLISH_AVAILABLE`):
         until then there is nothing to choose, and an updated installation
         shows the page it showed before. -->
    <q-card
      v-if="languageOptions.length > 2"
      flat
      bordered
      class="q-mb-md"
      style="max-width: 520px"
      data-test="language-card"
    >
      <q-card-section class="text-subtitle1">
        {{ t('common.language.label') }}
        <div class="text-caption text-muted">{{ t('common.language.hint') }}</div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-pt-sm">
        <q-option-group
          :model-value="language"
          :options="languageOptions"
          type="radio"
          :disable="savingLanguage"
          @update:model-value="saveLanguage"
        />
      </q-card-section>
    </q-card>

    <q-card flat bordered class="q-mb-md" style="max-width: 520px">
      <q-card-section class="text-subtitle1">
        {{ t('account.notifications.title') }}
        <div class="text-caption text-muted">
          {{ t('account.notifications.hint') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-pt-sm">
        <!-- A radio list and not a dropdown: the four options differ by a
             sentence each, and a select would hide the very text that lets
             someone choose between two daily digests. -->
        <q-option-group
          v-model="emailPreference"
          :options="preferenceOptions"
          type="radio"
          :disable="savingPreference"
          @update:model-value="savePreference"
        >
          <template #label="opt">
            <div class="q-ml-xs q-mb-sm">
              <div class="row items-center">
                <q-icon :name="opt.icon" size="18px" class="q-mr-sm" />
                <span>{{ opt.label }}</span>
              </div>
              <div class="text-caption text-muted q-ml-lg">{{ opt.hint }}</div>
            </div>
          </template>
        </q-option-group>
        <div v-if="savingPreference" class="text-caption text-muted q-mt-sm">
          <q-spinner size="14px" class="q-mr-xs" />
          {{ t('account.notifications.saving') }}
        </div>
      </q-card-section>
    </q-card>

    <!-- An account of the directory (C7): its password and second factor
         live there, not here. -->
    <q-banner
      v-if="external"
      class="surface-grey q-mb-md"
      rounded
      dense
      style="max-width: 520px"
      data-test="external-account"
    >
      <template #avatar><q-icon name="badge" /></template>
      {{ t('secondFactor.directory.externalAccount') }}
    </q-banner>

    <q-card v-if="!external && !enrolmentOnly" flat bordered style="max-width: 520px">
      <q-card-section class="text-subtitle1">{{ t('account.password.title') }}</q-card-section>

      <q-form @submit="onSubmit">
        <q-card-section class="q-gutter-md q-pt-none">
          <q-input
            v-model="currentPassword"
            type="password"
            :label="t('account.password.current')"
            outlined
            dense
            autocomplete="current-password"
            reactive-rules
            :rules="[required]"
          />
          <q-input
            v-model="newPassword"
            type="password"
            :label="t('account.password.new')"
            outlined
            dense
            autocomplete="new-password"
            :hint="t('account.password.minLength', { count: passwordMin })"
            reactive-rules
            :rules="[required, longEnough]"
          />
          <q-input
            v-model="confirmation"
            type="password"
            :label="t('account.password.confirm')"
            outlined
            dense
            autocomplete="new-password"
            reactive-rules
            :rules="[required, matches]"
          />
          <q-banner dense class="surface-blue">
            <template #avatar><q-icon name="info" /></template>
            {{ t('account.password.sessionsClosed') }}
          </q-banner>
        </q-card-section>

        <q-card-actions class="q-px-md q-pb-md">
          <q-btn
            type="submit"
            color="primary"
            :label="t('account.password.submit')"
            :loading="loading"
          />
        </q-card-actions>
      </q-form>
    </q-card>

    <SecondFactorCard v-if="!external" />
    <DirectoryCard v-if="!enrolmentOnly" />
    <ApiTokensCard />

    <q-card v-if="!enrolmentOnly" flat bordered class="q-mt-md" style="max-width: 520px">
      <q-card-section class="row items-start no-wrap">
        <div class="col">
          <div class="text-subtitle1">{{ t('account.sessions.title') }}</div>
          <div class="text-caption text-muted">
            {{ t('account.sessions.hint') }}
          </div>
        </div>
        <q-btn
          flat
          dense
          round
          icon="refresh"
          :aria-label="t('account.sessions.refresh')"
          :loading="sessionsLoading"
          @click="loadSessions"
        />
      </q-card-section>
      <q-separator />
      <!-- The list could not be read: said here, with « Réessayer », and never
           as « Aucune session ouverte » — the one sentence that would hide a
           stranger's session (item 2). -->
      <q-card-section v-if="sessionsError" class="q-pa-sm">
        <CardLoadError
          :what="t('account.sessions.what')"
          :loading="sessionsLoading"
          @retry="loadSessions"
        />
      </q-card-section>
      <q-list separator>
        <q-item v-for="s in sessions" :key="s.id">
          <q-item-section avatar>
            <q-icon
              :name="s.current ? 'computer' : 'devices'"
              :color="s.current ? 'primary' : ''"
            />
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ describeUserAgent(s.user_agent) }}
              <q-badge v-if="s.current" color="primary" class="q-ml-xs">{{
                t('account.sessions.current')
              }}</q-badge>
            </q-item-label>
            <q-item-label caption>
              {{
                t('account.sessions.lastActivity', {
                  ip: s.ip || t('account.sessions.unknownAddress'),
                  ago: timeAgoLabel(s.last_used_at),
                })
              }}
            </q-item-label>
            <q-item-label caption>{{
              t('account.sessions.openedOn', { date: formatDateTime(s.created_at) })
            }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn
              flat
              dense
              color="negative"
              :label="s.current ? t('account.sessions.logout') : t('account.sessions.close')"
              :loading="closing === s.id"
              @click="onCloseSession(s)"
            />
          </q-item-section>
        </q-item>
        <q-item v-if="!sessionsLoading && !sessionsError && sessions.length === 0">
          <q-item-section class="text-muted">{{ t('account.sessions.none') }}</q-item-section>
        </q-item>
      </q-list>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { groupName } from 'src/utils/groupText';
import { usePasswordPolicy } from 'src/composables/usePasswordPolicy';
import { computed, onMounted, ref, watch } from 'vue';
import { availableLocales, t } from 'src/i18n';
import ApiTokensCard from 'src/components/account/ApiTokensCard.vue';
import CardLoadError from 'src/components/CardLoadError.vue';
import DirectoryCard from 'src/components/account/DirectoryCard.vue';
import SecondFactorCard from 'src/components/account/SecondFactorCard.vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import {
  changePassword,
  closeSession,
  listSessions,
  updateMe,
  type AccountLanguage,
  type AuthSession,
  type EmailPreference,
} from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import {
  EMAIL_PREFERENCE_OPTIONS,
  emailPreferenceLabel,
  formatDateTime,
  timeAgoLabel,
} from 'src/utils/format';
import { describeUserAgent } from 'src/utils/userAgent';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const { passwordMin } = usePasswordPolicy();

const $q = useQuasar();
const auth = useAuthStore();
const router = useRouter();
/** An account of the directory (C7): no password, no second factor here. */
const external = computed(() => auth.user?.auth_source === 'oidc');
/** A session for enrolment only: the second factor, and nothing the API would refuse. */
const enrolmentOnly = computed(() => auth.user?.enrolment_only === true);

// --- Language: the account's choice, or the browser's (`BROWSER`).
const BROWSER = 'browser';
const language = computed(() => auth.user?.language ?? BROWSER);
const languageOptions = computed(() => [
  { value: BROWSER, label: t('common.language.browser') },
  ...availableLocales().map((locale) => ({ value: locale, label: t(`common.language.${locale}`) })),
]);
const savingLanguage = ref(false);

/** Saved on selection, like the e-mail preference; the console switches at once. */
async function saveLanguage(choice: string) {
  if (choice === language.value) return;
  savingLanguage.value = true;
  try {
    await auth.saveLanguage(choice === BROWSER ? null : (choice as AccountLanguage));
    notify($q, () => ({ type: 'positive', message: t('common.language.saved') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  } finally {
    savingLanguage.value = false;
  }
}

const currentPassword = ref('');
const newPassword = ref('');
const confirmation = ref('');
const loading = ref(false);

// `value`/`label` are what q-option-group binds on; the rest is read by the
// slot that renders each option with its explanation. A computed, the label
// worded in the language shown.
const preferenceOptions = computed(() =>
  EMAIL_PREFERENCE_OPTIONS.map((o) => ({ ...o, label: emailPreferenceLabel(o.value) })),
);
const emailPreference = ref<EmailPreference>(auth.user?.email_preference ?? 'digest_daily');
const savingPreference = ref(false);

/** Saved on selection — a settings page with one radio group and a Save button
 * is a page people leave without pressing it. */
async function savePreference(choice: EmailPreference) {
  const previous = auth.user?.email_preference ?? 'digest_daily';
  if (choice === previous) return;
  savingPreference.value = true;
  try {
    const user = await updateMe({ email_preference: choice });
    auth.user = user;
    emailPreference.value = user.email_preference;
    notify($q, () => ({ type: 'positive', message: t('account.notifications.saved') }));
  } catch (e) {
    // Rolled back to what the server still holds: leaving the radio on a choice
    // that was never saved would have the user believe they had changed it.
    emailPreference.value = previous;
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('account.notifications.saveFailed')),
    }));
  } finally {
    savingPreference.value = false;
  }
}

// Watched rather than read once on mount. On a hard reload the profile is
// fetched by the layout — the *parent*, whose onMounted runs after this page's —
// so at mount time there is nothing to read yet, and a radio left on the default
// would tell an operator set to « aucun e-mail » that they receive a digest
// every morning. That is a settings page lying about the setting.
watch(
  () => auth.user?.email_preference,
  (preference) => {
    // Not while a save is in flight: the optimistic selection is the truth
    // until the server answers, and savePreference rolls it back if it refuses.
    if (preference && !savingPreference.value) emailPreference.value = preference;
  },
  { immediate: true },
);

const required = (v: string) => !!v || t('account.password.required');
const longEnough = (v: string) =>
  v.length >= passwordMin.value || t('account.password.minLength', { count: passwordMin.value });
const matches = (v: string) => v === newPassword.value || t('account.password.mismatch');

async function onSubmit() {
  loading.value = true;
  try {
    await changePassword(currentPassword.value, newPassword.value);
    // The backend revokes every session of the account, including the one
    // that authenticated this request — so log out deliberately (which also
    // clears the refresh cookie) rather than letting the next call fail with
    // a confusing 401.
    await auth.logout();
    notify($q, () => ({
      type: 'positive',
      message: t('account.password.changed'),
    }));
    await router.push({ name: 'login' });
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('account.password.failed')),
    }));
  } finally {
    loading.value = false;
  }
}

// --- Sessions ouvertes ---------------------------------------------------------

const sessions = ref<AuthSession[]>([]);
const sessionsLoading = ref(false);
const sessionsError = ref<unknown>(null);
const closing = ref<string | null>(null);

async function loadSessions() {
  sessionsLoading.value = true;
  try {
    sessions.value = await listSessions();
    sessionsError.value = null;
  } catch (e) {
    sessionsError.value = e;
  } finally {
    sessionsLoading.value = false;
  }
}

onMounted(() => void loadSessions());

/** Closing another session is immediate and reversible by logging in again
 * there — no confirmation. Closing this one logs out, so it asks first. */
function onCloseSession(session: AuthSession) {
  if (!session.current) {
    void closeOne(session);
    return;
  }
  liveDialog($q, () => ({
    title: t('account.sessions.logoutTitle'),
    message: t('account.sessions.logoutMessage'),
    cancel: { label: t('account.sessions.cancel'), flat: true },
    ok: { label: t('account.sessions.logout'), color: 'negative', flat: true },
    persistent: true,
  })).onOk(() => void closeOne(session));
}

async function closeOne(session: AuthSession) {
  closing.value = session.id;
  try {
    if (session.current) {
      // Logout is the same act — and also clears the refresh cookie.
      await auth.logout();
      await router.push({ name: 'login' });
      return;
    }
    await closeSession(session.id);
    sessions.value = sessions.value.filter((s) => s.id !== session.id);
    notify($q, () => ({ type: 'positive', message: t('account.sessions.closed') }));
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('account.sessions.closeFailed')),
    }));
    // Closed elsewhere in the meantime, or not: the server's list is the truth.
    void loadSessions();
  } finally {
    closing.value = null;
  }
}
</script>

<style scoped>
/* A group name with no space in it (64 characters are allowed) wraps inside its
   chip rather than widening the page on a phone. */
.account-group-chip {
  height: auto;
  min-height: 1.5em;
}
.account-group-chip :deep(.q-chip__content) {
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
