<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center column">
        <div class="text-h2">404</div>
        <div class="text-subtitle1 q-mb-md">Page introuvable</div>
        <q-btn color="primary" to="/" label="Retour à l'accueil" />
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
// 404 page.
</script>
