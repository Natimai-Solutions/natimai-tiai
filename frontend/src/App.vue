<template>
  <router-view />
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar';

// Root component.
const $q = useQuasar();
// An empty table is not a warning: « Chargement… », « Rien à faire. » and
// « Aucune donnée » wore Quasar's warning triangle, which read as an error
// (item 12). A neutral mark instead.
$q.iconSet.table.warning = 'info_outline';
</script>
