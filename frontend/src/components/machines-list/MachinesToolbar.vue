<template>
  <!-- The page's own line — which columns, export, how fresh the list is —
       above the one about what is in it (search and filters). One row wearing
       all of it read as a strip of look-alike icons stuck together, so each
       button carries a label and a colour of its own. -->
  <div class="row items-center q-col-gutter-md q-mb-sm">
    <h1 class="text-h5 q-my-none col-auto">{{ t('machines.toolbar.title') }}</h1>
    <q-space />
    <div class="col-auto">
      <q-btn
        outline
        no-caps
        color="primary"
        icon="view_column"
        :label="t('machines.toolbar.columns')"
        @click="emit('columns')"
      >
        <q-tooltip>{{ t('machines.toolbar.columnsHint') }}</q-tooltip>
      </q-btn>
    </div>
    <div class="col-auto">
      <q-btn
        outline
        no-caps
        color="positive"
        icon="download"
        :label="t('machines.toolbar.export')"
        @click="emit('export')"
      >
        <q-tooltip>{{ t('machines.toolbar.exportHint') }}</q-tooltip>
      </q-btn>
    </div>
    <div v-if="lastRefreshedAt" class="text-caption text-muted col-auto">
      {{
        t('machines.toolbar.refreshedAt', { time: lastRefreshedAt.toLocaleTimeString(intlTag()) })
      }}
    </div>
    <div class="col-auto">
      <q-btn
        flat
        round
        color="primary"
        icon="refresh"
        :aria-label="t('machines.toolbar.refresh')"
        :loading="loading"
        @click="emit('refresh')"
      >
        <q-tooltip>{{ autoRefreshHint }}</q-tooltip>
      </q-btn>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { intlTag, t } from 'src/i18n';
import { AUTO_REFRESH_INTERVAL_MS } from 'src/composables/useAutoRefresh';

defineProps<{
  /** The user-visible load: only « Actualiser » turns the spinner on. */
  loading: boolean;
  lastRefreshedAt: Date | null;
}>();

const emit = defineEmits<{ columns: []; export: []; refresh: [] }>();

const autoRefreshHint = computed(() =>
  t('machines.toolbar.autoRefreshHint', { seconds: Math.round(AUTO_REFRESH_INTERVAL_MS / 1000) }),
);
</script>
