<template>
  <div class="col-12 col-md-6">
    <q-card flat bordered>
      <q-card-section class="text-subtitle1">
        Mémoire
        <div class="text-caption text-muted">
          {{ ramLabel(machine.ram_total_mb, machine.ram_slots_used, machine.ram_slots_total) }}
        </div>
      </q-card-section>
      <q-separator />
      <q-list v-if="machine.memory_modules.length" dense>
        <q-item v-for="m in machine.memory_modules" :key="m.id">
          <q-item-section>
            <q-item-label>
              {{ m.slot }}
              <span class="text-muted"> — {{ sizeLabel(m.capacity_mb) }}</span>
            </q-item-label>
            <q-item-label caption>
              {{ [m.type, m.form_factor].filter(Boolean).join(' ') || 'Type inconnu' }}
              <span v-if="m.speed_mhz"> — {{ m.speed_mhz }} MHz</span>
              <span v-if="m.manufacturer"> — {{ m.manufacturer }}</span>
              <span v-if="m.serial" class="text-muted"> — n° {{ m.serial }}</span>
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <q-card-section v-else class="text-caption text-muted">
        Aucune barrette relevée sur ce poste.
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import type { MachineDetail } from 'src/services/machines';
import { ramLabel, sizeLabel } from 'src/utils/format';

/**
 * The sticks, one per slot: what an upgrade decision reads — how many are in,
 * how big, what type, and whether the empty slot beside them takes the same.
 */
defineProps<{ machine: MachineDetail }>();
</script>
