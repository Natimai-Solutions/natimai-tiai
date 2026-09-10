<template>
  <!-- The cycle and the owner at one level (a room, a poste). Inheriting is
       the default and a real choice, so both fields can be cleared. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 460px; max-width: 95vw">
      <q-card-section class="text-h6">Maintenance — {{ subject }}</q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-select
            v-model="form.cycleMode"
            :options="cycleModes"
            emit-value
            map-options
            label="Cycle"
            outlined
            dense
          />
          <q-input
            v-if="form.cycleMode === 'custom'"
            v-model.number="form.cycleDays"
            type="number"
            min="1"
            max="3650"
            suffix="jours"
            label="Tous les"
            outlined
            dense
            :rules="[(v) => (Number.isInteger(v) && v >= 1) || 'Un nombre de jours']"
          />
          <q-select
            v-model="form.ownerId"
            :options="ownerOptions"
            emit-value
            map-options
            label="Responsable"
            outlined
            dense
            clearable
            :hint="inheritHint"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat label="Annuler" />
          <q-btn type="submit" color="primary" label="Enregistrer" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { listAssignableUsers } from 'src/services/checks';
import type { MaintenanceSettingsPayload } from 'src/services/maintenance';
import { apiErrorMessage } from 'src/services/errors';

const props = defineProps<{
  modelValue: boolean;
  subject: string;
  /** The level's own values; null = inherit. */
  cycleDays: number | null;
  ownerId: string | null;
  /** What "inherit" resolves to, for the hint. */
  inheritHint: string;
  save: (payload: MaintenanceSettingsPayload) => Promise<void>;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>();

const $q = useQuasar();
const saving = ref(false);
const form = reactive({
  cycleMode: 'inherit' as 'inherit' | 'custom' | 'excluded',
  cycleDays: 90,
  ownerId: null as string | null,
});
const cycleModes = [
  { label: 'Hériter (salle, puis parc)', value: 'inherit' },
  { label: 'Cycle propre', value: 'custom' },
  { label: 'Exclure de la maintenance', value: 'excluded' },
];
const ownerOptions = ref<{ label: string; value: string }[]>([]);

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    form.cycleMode =
      props.cycleDays === null ? 'inherit' : props.cycleDays === 0 ? 'excluded' : 'custom';
    form.cycleDays = props.cycleDays && props.cycleDays > 0 ? props.cycleDays : 90;
    form.ownerId = props.ownerId;
    void loadUsers();
  },
);

async function loadUsers() {
  try {
    ownerOptions.value = (await listAssignableUsers()).map((u) => ({ label: u.name, value: u.id }));
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Comptes indisponibles') });
  }
}

async function submit() {
  saving.value = true;
  try {
    await props.save({
      maintenance_cycle_days:
        form.cycleMode === 'inherit' ? null : form.cycleMode === 'excluded' ? 0 : form.cycleDays,
      maintenance_owner_id: form.ownerId,
    });
    emit('update:modelValue', false);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}
</script>
