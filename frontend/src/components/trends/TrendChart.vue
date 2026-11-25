<template>
  <div class="trend-chart">
    <div v-if="!hasData" class="text-muted q-pa-md" data-test="trend-empty">
      {{ t('trends.fleet.empty') }}
    </div>
    <template v-else>
      <div class="trend-plot" @mouseleave="hover = null">
        <svg
          :viewBox="`0 0 ${W} ${H}`"
          width="100%"
          role="img"
          :aria-label="t('trends.fleet.chartLabel', { series: labels })"
          class="trend-svg"
        >
          <g class="trend-axis">
            <template v-for="tick in yTicks" :key="`y${tick}`">
              <line
                :x1="LEFT"
                :x2="W - RIGHT"
                :y1="y(tick)"
                :y2="y(tick)"
                :class="tick === 0 ? 'trend-baseline' : 'trend-grid'"
              />
              <text :x="LEFT - 6" :y="y(tick) + 4" text-anchor="end" class="trend-tick">
                {{ frNumber(tick) }}
              </text>
            </template>
            <text
              v-for="i in xTickIndexes"
              :key="`x${i}`"
              :x="x(i)"
              :y="H - 8"
              :text-anchor="xAnchor(i)"
              class="trend-tick"
            >
              {{ shortDay(days[i] ?? '') }}
            </text>
          </g>
          <line
            v-if="hover !== null"
            :x1="x(hover)"
            :x2="x(hover)"
            :y1="TOP"
            :y2="H - BOTTOM"
            class="trend-crosshair"
          />
          <g v-for="s in drawn" :key="s.key" :style="{ color: colour(s.slot) }">
            <polyline
              v-for="(run, r) in s.lines"
              :key="`l${r}`"
              :points="run"
              class="trend-line"
              fill="none"
              stroke="currentColor"
            />
            <circle
              v-for="(p, r) in s.points"
              :key="`p${r}`"
              :cx="p.x"
              :cy="p.y"
              r="4"
              class="trend-point"
              fill="currentColor"
            />
            <template v-if="s.provisional">
              <line
                v-if="s.provisional.from"
                :x1="s.provisional.from.x"
                :y1="s.provisional.from.y"
                :x2="s.provisional.to.x"
                :y2="s.provisional.to.y"
                class="trend-provisional trend-provisional-line"
                stroke="currentColor"
              />
              <circle
                :cx="s.provisional.to.x"
                :cy="s.provisional.to.y"
                r="4"
                class="trend-provisional trend-provisional-point"
                stroke="currentColor"
              />
            </template>
          </g>
          <rect
            v-for="(_, i) in days"
            :key="`h${i}`"
            :x="hitX(i)"
            :y="TOP"
            :width="hitWidth"
            :height="H - TOP - BOTTOM"
            fill="transparent"
            class="trend-hit"
            @mouseenter="hover = i"
          />
        </svg>
        <div
          v-if="hover !== null"
          class="trend-tooltip"
          :style="tooltipStyle"
          role="status"
          data-test="trend-tooltip"
        >
          <div class="text-weight-medium">{{ formatDate(days[hover]) }}</div>
          <div v-for="s in series" :key="s.key" class="row items-center no-wrap q-gutter-x-xs">
            <span class="trend-swatch" :style="{ background: colour(s.slot) }" />
            <span>{{ s.label }}</span>
            <q-space />
            <span class="text-weight-medium q-pl-sm">{{ valueLabel(s.values[hover]) }}</span>
          </div>
        </div>
      </div>
      <div v-if="series.length >= 2" class="row q-gutter-md q-mt-xs trend-legend">
        <div v-for="s in series" :key="s.key" class="row items-center no-wrap q-gutter-x-xs">
          <span class="trend-swatch" :style="{ background: colour(s.slot) }" />
          <span class="text-caption">{{ s.label }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { intlTag, t } from 'src/i18n';
import type { TrendChartSeries } from 'src/services/trends';
import { formatDate, frNumber } from 'src/utils/format';

/**
 * A plain SVG line chart (no charting library in the console): one line per
 * series, a gap for a day never photographed (null), today's point dashed
 * because it is taken again every hour, a crosshair and a tooltip on hover.
 */
const props = defineProps<{
  /** `AAAA-MM-JJ`, one per point. */
  days: string[];
  series: TrendChartSeries[];
  provisionalDay?: string | null;
}>();

const W = 720;
const H = 240;
const LEFT = 44;
const RIGHT = 14;
const TOP = 12;
const BOTTOM = 28;
const PLOT_W = W - LEFT - RIGHT;
const PLOT_H = H - TOP - BOTTOM;

const hover = ref<number | null>(null);

const hasData = computed(
  () => props.days.length > 0 && props.series.some((s) => s.values.some((v) => v !== null)),
);

const labels = computed(() => props.series.map((s) => s.label).join(', '));

function niceStep(raw: number): number {
  if (raw <= 1) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return Math.max(1, factor * magnitude);
}

const scale = computed(() => {
  let max = 0;
  for (const s of props.series) for (const v of s.values) if (v !== null && v > max) max = v;
  const step = niceStep(max / 4);
  const top = Math.max(step, Math.ceil(max / step) * step);
  return { step, top };
});

const yTicks = computed(() => {
  const ticks: number[] = [];
  for (let v = 0; v <= scale.value.top; v += scale.value.step) ticks.push(v);
  return ticks;
});

function x(i: number): number {
  const n = props.days.length;
  return n <= 1 ? LEFT + PLOT_W / 2 : LEFT + (i * PLOT_W) / (n - 1);
}

function y(v: number): number {
  return TOP + PLOT_H - (v / scale.value.top) * PLOT_H;
}

const hitWidth = computed(() =>
  props.days.length <= 1 ? PLOT_W : PLOT_W / (props.days.length - 1),
);

function hitX(i: number): number {
  return props.days.length <= 1 ? LEFT : x(i) - hitWidth.value / 2;
}

/** At most six dates under the axis, the first and the last always. */
const xTickIndexes = computed(() => {
  const n = props.days.length;
  if (n <= 6) return Array.from({ length: n }, (_, i) => i);
  const out = new Set<number>();
  for (let k = 0; k < 6; k++) out.add(Math.round((k * (n - 1)) / 5));
  return [...out];
});

function xAnchor(i: number): 'start' | 'middle' | 'end' {
  if (props.days.length <= 1) return 'middle';
  if (i === 0) return 'start';
  if (i === props.days.length - 1) return 'end';
  return 'middle';
}

/** A calendar day read as written (no zone): `AAAA-MM-JJ` is not an instant. */
function shortDay(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return day;
  const at = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  const first = props.days[0] ?? day;
  const last = props.days[props.days.length - 1] ?? day;
  const longSpan = Date.parse(last) - Date.parse(first) > 300 * 86_400_000;
  return at.toLocaleDateString(intlTag(), {
    timeZone: 'UTC',
    ...(longSpan ? { month: 'short', year: '2-digit' } : { day: 'numeric', month: 'short' }),
  });
}

function colour(slot: number): string {
  return `var(--ti-series-${((slot - 1) % 8) + 1})`;
}

function valueLabel(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : frNumber(v);
}

interface Point {
  x: number;
  y: number;
}

const provisionalIndex = computed(() =>
  props.provisionalDay ? props.days.indexOf(props.provisionalDay) : -1,
);

/** Each series cut into runs of consecutive days: a line, or a dot for a lone day. */
const drawn = computed(() =>
  props.series.map((s) => {
    const lines: string[] = [];
    const points: Point[] = [];
    let run: Point[] = [];
    const flush = () => {
      if (run.length === 1 && run[0]) points.push(run[0]);
      else if (run.length > 1) lines.push(run.map((p) => `${p.x},${p.y}`).join(' '));
      run = [];
    };
    let provisional: { from: Point | null; to: Point } | null = null;
    s.values.forEach((v, i) => {
      if (i === provisionalIndex.value && v !== null) {
        const before = i > 0 ? s.values[i - 1] : null;
        provisional = {
          from: before !== null && before !== undefined ? { x: x(i - 1), y: y(before) } : null,
          to: { x: x(i), y: y(v) },
        };
        return;
      }
      if (v === null) flush();
      else run.push({ x: x(i), y: y(v) });
    });
    flush();
    return { key: s.key, slot: s.slot, lines, points, provisional } as {
      key: string;
      slot: number;
      lines: string[];
      points: Point[];
      provisional: { from: Point | null; to: Point } | null;
    };
  }),
);

const tooltipStyle = computed(() => {
  if (hover.value === null) return {};
  const ratio = x(hover.value) / W;
  return ratio > 0.6
    ? { right: `${(1 - ratio) * 100}%`, marginRight: '8px' }
    : { left: `${ratio * 100}%`, marginLeft: '8px' };
});
</script>

<style scoped>
.trend-plot {
  position: relative;
}

.trend-svg {
  display: block;
  height: auto;
  overflow: visible;
}

.trend-grid {
  stroke: var(--ti-rule-faint);
  stroke-width: 1;
}

.trend-baseline {
  stroke: var(--ti-rule);
  stroke-width: 1;
}

.trend-tick {
  fill: var(--ti-text-muted);
  font-size: 11px;
}

.trend-crosshair {
  stroke: var(--ti-rule);
  stroke-width: 1;
}

.trend-line {
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.trend-point {
  stroke: var(--ti-surface-card);
  stroke-width: 2;
}

.trend-provisional-line {
  stroke-width: 2;
  stroke-dasharray: 4 4;
}

.trend-provisional-point {
  fill: var(--ti-surface-card);
  stroke-width: 2;
}

.trend-tooltip {
  position: absolute;
  top: 8px;
  z-index: 1;
  min-width: 180px;
  padding: 6px 10px;
  border: 1px solid var(--ti-border);
  border-radius: 4px;
  background: var(--ti-surface-card);
  color: var(--ti-text-strong);
  font-size: 12px;
  pointer-events: none;
}

.trend-swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex: none;
}
</style>
