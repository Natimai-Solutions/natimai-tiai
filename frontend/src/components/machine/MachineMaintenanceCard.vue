<template>
  <q-card flat bordered>
    <q-card-section class="row items-center text-subtitle1">
      Maintenance
      <q-space />
      <q-btn
        v-if="canWrite"
        flat
        dense
        icon="tune"
        label="Régler"
        class="q-mr-xs"
        @click="settingsOpen = true"
      />
      <q-btn
        v-if="canWrite"
        dense
        color="primary"
        icon="build"
        label="Enregistrer une maintenance"
        @click="sessionOpen = true"
      />
    </q-card-section>
    <q-separator />
    <q-card-section v-if="info" class="q-gutter-xs">
      <div class="row items-center">
        <div class="col-4 text-grey-7">État</div>
        <div class="col">
          <q-badge :color="maintenanceStateColor(info.resolved.state)">
            {{ maintenanceStateLabel(info.resolved.state) }}
          </q-badge>
          <span v-if="info.resolved.due_at" class="q-ml-sm">
            due le {{ formatDateTime(info.resolved.due_at) }}
          </span>
        </div>
      </div>
      <div class="row items-center">
        <div class="col-4 text-grey-7">Cycle</div>
        <div class="col">
          {{ cycleLabel(info.resolved.cycle_days, info.resolved.cycle_origin) }}
        </div>
      </div>
      <div class="row items-center">
        <div class="col-4 text-grey-7">Responsable</div>
        <div class="col">
          <template v-if="info.resolved.owner">
            {{ info.resolved.owner.name }}
            <span class="text-caption text-grey"
              >({{ ORIGIN_LABELS[info.resolved.owner_origin] }})</span
            >
          </template>
          <span v-else class="text-grey">personne</span>
        </div>
      </div>
      <div class="row items-center">
        <div class="col-4 text-grey-7">Dernière maintenance</div>
        <div class="col">
          {{
            info.resolved.last_maintenance_at
              ? formatDateTime(info.resolved.last_maintenance_at)
              : 'jamais'
          }}
        </div>
      </div>
    </q-card-section>

    <MaintenanceSettingsDialog
      v-model="settingsOpen"
      :subject="hostname"
      :cycle-days="info?.maintenance_cycle_days ?? null"
      :owner-id="info?.maintenance_owner?.id ?? null"
      inherit-hint="Vide : hérite de la salle, puis du parc"
      :save="saveSettings"
    />
    <MaintenanceSessionDialog
      v-model="sessionOpen"
      :room-id="null"
      :room-name="null"
      :machines="[{ id: machineId, hostname }]"
      @recorded="onRecorded"
    />
  </q-card>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import MaintenanceSessionDialog from 'src/components/maintenance/MaintenanceSessionDialog.vue';
import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { apiErrorMessage } from 'src/services/errors';
import {
  cycleLabel,
  getMachineMaintenance,
  maintenanceStateColor,
  maintenanceStateLabel,
  ORIGIN_LABELS,
  updateMachineMaintenance,
  type MachineMaintenance,
  type MaintenanceSettingsPayload,
} from 'src/services/maintenance';
import { formatDateTime } from 'src/utils/format';

const props = defineProps<{ machineId: string; hostname: string; canWrite: boolean }>();
const emit = defineEmits<{ (e: 'changed'): void }>();

const $q = useQuasar();
const info = ref<MachineMaintenance | null>(null);
const settingsOpen = ref(false);
const sessionOpen = ref(false);

async function load() {
  try {
    info.value = await getMachineMaintenance(props.machineId);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Maintenance indisponible') });
  }
}

async function saveSettings(payload: MaintenanceSettingsPayload) {
  info.value = await updateMachineMaintenance(props.machineId, payload);
  $q.notify({ type: 'positive', message: 'Réglages de maintenance enregistrés' });
  emit('changed');
}

async function onRecorded() {
  await load();
  emit('changed');
}

watch(
  () => props.machineId,
  () => void load(),
);
onMounted(load);
defineExpose({ reload: load });
</script>
