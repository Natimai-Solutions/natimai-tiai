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
  updateSettings,
  type ConsoleSettings,
  type EnvGroup,
  type EnvItem,
} from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';

const $q = useQuasar();
const auth = useAuthStore();

const settings = ref<ConsoleSettings | null>(null);
const saving = ref(false);
const form = reactive({ cycle: 90, ownerId: null as string | null, dueSoon: 14 });
const ownerOptions = ref<{ label: string; value: string }[]>([]);
const canWrite = computed(() => auth.can('settings', 'write'));

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
