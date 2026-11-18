<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 460px; max-width: 90vw">
      <q-card-section class="text-h6">
        {{ room ? t('rooms.form.editRoom') : t('rooms.form.newRoom') }}
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
            :rules="[required]"
          />
          <q-select
            v-model="form.building_id"
            :options="buildingOptions"
            emit-value
            map-options
            :label="t('rooms.form.building')"
            outlined
            dense
            :hint="t('rooms.form.roomBuildingHint')"
          />
          <!-- Only a loose room carries a site of its own. -->
          <LocationSelect
            v-if="!form.building_id"
            v-model="form.location"
            :locations="locations"
            :label="t('rooms.form.location')"
            :hint="t('rooms.form.roomLocationHint')"
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
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import LocationSelect from './LocationSelect.vue';
import { createRoom, updateRoom, type Building, type Room } from 'src/services/rooms';
import { apiErrorMessage } from 'src/services/errors';
import { t } from 'src/i18n';

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
const required = (v: string) => !!v.trim() || t('rooms.form.required');

const buildingOptions = computed(() => [
  { label: t('rooms.form.noBuilding'), value: null },
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
    // The site the room is on, its building's included: choosing « Aucun
    // bâtiment » then keeps it rather than leaving the field empty (audit B22).
    form.location = props.room?.location ?? props.room?.effective_location ?? null;
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
    $q.notify({
      type: 'positive',
      message: props.room ? t('rooms.form.roomUpdated') : t('rooms.form.roomCreated'),
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
