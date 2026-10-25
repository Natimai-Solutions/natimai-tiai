<template>
  <div class="col-12 col-md-6">
    <q-card flat bordered>
      <q-card-section class="text-subtitle1 row items-center">
        <div>
          {{ title }}
          <div v-if="caption" class="text-caption text-muted">{{ caption }}</div>
        </div>
        <q-space />
        <slot name="side" />
      </q-card-section>
      <q-separator />
      <!-- The label/value list is the default body; a card with something else
           to say (an explanation instead of a table of dashes) overrides it. -->
      <slot>
        <q-list dense>
          <q-item v-for="r in rows ?? []" :key="r.label">
            <q-item-section>{{ r.label }}</q-item-section>
            <q-item-section side class="text-strong">{{ r.value }}</q-item-section>
          </q-item>
        </q-list>
      </slot>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import type { InfoRow } from './types';

/**
 * The half-width card the machine detail page is built out of: a title, an
 * optional caption, an optional badge on the right, and a list of label/value
 * rows.
 *
 * It carries its own column wrapper rather than letting the page wrap it. A
 * card that hides itself (`v-if` on the component) then takes its gutter with
 * it, where an empty column left behind would open a hole in the grid.
 */
defineProps<{
  title: string;
  // `| undefined` spelled out, and no `withDefaults`: the project compiles with
  // `exactOptionalPropertyTypes`, under which an omitted prop and one passed as
  // `undefined` are different types — and a caption computed from the machine
  // is the second.
  caption?: string | undefined;
  rows?: InfoRow[] | undefined;
}>();
</script>
