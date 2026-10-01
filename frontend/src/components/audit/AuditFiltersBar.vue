<template>
  <div class="row items-start q-col-gutter-sm">
    <div class="col-12 col-sm-6 col-md-3">
      <q-select
        :model-value="modelValue.action"
        :options="actionOptions"
        emit-value
        map-options
        clearable
        outlined
        dense
        options-dense
        label="Action"
        @update:model-value="(v: string | null) => set({ action: v || null })"
      />
    </div>
    <div class="col-12 col-sm-6 col-md-3">
      <q-input
        :model-value="modelValue.actor"
        outlined
        dense
        clearable
        debounce="300"
        label="Auteur"
        maxlength="320"
        placeholder="E-mail…"
        @update:model-value="(v) => set({ actor: v == null ? '' : String(v) })"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>
    </div>
    <div class="col-12 col-sm-4 col-md-2">
      <q-select
        :model-value="modelValue.resourceType"
        :options="resourceTypeOptions"
        emit-value
        map-options
        clearable
        outlined
        dense
        options-dense
        label="Type de ressource"
        @update:model-value="
          (v: string | null) => set({ resourceType: v || null, resourceId: null })
        "
      />
    </div>
    <!-- Calendar days in the reader's own time zone; the page turns them into
         instants, the last day included. -->
    <div class="col-6 col-sm-4 col-md-2">
      <q-input
        :model-value="modelValue.from"
        type="date"
        outlined
        dense
        clearable
        stack-label
        label="Du"
        :max="modelValue.to ?? undefined"
        @update:model-value="(v) => set({ from: v ? String(v) : null })"
      />
    </div>
    <div class="col-6 col-sm-4 col-md-2">
      <q-input
        :model-value="modelValue.to"
        type="date"
        outlined
        dense
        clearable
        stack-label
        label="Au (inclus)"
        :min="modelValue.from ?? undefined"
        :error="inverted"
        error-message="Antérieure à la date de début"
        hide-bottom-space
        @update:model-value="(v) => set({ to: v ? String(v) : null })"
      />
    </div>

    <div v-if="modelValue.resourceId || active" class="col-12 row items-center q-gutter-sm">
      <!-- The id filter has no field of its own: it arrives from a link or from
           an entry's « Toutes les actions sur cette ressource ». -->
      <q-chip
        v-if="modelValue.resourceId"
        removable
        dense
        color="primary"
        text-color="white"
        icon="filter_alt"
        @remove="set({ resourceId: null })"
      >
        {{ resourceChip }}
      </q-chip>
      <q-btn
        v-if="active"
        flat
        dense
        no-caps
        color="primary"
        icon="filter_alt_off"
        label="Réinitialiser les filtres"
        @click="emit('update:modelValue', emptyAuditFilters())"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import {
  AUDIT_RESOURCE_TYPE_LABELS,
  auditActionOptions,
  auditResourceTypeLabel,
} from 'src/utils/auditLabels';
import {
  emptyAuditFilters,
  hasAuditFilters,
  isAuditPeriodInverted,
  type AuditFilters,
} from 'src/utils/auditQuery';

const props = defineProps<{
  modelValue: AuditFilters;
  /** Action slugs to offer — those present in the log. */
  actions: string[];
}>();
const emit = defineEmits<{ (e: 'update:modelValue', value: AuditFilters): void }>();

// The selected action stays offered even when absent from the list (a URL
// pasted before the log was purged, or the list still loading).
const actionOptions = computed(() =>
  auditActionOptions(
    props.modelValue.action ? [...props.actions, props.modelValue.action] : props.actions,
  ),
);

const resourceTypeOptions = Object.entries(AUDIT_RESOURCE_TYPE_LABELS).map(([value, label]) => ({
  value,
  label,
}));

const active = computed(() => hasAuditFilters(props.modelValue));
const inverted = computed(() => isAuditPeriodInverted(props.modelValue.from, props.modelValue.to));

const resourceChip = computed(() => {
  const { resourceType, resourceId } = props.modelValue;
  return resourceType ? `${auditResourceTypeLabel(resourceType)} ${resourceId}` : resourceId;
});

function set(patch: Partial<AuditFilters>) {
  emit('update:modelValue', { ...props.modelValue, ...patch });
}
</script>
