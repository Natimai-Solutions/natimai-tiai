<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-sm">
      <h1 class="text-h5 q-my-none col-auto">{{ t('alerts.title') }}</h1>
      <q-space />
      <div class="col-auto">
        <!-- The postes of the tab as a list: to select them for a command,
             a verification, an export. -->
        <q-btn
          outline
          no-caps
          color="primary"
          icon="list"
          :label="t('alerts.machines')"
          :disable="!(rule === 'all' ? totalOpen : counts[rule])"
          :to="{ name: 'machines', query: { alert: rule === 'all' ? 'any' : rule } }"
        />
      </div>
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          :aria-label="t('alerts.refresh')"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>
    <div class="text-caption text-muted q-mb-md">{{ t('alerts.subtitle') }}</div>

    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />

    <q-card flat bordered>
      <!-- One tab per rule, with its count: the page answers « what is
           wrong on the parc » before the table says where. -->
      <q-tabs
        v-model="rule"
        dense
        no-caps
        align="left"
        outside-arrows
        mobile-arrows
        class="text-muted"
        active-color="primary"
        indicator-color="primary"
      >
        <q-tab name="all" :label="t('alerts.all')">
          <q-badge v-if="totalOpen" color="negative" class="q-ml-xs">{{ totalOpen }}</q-badge>
        </q-tab>
        <q-tab v-for="r in ALERT_RULES" :key="r" :name="r" :label="alertRuleLabel(r)">
          <q-badge v-if="counts[r]" color="negative" class="q-ml-xs">{{ counts[r] }}</q-badge>
        </q-tab>
      </q-tabs>
      <q-separator />
      <q-table
        v-model:pagination="pagination"
        :rows="items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        flat
        :grid="$q.screen.lt.sm"
        :rows-per-page-options="[25, 50, 100]"
        :no-data-label="noDataLabel"
        @request="onRequest"
      >
        <template #body-cell-machine="props">
          <q-td :props="props">
            <router-link
              :to="{ name: 'machine-detail', params: { id: props.row.machine_id } }"
              class="row-link text-weight-medium"
            >
              {{ props.row.machine?.hostname ?? '—' }}
            </router-link>
          </q-td>
        </template>
        <template #body-cell-detail="props">
          <q-td :props="props" style="white-space: normal; min-width: 240px">
            {{ props.value }}
            <q-badge v-if="props.row.check_open" color="primary" outline class="q-ml-xs">
              {{ t('alerts.check') }}
            </q-badge>
          </q-td>
        </template>
        <template #item="props">
          <div class="col-12 q-pa-xs">
            <q-card flat bordered>
              <q-card-section>
                <router-link
                  :to="{ name: 'machine-detail', params: { id: props.row.machine_id } }"
                  class="row-link text-weight-medium"
                >
                  {{ props.row.machine?.hostname ?? '—' }}
                </router-link>
                <div class="text-caption text-muted">{{ placeLabel(props.row) }}</div>
                <div class="q-mt-xs text-weight-medium">{{ alertRuleLabel(props.row.rule) }}</div>
                <div>{{ alertDetailText(props.row.rule, props.row.detail) }}</div>
                <div class="text-caption text-muted q-mt-xs">
                  {{ t('alerts.openSince', { date: formatDateTime(props.row.opened_at) }) }}
                </div>
              </q-card-section>
            </q-card>
          </div>
        </template>
      </q-table>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import {
  ALERT_RULES,
  alertDetailText,
  alertRuleLabel,
  isAlertRule,
  listAlerts,
  type Alert,
  type AlertRule,
} from 'src/services/alerts';
import { formatDateTime } from 'src/utils/format';
import { queryValue } from 'src/utils/machineQuery';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();

const items = ref<Alert[]>([]);
const counts = ref<Record<string, number>>({});
const loading = ref(false);
const loadError = ref<unknown>(null);

const initial = queryValue(route.query.rule);
const rule = ref<AlertRule | 'all'>(initial && isAlertRule(initial) ? initial : 'all');
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 });

const totalOpen = computed(() => Object.values(counts.value).reduce((a, b) => a + b, 0));

function placeLabel(a: Alert): string {
  const m = a.machine;
  if (!m) return '—';
  return [m.building_name, m.room_name].filter(Boolean).join(' — ') || '—';
}

const columns = computed<QTableColumn<Alert>[]>(() => [
  { name: 'machine', label: t('alerts.columns.machine'), field: 'machine_id', align: 'left' },
  {
    name: 'place',
    label: t('alerts.columns.place'),
    field: (row) => placeLabel(row),
    align: 'left',
  },
  {
    name: 'rule',
    label: t('alerts.columns.rule'),
    field: (row) => alertRuleLabel(row.rule),
    align: 'left',
  },
  {
    name: 'detail',
    label: t('alerts.columns.detail'),
    field: (row) => alertDetailText(row.rule, row.detail),
    align: 'left',
  },
  {
    name: 'opened',
    label: t('alerts.columns.opened'),
    field: (row) => formatDateTime(row.opened_at),
    align: 'left',
  },
]);

const noDataLabel = computed(() => {
  if (loadError.value) return t('alerts.empty.loadFailed');
  return rule.value === 'all' ? t('alerts.empty.none') : t('alerts.empty.noneRule');
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    const res = await listAlerts({
      state: 'open',
      ...(rule.value === 'all' ? {} : { rule: rule.value }),
      page: pagination.value.page,
      page_size: pagination.value.rowsPerPage,
    });
    items.value = res.items;
    counts.value = res.open_by_rule;
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

watch(rule, (value) => {
  pagination.value.page = 1;
  void router.replace({ query: value === 'all' ? {} : { rule: value } });
  void load();
});

onMounted(load);
</script>
