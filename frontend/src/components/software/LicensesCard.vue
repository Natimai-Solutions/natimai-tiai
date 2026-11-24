<template>
  <div>
    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />
    <q-card flat bordered>
      <q-card-section class="row items-start q-col-gutter-md">
        <div class="col text-caption text-muted">
          {{ t('licenses.caption') }}
          <div v-if="restricted" class="q-mt-xs text-warn" data-test="licenses-restricted">
            {{ t('licenses.restricted') }}
          </div>
        </div>
        <div v-if="canWrite" class="col-auto">
          <q-btn
            unelevated
            no-caps
            color="primary"
            icon="add"
            :label="t('licenses.add')"
            data-test="license-add"
            @click="openDialog(null)"
          />
        </div>
      </q-card-section>
      <q-separator />
      <q-table
        :rows="items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        flat
        :pagination="{ rowsPerPage: 50 }"
        :rows-per-page-options="[25, 50, 100, 0]"
        :no-data-label="t('licenses.empty')"
      >
        <template #body-cell-name="props">
          <q-td :props="props">
            <div class="text-weight-medium">{{ props.row.name }}</div>
            <div v-if="props.row.vendor || props.row.reference" class="text-caption text-muted">
              {{ [props.row.vendor, props.row.reference].filter(Boolean).join(' · ') }}
            </div>
          </q-td>
        </template>
        <template #body-cell-covers="props">
          <q-td :props="props">
            <q-chip v-for="p in props.row.patterns" :key="p" dense square>{{ p }}</q-chip>
            <span v-if="props.row.publisher" class="text-caption text-muted">
              ({{ props.row.publisher }})
            </span>
          </q-td>
        </template>
        <template #body-cell-usage="props">
          <q-td :props="props" :data-test="`license-usage-${props.row.id}`">
            <q-btn
              v-if="props.row.installed && canReadMachines"
              flat
              dense
              no-caps
              :color="props.row.over ? 'negative' : 'primary'"
              :label="usageLabel(props.row)"
              :to="{ name: 'machines', query: { license_id: props.row.id } }"
            >
              <q-tooltip>{{ t('licenses.seeMachines') }}</q-tooltip>
            </q-btn>
            <span v-else :class="props.row.over ? 'text-negative' : ''">
              {{ usageLabel(props.row) }}
            </span>
            <q-badge v-if="props.row.over" color="negative" class="q-ml-xs">
              {{ t('licenses.over') }}
            </q-badge>
          </q-td>
        </template>
        <template #body-cell-expires="props">
          <q-td :props="props">
            <span v-if="props.row.expires_on">{{ formatDate(props.row.expires_on) }}</span>
            <q-badge
              :color="expiryColor(props.row.expiry)"
              :outline="props.row.expiry === 'none' || props.row.expiry === 'active'"
              class="q-ml-xs"
            >
              {{ t(`licenses.expiry.${props.row.expiry}`) }}
            </q-badge>
          </q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props" auto-width>
            <q-btn
              flat
              round
              dense
              icon="edit"
              :aria-label="t('licenses.edit')"
              @click="openDialog(props.row)"
            >
              <q-tooltip>{{ t('licenses.edit') }}</q-tooltip>
            </q-btn>
            <q-btn
              flat
              round
              dense
              color="negative"
              icon="delete"
              :aria-label="t('licenses.delete')"
              @click="remove(props.row)"
            >
              <q-tooltip>{{ t('licenses.delete') }}</q-tooltip>
            </q-btn>
          </q-td>
        </template>
      </q-table>
    </q-card>

    <LicenseDialog v-model="dialogOpen" :license="editing" @saved="load" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import LicenseDialog from 'src/components/software/LicenseDialog.vue';
import { t } from 'src/i18n';
import { apiErrorMessage } from 'src/services/errors';
import {
  deleteLicense,
  listLicenses,
  type License,
  type LicenseExpiry,
} from 'src/services/licenses';
import { useAuthStore } from 'src/stores/auth';
import { formatDate } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();

const items = ref<License[]>([]);
const restricted = ref(false);
const loading = ref(false);
const loadError = ref<unknown>(null);
const dialogOpen = ref(false);
const editing = ref<License | null>(null);

// A licence is written for the whole parc: a reader limited to some places
// is shown no button the server would refuse.
const canWrite = computed(() => auth.can('license', 'write') && !restricted.value);
const canReadMachines = computed(() => auth.can('machine', 'read'));

const columns = computed<QTableColumn<License>[]>(() => [
  {
    name: 'name',
    field: 'name',
    label: t('licenses.columns.name'),
    align: 'left',
    sortable: true,
  },
  // On a phone, what the licence covers gives way to its count and its end.
  ...($q.screen.lt.sm
    ? []
    : [
        {
          name: 'covers',
          field: 'patterns' as const,
          label: t('licenses.columns.covers'),
          align: 'left' as const,
        },
      ]),
  {
    name: 'usage',
    field: 'installed',
    label: t('licenses.columns.usage'),
    align: 'left',
    sortable: true,
  },
  {
    name: 'expires',
    field: 'expires_on',
    label: t('licenses.columns.expires'),
    align: 'left',
    sortable: true,
  },
  ...(canWrite.value
    ? [{ name: 'actions', field: 'id' as const, label: '', align: 'right' as const }]
    : []),
]);

function usageLabel(lic: License): string {
  return lic.seats === null
    ? t('licenses.unlimited', { installed: lic.installed })
    : t('licenses.usage', { installed: lic.installed, seats: lic.seats });
}

function expiryColor(state: LicenseExpiry): string {
  if (state === 'expired') return 'negative';
  if (state === 'soon') return 'warning';
  return 'grey-7';
}

function openDialog(lic: License | null): void {
  editing.value = lic;
  dialogOpen.value = true;
}

function remove(lic: License): void {
  liveDialog($q, () => ({
    message: t('licenses.confirmDelete', { name: lic.name }),
    cancel: { flat: true, noCaps: true, label: t('licenses.dialog.cancel') },
    ok: { color: 'negative', noCaps: true, label: t('licenses.delete') },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteLicense(lic.id);
        notify($q, () => ({ type: 'positive', message: t('licenses.deleted') }));
        await load();
      } catch (e) {
        notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
      }
    })();
  });
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const res = await listLicenses();
    items.value = res.items;
    restricted.value = res.restricted;
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

defineExpose({ load });
</script>
