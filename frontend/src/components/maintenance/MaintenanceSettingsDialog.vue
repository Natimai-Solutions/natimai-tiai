<template>
  <!-- The cycle and the owner at one level (a room, a poste). Inheriting is
       the default and a real choice, so both fields can be cleared. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 460px; max-width: 95vw">
      <q-card-section class="text-h6">{{
        t('maintenance.settings.title', { subject })
      }}</q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-select
            v-model="form.cycleMode"
            :options="cycleModes"
            emit-value
            map-options
            :label="t('maintenance.settings.cycle')"
            outlined
            dense
          />
          <q-input
            v-if="form.cycleMode === 'custom'"
            v-model.number="form.cycleDays"
            type="number"
            min="1"
            max="3650"
            :suffix="t('maintenance.settings.days')"
            :label="t('maintenance.settings.every')"
            outlined
            dense
            reactive-rules
            :rules="[(v) => (Number.isInteger(v) && v >= 1) || t('maintenance.settings.daysRule')]"
          />
          <q-select
            v-model="form.ownerId"
            :options="ownerOptions"
            emit-value
            map-options
            :label="t('maintenance.settings.owner')"
            outlined
            dense
            clearable
            :hint="inheritHint"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat :label="t('maintenance.actions.cancel')" />
          <q-btn
            type="submit"
            color="primary"
            :label="t('maintenance.actions.save')"
            :loading="saving"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { listAssignableOwners, type MaintenanceSettingsPayload } from 'src/services/maintenance';
import { apiErrorMessage } from 'src/services/errors';
import { t } from 'src/i18n';

const props = defineProps<{
  modelValue: boolean;
  subject: string;
  /** The level's own values; null = inherit. */
  cycleDays: number | null;
  ownerId: string | null;
  /**
   * How to name the current owner when the picker does not offer it — an
   * account deactivated since, or out of reach: « Marie (désactivé) » rather
   * than its raw id.
   */
  ownerLabel?: string | null | undefined;
  /** What "inherit" resolves to, for the hint. */
  inheritHint: string;
  /**
   * The level being set — a poste or a room: the owner picker offers the
   * accounts the server accepts for that one, and no other.
   */
  machineId?: string | null;
  roomId?: string | null;
  save: (payload: MaintenanceSettingsPayload) => Promise<void>;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>();

const $q = useQuasar();
const saving = ref(false);
const form = reactive({
  cycleMode: 'inherit',
  cycleDays: 90,
  ownerId: null as string | null,
});
const cycleModes = computed(() => [
  { label: t('maintenance.settings.inherit'), value: 'inherit' },
  { label: t('maintenance.settings.custom'), value: 'custom' },
  { label: t('maintenance.settings.exclude'), value: 'excluded' },
]);
// Who the server accepts; the current owner, when not among them, is named
// at render time (`ownerOptions`).
const owners = ref<{ label: string; value: string }[]>([]);
const ownerOptions = computed(() =>
  props.ownerId && !owners.value.some((o) => o.value === props.ownerId)
    ? [
        {
          label: props.ownerLabel || t('maintenance.settings.unreachableOwner'),
          value: props.ownerId,
        },
        ...owners.value,
      ]
    : owners.value,
);

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
    const list = await listAssignableOwners({ machineId: props.machineId, roomId: props.roomId });
    owners.value = list.map((u) => ({ label: u.name, value: u.id }));
  } catch (e) {
    $q.notify({
      type: 'negative',
      message: apiErrorMessage(e, t('maintenance.settings.usersFailed')),
    });
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
    $q.notify({
      type: 'negative',
      message: apiErrorMessage(e, t('maintenance.settings.saveFailed')),
    });
  } finally {
    saving.value = false;
  }
}
</script>
