<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Paramètres</div>

    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        Maintenance
        <div class="text-caption text-grey">
          Les défauts du parc. Une salle ou un poste peut les remplacer ; la valeur la plus précise
          gagne.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-input
          v-model.number="form.cycle"
          type="number"
          min="0"
          max="3650"
          suffix="jours"
          label="Cycle par défaut"
          outlined
          dense
          :hint="`0 = aucune maintenance par défaut · variable d'environnement : ${settings.env_default_cycle_days} jours`"
          :disable="!canWrite"
        />
        <q-select
          v-model="form.ownerId"
          :options="ownerOptions"
          emit-value
          map-options
          label="Responsable par défaut"
          outlined
          dense
          clearable
          hint="Reçoit dans « Mes tâches » les salles et postes qui n'ont pas de responsable propre"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="form.dueSoon"
          type="number"
          min="0"
          max="365"
          suffix="jours"
          label="Fenêtre « à échéance »"
          outlined
          dense
          :hint="`Un poste est signalé à échéance ce nombre de jours avant sa date · variable d'environnement : ${settings.env_due_soon_days} jours`"
          :disable="!canWrite"
        />
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn color="primary" label="Enregistrer" :loading="saving" @click="save" />
      </q-card-actions>
    </q-card>

    <!-- The usage statistics' window and thresholds: what « peu utilisé » and
         « toujours allumé » mean on this parc. Saved on its own, so a refused
         threshold never holds the maintenance settings back. -->
    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        Utilisation des postes
        <div class="text-caption text-grey">
          Ce que comptent les cartes « Peu utilisés » et « Toujours allumés » du tableau de bord, et
          le filtre Utilisation de la liste des postes.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-input
          v-model.number="usageForm.windowDays"
          type="number"
          min="1"
          max="90"
          suffix="jours"
          label="Fenêtre d'observation"
          outlined
          dense
          :hint="`Les heures sont comptées sur ce nombre de jours glissants · variable d'environnement : ${settings.env_usage_window_days} jours`"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="usageForm.lowHours"
          type="number"
          min="0"
          suffix="heures"
          label="Poste peu utilisé en dessous de"
          outlined
          dense
          :hint="`Un poste enrôlé pendant la fenêtre n'est jamais compté peu utilisé · variable d'environnement : ${settings.env_usage_low_hours} heures`"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="usageForm.highHours"
          type="number"
          min="1"
          suffix="heures"
          label="Poste toujours allumé au-dessus de"
          outlined
          dense
          :hint="`variable d'environnement : ${settings.env_usage_high_hours} heures`"
          :disable="!canWrite"
        />
        <div v-if="usageError" class="text-negative text-caption">{{ usageError }}</div>
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          label="Enregistrer"
          :loading="savingUsage"
          :disable="usageError !== null"
          @click="saveUsage"
        />
      </q-card-actions>
    </q-card>

    <!-- How mail leaves: provider, sender, account. Saved on its own, and
         testable before it is saved — the test send carries the unsaved
         values. Secrets are write-only: the page only ever learns whether one
         is stored, and whether it must be typed again. -->
    <q-card v-if="settings" flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        Envoi des e-mails
        <div class="text-caption text-grey">
          Le chemin des alertes, des résumés et des liens « mot de passe oublié ». Un champ laissé
          vide reprend la valeur du serveur (<code>deploy/.env</code>), rappelée en dessous.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-gutter-md">
        <div
          :class="status.ok ? 'text-positive' : 'text-negative'"
          class="row items-center no-wrap q-gutter-x-sm"
        >
          <q-icon :name="status.ok ? 'check_circle' : 'error_outline'" size="sm" />
          <span>{{ status.text }}</span>
        </div>
        <div>
          <div class="text-caption text-grey-8 q-mb-xs">Fournisseur</div>
          <q-btn-toggle
            v-model="emailForm.provider"
            :options="providerOptions"
            no-caps
            unelevated
            toggle-color="primary"
            :disable="!canWrite"
          />
          <div class="text-caption text-grey q-mt-xs">
            valeur du serveur : {{ providerLabel(settings.email.env.provider) }}
          </div>
        </div>
        <q-input
          v-model="emailForm.fromEmail"
          label="Adresse d'expéditeur"
          outlined
          dense
          :placeholder="settings.email.env.from_email ?? ''"
          :hint="`Avec un compte SMTP authentifié, en général l'adresse du compte · valeur du serveur : ${settings.email.env.from_email ?? 'non définie'}`"
          :disable="!canWrite"
        />
        <q-input
          v-model="emailForm.fromName"
          label="Nom d'expéditeur"
          outlined
          dense
          :placeholder="settings.email.env.from_name"
          :hint="`valeur du serveur : ${settings.email.env.from_name}`"
          :disable="!canWrite"
        />

        <template v-if="emailForm.provider === 'smtp'">
          <q-input
            v-model="emailForm.smtpHost"
            label="Serveur SMTP"
            outlined
            dense
            :placeholder="settings.email.env.smtp_host ?? 'smtp.office365.com'"
            :hint="`Relais de l'établissement, Microsoft 365, Google Workspace… · valeur du serveur : ${settings.email.env.smtp_host ?? 'non définie'}`"
            :disable="!canWrite"
          />
          <div class="row q-col-gutter-md">
            <q-select
              v-model="emailForm.smtpSecurity"
              :options="SECURITY_OPTIONS"
              emit-value
              map-options
              label="Sécurité"
              outlined
              dense
              class="col-12 col-sm-7"
              :hint="`valeur du serveur : ${securityLabel(settings.email.env.smtp_security)}`"
              :disable="!canWrite"
            />
            <q-input
              v-model.number="emailForm.smtpPort"
              type="number"
              min="1"
              max="65535"
              label="Port"
              outlined
              dense
              class="col-12 col-sm-5"
              :placeholder="String(settings.email.env.smtp_port)"
              :hint="`valeur du serveur : ${settings.email.env.smtp_port}`"
              :disable="!canWrite"
            />
          </div>
          <q-input
            v-model="emailForm.smtpUser"
            label="Utilisateur"
            outlined
            dense
            autocomplete="off"
            :hint="`Vide = pas d'authentification (relais qui reconnaît le serveur) · valeur du serveur : ${settings.email.env.smtp_user_set ? 'définie' : 'aucune'}`"
            :disable="!canWrite"
          />
          <q-input
            v-model="emailForm.smtpPassword"
            type="password"
            label="Mot de passe"
            outlined
            dense
            autocomplete="new-password"
            :placeholder="smtpPasswordState.label === 'enregistré' ? '••••••••' : ''"
            :hint="secretHint(smtpPasswordState.label, emailForm.clearSmtpPassword)"
            :disable="!canWrite"
          >
            <template #append>
              <q-badge
                :color="smtpPasswordState.color"
                :label="smtpPasswordState.label"
                class="q-mr-xs"
              />
              <q-btn
                v-if="
                  canWrite &&
                  (settings.email.smtp_password_set || settings.email.smtp_password_unreadable)
                "
                flat
                dense
                round
                size="sm"
                :icon="emailForm.clearSmtpPassword ? 'undo' : 'delete_outline'"
                @click="emailForm.clearSmtpPassword = !emailForm.clearSmtpPassword"
              >
                <q-tooltip>{{
                  emailForm.clearSmtpPassword
                    ? 'Garder le mot de passe enregistré'
                    : 'Effacer le mot de passe enregistré'
                }}</q-tooltip>
              </q-btn>
            </template>
          </q-input>
          <div class="row q-col-gutter-md items-center">
            <div class="col-12 col-sm-7">
              <q-toggle
                v-model="emailForm.smtpVerifyTls"
                label="Vérifier le certificat du serveur"
                :disable="!canWrite"
              />
              <div class="text-caption text-grey">
                Non seulement pour un relais interne à certificat privé · valeur du serveur :
                {{ settings.email.env.smtp_verify_tls ? 'oui' : 'non' }}
              </div>
            </div>
            <q-input
              v-model.number="emailForm.smtpTimeout"
              type="number"
              min="1"
              max="120"
              suffix="s"
              label="Délai d'attente"
              outlined
              dense
              class="col-12 col-sm-5"
              :placeholder="String(settings.email.env.smtp_timeout_seconds)"
              :hint="`valeur du serveur : ${settings.email.env.smtp_timeout_seconds} s`"
              :disable="!canWrite"
            />
          </div>
        </template>

        <template v-else>
          <q-input
            v-model="emailForm.mailgunDomain"
            label="Domaine d'envoi Mailgun"
            outlined
            dense
            :placeholder="settings.email.env.mailgun_domain ?? 'mg.exemple.fr'"
            :hint="`valeur du serveur : ${settings.email.env.mailgun_domain ?? 'non définie'}`"
            :disable="!canWrite"
          />
          <q-input
            v-model="emailForm.mailgunApiKey"
            type="password"
            label="Clé API Mailgun"
            outlined
            dense
            autocomplete="new-password"
            :placeholder="mailgunKeyState.label === 'enregistré' ? '••••••••' : ''"
            :hint="secretHint(mailgunKeyState.label, emailForm.clearMailgunApiKey)"
            :disable="!canWrite"
          >
            <template #append>
              <q-badge
                :color="mailgunKeyState.color"
                :label="mailgunKeyState.label"
                class="q-mr-xs"
              />
              <q-btn
                v-if="
                  canWrite &&
                  (settings.email.mailgun_api_key_set || settings.email.mailgun_api_key_unreadable)
                "
                flat
                dense
                round
                size="sm"
                :icon="emailForm.clearMailgunApiKey ? 'undo' : 'delete_outline'"
                @click="emailForm.clearMailgunApiKey = !emailForm.clearMailgunApiKey"
              >
                <q-tooltip>{{
                  emailForm.clearMailgunApiKey
                    ? 'Garder la clé enregistrée'
                    : 'Effacer la clé enregistrée'
                }}</q-tooltip>
              </q-btn>
            </template>
          </q-input>
          <q-input
            v-model="emailForm.mailgunBaseUrl"
            label="Adresse de l'API Mailgun"
            outlined
            dense
            :placeholder="settings.email.env.mailgun_base_url"
            :hint="`Région EU : https://api.eu.mailgun.net/v3 · valeur du serveur : ${settings.email.env.mailgun_base_url}`"
            :disable="!canWrite"
          />
        </template>

        <div v-if="emailError" class="text-negative text-caption">{{ emailError }}</div>
      </q-card-section>

      <template v-if="canWrite">
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <div class="row items-start q-col-gutter-sm">
            <q-input
              v-model="testTo"
              label="Destinataire du test"
              outlined
              dense
              class="col-12 col-sm"
              :placeholder="auth.user?.email ?? ''"
              :error="testToError !== null"
              :error-message="testToError ?? undefined"
              hint="Vide = votre adresse. Le test essaie les valeurs du formulaire, même non enregistrées."
            />
            <div class="col-12 col-sm-auto">
              <q-btn
                outline
                color="primary"
                icon="send"
                label="Envoyer un e-mail de test"
                no-caps
                :loading="testing"
                :disable="emailError !== null || testToError !== null"
                @click="sendTest"
              />
            </div>
          </div>
          <q-banner
            v-if="testResult"
            dense
            rounded
            :class="testResult.ok ? 'bg-green-1 text-positive' : 'bg-red-1 text-negative'"
          >
            <template #avatar>
              <q-icon :name="testResult.ok ? 'check_circle' : 'error_outline'" />
            </template>
            {{ testResult.message }}
          </q-banner>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn
            color="primary"
            label="Enregistrer"
            :loading="savingEmail"
            :disable="emailError !== null"
            @click="saveEmail"
          />
        </q-card-actions>
      </template>
    </q-card>

    <!-- The server's environment, read-only. One card, one group per section
         of ``.env``: the page is where an administrator comes to answer
         « pourquoi ce poste est-il signalé ? » without opening a shell. -->
    <q-card v-if="settings" flat bordered style="max-width: 960px">
      <q-card-section class="text-subtitle1">
        Réglages du serveur
        <div class="text-caption text-grey">
          Variables d'environnement du serveur (<code>deploy/.env</code>), en lecture seule ici. Une
          valeur se change dans ce fichier, puis en redémarrant le serveur.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section class="q-pt-sm">
        <q-input
          v-model="envFilter"
          dense
          outlined
          clearable
          placeholder="Rechercher un réglage…"
          style="max-width: 360px"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </q-card-section>
      <template v-for="group in environmentGroups" :key="group.label">
        <q-separator />
        <q-card-section class="q-pb-none text-subtitle2">{{ group.label }}</q-card-section>
        <q-markup-table flat dense wrap-cells class="env-table">
          <tbody>
            <tr v-for="item in group.items" :key="item.key">
              <td class="env-key">
                <code>{{ item.key }}</code>
              </td>
              <td class="env-value">
                <span v-if="item.value !== null">{{ item.value }}</span>
                <span v-else class="text-grey">— non défini</span>
              </td>
              <td class="text-grey-8">{{ item.description }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </template>
      <q-card-section v-if="!environmentGroups.length" class="text-grey">
        Aucun réglage ne correspond.
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar } from 'quasar';
import { listAssignableUsers } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';
import {
  getSettings,
  sendTestEmail,
  updateSettings,
  type ConsoleSettings,
  type EmailProvider,
  type EmailTestResult,
  type EnvGroup,
  type EnvItem,
  type SmtpSecurity,
} from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';
import {
  SECURITY_OPTIONS,
  emailFormError,
  emailFormFrom,
  emailPayload,
  emailStatus,
  secretState,
  testRecipientError,
  type EmailForm,
} from 'src/utils/emailSettings';
import { usageSettingsError } from 'src/utils/usageFilter';

const $q = useQuasar();
const auth = useAuthStore();

const settings = ref<ConsoleSettings | null>(null);
const saving = ref(false);
const form = reactive({ cycle: 90, ownerId: null as string | null, dueSoon: 14 });
const ownerOptions = ref<{ label: string; value: string }[]>([]);
const canWrite = computed(() => auth.can('settings', 'write'));

// The usage card's own form. `number | string`: an emptied box hands back ''.
const savingUsage = ref(false);
const usageForm = reactive({
  windowDays: 7 as number | string,
  lowHours: 10 as number | string,
  highHours: 30 as number | string,
});
const usageError = computed(() =>
  usageSettingsError(usageForm.windowDays, usageForm.lowHours, usageForm.highHours),
);

function fillUsageForm(s: ConsoleSettings) {
  usageForm.windowDays = s.usage_window_days;
  usageForm.lowHours = s.usage_low_hours;
  usageForm.highHours = s.usage_high_hours;
}

// The mail card's own form, filled from what the console stored.
const savingEmail = ref(false);
const emailForm = reactive<EmailForm>({
  provider: 'mailgun',
  fromEmail: '',
  fromName: '',
  smtpHost: '',
  smtpPort: '',
  smtpSecurity: 'starttls',
  smtpUser: '',
  smtpPassword: '',
  clearSmtpPassword: false,
  smtpVerifyTls: true,
  smtpTimeout: '',
  mailgunDomain: '',
  mailgunApiKey: '',
  clearMailgunApiKey: false,
  mailgunBaseUrl: '',
});
const emailError = computed(() => emailFormError(emailForm));
const status = computed(() =>
  settings.value ? emailStatus(settings.value.email) : { ok: false, text: '' },
);
const smtpPasswordState = computed(() => {
  const e = settings.value?.email;
  return secretState(
    e?.smtp_password_set ?? false,
    e?.smtp_password_unreadable ?? false,
    e?.env.smtp_password_set ?? false,
  );
});
const mailgunKeyState = computed(() => {
  const e = settings.value?.email;
  return secretState(
    e?.mailgun_api_key_set ?? false,
    e?.mailgun_api_key_unreadable ?? false,
    e?.env.mailgun_api_key_set ?? false,
  );
});
const providerOptions = [
  { label: 'Serveur SMTP', value: 'smtp' },
  { label: 'Mailgun', value: 'mailgun' },
];
const testTo = ref('');
const testToError = computed(() => testRecipientError(testTo.value ?? ''));
const testing = ref(false);
const testResult = ref<EmailTestResult | null>(null);

function providerLabel(provider: EmailProvider): string {
  return provider === 'smtp' ? 'serveur SMTP' : 'Mailgun';
}

function securityLabel(security: SmtpSecurity): string {
  return SECURITY_OPTIONS.find((o) => o.value === security)?.label ?? security;
}

/** The line under a secret box: what saving will do with it. */
function secretHint(state: string, clearing: boolean): string {
  if (clearing) return "Sera effacé à l'enregistrement : la valeur du serveur s'appliquera.";
  if (state === 'à ressaisir')
    return 'Enregistré avec une autre clé SECRET_KEY du serveur, illisible : à ressaisir.';
  if (state === 'enregistré') return 'Laisser vide pour garder la valeur enregistrée.';
  return 'Chiffré dans la base, jamais réaffiché.';
}

function fillEmailForm(s: ConsoleSettings) {
  Object.assign(emailForm, emailFormFrom(s.email));
}

// The environment card, narrowed by the search box: on the variable's name,
// its value and its description alike, since a reader may know any of the
// three (« ROOM_SOURCE », « ad_ou », « salles »).
const envFilter = ref('');
const environmentGroups = computed<EnvGroup[]>(() => {
  const groups = settings.value?.environment ?? [];
  const needle = (envFilter.value ?? '').trim().toLocaleLowerCase('fr-FR');
  if (!needle) return groups;
  const matches = (item: EnvItem) =>
    [item.key, item.value ?? '', item.description].some((text) =>
      text.toLocaleLowerCase('fr-FR').includes(needle),
    );
  return groups
    .map((g) => ({ label: g.label, items: g.items.filter(matches) }))
    .filter((g) => g.items.length);
});

async function load() {
  try {
    settings.value = await getSettings();
    form.cycle = settings.value.maintenance_default_cycle_days;
    form.ownerId = settings.value.maintenance_default_owner?.id ?? null;
    form.dueSoon = settings.value.maintenance_due_soon_days;
    fillUsageForm(settings.value);
    fillEmailForm(settings.value);
    ownerOptions.value = (await listAssignableUsers()).map((u) => ({ label: u.name, value: u.id }));
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Chargement impossible') });
  }
}

async function save() {
  saving.value = true;
  try {
    settings.value = await updateSettings({
      maintenance_default_cycle_days: form.cycle,
      maintenance_default_owner_id: form.ownerId,
      maintenance_due_soon_days: form.dueSoon,
    });
    $q.notify({ type: 'positive', message: 'Paramètres enregistrés' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}

async function saveUsage() {
  if (usageError.value) return;
  savingUsage.value = true;
  try {
    settings.value = await updateSettings({
      usage_window_days: Number(usageForm.windowDays),
      usage_low_hours: Number(usageForm.lowHours),
      usage_high_hours: Number(usageForm.highHours),
    });
    fillUsageForm(settings.value);
    $q.notify({ type: 'positive', message: 'Paramètres enregistrés' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    savingUsage.value = false;
  }
}

async function saveEmail() {
  if (!settings.value || emailError.value) return;
  savingEmail.value = true;
  try {
    settings.value = await updateSettings({ email: emailPayload(emailForm, settings.value.email) });
    fillEmailForm(settings.value);
    $q.notify({ type: 'positive', message: 'Envoi des e-mails enregistré' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    savingEmail.value = false;
  }
}

async function sendTest() {
  if (!settings.value || emailError.value || testToError.value) return;
  testing.value = true;
  testResult.value = null;
  try {
    const to = (testTo.value ?? '').trim();
    testResult.value = await sendTestEmail({
      ...(to ? { to } : {}),
      email: emailPayload(emailForm, settings.value.email),
    });
  } catch (e) {
    testResult.value = { ok: false, message: apiErrorMessage(e, 'Envoi du test impossible') };
  } finally {
    testing.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.env-table td {
  vertical-align: top;
}
.env-key {
  width: 30%;
  white-space: nowrap;
}
.env-value {
  width: 20%;
  font-weight: 500;
}
</style>
