<template>
  <!-- role="alert": announced as it appears — the page behind it is empty, and
       a screen reader would otherwise read nothing at all. -->
  <q-banner role="alert" class="surface-red q-mb-md" rounded>
    <template #avatar><q-icon name="cloud_off" /></template>
    {{ apiErrorMessage(error, fallback) }}
    <template #action>
      <q-btn flat no-caps label="Réessayer" :loading="loading" @click="emit('retry')" />
    </template>
  </q-banner>
</template>

<script setup lang="ts">
import { apiErrorMessage } from 'src/services/errors';

/**
 * Shown when a page has never managed to load. Background refreshes fail
 * silently on purpose (`useAutoRefresh`); a page with nothing to show must not
 * — an unreachable API would read as an empty parc.
 */
withDefaults(defineProps<{ error: unknown; loading?: boolean; fallback?: string }>(), {
  loading: false,
  fallback: 'Chargement impossible : le serveur ne répond pas.',
});
const emit = defineEmits<{ retry: [] }>();
</script>
