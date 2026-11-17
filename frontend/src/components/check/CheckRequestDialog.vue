<template>
  <!-- Asking for a verification: who should look, and at what. One poste
       or a selection — the same form, the count in the title. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 480px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{ check ? 'Modifier la demande' : 'Demander une vérification' }}
      </q-card-section>
      <q-card-section v-if="subtitle" class="q-pt-none text-body2 text-muted">
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
import { reactive, ref, toRefs, watch } from 'vue';
import { useQuasar } from 'quasar';
import { listAssignableUsers, type Check, type CheckPayload } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';
import { useDraft } from 'src/composables/useDraft';

const props = defineProps<{
  modelValue: boolean;
  /** Editing an existing request; null when asking a new one. */
  check: Check | null;
  subtitle?: string | undefined;
  /** The poste, when there is one: only who can see it is offered. */
  machineId?: string | undefined;
  /** What to do with the form: the caller knows the poste(s). */
  save: (payload: CheckPayload) => Promise<void>;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>();

const $q = useQuasar();
const saving = ref(false);
const form = reactive({ assigned_to_id: null as string | null, instructions: '' });
const userOptions = ref<{ label: string; value: string }[]>([]);

// What is being typed survives a session that ends mid-form: the console goes
// to the login page and the dialog with it; reopened, the text is back. Per
// poste (or per request edited): a draft never opens on another poste.
const draft = useDraft(
  () =>
    props.check
      ? `check-edit:${props.check.id}`
      : `check-request:${props.machineId ?? 'selection'}`,
  toRefs(form),
);

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      // Closed by the reader (sent or cancelled): nothing left to keep. A
      // session that ends unmounts the page instead, and keeps the draft.
      draft.clear();
      return;
    }
    form.assigned_to_id = props.check?.assigned_to?.id ?? null;
    form.instructions = props.check?.instructions ?? '';
    draft.restore();
    void loadUsers();
  },
);

async function loadUsers() {
  try {
    const options = (await listAssignableUsers(props.check?.machine_id ?? props.machineId)).map(
      (u) => ({ label: u.name, value: u.id }),
    );
    // The current assignee, deactivated since (or out of reach), is not among
    // the choices: named, not shown as a raw id — and kept if left alone.
    const current = props.check?.assigned_to;
    if (current && !options.some((o) => o.value === current.id)) {
      options.unshift({
        label:
          current.active === false
            ? `${current.name} (désactivé)`
            : current.reachable === false
              ? `${current.name} (ne voit plus ce poste)`
              : current.name,
        value: current.id,
      });
    }
    userOptions.value = options;
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
