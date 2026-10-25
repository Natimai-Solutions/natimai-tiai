<template>
  <div class="col-12 col-md-6">
    <q-card flat bordered>
      <q-card-section class="text-subtitle1">
        Stockage
        <div class="text-caption text-muted">
          Occupation relevée au dernier inventaire — « Rafraîchir l'inventaire » force un relevé.
        </div>
      </q-card-section>
      <q-separator />

      <q-list v-if="machine.volumes.length" dense>
        <q-item v-for="v in machine.volumes" :key="v.id">
          <q-item-section>
            <q-item-label>
              {{ v.letter }}
              <span v-if="v.label" class="text-muted"> — {{ v.label }}</span>
              <q-badge v-if="v.is_system" color="primary" class="q-ml-sm" label="Système" />
              <q-badge
                :color="encryptionColor(v.encryption_status)"
                class="q-ml-sm"
                :label="encryptionLabel(v.encryption_status)"
              />
            </q-item-label>
            <!-- The bar is the whole point of this card: it is the one figure
                 an administrator reads at a glance, and the one that predicts a
                 poste about to stop taking Windows updates. -->
            <q-linear-progress
              :value="usedRatio(v)"
              :color="diskColor(freePercent(v.total_mb, v.free_mb))"
              size="8px"
              rounded
              class="q-mt-xs"
            />
            <q-item-label caption>
              {{ sizeLabel(v.free_mb) }} libres sur {{ sizeLabel(v.total_mb) }}
              <span v-if="freePercent(v.total_mb, v.free_mb) != null">
                ({{ freePercent(v.total_mb, v.free_mb) }} %)
              </span>
              <span v-if="v.filesystem" class="text-muted"> — {{ v.filesystem }}</span>
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <q-card-section v-else class="text-caption text-muted">
        Aucun volume relevé sur ce poste.
      </q-card-section>

      <template v-if="machine.disks.length">
        <q-separator />
        <q-card-section class="text-caption text-muted q-pb-none">Disques physiques</q-card-section>
        <q-list dense>
          <q-item v-for="d in machine.disks" :key="d.id">
            <q-item-section>
              <q-item-label>{{ d.model || d.device_id }}</q-item-label>
              <q-item-label caption>
                {{ mediaTypeLabel(d.media_type) }}
                <span v-if="d.bus_type"> — {{ d.bus_type }}</span>
                — {{ sizeLabel(d.size_mb) }}
                <span v-if="d.serial" class="text-muted"> — n° {{ d.serial }}</span>
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <!-- Only when it is not healthy: a green tick beside every disk on
                   every poste teaches the eye to skip the column, which is the
                   opposite of what a warning needs. -->
              <q-badge
                v-if="d.health_status && d.health_status !== 'Healthy'"
                color="negative"
                :label="d.health_status"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </template>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import type { MachineDetail, Volume } from 'src/services/machines';
import {
  diskColor,
  encryptionColor,
  encryptionLabel,
  freePercent,
  mediaTypeLabel,
  sizeLabel,
} from 'src/utils/format';

defineProps<{ machine: MachineDetail }>();

/** The bar fills with what is *used*: a full disk is a full bar. */
function usedRatio(v: Volume): number {
  if (!v.total_mb || v.free_mb == null) return 0;
  return Math.min(1, Math.max(0, (v.total_mb - v.free_mb) / v.total_mb));
}
</script>
