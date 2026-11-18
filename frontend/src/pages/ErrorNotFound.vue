<template>
  <!-- Route montée hors de MainLayout : QPage exige un QLayout ancêtre. -->
  <q-layout view="lHh Lpr lFf">
    <q-page-container>
      <q-page class="flex flex-center column">
        <div class="text-h2">404</div>
        <div class="text-subtitle1 q-mb-md">{{ t('layout.pages.notFound') }}</div>
        <q-btn color="primary" to="/" :label="t('layout.notFound.home')" />
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
// 404 page.
import { t } from 'src/i18n';
</script>
