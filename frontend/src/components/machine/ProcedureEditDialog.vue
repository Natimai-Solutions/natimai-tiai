<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 640px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{
          procedure
            ? t('procedures.edit.editTitle', { model: hwModel })
            : t('procedures.edit.newTitle', { model: hwModel })
        }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="q-gutter-md">
          <!-- A note of field knowledge draws « mot de passe BIOS : … »; the
               replaced text stays in the audit log besides. -->
          <q-banner dense rounded class="surface-orange" data-test="procedure-secrets">
            <template #avatar><q-icon name="warning" /></template>
            {{ t('procedures.edit.secrets') }}
          </q-banner>
          <q-input
            v-model="body"
            :label="t('procedures.edit.body')"
            :hint="t('procedures.edit.bodyHint')"
            type="textarea"
            autogrow
            outlined
            autofocus
            :maxlength="PROCEDURE_BODY_MAX"
            counter
            reactive-rules
            :rules="[required]"
            data-test="procedure-body"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn v-close-popup flat :label="t('procedures.edit.cancel')" />
          <q-btn
            type="submit"
            color="primary"
            :label="t('procedures.edit.save')"
            :loading="saving"
            data-test="procedure-save"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
import {
  createProcedure,
  PROCEDURE_BODY_MAX,
  updateProcedure,
  type Procedure,
} from 'src/services/procedures';
import { t } from 'src/i18n';
import { notify } from 'src/utils/notify';

/**
 * Write or edit the procedure note of a model (C11). An edit names the
 * version it was made from: changed by another in between, the parent reads
 * it again (`stale`) and the reader is told.
 */
const props = defineProps<{
  modelValue: boolean;
  hwModel: string;
  /** The note being edited; null to write the model's first. */
  procedure: Procedure | null;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', open: boolean): void;
  (e: 'saved', procedure: Procedure): void;
  /** Changed, deleted or created by another meanwhile: read it again. */
  (e: 'stale'): void;
}>();

const $q = useQuasar();
const body = ref('');
const saving = ref(false);

watch(
  () => props.modelValue,
  (open) => {
    if (open) body.value = props.procedure?.body ?? '';
  },
  { immediate: true },
);

const required = (v: string) => !!(v ?? '').trim() || t('procedures.edit.required');

async function submit() {
  const text = body.value.trim();
  if (!text) return;
  saving.value = true;
  try {
    const saved = props.procedure
      ? await updateProcedure(props.procedure.id, text, props.procedure.updated_at)
      : await createProcedure(props.hwModel, text);
    notify($q, () => ({
      type: 'positive',
      message: props.procedure ? t('procedures.edit.saved') : t('procedures.edit.created'),
    }));
    emit('saved', saved);
    emit('update:modelValue', false);
  } catch (e) {
    const code = apiErrorCode(e);
    if (code === 'procedure.changed' || code === 'procedure.exists') {
      // What the reader typed is not lost: the dialog stays, over the
      // version read again.
      notify($q, () => ({ type: 'warning', message: t('procedures.edit.changed') }));
      emit('stale');
    } else {
      notify($q, () => ({
        type: 'negative',
        message: apiErrorMessage(e, t('procedures.edit.saveFailed')),
      }));
    }
  } finally {
    saving.value = false;
  }
}
</script>
