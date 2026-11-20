<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-sm">
      <h1 class="text-h5 q-my-none col-auto">{{ t('assets.title') }}</h1>
      <q-space />
      <div v-if="canWrite" class="col-auto row q-gutter-sm">
        <q-btn
          outline
          no-caps
          color="primary"
          icon="add"
          :label="t('assets.newEquipment')"
          @click="openNew"
        />
        <q-btn
          outline
          no-caps
          color="primary"
          icon="upload_file"
          :label="t('assets.importButton')"
          @click="importing = true"
        />
      </div>
      <div class="col-auto">
        <q-btn
          outline
          no-caps
          color="primary"
          icon="qr_code_2"
          :label="
            selected.length
              ? t('assets.labelsSelected', { count: selected.length })
              : room
                ? t('assets.labelsRoom')
                : t('assets.labels')
          "
          :disable="!labelsTarget"
          :to="labelsTarget ?? undefined"
        />
      </div>
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          :aria-label="t('assets.refresh')"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>
    <div class="text-caption text-muted q-mb-md">{{ t('assets.subtitle') }}</div>

    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />

    <q-card flat bordered>
      <q-card-section class="row q-col-gutter-sm items-center">
        <q-input
          v-model="search"
          class="col-12 col-md-4"
          :aria-label="t('assets.search')"
          dense
          outlined
          clearable
          debounce="300"
          :placeholder="t('assets.searchPlaceholder')"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-btn-toggle
          v-model="scope"
          class="col-auto"
          no-caps
          unelevated
          toggle-color="primary"
          :options="scopeOptions"
        />
        <q-select
          v-model="status"
          class="col-6 col-md-2"
          :options="statusOptions"
          emit-value
          map-options
          clearable
          dense
          outlined
          :label="t('assets.filters.status')"
        />
        <q-select
          v-model="warranty"
          class="col-6 col-md-2"
          :options="warrantyOptions"
          emit-value
          map-options
          clearable
          dense
          outlined
          :label="t('assets.filters.warranty')"
        />
        <q-select
          v-if="canReadRooms"
          v-model="room"
          class="col-6 col-md-2"
          :options="roomOptions"
          emit-value
          map-options
          clearable
          dense
          outlined
          :label="t('assets.filters.room')"
        />
        <q-btn
          v-if="status && canReadMachines"
          flat
          no-caps
          dense
          color="primary"
          icon="list"
          class="col-auto"
          :label="t('assets.machinesWithStatus')"
          :to="{ name: 'machines', query: { asset_status: status } }"
        />
      </q-card-section>
      <q-card-section v-if="onlyIds" class="q-pt-none">
        <!-- A scanned label of equipment: that equipment, until let go. -->
        <q-chip removable color="primary" text-color="white" @remove="onlyIds = null">
          {{ t('assets.scanned') }}
        </q-chip>
      </q-card-section>
      <q-separator />
      <q-table
        v-model:pagination="pagination"
        v-model:selected="selected"
        selection="multiple"
        :rows="items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        flat
        :rows-per-page-options="[25, 50, 100]"
        :no-data-label="loadError ? t('assets.empty.loadFailed') : t('assets.empty.none')"
        @request="onRequest"
      >
        <template #body-cell-name="props">
          <q-td :props="props">
            <router-link
              v-if="props.row.machine_id"
              :to="{ name: 'machine-detail', params: { id: props.row.machine_id } }"
              class="row-link text-weight-medium"
            >
              {{ props.row.display_name ?? '—' }}
            </router-link>
            <a
              v-else-if="canWrite"
              href="#"
              class="row-link text-weight-medium"
              @click.prevent="openEdit(props.row)"
              >{{ props.row.display_name ?? '—' }}</a
            >
            <span v-else class="text-weight-medium">{{ props.row.display_name ?? '—' }}</span>
            <div class="text-caption text-muted">
              {{ [props.row.manufacturer, props.row.model].filter(Boolean).join(' ') }}
            </div>
          </q-td>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props">
            <q-badge :color="assetStatusColor(props.row.status)">
              {{ assetStatusLabel(props.row.status) }}
            </q-badge>
          </q-td>
        </template>
        <template #body-cell-warranty="props">
          <q-td :props="props" :class="warrantyClass(props.row.warranty_state)">
            {{ formatDate(props.row.warranty_end) }}
          </q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props" auto-width>
            <q-btn
              v-if="canWrite"
              flat
              dense
              round
              size="sm"
              icon="edit"
              :aria-label="t('assets.form.titleEdit')"
              @click="openEdit(props.row)"
            />
          </q-td>
        </template>
      </q-table>
    </q-card>

    <AssetEditDialog
      v-model="editing"
      :asset="current"
      :machine-id="current?.machine_id ?? null"
      :subtitle="current?.machine_id ? (current.display_name ?? undefined) : undefined"
      @saved="load"
    />
    <AssetImportDialog v-model="importing" @imported="load" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router';
import type { QTableColumn } from 'quasar';
import AssetEditDialog from 'src/components/asset/AssetEditDialog.vue';
import AssetImportDialog from 'src/components/asset/AssetImportDialog.vue';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import {
  ASSET_STATUSES,
  assetKindLabel,
  assetStatusColor,
  assetStatusLabel,
  listAssets,
  warrantyClass,
  type Asset,
  type AssetStatus,
  type ListAssetsParams,
} from 'src/services/assets';
import { listRooms, type Room } from 'src/services/rooms';
import { useAuthStore } from 'src/stores/auth';
import { formatDate } from 'src/utils/format';
import { queryValue } from 'src/utils/machineQuery';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const canWrite = computed(() => auth.can('asset', 'write'));
const canReadRooms = computed(() => auth.can('room', 'read'));
const canReadMachines = computed(() => auth.can('machine', 'read'));

const items = ref<Asset[]>([]);
const selected = ref<Asset[]>([]);
const loading = ref(false);
const loadError = ref<unknown>(null);
const search = ref<string | null>('');
const scope = ref<'all' | 'machines' | 'equipment'>('all');
const status = ref<AssetStatus | null>(null);
const warranty = ref<ListAssetsParams['warranty'] | null>(null);
// A room (« ?room= »: from a room's page) and the assets of a scanned label
// (« ?ids= »: from the QR code's landing page).
const room = ref<string | null>(queryValue(route.query.room) ?? null);
const onlyIds = ref<string | null>(queryValue(route.query.ids) ?? null);
const rooms = ref<Room[]>([]);
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 });
const editing = ref(false);
const importing = ref(false);
const current = ref<Asset | null>(null);

const scopeOptions = computed(() => [
  { label: t('assets.filters.all'), value: 'all' },
  { label: t('assets.filters.machines'), value: 'machines' },
  { label: t('assets.filters.equipment'), value: 'equipment' },
]);
const statusOptions = computed(() =>
  ASSET_STATUSES.map((s) => ({ label: assetStatusLabel(s), value: s })),
);
const roomOptions = computed(() =>
  rooms.value.map((r) => ({
    label: r.building ? `${r.name} — ${r.building.name}` : r.name,
    value: r.id,
  })),
);

// The sheet of labels: the rows ticked, else the room chosen.
const labelsTarget = computed<RouteLocationRaw | null>(() => {
  if (selected.value.length)
    return { name: 'asset-labels', query: { ids: selected.value.map((a) => a.id).join(',') } };
  if (room.value) return { name: 'asset-labels', query: { room_id: room.value } };
  return null;
});

const warrantyOptions = computed(() => [
  { label: t('assets.filters.warrantyActive'), value: 'active' },
  { label: t('assets.filters.warrantySoon'), value: 'soon' },
  { label: t('assets.filters.warrantyExpired'), value: 'expired' },
  { label: t('assets.filters.warrantyNone'), value: 'none' },
]);

const columns = computed<QTableColumn<Asset>[]>(() => [
  { name: 'name', label: t('assets.columns.name'), field: 'display_name', align: 'left' },
  {
    name: 'kind',
    label: t('assets.columns.kind'),
    field: (row) => assetKindLabel(row.kind),
    align: 'left',
  },
  {
    name: 'place',
    label: t('assets.columns.place'),
    field: (row) => [row.building_name, row.room_name].filter(Boolean).join(' — ') || '—',
    align: 'left',
  },
  {
    name: 'inventory',
    label: t('assets.columns.inventory'),
    field: (row) => row.inventory_number ?? '—',
    align: 'left',
  },
  { name: 'status', label: t('assets.columns.status'), field: 'status', align: 'left' },
  {
    name: 'purchase',
    label: t('assets.columns.purchase'),
    field: (row) => formatDate(row.purchase_date),
    align: 'left',
  },
  { name: 'warranty', label: t('assets.columns.warranty'), field: 'warranty_end', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const params: ListAssetsParams = {
      page: pagination.value.page,
      page_size: pagination.value.rowsPerPage,
    };
    if (search.value?.trim()) params.search = search.value.trim();
    if (scope.value !== 'all') params.with_machine = scope.value === 'machines';
    if (status.value) params.status = status.value;
    if (warranty.value) params.warranty = warranty.value;
    if (room.value) params.room_id = room.value;
    if (onlyIds.value) params.ids = onlyIds.value;
    const res = await listAssets(params);
    items.value = res.items;
    pagination.value.rowsNumber = res.total;
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  } finally {
    loading.value = false;
  }
}

function onRequest(props: { pagination: { page: number; rowsPerPage: number } }): void {
  pagination.value.page = props.pagination.page;
  pagination.value.rowsPerPage = props.pagination.rowsPerPage;
  void load();
}

function openNew(): void {
  current.value = null;
  editing.value = true;
}

function openEdit(asset: Asset): void {
  current.value = asset;
  editing.value = true;
}

watch([search, scope, status, warranty, room, onlyIds], () => {
  pagination.value.page = 1;
  // The room and the scanned label stay in the address, for a reload.
  const query: Record<string, string> = {};
  if (room.value) query.room = room.value;
  if (onlyIds.value) query.ids = onlyIds.value;
  void router.replace({ query });
  void load();
});

onMounted(() => {
  void load();
  if (canReadRooms.value)
    listRooms()
      .then((list) => (rooms.value = list))
      .catch(() => (rooms.value = []));
});
</script>
