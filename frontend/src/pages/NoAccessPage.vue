<template>
  <q-page padding class="flex flex-center column text-center">
    <q-icon name="lock" size="48px" color="grey-6" />
    <h1 class="text-h5 q-mb-sm">Aucune page accessible</h1>
    <p class="text-muted" style="max-width: 32em">
      Votre compte n'a le droit de consulter aucune page de la console. Demandez à un administrateur
      de vous ajouter au groupe qui convient ; la console le prendra en compte d'elle-même.
    </p>
    <q-btn flat no-caps color="primary" label="Mon compte" :to="{ name: 'account' }" />
  </q-page>
</template>

<script setup lang="ts">
// Landing page of an account whose groups grant no read permission at all.
</script>
