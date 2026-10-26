<template>
  <div class="col-12 col-md-6">
    <q-card flat bordered>
      <q-card-section class="text-subtitle1">Cartes graphiques</q-card-section>
      <q-separator />
      <q-list v-if="machine.gpus.length" dense>
        <q-item v-for="g in machine.gpus" :key="g.id">
          <q-item-section>
            <q-item-label>{{ g.name }}</q-item-label>
            <q-item-label caption>
              <span v-if="g.memory_mb != null">{{ sizeLabel(g.memory_mb) }}</span>
              <span v-if="g.resolution"> — {{ g.resolution }}</span>
              <span v-if="g.driver_version">
                — pilote {{ g.driver_version }}
                <span v-if="g.driver_date">({{ formatDate(g.driver_date) }})</span>
              </span>
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <q-card-section v-else class="text-caption text-muted">
        Aucune carte graphique relevée sur ce poste.
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import type { MachineDetail } from 'src/services/machines';
import { formatDate, sizeLabel } from 'src/utils/format';

/** Display adapters — two is the common case: an iGPU and a card. */
defineProps<{ machine: MachineDetail }>();
</script>
