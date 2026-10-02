<template>
  <!-- One row per kind of question, named on the left, so a reader finds
       « Salle » under Emplacement and « Modèle » under Matériel without
       scanning seventeen boxes — and the rows read in the order the questions
       are asked: is it protected, where is it, is it being looked after, what
       runs on it, what is it made of. -->
  <div class="q-mb-sm filter-panel">
    <div class="row items-center q-mb-xs">
      <div class="text-caption text-grey">
        {{ activeCount ? `${activeCount} filtre(s) actif(s)` : 'Aucun filtre' }}
      </div>
      <q-btn
        v-if="activeCount"
        flat
        dense
        no-caps
        size="sm"
        color="primary"
        icon="filter_list_off"
        label="Tout effacer"
        class="q-ml-sm"
        @click="emit('clear-all')"
      />
    </div>
    <div class="row no-wrap items-start q-mb-xs">
      <div class="text-caption text-grey filter-row-label">Sécurité</div>
      <div class="col row items-center q-col-gutter-sm">
        <q-select
          :model-value="modelValue.antivirus"
          :options="options.antivirus"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 200px"
          @update:model-value="(v) => set({ antivirus: v })"
        />
        <q-select
          :model-value="modelValue.status"
          :options="STATUS_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 190px"
          @update:model-value="(v) => set({ status: v })"
        />
        <q-select
          :model-value="modelValue.wu"
          :options="WU_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 210px"
          @update:model-value="(v) => set({ wu: v })"
        />
        <q-select
          :model-value="modelValue.scan"
          :options="SCAN_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 200px"
          @update:model-value="(v) => set({ scan: v })"
        />
      </div>
    </div>
    <!-- « Where » first among the rest: on a multi-site parc it is the facet
         everything else is asked within. The site the agent reports, then the
         console's placement (building, room, « Sans salle ») and the finding
         that ties the two — agent and room disagreeing. -->
    <div class="row no-wrap items-start q-mb-xs">
      <div class="text-caption text-grey filter-row-label">Emplacement</div>
      <div class="col row items-center q-col-gutter-sm">
        <q-select
          :model-value="modelValue.location"
          :options="options.location"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 220px"
          @update:model-value="(v) => set({ location: v })"
        />
        <q-select
          :model-value="modelValue.building"
          :options="options.building"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 200px"
          @update:model-value="(v) => set({ building: v })"
        />
        <q-select
          :model-value="modelValue.room"
          :options="options.room"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 220px"
          @update:model-value="(v) => set({ room: v })"
        />
        <q-select
          :model-value="modelValue.mismatch"
          :options="MISMATCH_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 230px"
          @update:model-value="(v) => set({ mismatch: v })"
        />
      </div>
    </div>
    <div class="row no-wrap items-start q-mb-xs">
      <div class="text-caption text-grey filter-row-label">Suivi</div>
      <div class="col row items-center q-col-gutter-sm">
        <q-select
          :model-value="modelValue.maintenance"
          :options="MAINTENANCE_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 220px"
          @update:model-value="(v) => set({ maintenance: v })"
        />
        <q-select
          :model-value="modelValue.checkOpen"
          :options="CHECK_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 220px"
          @update:model-value="(v) => set({ checkOpen: v })"
        />
      </div>
    </div>
    <div class="row no-wrap items-start q-mb-xs">
      <div class="text-caption text-grey filter-row-label">Système</div>
      <div class="col row items-center q-col-gutter-sm">
        <q-select
          :model-value="modelValue.os"
          :options="options.os"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 200px"
          @update:model-value="(v) => set({ os: v })"
        />
        <q-select
          :model-value="modelValue.agent"
          :options="options.agent"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 220px"
          @update:model-value="(v) => set({ agent: v })"
        />
      </div>
    </div>
    <!-- Hours on over the usage window. The dropdown asks the dashboard's own
         questions, drawn from the console's thresholds; « Personnalisé » opens
         the two bounds for any other. The URL only ever carries the bounds, so
         a card's link and a hand-picked entry read the same. -->
    <div class="row no-wrap items-start q-mb-xs">
      <div class="text-caption text-grey filter-row-label">Utilisation</div>
      <div class="col row items-center q-col-gutter-sm">
        <q-select
          v-model="usageMode"
          :options="usageOptions"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 250px"
        />
        <template v-if="usageMode === 'custom'">
          <q-input
            :model-value="modelValue.usageAbove"
            type="number"
            min="0"
            step="0.5"
            dense
            outlined
            debounce="400"
            prefix="plus de"
            suffix="h"
            class="col-auto"
            style="width: 150px"
            @update:model-value="(v) => set({ usageAbove: v })"
          />
          <q-input
            :model-value="modelValue.usageBelow"
            type="number"
            min="0"
            step="0.5"
            dense
            outlined
            debounce="400"
            prefix="moins de"
            suffix="h"
            class="col-auto"
            style="width: 160px"
            @update:model-value="(v) => set({ usageBelow: v })"
          />
        </template>
        <div class="col-auto text-caption text-grey">sur {{ usageWindowDays }} jours</div>
      </div>
    </div>
    <div class="row no-wrap items-start">
      <div class="text-caption text-grey filter-row-label">Matériel</div>
      <div class="col row items-center q-col-gutter-sm">
        <q-select
          :model-value="modelValue.manufacturer"
          :options="options.manufacturer"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 190px"
          @update:model-value="(v) => set({ manufacturer: v })"
        />
        <q-select
          :model-value="modelValue.model"
          :options="options.model"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 220px"
          @update:model-value="(v) => set({ model: v })"
        />
        <q-select
          :model-value="modelValue.processor"
          :options="options.processor"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 260px"
          @update:model-value="(v) => set({ processor: v })"
        />
        <q-select
          :model-value="modelValue.chassis"
          :options="options.chassis"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 170px"
          @update:model-value="(v) => set({ chassis: v })"
        />
        <!-- Memory as a bound and a figure: "au moins 16 Gio" is how the
             upgrade question is asked, and no closed list holds every parc's
             sizes. The filter applies once both halves are set. -->
        <q-select
          :model-value="modelValue.ramOp"
          :options="RAM_OP_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 180px"
          @update:model-value="(v) => set({ ramOp: v })"
        />
        <q-input
          :model-value="modelValue.ramGb"
          type="number"
          min="1"
          step="1"
          dense
          outlined
          debounce="400"
          suffix="Gio"
          placeholder="16"
          class="col-auto"
          style="width: 100px"
          :disable="!modelValue.ramOp"
          @update:model-value="(v) => set({ ramGb: v })"
        />
        <q-select
          :model-value="modelValue.diskFree"
          :options="DISK_OPTIONS"
          emit-value
          map-options
          dense
          outlined
          class="col-auto"
          style="width: 210px"
          @update:model-value="(v) => set({ diskFree: v })"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import {
  CHECK_OPTIONS,
  DISK_OPTIONS,
  MAINTENANCE_OPTIONS,
  MISMATCH_OPTIONS,
  RAM_OP_OPTIONS,
  SCAN_OPTIONS,
  STATUS_OPTIONS,
  WU_OPTIONS,
  clearUsageFilter,
  usageBoundsOf,
  type FilterOption,
  type MachineFilters,
  type MachineFleetOptions,
} from 'src/utils/machineListFilters';
import {
  usagePresetBounds,
  usagePresetOf,
  type UsagePreset,
  type UsageThresholds,
} from 'src/utils/usageFilter';

/**
 * The folded dropdowns of the machine list: each is reached for now and then,
 * and a bar wearing all of them at once buried the search. Every change is
 * emitted as a whole new set of filters, which the page writes into the URL.
 */
const props = defineProps<{
  modelValue: MachineFilters;
  options: MachineFleetOptions;
  /** The console's thresholds, once the first list response has served them. */
  usageThresholds: UsageThresholds | null;
  /** The usage window the server answered with, in days. */
  usageWindowDays: number;
  /** How many chips the active filters make. */
  activeCount: number;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: MachineFilters];
  'clear-all': [];
}>();

/**
 * « Personnalisé » picked with no bound typed yet: the bounds alone would read
 * as no filter at all and fold the boxes away before anything is typed. Held
 * by the bar, which also clears it with the usage filter's chip.
 */
const usageCustom = defineModel<boolean>('usageCustom', { required: true });

function set(patch: Partial<MachineFilters>) {
  emit('update:modelValue', { ...props.modelValue, ...patch });
}

/** The dropdown's entries, worded with the thresholds once the list served them. */
const usageOptions = computed<FilterOption<UsagePreset | null>[]>(() => {
  const t = props.usageThresholds;
  // The presets are drawn from the thresholds, which the first list response
  // brings: until then they are shown but not pickable, rather than picked
  // and silently dropped.
  return [
    { label: 'Utilisation : toutes', value: null },
    {
      label: t ? `Peu utilisés (moins de ${t.low} h)` : 'Peu utilisés',
      value: 'low',
      disable: !t,
    },
    {
      label: t ? `Entre ${t.low} et ${t.high} h` : 'Utilisation moyenne',
      value: 'mid',
      disable: !t,
    },
    {
      label: t ? `Toujours allumés (plus de ${t.high} h)` : 'Toujours allumés',
      value: 'high',
      disable: !t,
    },
    { label: 'Personnalisé…', value: 'custom' },
  ];
});

/** Which entry the bounds stand for; setting it writes the bounds. */
const usageMode = computed<UsagePreset | null>({
  get: () =>
    usageCustom.value
      ? 'custom'
      : usagePresetOf(usageBoundsOf(props.modelValue), props.usageThresholds),
  set: (mode) => {
    usageCustom.value = mode === 'custom';
    if (mode === 'custom') return; // the bounds stay, to be edited
    const t = props.usageThresholds;
    if (mode === null || !t) {
      // « toutes »: the window goes with the bounds — a link may have widened
      // it, and nothing else on the page could put it back.
      emit('update:modelValue', clearUsageFilter(props.modelValue));
    } else {
      const bounds = usagePresetBounds(mode, t);
      set({ usageBelow: bounds.below, usageAbove: bounds.above });
    }
  },
});
</script>

<style scoped>
/* The row captions line up with the dropdowns without taking a column, and
   sit on the first line of a row that wraps. */
.filter-row-label {
  flex: 0 0 96px;
  padding-top: 10px;
}
/* A quiet frame around the folded panel, so five rows of dropdowns read as
   one thing that opens and closes rather than as part of the page. */
.filter-panel {
  padding: 8px 12px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 4px;
}
</style>
