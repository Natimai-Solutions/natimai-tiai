<template>
  <!-- Asking for a verification: who should look, and at what. One poste
       or a selection — the same form, the count in the title. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 480px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{ check ? 'Modifier la demande' : 'Demander une vérification' }}
      </q-card-section>
      <q-card-section v-if="subtitle" class="q-pt-none text-body2 text-grey-8">
        {{ subtitle }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-select
            v-model="form.assigned_to_id"
            :options="userOptions"
            emit-value
            map-options
            label="Affecter à"
            outlined
            dense
            clearable
            hint="Personne : la demande reste à prendre par qui veut"
          />
          <q-input
            v-model="form.instructions"
            label="Consignes"
            outlined
            dense
            autogrow
            type="textarea"
            maxlength="5000"
            autofocus
            hint="Ce qu'il faut regarder, et pourquoi"
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
import { listAssignableUsers, type Check, type CheckPayload } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';

const props = defineProps<{
  modelValue: boolean;
  /** Editing an existing request; null when asking a new one. */
  check: Check | null;
  subtitle?: string | undefined;
  /** What to do with the form: the caller knows the poste(s). */
  save: (payload: CheckPayload) => Promise<void>;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>();

const $q = useQuasar();
const saving = ref(false);
const form = reactive({ assigned_to_id: null as string | null, instructions: '' });
const userOptions = ref<{ label: string; value: string }[]>([]);

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    form.assigned_to_id = props.check?.assigned_to?.id ?? null;
    form.instructions = props.check?.instructions ?? '';
    void loadUsers();
  },
);

async function loadUsers() {
  try {
    userOptions.value = (await listAssignableUsers()).map((u) => ({ label: u.name, value: u.id }));
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Comptes indisponibles') });
  }
}

async function submit() {
  saving.value = true;
  try {
    await props.save({
      assigned_to_id: form.assigned_to_id,
      instructions: form.instructions.trim() || null,
    });
    emit('update:modelValue', false);
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Enregistrement impossible') });
  } finally {
    saving.value = false;
  }
}
</script>
