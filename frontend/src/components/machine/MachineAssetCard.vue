<template>
  <div class="col-12 col-md-6">
    <q-card flat bordered class="full-height">
      <q-card-section class="row items-start no-wrap">
        <div class="col">
          <div class="text-subtitle1">{{ t('assets.card.title') }}</div>
          <div class="text-caption text-muted">{{ t('assets.card.caption') }}</div>
        </div>
        <q-btn
          v-if="asset"
          flat
          dense
          no-caps
          size="sm"
          color="primary"
          icon="qr_code_2"
          :label="t('assets.card.label')"
          :to="{ name: 'asset-labels', query: { ids: asset.id } }"
        />
        <q-btn
          v-if="canWrite && loaded"
          flat
          dense
          no-caps
          size="sm"
          color="primary"
          :icon="asset ? 'edit' : 'add'"
          :label="asset ? t('assets.card.edit') : t('assets.card.add')"
          @click="editing = true"
        />
      </q-card-section>
      <q-separator />

      <q-card-section v-if="failed" class="q-pa-sm">
        <CardLoadError :what="t('assets.card.what')" :loading="loading" @retry="load" />
      </q-card-section>
      <q-card-section v-else-if="loaded && !asset" class="text-caption text-muted">
        {{ t('assets.card.none') }}
      </q-card-section>
      <q-list v-else-if="asset" dense>
        <q-item>
          <q-item-section>
            <q-item-label caption>{{ t('assets.form.status') }}</q-item-label>
            <q-item-label>
              <q-badge :color="assetStatusColor(asset.status)">
                {{ assetStatusLabel(asset.status) }}
              </q-badge>
              <span v-if="asset.status === 'on_loan' && asset.borrower" class="q-ml-sm">
                {{ asset.borrower }}
                <template v-if="asset.loan_due">— {{ formatDate(asset.loan_due) }}</template>
              </span>
            </q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-for="row in rows" :key="row.label">
          <q-item-section>
            <q-item-label caption>{{ row.label }}</q-item-label>
            <q-item-label :class="row.class">{{ row.value }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-if="asset.updated_by">
          <q-item-section class="text-caption text-muted">
            {{
              t('assets.card.updatedBy', {
                name: asset.updated_by,
                date: formatDateTime(asset.updated_at),
              })
            }}
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>

    <AssetEditDialog
      v-model="editing"
      :asset="asset"
      :machine-id="machineId"
      @saved="(a) => (asset = a)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import CardLoadError from 'src/components/CardLoadError.vue';
import AssetEditDialog from 'src/components/asset/AssetEditDialog.vue';
import { intlTag, t } from 'src/i18n';
import {
  assetStatusColor,
  assetStatusLabel,
  getMachineAsset,
  warrantyState,
  type Asset,
} from 'src/services/assets';
import { useAuthStore } from 'src/stores/auth';
import { formatDate, formatDateTime } from 'src/utils/format';

const props = defineProps<{ machineId: string }>();

const auth = useAuthStore();
const canWrite = computed(() => auth.can('asset', 'write'));
const asset = ref<Asset | null>(null);
const loaded = ref(false);
const loading = ref(false);
const failed = ref(false);
const editing = ref(false);

function price(value: string | null): string {
  if (value === null) return '—';
  const amount = Number(value);
  return Number.isFinite(amount)
    ? amount.toLocaleString(intlTag(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : value;
}

const rows = computed(() => {
  const a = asset.value;
  if (!a) return [];
  const warranty = warrantyState(a.warranty_end);
  return [
    { label: t('assets.form.inventory'), value: a.inventory_number ?? '—' },
    { label: t('assets.form.purchaseDate'), value: formatDate(a.purchase_date) },
    {
      label: t('assets.form.warrantyEnd'),
      value:
        warranty === 'none'
          ? t('assets.warranty.none')
          : `${formatDate(a.warranty_end)} — ${t(`assets.warranty.${warranty}`)}`,
      class: warranty === 'expired' ? 'text-negative' : warranty === 'soon' ? 'text-warn' : '',
    },
    { label: t('assets.form.supplier'), value: a.supplier ?? '—' },
    { label: t('assets.form.orderReference'), value: a.order_reference ?? '—' },
    { label: t('assets.form.price'), value: price(a.purchase_price) },
    ...(a.notes ? [{ label: t('assets.form.notes'), value: a.notes }] : []),
  ];
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    asset.value = await getMachineAsset(props.machineId);
    failed.value = false;
    loaded.value = true;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.machineId,
  () => void load(),
  { immediate: true },
);
</script>
