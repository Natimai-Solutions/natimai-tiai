<template>
  <q-card flat bordered class="q-mb-md" data-test="procedure-card">
    <q-card-section class="row items-center text-subtitle1">
      <span>
        {{
          info?.hw_model
            ? t('procedures.card.titleWithModel', { model: info.hw_model })
            : t('procedures.card.title')
        }}
      </span>
      <q-space />
      <q-btn
        flat
        dense
        no-caps
        icon="menu_book"
        :label="t('procedures.card.all')"
        data-test="procedure-all"
        @click="listOpen = true"
      />
    </q-card-section>
    <q-separator />

    <q-card-section v-if="failed" class="q-pa-sm">
      <CardLoadError :what="t('procedures.card.what')" :loading="loading" @retry="load" />
    </q-card-section>
    <q-card-section v-else-if="loading && !info">
      <q-skeleton type="text" />
    </q-card-section>
    <template v-else-if="info">
      <q-card-section v-if="!info.hw_model" class="text-muted" data-test="procedure-unknown">
        {{ t('procedures.card.unknownModel') }}
      </q-card-section>
      <template v-else-if="info.procedure">
        <!-- Plain text, kept as typed: no Markdown, no link made clickable. -->
        <q-card-section style="white-space: pre-line" data-test="procedure-body-text">{{
          info.procedure.body
        }}</q-card-section>
        <q-card-section class="row items-center q-pt-none">
          <span class="text-caption text-muted">
            {{
              t('procedures.card.updated', {
                who: info.procedure.updated_by,
                date: formatDateTime(info.procedure.updated_at),
              })
            }}
          </span>
          <q-space />
          <template v-if="canWrite">
            <q-btn
              flat
              dense
              icon="edit"
              :label="t('procedures.card.edit')"
              data-test="procedure-edit"
              @click="editOpen = true"
            />
            <q-btn
              flat
              dense
              color="negative"
              icon="delete"
              :label="t('procedures.card.delete')"
              data-test="procedure-delete"
              @click="confirmDelete"
            />
          </template>
        </q-card-section>
      </template>
      <q-card-section v-else class="row items-center">
        <span class="text-muted" data-test="procedure-none">{{ t('procedures.card.none') }}</span>
        <q-space />
        <q-btn
          v-if="canWrite"
          dense
          color="primary"
          icon="edit_note"
          :label="t('procedures.card.write')"
          data-test="procedure-write"
          @click="editOpen = true"
        />
      </q-card-section>
      <q-card-section
        v-if="info.scope_limited && auth.can('procedure', 'write')"
        class="text-caption text-muted q-pt-none"
        data-test="procedure-scope-limited"
      >
        {{ t('procedures.card.scopeLimited') }}
      </q-card-section>
    </template>

    <ProcedureEditDialog
      v-if="info?.hw_model"
      v-model="editOpen"
      :hw-model="info.hw_model"
      :procedure="info.procedure"
      @saved="load"
      @stale="load"
    />
    <ProceduresListDialog v-model="listOpen" :can-write="canWrite" @changed="load" />
  </q-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import CardLoadError from 'src/components/CardLoadError.vue';
import ProcedureEditDialog from 'src/components/machine/ProcedureEditDialog.vue';
import ProceduresListDialog from 'src/components/machine/ProceduresListDialog.vue';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
import {
  deleteProcedure,
  getMachineProcedure,
  type MachineProcedure,
} from 'src/services/procedures';
import { useAuthStore } from 'src/stores/auth';
import { t } from 'src/i18n';
import { formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

/**
 * « Procédure pour ce modèle » (C11), at the head of a poste's
 * « Interventions » tab — where the technician is when repairing: the note
 * written once for the poste's `hw_model`. Written by the accounts that hold
 * `procedure:write` and see every poste; a confined account reads only.
 */
const props = defineProps<{ machineId: string }>();

const $q = useQuasar();
const auth = useAuthStore();
const info = ref<MachineProcedure | null>(null);
const loading = ref(false);
const failed = ref(false);
const editOpen = ref(false);
const listOpen = ref(false);

const canWrite = computed(
  () => auth.can('procedure', 'write') && info.value !== null && !info.value.scope_limited,
);

async function load() {
  const id = props.machineId;
  loading.value = true;
  try {
    const answer = await getMachineProcedure(id);
    if (id !== props.machineId) return;
    info.value = answer;
    failed.value = false;
  } catch {
    if (id === props.machineId) failed.value = true;
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.machineId,
  () => {
    info.value = null;
    void load();
  },
  { immediate: true },
);

function confirmDelete() {
  const note = info.value?.procedure;
  if (!note) return;
  liveDialog($q, () => ({
    title: t('procedures.delete.title'),
    message: t('procedures.delete.ask', { model: note.hw_model }),
    cancel: true,
    ok: { label: t('procedures.delete.ok'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteProcedure(note.id, note.updated_at);
        notify($q, () => ({ type: 'positive', message: t('procedures.delete.done') }));
      } catch (e) {
        notify($q, () =>
          apiErrorCode(e) === 'procedure.changed'
            ? { type: 'warning', message: t('procedures.edit.changed') }
            : { type: 'negative', message: apiErrorMessage(e, t('procedures.delete.failed')) },
        );
      }
      await load();
    })();
  });
}
</script>
