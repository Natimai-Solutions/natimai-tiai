<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-sm">
      <h1 class="text-h5 q-my-none col-auto">{{ t('reports.title') }}</h1>
      <q-space />
      <div class="col-auto">
        <q-btn-toggle
          v-model="state"
          no-caps
          unelevated
          toggle-color="primary"
          :options="stateOptions"
        />
      </div>
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          :aria-label="t('reports.refresh')"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>
    <div class="text-caption text-muted q-mb-md">{{ t('reports.subtitle') }}</div>
    <q-banner v-if="loaded && !enabled" class="surface-orange q-mb-md" rounded dense>
      {{ t('reports.disabledBanner') }}
    </q-banner>

    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />

    <div v-if="loaded && !items.length && !loadError" class="text-muted q-pa-md">
      {{ t('reports.empty.none') }}
    </div>
    <q-card v-for="r in items" :key="r.id" flat bordered class="q-mb-sm">
      <q-card-section>
        <div class="row items-center q-gutter-sm">
          <router-link
            v-if="r.machine_id"
            :to="{ name: 'machine-detail', params: { id: r.machine_id } }"
            class="row-link text-weight-medium"
          >
            {{ r.subject ?? '—' }}
          </router-link>
          <span v-else class="text-weight-medium">
            {{ r.subject ?? '—' }}
            <span class="text-caption text-muted">({{ t('reports.equipment') }})</span>
          </span>
          <span class="text-caption text-muted">{{ place(r) }}</span>
          <q-space />
          <q-badge outline color="primary">{{ t(`checks.category.${r.category}`) }}</q-badge>
          <q-badge :color="statusColor(r.status)">{{ t(`reports.status.${r.status}`) }}</q-badge>
          <span class="text-caption text-muted">{{ formatDateTime(r.created_at) }}</span>
        </div>
        <div class="q-mt-sm" style="white-space: pre-line">{{ r.text }}</div>
        <div v-if="r.contact" class="text-caption q-mt-xs">
          {{ t('reports.contact', { contact: r.contact }) }}
        </div>
        <div v-if="r.handled_by" class="text-caption text-muted q-mt-xs">
          {{ t('reports.handled', { by: r.handled_by, date: formatDateTime(r.handled_at) }) }}
          <span v-if="r.handling_note"> — {{ r.handling_note }}</span>
        </div>
      </q-card-section>
      <q-card-actions v-if="canWrite && r.status === 'new'" align="right">
        <q-btn
          v-if="r.machine_id && !r.open_check_id && canCheck"
          flat
          no-caps
          color="primary"
          icon="fact_check"
          :label="t('reports.actions.convert')"
          @click="openConvert(r)"
        />
        <q-btn
          v-if="r.machine_id && r.open_check_id && canCheck"
          flat
          no-caps
          color="primary"
          icon="link"
          :label="t('reports.actions.attach')"
          @click="attach(r)"
        />
        <q-btn
          flat
          no-caps
          icon="done"
          :label="t('reports.actions.close')"
          @click="openNote(r, false)"
        />
        <q-btn
          flat
          no-caps
          color="negative"
          icon="block"
          :label="t('reports.actions.reject')"
          @click="openNote(r, true)"
        />
      </q-card-actions>
    </q-card>
    <div v-if="total > items.length" class="row justify-center q-mt-md">
      <q-pagination v-model="page" :max="Math.ceil(total / pageSize)" @update:model-value="load" />
    </div>

    <!-- Into a verification: who, how urgent, by when. -->
    <q-dialog v-model="convertOpen">
      <q-card style="width: 480px; max-width: 95vw">
        <q-card-section class="text-h6">{{ t('reports.actions.convert') }}</q-card-section>
        <q-card-section class="q-gutter-md">
          <div class="text-body2" style="white-space: pre-line">{{ current?.text }}</div>
          <q-select
            v-model="convertForm.assigned_to_id"
            :options="assignable"
            emit-value
            map-options
            clearable
            outlined
            dense
            :label="t('reports.actions.assignTo')"
          />
          <q-select
            v-model="convertForm.priority"
            :options="priorityOptions"
            emit-value
            map-options
            outlined
            dense
            :label="t('checks.request.priority')"
          />
          <q-input
            v-model="convertForm.due_date"
            type="date"
            stack-label
            clearable
            outlined
            dense
            :label="t('checks.request.dueDate')"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat no-caps :label="t('reports.actions.cancel')" />
          <q-btn
            color="primary"
            no-caps
            :label="t('reports.actions.confirm')"
            :loading="busy"
            @click="convert"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Closed or rejected, with a note. -->
    <q-dialog v-model="noteOpen">
      <q-card style="width: 480px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{ rejecting ? t('reports.actions.reject') : t('reports.actions.close') }}
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="note"
            type="textarea"
            autogrow
            outlined
            maxlength="2000"
            :label="t('reports.actions.note')"
            :hint="t('reports.actions.noteHint')"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat no-caps :label="t('reports.actions.cancel')" />
          <q-btn
            :color="rejecting ? 'negative' : 'primary'"
            no-caps
            :label="t('reports.actions.confirm')"
            :loading="busy"
            @click="close"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { notifyReportsChanged } from 'src/composables/useReportsBadge';
import { t } from 'src/i18n';
import { CHECK_PRIORITIES, listAssignableUsers, type CheckPriority } from 'src/services/checks';
import { apiErrorMessage } from 'src/services/errors';
import {
  attachReport,
  closeReport,
  convertReport,
  listReports,
  type Report,
} from 'src/services/reports';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();
const canWrite = computed(() => auth.can('report', 'write'));
const canCheck = computed(() => auth.can('check', 'write'));

const state = ref<'new' | 'handled' | 'all'>('new');
const items = ref<Report[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 50;
const enabled = ref(true);
const loaded = ref(false);
const loading = ref(false);
const loadError = ref<unknown>(null);
const busy = ref(false);
const current = ref<Report | null>(null);
const convertOpen = ref(false);
const noteOpen = ref(false);
const rejecting = ref(false);
const note = ref('');
const assignable = ref<{ label: string; value: string }[]>([]);
const convertForm = reactive({
  assigned_to_id: null as string | null,
  priority: 'normal' as CheckPriority,
  due_date: '' as string | null,
});

const stateOptions = computed(() =>
  (['new', 'handled', 'all'] as const).map((s) => ({ label: t(`reports.states.${s}`), value: s })),
);
const priorityOptions = computed(() =>
  CHECK_PRIORITIES.map((p) => ({ label: t(`checks.priority.${p}`), value: p })),
);

function place(r: Report): string {
  return [r.building_name, r.room_name].filter(Boolean).join(' — ');
}

function statusColor(status: string): string {
  if (status === 'new') return 'orange-8';
  if (status === 'rejected') return 'grey-7';
  return 'positive';
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const res = await listReports({ state: state.value, page: page.value, page_size: pageSize });
    items.value = res.items;
    total.value = res.total;
    enabled.value = res.enabled;
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  } finally {
    loading.value = false;
    loaded.value = true;
  }
}

async function done(): Promise<void> {
  notify($q, () => ({ type: 'positive', message: t('reports.actions.done') }));
  notifyReportsChanged();
  await load();
}

function failed(e: unknown): void {
  notify($q, () => ({
    type: 'negative',
    message: apiErrorMessage(e, t('reports.actions.failed')),
  }));
}

async function openConvert(r: Report): Promise<void> {
  current.value = r;
  Object.assign(convertForm, { assigned_to_id: null, priority: 'normal', due_date: '' });
  convertOpen.value = true;
  try {
    assignable.value = (await listAssignableUsers(r.machine_id ?? undefined)).map((u) => ({
      label: u.name,
      value: u.id,
    }));
  } catch {
    assignable.value = [];
  }
}

async function convert(): Promise<void> {
  if (!current.value) return;
  busy.value = true;
  try {
    await convertReport(current.value.id, {
      assigned_to_id: convertForm.assigned_to_id,
      priority: convertForm.priority,
      due_date: convertForm.due_date || null,
    });
    convertOpen.value = false;
    await done();
  } catch (e) {
    failed(e);
  } finally {
    busy.value = false;
  }
}

async function attach(r: Report): Promise<void> {
  try {
    await attachReport(r.id);
    await done();
  } catch (e) {
    failed(e);
  }
}

function openNote(r: Report, reject: boolean): void {
  current.value = r;
  rejecting.value = reject;
  note.value = '';
  noteOpen.value = true;
}

async function close(): Promise<void> {
  if (!current.value) return;
  busy.value = true;
  try {
    await closeReport(current.value.id, note.value.trim() || null, rejecting.value);
    noteOpen.value = false;
    await done();
  } catch (e) {
    failed(e);
  } finally {
    busy.value = false;
  }
}

watch(state, () => {
  page.value = 1;
  void load();
});

onMounted(load);
</script>
