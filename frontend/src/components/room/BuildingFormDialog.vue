<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 460px; max-width: 90vw">
      <q-card-section class="text-h6">
        {{ building ? t('rooms.form.editBuilding') : t('rooms.form.newBuilding') }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-input
            v-model="form.name"
            :label="t('rooms.form.name')"
            outlined
            dense
            autofocus
            maxlength="100"
            reactive-rules
            :rules="[required]"
          />
          <LocationSelect
            v-model="form.location"
            :locations="locations"
            :label="t('rooms.form.location')"
            :hint="t('rooms.form.buildingLocationHint')"
          />
          <q-input
            v-model="form.notes"
            :label="t('rooms.form.notes')"
            outlined
            dense
            autogrow
            maxlength="2000"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat :label="t('rooms.actions.cancel')" />
          <q-btn type="submit" color="primary" :label="t('rooms.actions.save')" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import LocationSelect from './LocationSelect.vue';
import { createBuilding, updateBuilding, type Building } from 'src/services/rooms';
import { apiErrorMessage } from 'src/services/errors';
import { t } from 'src/i18n';

const props = defineProps<{
  modelValue: boolean;
  building: Building | null;
  locations: string[];
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'saved', building: Building): void;
}>();

const $q = useQuasar();
const saving = ref(false);
const form = reactive({ name: '', location: null as string | null, notes: '' });
const required = (v: string) => !!v.trim() || t('rooms.form.required');

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    form.name = props.building?.name ?? '';
    form.location = props.building?.location ?? null;
    form.notes = props.building?.notes ?? '';
  },
);

async function submit() {
  saving.value = true;
  try {
    const payload = {
      name: form.name.trim(),
      location: form.location?.trim() || null,
      notes: form.notes.trim() || null,
    };
    const saved = props.building
      ? await updateBuilding(props.building.id, payload)
      : await createBuilding(payload);
    $q.notify({
      type: 'positive',
      message: props.building ? t('rooms.form.buildingUpdated') : t('rooms.form.buildingCreated'),
    });
    emit('update:modelValue', false);
    emit('saved', saved);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, t('rooms.form.saveFailed')) });
  } finally {
    saving.value = false;
  }
}
</script>
