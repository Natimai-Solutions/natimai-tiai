<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 460px; max-width: 90vw">
      <q-card-section class="text-h6">
        {{ room ? 'Modifier la salle' : 'Nouvelle salle' }}
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
          <q-select
            v-model="form.building_id"
            :options="buildingOptions"
            emit-value
            map-options
            label="Bâtiment"
            outlined
            dense
            hint="La salle prend l'emplacement de son bâtiment"
          />
          <!-- Only a loose room carries a site of its own. -->
          <LocationSelect
            v-if="!form.building_id"
            v-model="form.location"
            :locations="locations"
            label="Emplacement"
            hint="Sans bâtiment, la salle porte elle-même son emplacement"
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
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import LocationSelect from './LocationSelect.vue';
import { createRoom, updateRoom, type Building, type Room } from 'src/services/rooms';
import { apiErrorMessage } from 'src/services/errors';

const props = defineProps<{
  modelValue: boolean;
  room: Room | null;
  buildings: Building[];
  locations: string[];
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'saved', room: Room): void;
}>();

const $q = useQuasar();
const saving = ref(false);
const form = reactive({
  name: '',
  building_id: null as string | null,
  location: null as string | null,
  notes: '',
});
const required = (v: string) => !!v.trim() || 'Requis';

const buildingOptions = computed(() => [
  { label: 'Aucun bâtiment', value: null },
  ...props.buildings.map((b) => ({
    label: b.location ? `${b.name} — ${b.location}` : b.name,
    value: b.id,
  })),
]);

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    form.name = props.room?.name ?? '';
    form.building_id = props.room?.building?.id ?? null;
    form.location = props.room?.location ?? null;
    form.notes = props.room?.notes ?? '';
  },
);

async function submit() {
  saving.value = true;
  try {
    const payload = {
      name: form.name.trim(),
      building_id: form.building_id,
      location: form.building_id ? null : form.location?.trim() || null,
      notes: form.notes.trim() || null,
    };
    const saved = props.room ? await updateRoom(props.room.id, payload) : await createRoom(payload);
    $q.notify({ type: 'positive', message: props.room ? 'Salle mise à jour' : 'Salle créée' });
    emit('update:modelValue', false);
    emit('saved', saved);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}
</script>
