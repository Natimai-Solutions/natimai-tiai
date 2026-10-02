<template>
  <!-- The page's own line — which columns, export, how fresh the list is —
       above the one about what is in it (search and filters). One row wearing
       all of it read as a strip of look-alike icons stuck together, so each
       button carries a label and a colour of its own. -->
  <div class="row items-center q-col-gutter-md q-mb-sm">
    <div class="text-h5 col-auto">Postes</div>
    <q-space />
    <div class="col-auto">
      <q-btn
        outline
        no-caps
        color="primary"
        icon="view_column"
        label="Colonnes"
        @click="emit('columns')"
      >
        <q-tooltip>Colonnes affichées et leur ordre — enregistrés sur votre compte</q-tooltip>
      </q-btn>
    </div>
    <div class="col-auto">
      <q-btn
        outline
        no-caps
        color="positive"
        icon="download"
        label="Exporter"
        @click="emit('export')"
      >
        <q-tooltip>Exporter le parc filtré (Excel ou CSV, colonnes au choix)</q-tooltip>
      </q-btn>
    </div>
    <div v-if="lastRefreshedAt" class="text-caption text-grey col-auto">
      Actualisé à {{ lastRefreshedAt.toLocaleTimeString('fr-FR') }}
    </div>
    <div class="col-auto">
      <q-btn
        flat
        round
        color="primary"
        icon="refresh"
        aria-label="Actualiser"
        :loading="loading"
        @click="emit('refresh')"
      >
        <q-tooltip>{{ autoRefreshHint }}</q-tooltip>
      </q-btn>
    </div>
  </div>
</template>

<script setup lang="ts">
import { AUTO_REFRESH_INTERVAL_MS } from 'src/composables/useAutoRefresh';

defineProps<{
  /** The user-visible load: only « Actualiser » turns the spinner on. */
  loading: boolean;
  lastRefreshedAt: Date | null;
}>();

const emit = defineEmits<{ columns: []; export: []; refresh: [] }>();

const autoRefreshHint = `Actualiser — automatique toutes les ${Math.round(
  AUTO_REFRESH_INTERVAL_MS / 1000,
)} s, en pause pendant une sélection`;
</script>
