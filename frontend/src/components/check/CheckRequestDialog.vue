<template>
  <!-- Asking for a verification: who should look, and at what. One poste
       or a selection — the same form, the count in the title. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 480px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{ check ? t('checks.request.edit') : t('checks.request.ask') }}
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
            :label="t('checks.request.assignTo')"
            outlined
            dense
            clearable
            :hint="t('checks.request.assignHint')"
          />
          <div class="row q-col-gutter-sm">
            <q-select
              v-model="form.priority"
              class="col-12 col-sm-4"
              :options="priorityOptions"
              emit-value
              map-options
              outlined
              dense
              :label="t('checks.request.priority')"
            />
            <q-select
              v-model="form.category"
              class="col-12 col-sm-4"
              :options="categoryOptions"
              emit-value
              map-options
              clearable
              outlined
              dense
              :label="t('checks.request.category')"
            />
            <q-input
              v-model="form.due_date"
              class="col-12 col-sm-4"
              type="date"
              outlined
              dense
              stack-label
              clearable
              :label="t('checks.request.dueDate')"
              :hint="t('checks.request.dueHint')"
            />
          </div>
          <q-input
            v-model="form.instructions"
            :label="t('checks.request.instructions')"
            outlined
            dense
            autogrow
            type="textarea"
            maxlength="5000"
            autofocus
            :hint="t('checks.request.instructionsHint')"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat :label="t('checks.actions.cancel')" />
          <q-btn
            type="submit"
            color="primary"
            :label="t('checks.actions.save')"
            :loading="saving"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, toRefs, watch } from 'vue';
import { useQuasar } from 'quasar';
import {
  CHECK_CATEGORIES,
  CHECK_PRIORITIES,
  listAssignableUsers,
  type Check,
  type CheckPayload,
  type CheckPriority,
} from 'src/services/checks';
import { checkInstructionsText } from 'src/services/alerts';
import { apiErrorMessage } from 'src/services/errors';
import { t } from 'src/i18n';
import { useDraft } from 'src/composables/useDraft';
import { notify } from 'src/utils/notify';

const props = defineProps<{
  modelValue: boolean;
  /** Editing an existing request; null when asking a new one. */
  check: Check | null;
  subtitle?: string | undefined;
  /** The poste, when there is one: only who can see it is offered. */
  machineId?: string | undefined;
  /** The postes of a selection, when the request is for several at once. */
  machineIds?: string[] | undefined;
  /** What to do with the form: the caller knows the poste(s). */
  save: (payload: CheckPayload) => Promise<void>;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>();

const $q = useQuasar();
const saving = ref(false);
const form = reactive({
  assigned_to_id: null as string | null,
  instructions: '',
  priority: 'normal' as CheckPriority,
  category: null as string | null,
  due_date: '' as string | null,
});
const priorityOptions = computed(() =>
  CHECK_PRIORITIES.map((p) => ({ label: t(`checks.priority.${p}`), value: p })),
);
const categoryOptions = computed(() =>
  CHECK_CATEGORIES.map((c) => ({ label: t(`checks.category.${c}`), value: c })),
);
// The instructions as the dialog opened on them: the server's coded ones
// (a verification opened for an alert) worded in the reader's language.
// Sent back only when changed — a reassignment keeps them coded, readable in
// every language, rather than freezing the words of whoever reassigned.
const initialInstructions = ref('');
// Who can be given the task, as the server lists them.
const assignable = ref<{ label: string; value: string }[]>([]);
// The current assignee, deactivated since (or out of reach), is not among
// the choices: named, not shown as a raw id — and kept if left alone. Worded
// at render time, in the language shown.
const userOptions = computed(() => {
  const current = props.check?.assigned_to;
  if (!current || assignable.value.some((o) => o.value === current.id)) return assignable.value;
  const label =
    current.active === false
      ? t('checks.request.deactivated', { name: current.name })
      : current.reachable === false
        ? t('checks.request.unreachable', { name: current.name })
        : current.name;
  return [{ label, value: current.id }, ...assignable.value];
});

// What is being typed survives a session that ends mid-form: the console goes
// to the login page and the dialog with it; reopened, the text is back — for
// the account that typed it (`useDraft`), and for what it was typed about. Per
// poste, or per request edited: a draft never opens on another poste. For a
// selection: on the very same postes only, compared id by id rather than by a
// digest that two selections could share; and nothing is kept for a form that
// knows neither.
//
// Where the draft goes is settled as the dialog opens, and holds until it
// closes: the list empties its selection as soon as the requests are made,
// before this dialog closes, and the draft just sent must still be found to
// be forgotten.
const draftSlot = ref<{ key: string | null; scope: string }>({ key: null, scope: '' });
function slotNow(): { key: string | null; scope: string } {
  if (props.check) return { key: `check-edit:${props.check.id}`, scope: '' };
  if (props.machineId) return { key: `check-request:${props.machineId}`, scope: '' };
  if (!props.machineIds?.length) return { key: null, scope: '' };
  return { key: 'check-request:selection', scope: [...props.machineIds].sort().join(',') };
}
const draft = useDraft(() => draftSlot.value.key, toRefs(form), {
  scope: () => draftSlot.value.scope,
});

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      // Closed by the reader (sent or cancelled): nothing left to keep. A
      // session that ends unmounts the page instead, and keeps the draft.
      draft.clear();
      return;
    }
    draftSlot.value = slotNow();
    form.assigned_to_id = props.check?.assigned_to?.id ?? null;
    form.priority = props.check?.priority ?? 'normal';
    form.category = props.check?.category ?? null;
    form.due_date = props.check?.due_date ?? '';
    initialInstructions.value = (props.check ? checkInstructionsText(props.check) : null) ?? '';
    form.instructions = initialInstructions.value;
    draft.restore();
    void loadUsers();
  },
);

async function loadUsers() {
  try {
    assignable.value = (await listAssignableUsers(props.check?.machine_id ?? props.machineId)).map(
      (u) => ({ label: u.name, value: u.id }),
    );
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('checks.request.usersFailed')),
    }));
  }
}

async function submit() {
  saving.value = true;
  try {
    const instructions = form.instructions.trim();
    const payload: CheckPayload = {
      assigned_to_id: form.assigned_to_id,
      priority: form.priority,
      category: form.category || null,
      due_date: form.due_date || null,
    };
    if (!props.check || instructions !== initialInstructions.value.trim()) {
      payload.instructions = instructions || null;
    }
    await props.save(payload);
    emit('update:modelValue', false);
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('checks.request.saveFailed')),
    }));
  } finally {
    saving.value = false;
  }
}
</script>
