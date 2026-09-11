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

    <q-card v-if="settings" flat bordered style="max-width: 640px">
      <q-card-section class="text-subtitle1">
        Salles
        <div class="text-caption text-grey">
          Réglé par l'environnement du serveur, en lecture seule ici.
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section>
        <div class="row items-center">
          <div class="col-5 text-grey-7">Classement des postes</div>
          <div class="col">
            <code>ROOM_SOURCE={{ settings.room_source }}</code>
            <span class="q-ml-sm text-caption text-grey">{{ sourceLabel }}</span>
          </div>
        </div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar } from 'quasar';
import { listAssignableUsers } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';
import { ROOM_SOURCE_LABELS } from 'src/services/rooms';
import { getSettings, updateSettings, type ConsoleSettings } from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';

const $q = useQuasar();
const auth = useAuthStore();

const settings = ref<ConsoleSettings | null>(null);
const saving = ref(false);
const form = reactive({ cycle: 90, ownerId: null as string | null, dueSoon: 14 });
const ownerOptions = ref<{ label: string; value: string }[]>([]);
const canWrite = computed(() => auth.can('settings', 'write'));
const sourceLabel = computed(() =>
  settings.value ? (ROOM_SOURCE_LABELS[settings.value.room_source] ?? '') : '',
);

async function load() {
  try {
    settings.value = await getSettings();
    form.cycle = settings.value.maintenance_default_cycle_days;
    form.ownerId = settings.value.maintenance_default_owner?.id ?? null;
    form.dueSoon = settings.value.maintenance_due_soon_days;
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

onMounted(load);
</script>
