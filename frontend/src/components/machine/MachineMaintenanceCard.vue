<template>
  <q-card flat bordered>
    <q-card-section class="row items-center text-subtitle1">
      {{ t('maintenance.card.title') }}
      <q-space />
      <!-- Only over settings that were read: opened on a card that could not
           load, the dialog would show empty fields and save them. -->
      <q-btn
        v-if="canWrite && info"
        flat
        dense
        icon="tune"
        :label="t('maintenance.card.adjust')"
        class="q-mr-xs"
        @click="settingsOpen = true"
      />
      <q-btn
        v-if="canWrite"
        dense
        color="primary"
        icon="build"
        :label="t('maintenance.card.record')"
        @click="sessionOpen = true"
      />
    </q-card-section>
    <q-separator />
    <!-- The read failed: said here, with a retry — a card left blank reads as
         a poste without maintenance. -->
    <q-card-section v-if="failed" class="q-pa-sm">
      <CardLoadError :what="t('maintenance.card.what')" :loading="loading" @retry="load" />
    </q-card-section>
    <q-card-section v-if="info" class="q-gutter-xs">
      <div class="row items-center">
        <div class="col-4 text-muted">{{ t('maintenance.card.state') }}</div>
        <div class="col">
          <q-badge :color="maintenanceStateColor(info.resolved.state)">
            {{ maintenanceStateLabel(info.resolved.state) }}
          </q-badge>
          <!-- The leading space keeps « À jour due le … » two words in the
               text (copy, textContent), as the literal text did before. -->
          <span v-if="info.resolved.due_at" class="q-ml-sm">{{
            ' ' + t('maintenance.card.dueOn', { date: dueDate(info.resolved.due_at) })
          }}</span>
        </div>
      </div>
      <div class="row items-center">
        <div class="col-4 text-muted">{{ t('maintenance.card.cycle') }}</div>
        <div class="col">
          {{ cycleLabel(info.resolved.cycle_days, info.resolved.cycle_origin) }}
        </div>
      </div>
      <div class="row items-center">
        <div class="col-4 text-muted">{{ t('maintenance.card.owner') }}</div>
        <div class="col">
          <template v-if="info.resolved.owner">
            {{ info.resolved.owner.name }}
            <span class="text-caption text-muted"
              >({{ originLabel(info.resolved.owner_origin) }})</span
            >
          </template>
          <span v-else class="text-muted">{{ t('maintenance.card.nobody') }}</span>
        </div>
      </div>
      <div class="row items-center">
        <div class="col-4 text-muted">{{ t('maintenance.card.last') }}</div>
        <div class="col">
          {{
            info.resolved.last_maintenance_at
              ? formatDateTime(info.resolved.last_maintenance_at)
              : t('maintenance.card.never')
          }}
        </div>
      </div>
    </q-card-section>

    <MaintenanceSettingsDialog
      v-model="settingsOpen"
      :subject="hostname"
      :machine-id="machineId"
      :cycle-days="info?.maintenance_cycle_days ?? null"
      :owner-id="info?.maintenance_owner?.id ?? null"
      :owner-label="ownerLabel(info?.maintenance_owner)"
      :inherit-hint="t('maintenance.card.inheritHint')"
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
import CardLoadError from 'src/components/CardLoadError.vue';
import MaintenanceSessionDialog from 'src/components/maintenance/MaintenanceSessionDialog.vue';
import MaintenanceSettingsDialog from 'src/components/maintenance/MaintenanceSettingsDialog.vue';
import { notifyTasksChanged, tasksVersion } from 'src/composables/useTasksBadge';
import {
  cycleLabel,
  dueDate,
  getMachineMaintenance,
  maintenanceStateColor,
  maintenanceStateLabel,
  originLabel,
  ownerLabel,
  updateMachineMaintenance,
  type MachineMaintenance,
  type MaintenanceSettingsPayload,
} from 'src/services/maintenance';
import { formatDateTime } from 'src/utils/format';
import { t } from 'src/i18n';
import { notify } from 'src/utils/notify';

const props = defineProps<{ machineId: string; hostname: string; canWrite: boolean }>();
const emit = defineEmits<{ (e: 'changed'): void }>();

const $q = useQuasar();
const info = ref<MachineMaintenance | null>(null);
const settingsOpen = ref(false);
const sessionOpen = ref(false);
// The last read failed: the card says so, over whatever an earlier read of
// the same poste had shown.
const failed = ref(false);
const loading = ref(false);

async function load() {
  const id = props.machineId;
  loading.value = true;
  try {
    const read = await getMachineMaintenance(id);
    // The reader walked to another poste meanwhile: its own read decides.
    if (id !== props.machineId) return;
    info.value = read;
    failed.value = false;
  } catch {
    if (id === props.machineId) failed.value = true;
  } finally {
    if (id === props.machineId) loading.value = false;
  }
}

async function saveSettings(payload: MaintenanceSettingsPayload) {
  info.value = await updateMachineMaintenance(props.machineId, payload);
  // Another owner or cycle moves the poste in or out of somebody's « Mes
  // tâches »: the menu badge reads again (audit U19).
  notifyTasksChanged();
  notify($q, () => ({ type: 'positive', message: t('maintenance.card.saved') }));
  emit('changed');
}

async function onRecorded() {
  await load();
  emit('changed');
}

watch(
  () => props.machineId,
  () => {
    // Another poste: what was read belongs to the one left, and must not
    // stand under the new name while — or if — its own read fails.
    info.value = null;
    failed.value = false;
    void load();
  },
);
// A line of the journal added, edited or deleted — a maintenance typed by
// hand, one turned into « Autre », a visit removed — moves the due date and
// the last maintenance shown here: every such change bumps the tasks version.
watch(tasksVersion, () => void load());
onMounted(load);
defineExpose({ reload: load });
</script>
