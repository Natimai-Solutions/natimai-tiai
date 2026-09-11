<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 460px; max-width: 90vw">
      <q-card-section class="text-h6">
        {{ building ? 'Modifier le bâtiment' : 'Nouveau bâtiment' }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-input
            v-model="form.name"
            label="Nom"
            outlined
            dense
            autofocus
            maxlength="100"
            :rules="[required]"
          />
          <LocationSelect
            v-model="form.location"
            :locations="locations"
            label="Emplacement"
            hint="Dans les mots que les agents remontent ; un poste dont l'agent dit autre chose sera signalé"
          />
          <q-input v-model="form.notes" label="Notes" outlined dense autogrow maxlength="2000" />
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
import LocationSelect from './LocationSelect.vue';
import { createBuilding, updateBuilding, type Building } from 'src/services/rooms';
import { apiErrorMessage } from 'src/services/errors';

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
const required = (v: string) => !!v.trim() || 'Requis';

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
      message: props.building ? 'Bâtiment mis à jour' : 'Bâtiment créé',
    });
    emit('update:modelValue', false);
    emit('saved', saved);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}
</script>
