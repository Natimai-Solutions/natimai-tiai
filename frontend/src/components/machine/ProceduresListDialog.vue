<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 760px; max-width: 95vw" data-test="procedures-list">
      <q-card-section class="row items-center">
        <div class="text-h6">{{ t('procedures.list.title') }}</div>
        <q-space />
        <q-btn
          v-close-popup
          flat
          dense
          round
          icon="close"
          :aria-label="t('procedures.list.close')"
        />
      </q-card-section>
      <q-separator />

      <q-card-section v-if="failed" class="q-pa-sm">
        <CardLoadError :what="t('procedures.list.what')" :loading="loading" @retry="load" />
      </q-card-section>
      <q-card-section v-else-if="loading && !items.length">
        <q-skeleton type="text" />
        <q-skeleton type="text" />
      </q-card-section>
      <q-card-section v-else-if="!items.length" class="text-muted" data-test="procedures-empty">
        {{ t('procedures.list.empty') }}
      </q-card-section>
      <!-- One line per model: opened, it reads the note; the notes of models
           without a poste any more are cleaned up here. -->
      <q-list v-else separator style="max-height: 70vh; overflow-y: auto">
        <q-expansion-item
          v-for="p in items"
          :key="p.id"
          dense-toggle
          :label="p.hw_model"
          :caption="caption(p)"
          data-test="procedure-row"
        >
          <q-card-section style="white-space: pre-line" class="q-pt-none">{{
            p.body
          }}</q-card-section>
          <q-card-actions v-if="canWrite" align="right">
            <q-btn
              flat
              dense
              icon="edit"
              :label="t('procedures.list.edit')"
              data-test="procedure-row-edit"
              @click="openEdit(p)"
            />
            <q-btn
              flat
              dense
              color="negative"
              icon="delete"
              :label="t('procedures.list.delete')"
              data-test="procedure-row-delete"
              @click="confirmDelete(p)"
            />
          </q-card-actions>
        </q-expansion-item>
      </q-list>
    </q-card>

    <ProcedureEditDialog
      v-if="editing"
      v-model="editOpen"
      :hw-model="editing.hw_model"
      :procedure="editing"
      @saved="onChanged"
      @stale="onChanged"
    />
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import CardLoadError from 'src/components/CardLoadError.vue';
import ProcedureEditDialog from 'src/components/machine/ProcedureEditDialog.vue';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
import { deleteProcedure, listProcedures, type ProcedureListItem } from 'src/services/procedures';
import { t } from 'src/i18n';
import { formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

/**
 * Every procedure note (C11) the account may read — those of the models of
 * its scope, all of them for an account that sees every poste — with the
 * postes in service of each model and the last edit. Read when opened.
 */
const props = defineProps<{ modelValue: boolean; canWrite: boolean }>();
const emit = defineEmits<{
  (e: 'update:modelValue', open: boolean): void;
  /** A note was edited or deleted here: the card reads its own again. */
  (e: 'changed'): void;
}>();

const $q = useQuasar();
const items = ref<ProcedureListItem[]>([]);
const loading = ref(false);
const failed = ref(false);
const editing = ref<ProcedureListItem | null>(null);
const editOpen = ref(false);

function caption(p: ProcedureListItem): string {
  const machines = p.machine_count
    ? t('procedures.list.machines', { count: p.machine_count }, p.machine_count)
    : t('procedures.list.noMachine');
  const updated = t('procedures.list.updatedLine', {
    date: formatDateTime(p.updated_at),
    who: p.updated_by,
  });
  return `${machines} · ${updated}`;
}

async function load() {
  loading.value = true;
  try {
    items.value = await listProcedures();
    failed.value = false;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) void load();
  },
  { immediate: true },
);

function openEdit(p: ProcedureListItem) {
  editing.value = p;
  editOpen.value = true;
}

async function onChanged() {
  emit('changed');
  await load();
}

function confirmDelete(p: ProcedureListItem) {
  liveDialog($q, () => ({
    title: t('procedures.delete.title'),
    message: t('procedures.delete.ask', { model: p.hw_model }),
    cancel: true,
    ok: { label: t('procedures.delete.ok'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteProcedure(p.id, p.updated_at);
        notify($q, () => ({ type: 'positive', message: t('procedures.delete.done') }));
      } catch (e) {
        notify($q, () =>
          apiErrorCode(e) === 'procedure.changed'
            ? { type: 'warning', message: t('procedures.edit.changed') }
            : { type: 'negative', message: apiErrorMessage(e, t('procedures.delete.failed')) },
        );
      }
      await onChanged();
    })();
  });
}
</script>
