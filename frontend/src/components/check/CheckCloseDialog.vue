<template>
  <!-- Closing: what was found. The note is optional but is the point — it
       stays on the request and goes into the poste's journal. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 480px; max-width: 95vw">
      <q-card-section class="text-h6">Clore la vérification</q-card-section>
      <q-card-section v-if="check?.instructions" class="q-pt-none text-body2 text-grey-8">
        Consignes : {{ check.instructions }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-input
            v-model="note"
            label="Ce qui a été constaté"
            outlined
            dense
            autogrow
            type="textarea"
            maxlength="5000"
            autofocus
            hint="Conservé sur la demande et inscrit dans l'historique du poste"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat label="Annuler" />
          <q-btn type="submit" color="primary" label="Clore" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { closeCheck } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';

const props = defineProps<{
  modelValue: boolean;
  check: { id: string; instructions: string | null } | null;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'closed'): void;
}>();

const $q = useQuasar();
const saving = ref(false);
const note = ref('');

watch(
  () => props.modelValue,
  (open) => {
    if (open) note.value = '';
  },
);

async function submit() {
  if (!props.check) return;
  saving.value = true;
  try {
    await closeCheck(props.check.id, { note: note.value.trim() || null });
    $q.notify({ type: 'positive', message: 'Vérification close' });
    emit('update:modelValue', false);
    emit('closed');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Clôture impossible') });
  } finally {
    saving.value = false;
  }
}
</script>
