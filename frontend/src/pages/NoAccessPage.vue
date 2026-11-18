<template>
  <q-page padding class="flex flex-center column text-center">
    <q-icon name="lock" size="48px" color="grey-6" />
    <h1 class="text-h5 q-mb-sm">{{ t('layout.pages.noAccess') }}</h1>
    <p class="text-muted" style="max-width: 32em">
      {{ t('layout.noAccess.body') }}
    </p>
    <q-btn
      flat
      no-caps
      color="primary"
      :label="t('layout.pages.account')"
      :to="{ name: 'account' }"
    />
  </q-page>
</template>

<script setup lang="ts">
// Landing page of an account whose groups grant no read permission at all.
import { t } from 'src/i18n';
</script>
