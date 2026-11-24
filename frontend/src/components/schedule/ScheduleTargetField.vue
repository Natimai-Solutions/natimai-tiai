<template>
  <!-- What a schedule (or one of its stages) is aimed at: a kind, then the
       room, building, site or domain it names. -->
  <div class="row q-col-gutter-sm">
    <q-select
      :model-value="modelValue.kind"
      class="col-12 col-sm-5"
      :options="kindOptions"
      emit-value
      map-options
      outlined
      dense
      :label="label"
      @update:model-value="setKind"
    />
    <q-select
      v-if="modelValue.kind === 'room' || modelValue.kind === 'building'"
      :model-value="modelValue.value ?? null"
      class="col-12 col-sm-7"
      :options="modelValue.kind === 'room' ? roomOptions : buildingOptions"
      emit-value
      map-options
      outlined
      dense
      :label="modelValue.kind === 'room' ? t('schedules.form.room') : t('schedules.form.building')"
      reactive-rules
      :rules="[(v: string | null) => !!v || t('schedules.form.required')]"
      @update:model-value="(v: string) => emit('update:modelValue', { ...modelValue, value: v })"
    />
    <q-input
      v-else-if="modelValue.kind === 'location' || modelValue.kind === 'domain'"
      :model-value="modelValue.value ?? ''"
      class="col-12 col-sm-7"
      outlined
      dense
      maxlength="200"
      :label="t(`schedules.form.${modelValue.kind}`)"
      reactive-rules
      :rules="[(v: string) => !!v?.trim() || t('schedules.form.required')]"
      @update:model-value="
        (v: string | number | null) =>
          emit('update:modelValue', { ...modelValue, value: String(v ?? '').trim() })
      "
    />
    <div v-else-if="modelValue.kind === 'machines'" class="col-12 col-sm-7 text-body2 self-center">
      {{
        t(
          'schedules.form.machinesChosen',
          { count: modelValue.machine_ids?.length ?? 0 },
          modelValue.machine_ids?.length ?? 0,
        )
      }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';
import type { Building, Room } from 'src/services/rooms';
import type { ScheduleTargetIn, TargetKind } from 'src/services/schedules';

const props = defineProps<{
  modelValue: ScheduleTargetIn;
  label: string;
  rooms: Room[];
  buildings: Building[];
  /** The postes of a selection, when the form was opened on one. */
  initialMachineIds?: string[] | undefined;
  /** The kinds offered; every one by default. */
  kinds?: TargetKind[] | undefined;
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: ScheduleTargetIn): void }>();

const kindOptions = computed(() => {
  const machines = props.initialMachineIds?.length || props.modelValue.kind === 'machines';
  const all: TargetKind[] = props.kinds ?? [
    ...(machines ? (['machines'] as TargetKind[]) : []),
    'room',
    'building',
    'location',
    'domain',
    'all',
  ];
  return all.map((k) => ({ label: t(`schedules.form.targetKind.${k}`), value: k }));
});
const roomOptions = computed(() =>
  props.rooms
    .map((r) => ({ label: r.building ? `${r.building.name} — ${r.name}` : r.name, value: r.id }))
    .sort((a, b) => a.label.localeCompare(b.label)),
);
const buildingOptions = computed(() =>
  props.buildings
    .map((b) => ({ label: b.name, value: b.id }))
    .sort((a, b) => a.label.localeCompare(b.label)),
);

function setKind(kind: TargetKind): void {
  if (kind === 'machines') {
    const ids = props.modelValue.machine_ids?.length
      ? props.modelValue.machine_ids
      : (props.initialMachineIds ?? []);
    emit('update:modelValue', { kind, machine_ids: ids });
  } else emit('update:modelValue', { kind, value: null });
}
</script>
