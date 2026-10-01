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

    <!-- Parc thresholds: what makes the console call a poste « périmé »,
         « inactif », short of disk, due for renewal or behind on its agent,
         and how long a queued command waits for it. The environment gives the
         initial value; the value saved here wins, without a restart. -->
    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        Supervision du parc
        <div class="text-caption text-grey">
          Les seuils qui décident de ce que la console signale sur un poste. Appliqués aussitôt,
          sans redémarrer le serveur.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-input
          v-model.number="fleetForm.signatureMaxAgeDays"
          type="number"
          min="0"
          max="365"
          suffix="jours"
          label="Base antivirus périmée au-delà de"
          outlined
          dense
          :hint="`Âge des signatures ; recalculé aussitôt pour tout le parc, postes éteints compris · variable d'environnement : ${settings.env_signature_max_age_days} jours`"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.inactiveAfterDays"
          type="number"
          min="1"
          max="3650"
          suffix="jours"
          label="Poste inactif après"
          outlined
          dense
          :hint="`Jours sans contact de l'agent · variable d'environnement : ${settings.env_inactive_after_days} jours`"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.lowDiskFreePercent"
          type="number"
          min="1"
          max="99"
          suffix="% libres"
          label="Disque presque plein en dessous de"
          outlined
          dense
          :hint="`Sur le volume système · variable d'environnement : ${settings.env_low_disk_free_percent} %`"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.hardwareAgingYears"
          type="number"
          min="1"
          max="30"
          suffix="ans"
          label="Poste à renouveler à partir de"
          outlined
          dense
          :hint="`Âge lu sur la date du BIOS · variable d'environnement : ${settings.env_hardware_aging_years} ans`"
          :disable="!canWrite"
        />
        <q-input
          v-model="fleetForm.agentExpectedVersion"
          label="Version d'agent de référence"
          placeholder="Automatique"
          outlined
          dense
          clearable
          :error="!agentVersionValid"
          error-message="Une version comme 1.2.0 ou v1.2.0-rc.1, ou vide pour automatique"
          :hint="`Vide = automatique, la plus haute version remontée par le parc · variable d'environnement : ${settings.env_agent_expected_version ?? 'automatique'}`"
          :disable="!canWrite"
        />
        <q-input
          v-model.number="fleetForm.commandDefaultTtlMinutes"
          type="number"
          min="1"
          :max="60 * 24 * 30"
          suffix="minutes"
          label="Durée de vie d'une commande en attente"
          outlined
          dense
          :hint="`Au-delà, une commande jamais remise à son poste est périmée · variable d'environnement : ${settings.env_command_default_ttl_minutes} minutes`"
          :disable="!canWrite"
        />
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          label="Enregistrer"
          :loading="savingFleet"
          :disable="!agentVersionValid"
          @click="saveFleet"
        />
      </q-card-actions>
    </q-card>

    <!-- The worker's mails. The server counts in UTC; the hints say when the
         mail lands on the reader's own clock, weekday shift included. -->
    <q-card flat bordered style="max-width: 640px" class="q-mb-md">
      <q-card-section class="text-subtitle1">
        E-mails programmés
        <div class="text-caption text-grey">
          L'heure du résumé quotidien et le jour du rappel hebdomadaire des maintenances. Pris en
          compte en moins d'une minute, sans redémarrer le serveur.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section v-if="settings" class="q-gutter-md">
        <q-select
          v-model="scheduleForm.digestHourUtc"
          :options="hourOptions"
          emit-value
          map-options
          label="Heure du résumé quotidien (UTC)"
          outlined
          dense
          :hint="`Arrive ${digestHint} · variable d'environnement : ${settings.env_digest_hour_utc} h UTC`"
          :disable="!canWrite"
        />
        <q-select
          v-model="scheduleForm.reminderWeekday"
          :options="weekdayOptions"
          emit-value
          map-options
          label="Jour du rappel des maintenances (UTC)"
          outlined
          dense
          :hint="`À l'heure du résumé : arrive ${reminderHint} · variable d'environnement : ${WEEKDAYS_FR[settings.env_maintenance_reminder_weekday]}`"
          :disable="!canWrite"
        />
      </q-card-section>
      <q-card-actions v-if="canWrite && settings" align="right" class="q-px-md q-pb-md">
        <q-btn
          color="primary"
          label="Enregistrer"
          :loading="savingSchedule"
          @click="saveSchedule"
        />
      </q-card-actions>
    </q-card>

    <!-- The server's environment, read-only. One card, one group per section
         of ``.env``: the page is where an administrator comes to answer
         « pourquoi ce poste est-il signalé ? » without opening a shell. -->
    <q-card v-if="settings" flat bordered style="max-width: 960px">
      <q-card-section class="text-subtitle1">
        Réglages du serveur
        <div class="text-caption text-grey">
          Variables d'environnement du serveur (<code>deploy/.env</code>), en lecture seule ici. Une
          valeur se change dans ce fichier, puis en redémarrant le serveur — sauf celles marquées «
          valeur initiale », que les réglages ci-dessus remplacent dès qu'ils sont enregistrés.
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
  updateSettings,
  type ConsoleSettings,
  type EnvGroup,
  type EnvItem,
} from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';
import { usageSettingsError } from 'src/utils/usageFilter';
import {
  WEEKDAYS_FR,
  digestSummary,
  isAgentVersion,
  readerTimeZone,
  reminderSummary,
} from 'src/utils/settingsSchedule';

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

// The parc thresholds card. The agent version is a string: '' = automatic.
const savingFleet = ref(false);
const fleetForm = reactive({
  signatureMaxAgeDays: 3 as number | string,
  inactiveAfterDays: 30 as number | string,
  lowDiskFreePercent: 10 as number | string,
  hardwareAgingYears: 5 as number | string,
  agentExpectedVersion: '' as string | null,
  commandDefaultTtlMinutes: 60 as number | string,
});
const agentVersionValid = computed(() => isAgentVersion(fleetForm.agentExpectedVersion ?? ''));

function fillFleetForm(s: ConsoleSettings) {
  fleetForm.signatureMaxAgeDays = s.signature_max_age_days;
  fleetForm.inactiveAfterDays = s.inactive_after_days;
  fleetForm.lowDiskFreePercent = s.low_disk_free_percent;
  fleetForm.hardwareAgingYears = s.hardware_aging_years;
  fleetForm.agentExpectedVersion = s.agent_expected_version ?? '';
  fleetForm.commandDefaultTtlMinutes = s.command_default_ttl_minutes;
}

// The mail schedule card, and when each mail lands for the reader.
const savingSchedule = ref(false);
const scheduleForm = reactive({ digestHourUtc: 18, reminderWeekday: 0 });
const timeZone = readerTimeZone();
const hourOptions = Array.from({ length: 24 }, (_, h) => ({
  label: `${h} h UTC`,
  value: h,
}));
const weekdayOptions = WEEKDAYS_FR.map((day, i) => ({
  label: day.charAt(0).toUpperCase() + day.slice(1),
  value: i,
}));
const digestHint = computed(() => digestSummary(scheduleForm.digestHourUtc, timeZone));
const reminderHint = computed(() =>
  reminderSummary(scheduleForm.reminderWeekday, scheduleForm.digestHourUtc, timeZone),
);

function fillScheduleForm(s: ConsoleSettings) {
  scheduleForm.digestHourUtc = s.digest_hour_utc;
  scheduleForm.reminderWeekday = s.maintenance_reminder_weekday;
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
    fillFleetForm(settings.value);
    fillScheduleForm(settings.value);
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

async function saveFleet() {
  if (!agentVersionValid.value) return;
  savingFleet.value = true;
  try {
    settings.value = await updateSettings({
      signature_max_age_days: Number(fleetForm.signatureMaxAgeDays),
      inactive_after_days: Number(fleetForm.inactiveAfterDays),
      low_disk_free_percent: Number(fleetForm.lowDiskFreePercent),
      hardware_aging_years: Number(fleetForm.hardwareAgingYears),
      // '' and not null: « automatique » is a choice the console makes, and
      // must win over a version pinned in the environment.
      agent_expected_version: (fleetForm.agentExpectedVersion ?? '').trim(),
      command_default_ttl_minutes: Number(fleetForm.commandDefaultTtlMinutes),
    });
    fillFleetForm(settings.value);
    $q.notify({ type: 'positive', message: 'Paramètres enregistrés' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    savingFleet.value = false;
  }
}

async function saveSchedule() {
  savingSchedule.value = true;
  try {
    settings.value = await updateSettings({
      digest_hour_utc: scheduleForm.digestHourUtc,
      maintenance_reminder_weekday: scheduleForm.reminderWeekday,
    });
    fillScheduleForm(settings.value);
    $q.notify({ type: 'positive', message: 'Paramètres enregistrés' });
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    savingSchedule.value = false;
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
