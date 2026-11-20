<template>
  <!-- A sheet of labels to print: outside the console's frame, so that the
       printer gets the labels and nothing else. -->
  <div class="labels-page">
    <div class="labels-toolbar row items-center q-gutter-sm q-pa-md">
      <q-btn flat no-caps icon="arrow_back" :label="t('assets.labelsPage.back')" @click="back" />
      <div class="text-h6">{{ t('assets.labelsPage.title') }}</div>
      <q-space />
      <div class="text-caption text-muted">{{ t('assets.labelsPage.hint') }}</div>
      <q-btn
        color="primary"
        icon="print"
        no-caps
        :label="t('assets.labelsPage.print')"
        :disable="!labels.length"
        @click="print"
      />
    </div>
    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />
    <div v-if="!loading && !labels.length && !loadError" class="q-pa-md text-muted">
      {{ t('assets.labelsPage.none') }}
    </div>
    <div class="labels-grid q-pa-md">
      <div v-for="label in labels" :key="label.id" class="label">
        <svg
          class="label-qr"
          :viewBox="`-2 -2 ${label.qr.size + 4} ${label.qr.size + 4}`"
          role="img"
          :aria-label="label.name"
          shape-rendering="crispEdges"
        >
          <rect x="-2" y="-2" :width="label.qr.size + 4" :height="label.qr.size + 4" fill="#fff" />
          <path :d="label.qr.path" fill="#000" />
        </svg>
        <div class="label-text">
          <div class="label-name">{{ label.name }}</div>
          <div v-if="label.inventory" class="label-inventory">{{ label.inventory }}</div>
          <div v-if="label.place" class="label-place">{{ label.place }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import { labelUrl, listAssets, qrPath, type Asset } from 'src/services/assets';
import { queryValue } from 'src/utils/machineQuery';

const route = useRoute();
const router = useRouter();
const assets = ref<Asset[]>([]);
const loading = ref(false);
const loadError = ref<unknown>(null);

const labels = computed(() =>
  assets.value.map((a) => ({
    id: a.id,
    name: a.display_name ?? '—',
    inventory: a.inventory_number,
    place: [a.building_name, a.room_name].filter(Boolean).join(' — '),
    qr: qrPath(labelUrl(a.public_token)),
  })),
);

async function load(): Promise<void> {
  const ids = queryValue(route.query.ids);
  if (!ids) return;
  loading.value = true;
  try {
    const res = await listAssets({ ids, page_size: 500 });
    assets.value = res.items;
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  } finally {
    loading.value = false;
  }
}

function print(): void {
  window.print();
}

function back(): void {
  if (window.history.length > 1) router.back();
  else void router.push({ name: 'assets' });
}

onMounted(load);
</script>

<style scoped>
.labels-page {
  background: #fff;
  color: #000;
  min-height: 100vh;
}
.labels-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(62mm, 1fr));
  gap: 4mm;
}
.label {
  display: flex;
  align-items: center;
  gap: 3mm;
  border: 1px dashed #999;
  padding: 2mm;
  break-inside: avoid;
}
.label-qr {
  width: 24mm;
  height: 24mm;
  flex: none;
}
.label-name {
  font-weight: 600;
  font-size: 11pt;
}
.label-inventory {
  font-family: monospace;
  font-size: 10pt;
}
.label-place {
  font-size: 8pt;
}
@media print {
  .labels-toolbar {
    display: none !important;
  }
  .labels-grid {
    padding: 0 !important;
  }
}
</style>
