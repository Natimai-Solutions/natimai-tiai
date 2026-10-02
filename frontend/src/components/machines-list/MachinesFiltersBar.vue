<template>
  <div class="row items-center q-col-gutter-md q-mb-sm">
    <div class="col-12 col-sm">
      <q-input
        :model-value="modelValue.search"
        dense
        outlined
        clearable
        debounce="300"
        placeholder="Nom, IP, MAC, antivirus ou UUID…"
        style="max-width: 480px"
        @update:model-value="(v) => set({ search: v == null ? '' : String(v) })"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>
    </div>
    <!-- The two everyday facets stay on the bar: "on right now" and "carrying
         an active threat" are asked on the way to an action, and a toggle
         costs a glance where a dropdown costs a read. -->
    <div class="col-auto">
      <q-toggle
        :model-value="modelValue.onlineOnly"
        dense
        label="Allumés"
        @update:model-value="(v: boolean) => set({ onlineOnly: v })"
      >
        <q-tooltip>Postes allumés — agent en contact ces dernières minutes</q-tooltip>
      </q-toggle>
    </div>
    <div class="col-auto">
      <q-toggle
        :model-value="modelValue.threatsOnly"
        dense
        label="Menaces actives"
        @update:model-value="(v: boolean) => set({ threatsOnly: v })"
      />
    </div>
    <div class="col-auto">
      <q-btn
        :outline="!filtersOpen"
        :unelevated="filtersOpen"
        no-caps
        color="secondary"
        icon="filter_list"
        label="Filtres"
        @click="filtersOpen = !filtersOpen"
      >
        <q-badge v-if="!filtersOpen && chips.length" color="primary" floating>
          {{ chips.length }}
        </q-badge>
      </q-btn>
    </div>
  </div>

  <q-slide-transition>
    <MachinesFilterPanel
      v-show="filtersOpen"
      v-model:usage-custom="usageCustom"
      :model-value="modelValue"
      :options="options"
      :usage-thresholds="usageThresholds"
      :usage-window-days="usageWindowDays"
      :active-count="chips.length"
      @update:model-value="(f) => emit('update:modelValue', f)"
      @clear-all="clearAll"
    />
  </q-slide-transition>

  <!-- A folded filter must never narrow the list silently — the dashboard
       cards land here with one already set. Chips name the active ones, and
       removing one clears it without opening the panel. -->
  <div v-if="!filtersOpen && chips.length" class="row items-center q-mb-sm">
    <q-chip
      v-for="chip in chips"
      :key="chip.key"
      removable
      dense
      color="primary"
      text-color="white"
      @remove="clear(chip.key)"
    >
      {{ chip.label }}
    </q-chip>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import MachinesFilterPanel from './MachinesFilterPanel.vue';
import {
  clearMachineFilter,
  emptyMachineFilters,
  machineFilterChips,
  type MachineFilterKey,
  type MachineFilters,
  type MachineFleetOptions,
} from 'src/utils/machineListFilters';
import type { UsageThresholds } from 'src/utils/usageFilter';

/**
 * The machine list's search and filters: the search box and the two everyday
 * toggles, the folded panel of dropdowns, and the chips that name what the
 * folded panel is filtering. Every change is emitted as a whole new set of
 * filters; the page writes it into the URL, which stays the source of truth.
 */
const props = defineProps<{
  modelValue: MachineFilters;
  options: MachineFleetOptions;
  usageThresholds: UsageThresholds | null;
  usageWindowDays: number;
}>();

const emit = defineEmits<{ 'update:modelValue': [value: MachineFilters] }>();

// UI state, not query state: the panel starts folded even when a filter is
// active — the chips under the bar say what is filtering instead.
const filtersOpen = ref(false);

// « Personnalisé » chosen before any bound is typed: see MachinesFilterPanel.
// Not in the URL, so a reload of the list's query leaves it alone.
const usageCustom = ref(false);

const chips = computed(() =>
  machineFilterChips(props.modelValue, props.options, props.usageWindowDays),
);

function set(patch: Partial<MachineFilters>) {
  emit('update:modelValue', { ...props.modelValue, ...patch });
}

/** Back to the whole parc: every folded filter off, the two toggles and the
 * search too. The sort and page size are the table's, and are kept. */
function clearAll() {
  usageCustom.value = false;
  emit('update:modelValue', emptyMachineFilters());
}

function clear(key: MachineFilterKey) {
  if (key === 'usage') usageCustom.value = false;
  emit('update:modelValue', clearMachineFilter(props.modelValue, key));
}
</script>
