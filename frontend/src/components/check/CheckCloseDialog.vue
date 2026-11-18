<template>
  <!-- Closing: what was found. The note is optional but is the point — it
       stays on the request and goes into the poste's journal. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 480px; max-width: 95vw">
      <q-card-section class="text-h6">{{ t('checks.close.title') }}</q-card-section>
      <q-card-section v-if="check?.instructions" class="q-pt-none text-body2 text-muted">
        {{ t('checks.close.instructions', { text: check.instructions }) }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <q-input
            v-model="note"
            :label="t('checks.close.found')"
            outlined
            dense
            autogrow
            type="textarea"
            maxlength="5000"
            autofocus
            :hint="t('checks.close.foundHint')"
          />
          <!-- When it was done, if not now: never before the request, never
               in the future — the server refuses both. -->
          <q-input
            v-model="closedAt"
            :label="t('checks.close.date')"
            outlined
            dense
            type="datetime-local"
            stack-label
            :min="minInput"
            :max="maxInput"
            :error="dateError !== null"
            :error-message="dateError ?? ''"
            :hint="t('checks.close.dateHint')"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat :label="t('checks.actions.cancel')" />
          <q-btn
            type="submit"
            color="primary"
            :label="t('checks.close.close')"
            :disable="dateError !== null"
            :loading="saving"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { closeCheck } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';
import { t } from 'src/i18n';
import { notify } from 'src/utils/notify';

const props = defineProps<{
  modelValue: boolean;
  /** `created_at`: the earliest date the closing may carry. */
  check: { id: string; instructions: string | null; created_at?: string } | null;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'closed'): void;
}>();

const $q = useQuasar();
const saving = ref(false);
const note = ref('');
// The datetime-local value, in local time; what was there when the dialog
// opened means « now » and is not sent.
const closedAt = ref('');
let openedAt = '';

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const minInput = computed(() =>
  props.check?.created_at ? toLocalInput(new Date(props.check.created_at)) : undefined,
);
const maxInput = ref<string | undefined>(undefined);

const dateError = computed<string | null>(() => {
  if (!closedAt.value || closedAt.value === openedAt) return null;
  const when = new Date(closedAt.value).getTime();
  if (Number.isNaN(when)) return t('checks.close.invalidDate');
  if (when > Date.now() + 5 * 60 * 1000) return t('checks.close.future');
  // To the minute, as the input shows it: the request's own minute is fine.
  const created = props.check?.created_at ? new Date(props.check.created_at).getTime() : null;
  if (created !== null && when < created - (created % 60000)) {
    return t('checks.close.beforeRequest');
  }
  return null;
});

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    note.value = '';
    openedAt = toLocalInput(new Date());
    closedAt.value = openedAt;
    maxInput.value = openedAt;
  },
);

/** The instant to send: none when left at « now », else the date picked. */
function closedAtPayload(): string | null {
  if (!closedAt.value || closedAt.value === openedAt) return null;
  const picked = new Date(closedAt.value).getTime();
  const created = props.check?.created_at ? new Date(props.check.created_at).getTime() : null;
  // The request's own minute, picked: not a second before the request.
  return new Date(created !== null && picked < created ? created : picked).toISOString();
}

async function submit() {
  if (!props.check) return;
  saving.value = true;
  try {
    const at = closedAtPayload();
    await closeCheck(props.check.id, {
      note: note.value.trim() || null,
      ...(at ? { closed_at: at } : {}),
    });
    notify($q, () => ({ type: 'positive', message: t('checks.close.closed') }));
    emit('update:modelValue', false);
    notifyTasksChanged();
    emit('closed');
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('checks.close.closeFailed')),
    }));
  } finally {
    saving.value = false;
  }
}
</script>
