<template>
  <!-- The site in the agents' own words: the list is what the parc reports,
       free entry is for a building created before its first poste speaks. -->
  <q-select
    :model-value="modelValue"
    :options="filtered"
    use-input
    fill-input
    hide-selected
    clearable
    new-value-mode="add-unique"
    input-debounce="0"
    :label="label"
    outlined
    dense
    :hint="hint"
    @filter="filterFn"
    @update:model-value="(v) => emit('update:modelValue', v || null)"
    @input-value="(v) => emit('update:modelValue', v || null)"
  />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

const props = defineProps<{
  modelValue: string | null;
  locations: string[];
  label?: string;
  hint?: string;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: string | null): void }>();

const filtered = ref<string[]>(props.locations);
watch(
  () => props.locations,
  (l) => {
    filtered.value = l;
  },
);

function filterFn(val: string, update: (fn: () => void) => void) {
  update(() => {
    const needle = val.toLowerCase();
    filtered.value = props.locations.filter((l) => l.toLowerCase().includes(needle));
  });
}
</script>
