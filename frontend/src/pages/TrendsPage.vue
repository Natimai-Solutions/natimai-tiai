<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-sm">
      <h1 class="text-h5 q-my-none col-auto">{{ t('trends.title') }}</h1>
      <q-space />
      <div class="col-auto">
        <q-btn-toggle
          v-model="months"
          no-caps
          unelevated
          toggle-color="primary"
          :options="periodOptions"
          :aria-label="t('trends.period')"
          data-test="trends-period"
        />
      </div>
      <div class="col-auto">
        <q-btn
          outline
          no-caps
          color="primary"
          icon="file_download"
          :label="t('trends.report.button')"
          :loading="reporting"
          data-test="trends-report"
          @click="report"
        >
          <q-tooltip>{{ t('trends.report.hint') }}</q-tooltip>
        </q-btn>
      </div>
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          :aria-label="t('trends.refresh')"
          :loading="loadingTrends || loadingIndicators"
          @click="reloadAll"
        />
      </div>
    </div>
    <div class="text-caption text-muted q-mb-md">{{ t('trends.subtitle') }}</div>

    <!-- The fleet over time: the dashboard's counters, photographed daily. -->
    <q-card flat bordered class="q-mb-md" data-test="trends-fleet">
      <q-card-section>
        <div class="text-h6">{{ t('trends.fleet.title') }}</div>
        <div class="row items-center q-gutter-sm q-mt-sm">
          <q-chip
            v-for="s in selected"
            :key="s.key"
            removable
            dense
            :remove-aria-label="t('trends.fleet.removeSeries', { label: seriesLabel(s.key) })"
            data-test="trend-chip"
            @remove="removeSeries(s.key)"
          >
            <span class="trend-chip-swatch q-mr-xs" :style="{ background: colour(s.slot) }" />
            {{ seriesLabel(s.key) }}
          </q-chip>
          <q-select
            v-model="adding"
            :label="t('trends.fleet.addSeries')"
            :options="addOptions"
            emit-value
            map-options
            dense
            outlined
            options-dense
            :disable="selected.length >= MAX_SERIES"
            style="min-width: 220px"
            data-test="trend-add"
            @update:model-value="addSeries"
          >
            <q-tooltip v-if="selected.length >= MAX_SERIES">{{
              t('trends.fleet.maxSeries')
            }}</q-tooltip>
          </q-select>
          <q-btn
            v-if="!isDefaultSelection"
            flat
            dense
            no-caps
            color="primary"
            :label="t('trends.fleet.resetSeries')"
            @click="resetSeries"
          />
        </div>
      </q-card-section>
      <q-card-section class="q-pt-none">
        <LoadErrorBanner
          v-if="trendsError"
          :error="trendsError"
          :loading="loadingTrends"
          :fallback="t('trends.fleet.loadFailed')"
          @retry="loadTrends"
        />
        <template v-else-if="trends">
          <TrendChart
            :days="trends.days"
            :series="chartSeries"
            :provisional-day="trends.provisional_day"
          />
          <div class="text-caption text-muted q-mt-sm">
            <div>{{ t('trends.fleet.scope') }}</div>
            <div v-if="trends.since" data-test="trends-since">
              {{ t('trends.fleet.since', { date: formatDate(trends.since) }) }}
              {{ t('trends.fleet.gaps') }}
            </div>
            <div v-else data-test="trends-not-started">{{ t('trends.fleet.notStarted') }}</div>
            <div v-if="trends.step === 'week'">{{ t('trends.fleet.weekly') }}</div>
            <div v-if="trends.provisional_day">{{ t('trends.fleet.provisional') }}</div>
          </div>
          <div v-if="trends.policy_changes.length" class="q-mt-sm" data-test="trends-policies">
            <div class="text-caption text-weight-medium">
              {{ t('trends.fleet.policyChanges') }}
            </div>
            <div v-for="(c, i) in trends.policy_changes" :key="i" class="text-caption">
              {{
                t('trends.fleet.policyChange', {
                  date: formatDate(c.day),
                  setting: policyLabel(c.key),
                  before: policyValue(c.key, c.before),
                  after: policyValue(c.key, c.after),
                })
              }}
            </div>
          </div>
          <q-btn
            flat
            dense
            no-caps
            color="primary"
            class="q-mt-sm"
            :icon="showTable ? 'expand_less' : 'table_rows'"
            :label="showTable ? t('trends.fleet.hideTable') : t('trends.fleet.showTable')"
            data-test="trends-table-toggle"
            @click="showTable = !showTable"
          />
          <div v-if="showTable" class="trend-table-wrap q-mt-sm">
            <q-markup-table flat bordered dense data-test="trends-table">
              <thead>
                <tr>
                  <th class="text-left">{{ t('trends.fleet.date') }}</th>
                  <th v-for="s in chartSeries" :key="s.key" class="text-right">
                    {{ s.label }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(day, i) in trends.days" :key="day">
                  <td>{{ formatDate(day) }}</td>
                  <td v-for="s in chartSeries" :key="s.key" class="text-right">
                    {{ cell(s.values[i]) }}
                  </td>
                </tr>
              </tbody>
            </q-markup-table>
          </div>
        </template>
      </q-card-section>
    </q-card>

    <!-- Indicators: delays and rates, month by month. -->
    <q-card flat bordered class="q-mb-md" data-test="trends-indicators">
      <q-card-section>
        <div class="text-h6 q-mb-xs">{{ t('trends.indicators.title') }}</div>
        <LoadErrorBanner
          v-if="indicatorsError"
          :error="indicatorsError"
          :loading="loadingIndicators"
          :fallback="t('trends.indicators.loadFailed')"
          @retry="loadIndicators"
        />
        <IndicatorsCard v-else-if="indicators" :data="indicators" :months="months" />
      </q-card-section>
    </q-card>

    <!-- Recurring failures: needs the interventions, not only the parc. -->
    <q-card v-if="canReadInterventions" flat bordered data-test="trends-failures">
      <q-card-section>
        <div class="text-h6 q-mb-xs">{{ t('trends.failures.title') }}</div>
        <RecurringFailuresCard ref="failuresCard" :months="months" />
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import IndicatorsCard from 'src/components/trends/IndicatorsCard.vue';
import RecurringFailuresCard from 'src/components/trends/RecurringFailuresCard.vue';
import TrendChart from 'src/components/trends/TrendChart.vue';
import { t } from 'src/i18n';
import trendsTexts from 'src/i18n/messages/trends';
import { apiErrorMessage } from 'src/services/errors';
import {
  DEFAULT_TREND_KEYS,
  TREND_KEYS,
  TREND_PERIODS,
  downloadReport,
  getIndicators,
  getTrends,
  type Indicators,
  type TrendChartSeries,
  type TrendPeriod,
  type Trends,
} from 'src/services/trends';
import { useAuthStore } from 'src/stores/auth';
import { downloadBlob, formatDate, frNumber } from 'src/utils/format';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();
const canReadInterventions = computed(() => auth.can('intervention', 'read'));

/** Eight colour slots: a ninth series would need a ninth hue nobody can tell apart. */
const MAX_SERIES = 8;

const months = ref<TrendPeriod>(12);
const periodOptions = computed(() =>
  TREND_PERIODS.map((m) => ({ label: t('trends.periodMonths', { count: m }, m), value: m })),
);

interface Selected {
  key: string;
  slot: number;
}
const defaultSelection = (): Selected[] =>
  DEFAULT_TREND_KEYS.map((key, i) => ({ key, slot: i + 1 }));
const selected = ref<Selected[]>(defaultSelection());
const adding = ref<string | null>(null);
const isDefaultSelection = computed(
  () =>
    selected.value.length === DEFAULT_TREND_KEYS.length &&
    selected.value.every((s, i) => s.key === DEFAULT_TREND_KEYS[i]),
);

const trends = ref<Trends | null>(null);
const trendsError = ref<unknown>(null);
const loadingTrends = ref(false);
const indicators = ref<Indicators | null>(null);
const indicatorsError = ref<unknown>(null);
const loadingIndicators = ref(false);
const showTable = ref(false);
const reporting = ref(false);
const failuresCard = ref<InstanceType<typeof RecurringFailuresCard> | null>(null);

function seriesLabel(key: string): string {
  if (key.startsWith('alerts.')) {
    return t('trends.seriesAlert', { rule: t(`alerts.rules.${key.slice('alerts.'.length)}`) });
  }
  if (key.startsWith('compliance.')) {
    return t('trends.seriesCompliance', {
      check: t(`compliance.checks.${key.slice('compliance.'.length)}`),
    });
  }
  return t(`trends.series.${key}`);
}

function colour(slot: number): string {
  return `var(--ti-series-${slot})`;
}

const addOptions = computed(() => {
  const taken = new Set(selected.value.map((s) => s.key));
  return TREND_KEYS.filter((k) => !taken.has(k)).map((k) => ({
    label: seriesLabel(k),
    value: k,
  }));
});

const chartSeries = computed<TrendChartSeries[]>(() =>
  selected.value
    .filter((s) => trends.value?.series[s.key])
    .map((s) => ({
      key: s.key,
      slot: s.slot,
      label: seriesLabel(s.key),
      values: trends.value?.series[s.key] ?? [],
    })),
);

function addSeries(key: string | null): void {
  adding.value = null;
  if (!key || selected.value.length >= MAX_SERIES) return;
  if (selected.value.some((s) => s.key === key)) return;
  // The first free slot: the series already drawn keep their colours.
  const used = new Set(selected.value.map((s) => s.slot));
  const slot = Array.from({ length: MAX_SERIES }, (_, i) => i + 1).find((n) => !used.has(n)) ?? 1;
  selected.value = [...selected.value, { key, slot }];
  void loadTrends();
}

function removeSeries(key: string): void {
  // Nothing to ask the server: the other series are already here.
  selected.value = selected.value.filter((s) => s.key !== key);
}

function resetSeries(): void {
  selected.value = defaultSelection();
  void loadTrends();
}

const knownPolicies = new Set(Object.keys(trendsTexts.fr.policies));

function policyLabel(key: string): string {
  const name = key.replace(/\./g, '_');
  return knownPolicies.has(name) ? t(`trends.policies.${name}`) : key;
}

/** The settings whose values are a choice in a list, with their wording. */
const policyChoices: Record<string, unknown> = trendsTexts.fr.policyValues;

function policyValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return t('trends.fleet.policyNone');
  if (typeof value === 'number') return frNumber(value, Number.isInteger(value) ? 0 : 1);
  if (typeof value === 'boolean')
    return t(value ? 'trends.policyValues.yes' : 'trends.policyValues.no');
  if (typeof value === 'string') {
    // A choice (the encryption scope…) in the reader's words; free text (the
    // agent version) as it is.
    const name = key.replace(/\./g, '_');
    const choices = policyChoices[name];
    if (choices && typeof choices === 'object' && Object.hasOwn(choices, value)) {
      return t(`trends.policyValues.${name}.${value}`);
    }
    return value;
  }
  return JSON.stringify(value);
}

function cell(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : frNumber(value);
}

// Each load is numbered: a late answer to an earlier period or set of series
// is dropped rather than drawn under the period now chosen.
let trendsSeq = 0;
let indicatorsSeq = 0;

async function loadTrends(): Promise<void> {
  const seq = ++trendsSeq;
  loadingTrends.value = true;
  try {
    const answer = await getTrends({
      months: months.value,
      keys: selected.value.map((s) => s.key),
    });
    if (seq !== trendsSeq) return;
    trends.value = answer;
    trendsError.value = null;
  } catch (e) {
    if (seq !== trendsSeq) return;
    trendsError.value = e;
  } finally {
    if (seq === trendsSeq) loadingTrends.value = false;
  }
}

async function loadIndicators(): Promise<void> {
  const seq = ++indicatorsSeq;
  loadingIndicators.value = true;
  try {
    const answer = await getIndicators(months.value);
    if (seq !== indicatorsSeq) return;
    indicators.value = answer;
    indicatorsError.value = null;
  } catch (e) {
    if (seq !== indicatorsSeq) return;
    indicatorsError.value = e;
  } finally {
    if (seq === indicatorsSeq) loadingIndicators.value = false;
  }
}

function reloadAll(): void {
  void loadTrends();
  void loadIndicators();
  void failuresCard.value?.load();
}

/** Today in the reader's calendar, for the file's name. */
function today(): string {
  const now = new Date();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${mm}-${dd}`;
}

async function report(): Promise<void> {
  reporting.value = true;
  try {
    const blob = await downloadReport(months.value);
    downloadBlob(blob, `${t('trends.report.fileName')}-${today()}.xlsx`);
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('trends.report.failed')),
    }));
  } finally {
    reporting.value = false;
  }
}

// The failures card follows the period on its own (its `months` prop).
watch(months, () => {
  void loadTrends();
  void loadIndicators();
});

onMounted(() => {
  void loadTrends();
  void loadIndicators();
});
</script>

<style scoped>
.trend-chip-swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.trend-table-wrap {
  max-height: 420px;
  overflow: auto;
}
</style>
