<template>
  <!-- role="alert": the card around it would otherwise read as empty — and an
       empty card is exactly the all-clear this replaces. -->
  <q-banner role="alert" dense class="surface-red" rounded>
    <template #avatar><q-icon name="cloud_off" /></template>
    {{ t('common.loadError.card', { what }) }}
    <template #action>
      <q-btn
        flat
        dense
        no-caps
        :label="t('common.loadError.retry')"
        :loading="loading"
        @click="emit('retry')"
      />
    </template>
  </q-banner>
</template>

<script setup lang="ts">
import { t } from 'src/i18n';

/**
 * The error state of one card whose own request failed while the page around
 * it loaded. A card that could not read its data must say so: left to its
 * empty state, it would claim « aucune menace » about a list nobody read.
 *
 * `what` comes from the card, in the language shown (« les menaces »).
 */
withDefaults(defineProps<{ what: string; loading?: boolean }>(), { loading: false });
const emit = defineEmits<{ retry: [] }>();
</script>
