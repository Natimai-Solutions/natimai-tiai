<template>
  <!-- role="alert": announced as it appears — the page behind it is empty, and
       a screen reader would otherwise read nothing at all. -->
  <q-banner role="alert" class="surface-red q-mb-md" rounded>
    <template #avatar><q-icon name="cloud_off" /></template>
    {{ apiErrorMessage(error, fallback ?? t('common.loadError.fallback')) }}
    <template #action>
      <q-btn
        flat
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
import { apiErrorMessage } from 'src/services/errors';

/**
 * Shown when a page has never managed to load. Background refreshes fail
 * silently on purpose (`useAutoRefresh`); a page with nothing to show must not
 * — an unreachable API would read as an empty parc.
 *
 * Without a `fallback` of its own, it says the server did not answer — in the
 * language shown when it renders: the default is no text, worded in the
 * template.
 */
withDefaults(defineProps<{ error: unknown; loading?: boolean; fallback?: string | undefined }>(), {
  loading: false,
  fallback: undefined,
});
const emit = defineEmits<{ retry: [] }>();
</script>
