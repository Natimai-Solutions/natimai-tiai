<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="row items-center text-subtitle1">
      {{ t('interventions.history.title') }}
      <q-space />
      <q-btn
        v-if="canWrite"
        dense
        color="primary"
        icon="add"
        :label="t('interventions.history.add')"
        @click="openCreate"
      />
    </q-card-section>
    <q-separator />

    <!-- « Aucune intervention » is a statement about the journal: made only
         once it was read. Not read — the request failed, or the account has
         no right to it — the card says that instead. -->
    <q-card-section v-if="failed" class="q-pa-sm">
      <CardLoadError
        :what="t('interventions.history.what')"
        :loading="loading"
        @retry="emit('retry')"
      />
    </q-card-section>
    <q-card-section v-if="!canRead" class="text-muted">
      {{ t('interventions.history.cannotRead') }}
    </q-card-section>
    <q-card-section v-else-if="!items.length && !loading && !failed" class="text-muted">
      {{ t('interventions.history.empty') }}
    </q-card-section>

    <!-- A timeline rather than a table: a journal is read top to bottom,
         and a note is a paragraph, not a cell. -->
    <q-list v-else-if="items.length" separator>
      <q-item v-for="item in items" :key="item.id" class="q-py-md">
        <q-item-section avatar top>
          <q-avatar :color="interventionKindColor(item.kind)" text-color="white" size="36px">
            <q-icon :name="interventionKindIcon(item.kind)" size="20px" />
          </q-avatar>
        </q-item-section>
        <q-item-section>
          <q-item-label>
            <span class="text-weight-medium">{{ interventionHeading(item) }}</span>
          </q-item-label>
          <q-item-label caption>
            {{ formatDateTime(item.performed_at) }} · {{ item.performed_by }}
            <span v-if="wasEdited(item)"> · {{ t('interventions.history.edited') }}</span>
          </q-item-label>
          <q-item-label v-if="item.note" class="q-mt-xs" style="white-space: pre-line">
            {{ item.note }}
          </q-item-label>
          <!-- A line of a maintenance visit: the visit holds the global note
               and the other postes, one click away. -->
          <q-item-label v-if="item.maintenance_id && canReadMaintenance" class="q-mt-xs">
            <q-btn
              flat
              dense
              no-caps
              size="sm"
              color="primary"
              icon="event_note"
              :label="t('interventions.history.viewSession')"
              class="q-px-xs"
              @click="openSession(item.maintenance_id)"
            />
          </q-item-label>
        </q-item-section>
        <q-item-section v-if="canWrite" side top>
          <q-btn flat dense round icon="more_vert" :aria-label="t('interventions.history.actions')">
            <q-menu>
              <q-list style="min-width: 160px">
                <q-item v-close-popup clickable @click="openEdit(item)">
                  <q-item-section avatar><q-icon name="edit" /></q-item-section>
                  <q-item-section>{{ t('interventions.actions.edit') }}</q-item-section>
                </q-item>
                <q-item v-close-popup clickable class="text-negative" @click="confirmDelete(item)">
                  <q-item-section avatar><q-icon name="delete" /></q-item-section>
                  <q-item-section>{{ t('interventions.actions.delete') }}</q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-btn>
        </q-item-section>
      </q-item>
    </q-list>

    <q-card-section v-if="total > items.length" class="row justify-center q-pt-none">
      <q-btn
        flat
        dense
        :label="t('interventions.history.showMore')"
        :loading="loading"
        @click="emit('more')"
      />
    </q-card-section>

    <MaintenanceSessionViewDialog
      v-model="sessionOpen"
      :session-id="sessionId"
      @deleted="emit('changed')"
    />

    <q-dialog v-model="formOpen">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{ editing ? t('interventions.history.editTitle') : t('interventions.history.newTitle') }}
        </q-card-section>
        <q-form @submit="submit">
          <q-card-section class="q-gutter-md">
            <q-select
              v-model="form.kind"
              :options="kindOptions"
              emit-value
              map-options
              :label="t('interventions.history.kind')"
              outlined
              dense
            />
            <q-input
              v-model="form.title"
              :label="t('interventions.history.titleField')"
              outlined
              dense
              maxlength="200"
              autofocus
            />
            <q-input
              v-model="form.note"
              :label="t('interventions.history.note')"
              outlined
              dense
              autogrow
              maxlength="5000"
              type="textarea"
            />
            <!-- When it happened, not when it is typed: a journal can start
                 before the console did. -->
            <q-input
              v-model="form.performed_at"
              :label="t('interventions.history.date')"
              outlined
              dense
              type="datetime-local"
              stack-label
              :hint="t('interventions.history.dateHint')"
            />
          </q-card-section>
          <q-card-actions align="right" class="q-px-md q-pb-md">
            <q-btn v-close-popup flat :label="t('interventions.actions.cancel')" />
            <q-btn
              type="submit"
              color="primary"
              :label="t('interventions.actions.save')"
              :loading="saving"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useQuasar } from 'quasar';
import CardLoadError from 'src/components/CardLoadError.vue';
import MaintenanceSessionViewDialog from 'src/components/maintenance/MaintenanceSessionViewDialog.vue';
import {
  createIntervention,
  deleteIntervention,
  INTERVENTION_KINDS,
  interventionHeading,
  interventionKindColor,
  interventionKindIcon,
  interventionKindLabel,
  interventionTitle,
  updateIntervention,
  type Intervention,
  type InterventionKind,
} from 'src/services/interventions';
import { notifyTasksChanged } from 'src/composables/useTasksBadge';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { t } from 'src/i18n';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const props = withDefaults(
  defineProps<{
    machineId: string;
    items: Intervention[];
    total: number;
    loading: boolean;
    canWrite: boolean;
    /** The account may read the journal (intervention:read). False for the
     * rare group holding the write alone: it adds lines and sees none. */
    canRead?: boolean;
    /** The last read of the journal failed: `items` is not the journal. */
    failed?: boolean;
  }>(),
  { canRead: true, failed: false },
);
const emit = defineEmits<{ (e: 'changed'): void; (e: 'more'): void; (e: 'retry'): void }>();

const $q = useQuasar();
const auth = useAuthStore();
const canReadMaintenance = computed(() => auth.can('maintenance', 'read'));
const sessionOpen = ref(false);
const sessionId = ref<string | null>(null);
function openSession(id: string) {
  sessionId.value = id;
  sessionOpen.value = true;
}
const formOpen = ref(false);
const saving = ref(false);
const editing = ref<Intervention | null>(null);
const form = reactive({
  kind: 'incident' as InterventionKind,
  title: '',
  note: '',
  performed_at: '',
});

const kindOptions = computed(() =>
  INTERVENTION_KINDS.map((k) => ({ label: interventionKindLabel(k.value), value: k.value })),
);
// The title the form opened on, as shown: a title the server wrote under a
// code, left as is, is not sent — it would replace the code, and the line
// would no longer follow the reader's language.
let shownTitle = '';

/** Edited after the fact — not the same instant written twice at creation. */
function wasEdited(item: Intervention): boolean {
  return new Date(item.updated_at).getTime() - new Date(item.created_at).getTime() > 1000;
}

/** An ISO instant as the datetime-local input wants it, in local time. */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function openCreate() {
  editing.value = null;
  Object.assign(form, {
    kind: 'incident',
    title: '',
    note: '',
    performed_at: toLocalInput(new Date().toISOString()),
  });
  formOpen.value = true;
}

function openEdit(item: Intervention) {
  editing.value = item;
  shownTitle = interventionTitle(item) ?? '';
  Object.assign(form, {
    kind: item.kind as InterventionKind,
    title: shownTitle,
    note: item.note ?? '',
    performed_at: toLocalInput(item.performed_at),
  });
  formOpen.value = true;
}

async function submit() {
  saving.value = true;
  try {
    const performedAt = form.performed_at ? new Date(form.performed_at).toISOString() : null;
    const payload = {
      kind: form.kind,
      title: form.title.trim() || null,
      note: form.note.trim() || null,
      performed_at: performedAt,
    };
    if (editing.value) {
      const { title, ...rest } = payload;
      const keepCode = !!editing.value.title_code && form.title.trim() === shownTitle.trim();
      await updateIntervention(editing.value.id, keepCode ? rest : { ...rest, title });
      notify($q, () => ({ type: 'positive', message: t('interventions.history.updated') }));
    } else {
      await createIntervention(props.machineId, payload);
      notify($q, () => ({ type: 'positive', message: t('interventions.history.created') }));
    }
    formOpen.value = false;
    // A maintenance line moves the poste's due date, and with it « Mes
    // tâches »: the menu badge reads again (audit U19).
    notifyTasksChanged();
    emit('changed');
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('interventions.history.saveFailed')),
    }));
  } finally {
    saving.value = false;
  }
}

function confirmDelete(item: Intervention) {
  liveDialog($q, () => ({
    title: t('interventions.history.deleteTitle'),
    message: t('interventions.history.deleteAsk', {
      heading: interventionHeading(item),
      date: formatDateTime(item.performed_at),
    }),
    cancel: true,
    ok: { label: t('interventions.actions.delete'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteIntervention(item.id);
        notify($q, () => ({ type: 'positive', message: t('interventions.history.deleted') }));
        notifyTasksChanged();
        emit('changed');
      } catch (e) {
        notify($q, () => ({
          type: 'negative',
          message: apiErrorMessage(e, t('interventions.history.deleteFailed')),
        }));
      }
    })();
  });
}
</script>
