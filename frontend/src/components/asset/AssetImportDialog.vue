<template>
  <!-- Two steps: check, then import. The server reads the file and says what
       each row would change before anything is written. -->
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 900px; max-width: 95vw">
      <q-card-section class="text-h6">{{ t('assets.import.title') }}</q-card-section>
      <q-card-section class="q-pt-none text-body2 text-muted">
        {{ t('assets.import.intro', { rows: importMaxRows(), mb: IMPORT_MAX_MB }) }}
      </q-card-section>
      <q-card-section class="row items-center q-gutter-sm">
        <q-file
          v-model="file"
          class="col"
          :label="t('assets.import.file')"
          accept=".csv,.txt,.xlsx"
          outlined
          dense
          clearable
          @update:model-value="result = null"
        >
          <template #prepend><q-icon name="attach_file" /></template>
        </q-file>
        <q-btn
          color="primary"
          outline
          no-caps
          :label="t('assets.import.preview')"
          :disable="!file"
          :loading="checking"
          @click="run(true)"
        />
      </q-card-section>

      <q-card-section v-if="result" class="q-pt-none">
        <div class="row q-gutter-sm q-mb-sm">
          <q-badge
            v-for="(count, action) in result.counts"
            :key="action"
            :color="actionColor(action)"
            outline
          >
            {{ t(`assets.import.action.${action}`) }} : {{ count }}
          </q-badge>
        </div>
        <q-table
          :rows="result.rows"
          :columns="columns"
          row-key="line"
          flat
          dense
          :pagination="{ rowsPerPage: 10 }"
        >
          <template #body-cell-action="props">
            <q-td :props="props">
              <q-badge :color="actionColor(props.row.action)">
                {{ t(`assets.import.action.${props.row.action}`) }}
              </q-badge>
              <div v-if="props.row.errors.length" class="text-caption text-negative">
                {{ errorsText(props.row.errors) }}
              </div>
            </q-td>
          </template>
        </q-table>
      </q-card-section>

      <q-card-actions align="right" class="q-px-md q-pb-md">
        <q-btn v-close-popup flat :label="t('assets.form.cancel')" />
        <q-btn
          color="primary"
          no-caps
          :label="t('assets.import.apply', { count: writable }, writable)"
          :disable="!result || !result.dry_run || writable === 0"
          :loading="applying"
          @click="run(false)"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import { intlTag, t } from 'src/i18n';
import {
  assetStatusLabel,
  importAssets,
  type ImportResult,
  type ImportRow,
} from 'src/services/assets';
import { formatDate } from 'src/utils/format';
import { apiErrorMessage } from 'src/services/errors';
import { notify } from 'src/utils/notify';

const dialog = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'imported'): void;
}>();

const $q = useQuasar();
const file = ref<File | null>(null);
const result = ref<ImportResult | null>(null);
const checking = ref(false);
const applying = ref(false);

watch(
  () => dialog.modelValue,
  (open) => {
    if (open) {
      file.value = null;
      result.value = null;
    }
  },
);

const writable = computed(
  () => (result.value?.counts.create ?? 0) + (result.value?.counts.update ?? 0),
);

const columns = computed<QTableColumn<ImportRow>[]>(() => [
  { name: 'line', label: t('assets.import.columns.line'), field: 'line', align: 'left' },
  { name: 'serial', label: t('assets.import.columns.serial'), field: 'serial', align: 'left' },
  {
    name: 'machine',
    label: t('assets.import.columns.machine'),
    field: (row) => row.hostname ?? '—',
    align: 'left',
  },
  { name: 'action', label: t('assets.import.columns.action'), field: 'action', align: 'left' },
  {
    name: 'changes',
    label: t('assets.import.columns.changes'),
    field: (row) => changesText(row.changes),
    align: 'left',
    style: 'white-space: normal',
  },
]);

// The server's limits (`asset.importer`, `MAX_IMPORT_BYTES`), said up front.
const IMPORT_MAX_MB = 8;
function importMaxRows(): string {
  return (5000).toLocaleString(intlTag());
}

// A change's field as the asset form names it, its value as the console
// writes it: « Date d’achat : 01/03/2024 », not « purchase_date = 2024-03-01 ».
const FIELD_LABELS: Record<string, string> = {
  inventory_number: 'assets.form.inventory',
  status: 'assets.form.status',
  purchase_date: 'assets.form.purchaseDate',
  supplier: 'assets.form.supplier',
  order_reference: 'assets.form.orderReference',
  warranty_end: 'assets.form.warrantyEnd',
  purchase_price: 'assets.form.price',
  notes: 'assets.form.notes',
};

function changeValue(field: string, value: string | null): string {
  if (value === null) return '—';
  if (field === 'status') return assetStatusLabel(value);
  if (field === 'purchase_date' || field === 'warranty_end') return formatDate(value);
  if (field === 'purchase_price') {
    const amount = Number(value);
    return Number.isFinite(amount)
      ? amount.toLocaleString(intlTag(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : value;
  }
  return value;
}

function changesText(changes: Record<string, string | null>): string {
  return (
    Object.entries(changes)
      .map(([field, value]) => {
        const key = FIELD_LABELS[field];
        const label = key ? t(key) : field;
        return t('assets.import.change', { field: label, value: changeValue(field, value) });
      })
      .join(' · ') || '—'
  );
}

function actionColor(action: string): string {
  switch (action) {
    case 'create':
    case 'update':
      return 'positive';
    case 'unchanged':
      return 'grey-7';
    default:
      return 'negative';
  }
}

function errorsText(errors: string[]): string {
  return errors
    .map((e) => {
      const key = `assets.import.error.${e}`;
      const text = t(key);
      return text === key ? e : text;
    })
    .join(', ');
}

async function run(dryRun: boolean): Promise<void> {
  if (!file.value) return;
  const busy = dryRun ? checking : applying;
  busy.value = true;
  try {
    const res = await importAssets(file.value, dryRun);
    if (dryRun) {
      result.value = res;
    } else {
      const count = (res.counts.create ?? 0) + (res.counts.update ?? 0);
      notify($q, () => ({
        type: 'positive',
        message: t('assets.import.applied', { count }, count),
      }));
      emit('imported');
      emit('update:modelValue', false);
    }
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('assets.import.failed')),
    }));
  } finally {
    busy.value = false;
  }
}
</script>
