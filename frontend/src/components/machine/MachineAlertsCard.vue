<template>
  <!-- Only once there is something to say: a poste with no alert, open or
       past, does not need a card saying so above its tabs. -->
  <q-card v-if="failed || alerts.length" flat bordered class="q-mb-md">
    <q-card-section class="row items-center no-wrap q-pb-sm">
      <q-icon
        name="notifications_active"
        :color="open.length ? 'negative' : 'grey-6'"
        class="q-mr-sm"
      />
      <div class="col">
        <div class="text-subtitle1">{{ t('alerts.card.title') }}</div>
        <div class="text-caption text-muted">{{ t('alerts.card.caption') }}</div>
      </div>
      <q-btn
        v-if="resolved.length"
        flat
        dense
        no-caps
        size="sm"
        color="primary"
        :label="
          showHistory
            ? t('alerts.card.hideHistory')
            : t('alerts.card.history', { count: resolved.length })
        "
        @click="showHistory = !showHistory"
      />
    </q-card-section>
    <q-separator />

    <q-card-section v-if="failed && !alerts.length" class="q-pa-sm">
      <CardLoadError :what="t('alerts.card.what')" :loading="loading" @retry="load" />
    </q-card-section>

    <q-list v-else separator dense>
      <q-item v-if="!open.length">
        <q-item-section class="text-caption text-muted">{{ t('alerts.card.none') }}</q-item-section>
      </q-item>
      <q-item v-for="a in shown" :key="a.id" :class="{ 'text-muted': a.resolved_at }">
        <q-item-section avatar>
          <q-icon
            :name="a.resolved_at ? 'check_circle' : 'error'"
            :color="a.resolved_at ? 'grey-6' : 'negative'"
          />
        </q-item-section>
        <q-item-section>
          <q-item-label class="text-weight-medium">{{ alertRuleLabel(a.rule) }}</q-item-label>
          <q-item-label caption>{{ alertDetailText(a.rule, a.detail) }}</q-item-label>
        </q-item-section>
        <q-item-section side class="text-caption">
          <div>{{ t('alerts.openSince', { date: formatDateTime(a.opened_at) }) }}</div>
          <div v-if="a.resolved_at">
            {{ t('alerts.resolvedOn', { date: formatDateTime(a.resolved_at) }) }}
          </div>
          <q-badge v-else-if="a.check_id" color="primary" outline>{{ t('alerts.check') }}</q-badge>
        </q-item-section>
      </q-item>
    </q-list>
  </q-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import CardLoadError from 'src/components/CardLoadError.vue';
import { t } from 'src/i18n';
import { alertDetailText, alertRuleLabel, listAlerts, type Alert } from 'src/services/alerts';
import { formatDateTime } from 'src/utils/format';

const props = defineProps<{
  machineId: string;
  /** Changes when the fiche reloads: the alerts are read again with it. */
  refreshKey?: string | number | null;
}>();

const alerts = ref<Alert[]>([]);
const loading = ref(false);
const failed = ref(false);
const showHistory = ref(false);

const open = computed(() => alerts.value.filter((a) => !a.resolved_at));
const resolved = computed(() => alerts.value.filter((a) => a.resolved_at));
const shown = computed(() => (showHistory.value ? alerts.value : open.value));

async function load(): Promise<void> {
  loading.value = true;
  try {
    // Open first, then the most recent past ones; a hundred is a long
    // history for one poste.
    const res = await listAlerts({ machine_id: props.machineId, state: 'all', page_size: 100 });
    alerts.value = res.items;
    failed.value = false;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.machineId, props.refreshKey],
  () => void load(),
  { immediate: true },
);

defineExpose({ load });
</script>
