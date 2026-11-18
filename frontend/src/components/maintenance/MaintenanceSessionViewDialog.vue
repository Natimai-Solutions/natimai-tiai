<template>
  <!-- One recorded visit, read back: when, by whom, the global note, the
       postes done and those left out, each with its own note. Opened from a
       poste's journal and from a room's list of visits. -->
  <!-- The whole screen on a phone, its list scrolling under the title
       (audit U23). -->
  <q-dialog
    :model-value="modelValue"
    :maximized="small"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <q-card
      :class="small ? 'column no-wrap' : ''"
      :style="small ? undefined : 'width: 640px; max-width: 95vw'"
      data-test="visit-card"
    >
      <q-card-section class="text-h6">
        {{
          visit?.room_name
            ? t('maintenance.view.titleIn', { room: visit.room_name })
            : t('maintenance.view.title')
        }}
      </q-card-section>
      <q-card-section v-if="loading" class="row justify-center">
        <q-spinner size="32px" />
      </q-card-section>
      <q-card-section v-else-if="error" class="text-negative">{{
        apiErrorMessage(error.cause, t('maintenance.view.loadFailed'))
      }}</q-card-section>
      <div v-else-if="visit" :class="small ? 'col scroll' : ''">
        <!-- Seen through a poste of the reader's scope: the rest of the visit
             — other postes, and the room and its note when the room is not
             the reader's — is not shown (audit S06). -->
        <q-card-section v-if="visit.partial" class="q-pt-none" data-test="visit-partial">
          <q-banner rounded dense class="surface-blue">
            {{
              visit.note === null
                ? t('maintenance.view.partialNoNote')
                : t('maintenance.view.partial')
            }}
          </q-banner>
        </q-card-section>
        <q-card-section class="q-pt-none q-gutter-xs">
          <div class="row">
            <div class="col-4 text-muted">{{ t('maintenance.view.date') }}</div>
            <div class="col" data-test="visit-date">{{ formatDateTime(visit.performed_at) }}</div>
          </div>
          <div class="row">
            <div class="col-4 text-muted">{{ t('maintenance.view.by') }}</div>
            <div class="col">{{ visit.performed_by }}</div>
          </div>
          <div class="row">
            <div class="col-4 text-muted">{{ t('maintenance.view.generalNote') }}</div>
            <div class="col" style="white-space: pre-line" data-test="visit-note">
              {{ visit.note || '—' }}
            </div>
          </div>
        </q-card-section>
        <q-separator />
        <q-card-section>
          <div class="text-subtitle2 q-mb-xs">
            {{ t('maintenance.view.done', { count: visit.machine_count }) }}
          </div>
          <q-list v-if="visit.items.length" dense data-test="visit-done">
            <q-item v-for="i in visit.items" :key="i.intervention_id" class="q-px-none">
              <q-item-section>
                <q-item-label>{{ i.hostname ?? i.machine_id }}</q-item-label>
                <q-item-label v-if="i.note" caption style="white-space: pre-line">{{
                  i.note
                }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-else class="text-muted">{{ t('maintenance.view.noneDone') }}</div>
          <template v-if="visit.skipped?.length">
            <div class="text-subtitle2 q-mt-md q-mb-xs">{{ t('maintenance.view.skipped') }}</div>
            <q-list dense data-test="visit-skipped">
              <q-item v-for="i in visit.skipped" :key="i.intervention_id" class="q-px-none">
                <q-item-section>
                  <q-item-label>{{ i.hostname ?? i.machine_id }}</q-item-label>
                  <q-item-label v-if="i.note" caption style="white-space: pre-line">{{
                    i.note
                  }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>
        </q-card-section>
      </div>
      <q-separator v-if="small" />
      <q-card-actions align="right" class="q-px-md q-pb-md" :class="small ? 'q-pt-md' : ''">
        <!-- Not on a partial visit: removing it would remove lines and a
             note beyond the reader's scope, which the server refuses. -->
        <q-btn
          v-if="visit && canDelete && !visit.partial"
          flat
          color="negative"
          icon="delete"
          :label="t('maintenance.view.delete')"
          :loading="deleting"
          @click="confirmDelete"
        />
        <q-space />
        <q-btn v-close-popup flat :label="t('maintenance.actions.close')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import { apiErrorMessage } from 'src/services/errors';
import { deleteSession, getSession, type MaintenanceSession } from 'src/services/maintenance';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { t } from 'src/i18n';

const props = defineProps<{ modelValue: boolean; sessionId: string | null }>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'deleted'): void;
}>();

const $q = useQuasar();
const small = computed(() => $q.screen.lt.sm);
const auth = useAuthStore();
const canDelete = computed(() => auth.can('maintenance', 'write'));
const visit = ref<MaintenanceSession | null>(null);
const loading = ref(false);
const deleting = ref(false);
// The failure itself, worded at render: a language changed while the dialog
// is open shows in it too.
const error = ref<{ cause: unknown } | null>(null);

watch(
  () => [props.modelValue, props.sessionId] as const,
  ([open, id]) => {
    if (open && id) void load(id);
  },
  { immediate: true },
);

async function load(id: string) {
  loading.value = true;
  error.value = null;
  visit.value = null;
  try {
    visit.value = await getSession(id);
  } catch (e) {
    error.value = { cause: e };
  } finally {
    loading.value = false;
  }
}

function confirmDelete() {
  const v = visit.value;
  if (!v) return;
  const lines = v.items.length + (v.skipped?.length ?? 0);
  $q.dialog({
    title: t('maintenance.view.deleteTitle'),
    message: t(
      'maintenance.view.deleteAsk',
      { date: formatDateTime(v.performed_at), count: lines },
      lines,
    ),
    cancel: true,
    ok: { label: t('maintenance.actions.delete'), color: 'negative' },
  }).onOk(() => {
    void (async () => {
      deleting.value = true;
      try {
        await deleteSession(v.id);
        $q.notify({ type: 'positive', message: t('maintenance.view.deleted') });
        // The postes' due dates moved: « Mes tâches » and its badge too.
        notifyTasksChanged();
        emit('update:modelValue', false);
        emit('deleted');
      } catch (e) {
        $q.notify({
          type: 'negative',
          message: apiErrorMessage(e, t('maintenance.view.deleteFailed')),
        });
      } finally {
        deleting.value = false;
      }
    })();
  });
}
</script>
