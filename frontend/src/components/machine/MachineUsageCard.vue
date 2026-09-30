<template>
  <div class="col-12">
    <q-card flat bordered>
      <q-card-section class="row items-start no-wrap">
        <div class="col">
          <div class="text-subtitle1">Utilisation</div>
          <div class="text-caption text-grey">
            Heures allumées par jour sur les {{ DAYS }} derniers jours, comptées à partir des
            battements de l'agent, dans votre fuseau horaire.
          </div>
        </div>
        <q-btn
          v-if="usage"
          flat
          dense
          no-caps
          size="sm"
          color="primary"
          :icon="showTable ? 'bar_chart' : 'table_rows'"
          :label="showTable ? 'Graphique' : 'Tableau'"
          @click="showTable = !showTable"
        />
      </q-card-section>
      <q-separator />

      <q-card-section v-if="!usage" class="text-caption text-grey">
        {{ failed ? "Impossible de lire l'utilisation de ce poste." : 'Chargement…' }}
      </q-card-section>

      <template v-else>
        <!-- The figures first: the window's, which is the list's own column,
             then the chart's span. -->
        <q-card-section class="row q-col-gutter-xl">
          <div>
            <div class="text-h5">
              {{ machine.usage_hours === null ? '—' : hoursLabel(machine.usage_hours) }}
            </div>
            <div class="text-caption text-grey">
              {{
                machine.usage_hours === null
                  ? `enrôlé il y a moins de ${machine.usage_days} jours`
                  : `sur les ${machine.usage_days} derniers jours`
              }}
            </div>
          </div>
          <div>
            <div class="text-h5">{{ hoursLabel(summary.hours) }}</div>
            <div class="text-caption text-grey">
              sur {{ summary.days }} jour{{ summary.days > 1 ? 's' : '' }} mesuré{{
                summary.days > 1 ? 's' : ''
              }}
            </div>
          </div>
          <div v-if="summary.days">
            <div class="text-h5">{{ hoursLabel(average) }}</div>
            <div class="text-caption text-grey">par jour mesuré, en moyenne</div>
          </div>
        </q-card-section>

        <q-card-section v-if="!showTable" class="q-pt-none">
          <!-- One bar per day on a fixed 24 h scale, so two fiches compare at a
               glance. Each whole column is the hover target, not just its bar:
               a zero-hour day has no bar to point at. Days before counting
               began are hatched — not measured is not idle. -->
          <div class="usage-plot" role="img" :aria-label="ariaLabel">
            <div
              v-for="tick in TICKS"
              :key="tick"
              class="usage-grid"
              :style="{ bottom: `${(tick / 24) * 100}%` }"
            >
              <span class="usage-tick">{{ tick }} h</span>
            </div>
            <div class="usage-bars">
              <div
                v-for="bar in bars"
                :key="bar.date"
                class="usage-col"
                :class="{
                  'usage-col--weekend': bar.weekend,
                  'usage-col--unmeasured': !bar.counted,
                }"
                tabindex="0"
              >
                <div
                  v-if="bar.counted && bar.hours > 0"
                  class="usage-bar"
                  :style="{ height: `${bar.percent}%` }"
                />
                <q-tooltip>
                  <div class="text-weight-bold">
                    {{ bar.counted ? hoursLabel(bar.hours) : 'non mesuré' }}
                  </div>
                  <div>{{ bar.label }}</div>
                </q-tooltip>
              </div>
            </div>
          </div>
          <div class="usage-axis">
            <div v-for="(bar, i) in bars" :key="bar.date" class="usage-axis-label">
              {{ (bars.length - 1 - i) % 7 === 0 ? axisLabel(bar.date) : '' }}
            </div>
          </div>
          <div class="text-caption text-grey q-mt-sm">
            Fonds grisés : samedis et dimanches.
            <template v-if="bars.some((b) => !b.counted)">
              Hachures : jours antérieurs au début du comptage.
            </template>
          </div>
        </q-card-section>

        <q-card-section v-else class="q-pt-none">
          <q-markup-table flat dense separator="horizontal">
            <thead>
              <tr>
                <th class="text-left">Jour</th>
                <th class="text-right">Heures allumées</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="bar in [...bars].reverse()" :key="bar.date">
                <td class="text-left">{{ bar.label }}</td>
                <td class="text-right" :class="{ 'text-grey': !bar.counted }">
                  {{ bar.counted ? hoursLabel(bar.hours) : 'non mesuré' }}
                </td>
              </tr>
            </tbody>
          </q-markup-table>
        </q-card-section>
      </template>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { getMachineUsage, type MachineDetail, type MachineUsage } from 'src/services/machines';
import { measuredSummary, usageBars } from 'src/utils/usageChart';
import { hoursLabel } from 'src/utils/usageFilter';

const props = defineProps<{ machine: MachineDetail }>();

/** Four weeks: enough to see a pattern, few enough bars to read one by one. */
const DAYS = 28;
/** Gridlines, in hours: a working day and a full one, on a recessive scale. */
const TICKS = [8, 16, 24];

const usage = ref<MachineUsage | null>(null);
const failed = ref(false);
const showTable = ref(false);

const bars = computed(() => (usage.value ? usageBars(usage.value) : []));
const summary = computed(() => measuredSummary(bars.value));
const average = computed(() =>
  summary.value.days ? Math.round((summary.value.hours / summary.value.days) * 10) / 10 : 0,
);
const ariaLabel = computed(
  () =>
    `Heures allumées par jour sur ${DAYS} jours : ${hoursLabel(summary.value.hours)} ` +
    `sur ${summary.value.days} jours mesurés. Le bouton Tableau donne chaque jour.`,
);

function axisLabel(date: string): string {
  const [, m, d] = date.split('-');
  return `${d}/${m}`;
}

// Which fetch is the current one: a walk to the next poste must not have the
// previous poste's answer land on its card.
let requestId = 0;

async function load() {
  const id = ++requestId;
  try {
    const data = await getMachineUsage(props.machine.id, DAYS);
    if (id !== requestId) return;
    usage.value = data;
    failed.value = false;
  } catch {
    if (id !== requestId) return;
    // A background re-read keeps what it had; only a first read shows the error.
    failed.value = usage.value === null;
  }
}

// The fiche re-reads its machine every 90 s (`useAutoRefresh` on the page):
// following that object rather than running a second timer keeps the card in
// step with the figures above it, and pauses with the page. A different poste
// clears the card first, so it never shows another poste's bars.
watch(
  () => props.machine,
  (next, previous) => {
    if (previous && next.id !== previous.id) {
      usage.value = null;
      failed.value = false;
    }
    void load();
  },
  { immediate: true },
);
</script>

<style scoped>
.usage-plot {
  position: relative;
  height: 140px;
  margin-left: 36px;
  border-bottom: 1px solid #bdbdbd;
}

.usage-grid {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 1px solid #eeeeee;
}

.usage-tick {
  position: absolute;
  left: -36px;
  top: -8px;
  width: 30px;
  text-align: right;
  font-size: 11px;
  color: #757575;
}

.usage-bars {
  position: absolute;
  inset: 0;
  display: flex;
  gap: 2px;
}

.usage-col {
  flex: 1;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  outline: none;
}

.usage-col--weekend {
  background: rgba(0, 0, 0, 0.035);
}

/* Not measured: a 45° hatch, so the day reads as unknown rather than idle. */
.usage-col--unmeasured {
  background: repeating-linear-gradient(45deg, rgba(0, 0, 0, 0.06) 0 2px, transparent 2px 6px);
}

.usage-col:hover,
.usage-col:focus-visible {
  background-color: rgba(0, 0, 0, 0.07);
}

.usage-bar {
  width: 100%;
  max-width: 24px;
  border-radius: 4px 4px 0 0;
  background: var(--q-primary);
}

.usage-col:hover .usage-bar,
.usage-col:focus-visible .usage-bar {
  opacity: 0.8;
}

.usage-axis {
  display: flex;
  gap: 2px;
  margin-left: 36px;
  margin-top: 4px;
}

.usage-axis-label {
  flex: 1;
  font-size: 11px;
  color: #757575;
  white-space: nowrap;
  overflow: visible;
  text-align: center;
  min-width: 0;
}
</style>
