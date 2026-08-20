<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Mon compte</div>

    <q-card flat bordered class="q-mb-md" style="max-width: 520px">
      <q-card-section class="q-gutter-xs">
        <div class="row items-center">
          <div class="col-4 text-grey-7">E-mail</div>
          <div class="col">{{ auth.user?.email ?? '—' }}</div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-grey-7">Nom</div>
          <div class="col">{{ auth.user?.full_name || '—' }}</div>
        </div>
        <div class="row items-center">
          <div class="col-4 text-grey-7">Rôle</div>
          <div class="col">
            <q-badge :color="auth.isAdmin ? 'primary' : 'grey-7'">
              {{ auth.isAdmin ? 'Administrateur' : 'Lecture seule' }}
            </q-badge>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <q-card flat bordered class="q-mb-md" style="max-width: 520px">
      <q-card-section class="text-subtitle1">
        Notifications par e-mail
        <div class="text-caption text-grey">
          Ce que Tia'i vous envoie. Le choix est personnel : il ne change rien pour les autres
          comptes de la console.
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
              <div class="text-caption text-grey q-ml-lg">{{ opt.hint }}</div>
            </div>
          </template>
        </q-option-group>
        <div v-if="savingPreference" class="text-caption text-grey q-mt-sm">
          <q-spinner size="14px" class="q-mr-xs" />
          Enregistrement…
        </div>
      </q-card-section>
    </q-card>

    <q-card flat bordered style="max-width: 520px">
      <q-card-section class="text-subtitle1">Changer mon mot de passe</q-card-section>

      <q-form @submit="onSubmit">
        <q-card-section class="q-gutter-md q-pt-none">
          <q-input
            v-model="currentPassword"
            type="password"
            label="Mot de passe actuel"
            outlined
            dense
            autocomplete="current-password"
            :rules="[required]"
          />
          <q-input
            v-model="newPassword"
            type="password"
            label="Nouveau mot de passe"
            outlined
            dense
            autocomplete="new-password"
            :hint="`${PASSWORD_MIN_LENGTH} caractères minimum`"
            :rules="[required, longEnough]"
          />
          <q-input
            v-model="confirmation"
            type="password"
            label="Confirmer le nouveau mot de passe"
            outlined
            dense
            autocomplete="new-password"
            :rules="[required, matches]"
          />
          <q-banner dense class="bg-blue-1 text-blue-9">
            <template #avatar><q-icon name="info" /></template>
            Toutes vos sessions seront fermées : vous devrez vous reconnecter.
          </q-banner>
        </q-card-section>

        <q-card-actions class="q-px-md q-pb-md">
          <q-btn type="submit" color="primary" label="Changer le mot de passe" :loading="loading" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { changePassword, updateMe, type EmailPreference } from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { PASSWORD_MIN_LENGTH } from 'src/services/users';
import { useAuthStore } from 'src/stores/auth';
import { EMAIL_PREFERENCE_OPTIONS } from 'src/utils/format';

const $q = useQuasar();
const auth = useAuthStore();
const router = useRouter();

const currentPassword = ref('');
const newPassword = ref('');
const confirmation = ref('');
const loading = ref(false);

// `value`/`label` are what q-option-group binds on; the rest is read by the
// slot that renders each option with its explanation.
const preferenceOptions = EMAIL_PREFERENCE_OPTIONS;
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
    $q.notify({ type: 'positive', message: 'Préférence enregistrée' });
  } catch (e) {
    // Rolled back to what the server still holds: leaving the radio on a choice
    // that was never saved would have the user believe they had changed it.
    emailPreference.value = previous;
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
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

const required = (v: string) => !!v || 'Requis';
const longEnough = (v: string) =>
  v.length >= PASSWORD_MIN_LENGTH || `${PASSWORD_MIN_LENGTH} caractères minimum`;
const matches = (v: string) => v === newPassword.value || 'Les mots de passe ne correspondent pas';

async function onSubmit() {
  loading.value = true;
  try {
    await changePassword(currentPassword.value, newPassword.value);
    // The backend invalidates every token issued before the change, including
    // the one that authenticated this request — so log out deliberately rather
    // than letting the next call fail with a confusing 401.
    auth.logout();
    $q.notify({
      type: 'positive',
      message: 'Mot de passe changé. Reconnectez-vous.',
    });
    await router.push({ name: 'login' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Changement impossible') });
  } finally {
    loading.value = false;
  }
}
</script>
