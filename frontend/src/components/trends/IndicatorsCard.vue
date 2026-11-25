<template>
  <div>
    <div class="text-caption text-muted q-mb-sm">{{ t('trends.indicators.caption') }}</div>
    <div v-if="!sections.length" class="text-muted q-pa-md" data-test="indicators-none">
      {{ t('trends.indicators.none') }}
    </div>
    <div class="row q-col-gutter-md">
      <div
        v-for="s in sections"
        :key="s.key"
        class="col-12 col-sm-6 col-lg-3"
        :data-test="`indicator-${s.key}`"
      >
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-subtitle2">{{ s.title }}</div>
            <div class="text-caption text-muted">
              {{ t('trends.indicators.lastMonth', { month: monthLabel(lastMonth) }) }}
            </div>
            <div class="text-h5 q-mt-xs text-strong">{{ s.headline }}</div>
            <div v-for="line in s.lines" :key="line" class="text-caption">{{ line }}</div>
            <svg
              :viewBox="`0 0 ${BAR_W} ${BAR_H}`"
              width="100%"
              class="indicator-bars q-mt-sm"
              role="img"
              :aria-label="s.barsLabel"
            >
              <line :x1="0" :x2="BAR_W" :y1="BAR_H - 0.5" :y2="BAR_H - 0.5" class="bars-base" />
              <g v-for="(b, i) in s.bars" :key="b.month">
                <rect
                  v-if="b.value !== null"
                  :x="barX(i, s.bars.length)"
                  :y="BAR_H - 1 - barHeight(b.value, s.max)"
                  :width="barWidth(s.bars.length)"
                  :height="barHeight(b.value, s.max)"
                  rx="1"
                  class="bar"
                >
                  <title>
                    {{ t('trends.indicators.bar', { month: monthLabel(b.month), value: b.text }) }}
                  </title>
                </rect>
              </g>
            </svg>
            <div v-if="s.caption" class="text-caption text-muted q-mt-xs">{{ s.caption }}</div>
            <div
              v-for="w in s.warnings"
              :key="w"
              class="text-caption text-warn q-mt-xs"
              data-test="indicators-retention"
            >
              <q-icon name="history" class="q-mr-xs" />{{ w }}
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { intlTag, t } from 'src/i18n';
import type { CommandMonth, Indicators } from 'src/services/trends';
import { frNumber } from 'src/utils/format';

/**
 * One card per indicator section the reader may read (a null section is a
 * right the account does not have): the last full month's figure, the months
 * as a small histogram, and the warning when the history is purged sooner
 * than the period asked.
 */
const props = defineProps<{
  data: Indicators;
  /** The period asked, in months. */
  months: number;
}>();

const BAR_W = 240;
const BAR_H = 48;

/** The month in progress is the last one: the last full month is the one before. */
const lastIndex = computed(() => Math.max(0, props.data.months.length - 2));
const lastMonth = computed(() => props.data.months[lastIndex.value] ?? '');

function monthLabel(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return month;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)).toLocaleDateString(
    intlTag(),
    { timeZone: 'UTC', month: 'long', year: 'numeric' },
  );
}

function rate(m: Pick<CommandMonth, 'succeeded' | 'failed'> | undefined): number | null {
  if (!m) return null;
  const total = m.succeeded + m.failed;
  return total ? Math.round((m.succeeded * 100) / total) : null;
}

function percentText(value: number | null): string {
  return value === null ? t('trends.indicators.rateNone') : `${frNumber(value)} %`;
}

function sum(a: CommandMonth | undefined, b: CommandMonth | undefined): CommandMonth | undefined {
  if (!a || !b) return a ?? b;
  return {
    month: a.month,
    succeeded: a.succeeded + b.succeeded,
    failed: a.failed + b.failed,
    expired: a.expired + b.expired,
    unanswered: a.unanswered + b.unanswered,
  };
}

interface Bar {
  month: string;
  value: number | null;
  text: string;
}

interface Section {
  key: string;
  title: string;
  headline: string;
  lines: string[];
  bars: Bar[];
  max: number;
  barsLabel: string;
  caption: string | null;
  warnings: string[];
}

/** Days from the period's first day (the 1st, `months - 1` months back) to today. */
const periodDays = computed(() => {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() - (props.months - 1), 1);
  return Math.ceil((now.getTime() - start.getTime()) / 86_400_000);
});

/** Whether a purge keeps less than the period asked. */
function purgedSooner(days: number | null): boolean {
  return days !== null && days < periodDays.value;
}

function bars(values: (number | null)[], months: string[], unit: (v: number) => string): Bar[] {
  return months.map((month, i) => {
    const value = values[i] ?? null;
    return { month, value, text: value === null ? '—' : unit(value) };
  });
}

function maxOf(list: Bar[], floor: number): number {
  return Math.max(floor, ...list.map((b) => b.value ?? 0));
}

const sections = computed<Section[]>(() => {
  const d = props.data;
  const i = lastIndex.value;
  const out: Section[] = [];
  const commandsWarning = purgedSooner(d.retention.commands_days)
    ? [t('trends.indicators.retention', { days: d.retention.commands_days ?? 0 })]
    : [];

  if (d.checks) {
    const m = d.checks[i];
    const list = bars(
      d.checks.map((c) => c.median_hours),
      d.months,
      (v) => `${frNumber(v, 1)} h`,
    );
    out.push({
      key: 'checks',
      title: t('trends.indicators.checks.title'),
      headline:
        m?.median_hours != null
          ? t('trends.indicators.checks.median', { hours: frNumber(m.median_hours, 1) })
          : t('trends.indicators.rateNone'),
      lines: [
        t('trends.indicators.checks.closed', { count: m?.closed ?? 0 }, m?.closed ?? 0),
        ...(m?.p90_hours != null
          ? [t('trends.indicators.checks.p90', { hours: frNumber(m.p90_hours, 1) })]
          : []),
        ...(m?.with_due
          ? [t('trends.indicators.checks.onTime', { done: m.on_time_due, total: m.with_due })]
          : []),
      ],
      bars: list,
      max: maxOf(list, 1),
      barsLabel: t('trends.indicators.checks.bars'),
      caption: t('trends.indicators.checks.caption'),
      warnings: [],
    });
  }

  if (d.maintenance) {
    const m = d.maintenance[i];
    const pct = (x: { done: number; on_time: number }) =>
      x.done ? Math.round((x.on_time * 100) / x.done) : null;
    const list = bars(d.maintenance.map(pct), d.months, (v) => `${frNumber(v)} %`);
    const current = m ? pct(m) : null;
    out.push({
      key: 'maintenance',
      title: t('trends.indicators.maintenance.title'),
      headline:
        current === null
          ? t('trends.indicators.rateNone')
          : t('trends.indicators.maintenance.rate', { percent: frNumber(current) }),
      lines: [t('trends.indicators.maintenance.done', { count: m?.done ?? 0 }, m?.done ?? 0)],
      bars: list,
      max: 100,
      barsLabel: t('trends.indicators.maintenance.bars'),
      caption: t('trends.indicators.maintenance.caption'),
      warnings: [],
    });
  }

  if (d.commands) {
    const m = d.commands[i];
    const list = bars(d.commands.map(rate), d.months, (v) => `${frNumber(v)} %`);
    const current = rate(m);
    out.push({
      key: 'commands',
      title: t('trends.indicators.commands.title'),
      headline:
        current === null
          ? t('trends.indicators.rateNone')
          : t('trends.indicators.commands.rate', { percent: frNumber(current) }),
      lines: [
        t('trends.indicators.commands.counts', {
          succeeded: m?.succeeded ?? 0,
          failed: m?.failed ?? 0,
        }),
        t('trends.indicators.commands.apart', {
          expired: m?.expired ?? 0,
          unanswered: m?.unanswered ?? 0,
        }),
      ],
      bars: list,
      max: 100,
      barsLabel: t('trends.indicators.commands.bars'),
      caption: t('trends.indicators.commands.caption'),
      warnings: commandsWarning,
    });
  }

  if (d.deployments) {
    const dep = d.deployments;
    const both = d.months.map((_, k) => rate(sum(dep.direct[k], dep.scheduled[k])));
    const list = bars(both, d.months, (v) => `${frNumber(v)} %`);
    const current = both[i] ?? null;
    const halted = dep.halted_runs;
    const warnings = [...commandsWarning];
    if (halted && purgedSooner(d.retention.schedule_runs_days)) {
      warnings.push(
        t('trends.indicators.deployments.haltedRetention', {
          days: d.retention.schedule_runs_days,
        }),
      );
    }
    out.push({
      key: 'deployments',
      title: t('trends.indicators.deployments.title'),
      headline: percentText(current),
      lines: [
        t('trends.indicators.deployments.direct', { rate: percentText(rate(dep.direct[i])) }),
        t('trends.indicators.deployments.scheduled', {
          rate: percentText(rate(dep.scheduled[i])),
        }),
        ...(halted
          ? [t('trends.indicators.deployments.halted', { count: halted[i] ?? 0 }, halted[i] ?? 0)]
          : []),
      ],
      bars: list,
      max: 100,
      barsLabel: t('trends.indicators.deployments.bars'),
      caption: null,
      warnings,
    });
  }
  return out;
});

function barWidth(n: number): number {
  return Math.max(2, BAR_W / Math.max(n, 1) - 2);
}

function barX(i: number, n: number): number {
  return (i * BAR_W) / Math.max(n, 1) + 1;
}

function barHeight(value: number, max: number): number {
  return Math.max(value > 0 ? 2 : 0, (value / max) * (BAR_H - 2));
}
</script>

<style scoped>
.indicator-bars {
  display: block;
  height: auto;
}

.bars-base {
  stroke: var(--ti-rule);
  stroke-width: 1;
}

.bar {
  fill: var(--ti-series-1);
}
</style>
