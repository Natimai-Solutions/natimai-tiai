<template>
  <div v-if="readiness" class="col-12 col-md-6">
    <q-card flat bordered class="full-height">
      <q-card-section>
        <div class="text-subtitle1">{{ t('assets.win11.title') }}</div>
        <div class="text-caption text-muted">{{ t('assets.win11.caption') }}</div>
      </q-card-section>
      <q-separator />
      <q-card-section class="row items-center no-wrap">
        <q-icon :name="icon" :color="color" size="28px" class="q-mr-sm" />
        <div class="text-body1 text-weight-medium">
          {{ t(`assets.win11.verdict.${readiness.verdict}`) }}
        </div>
      </q-card-section>
      <q-list v-if="readiness.verdict !== 'already'" dense>
        <q-item v-for="part in PARTS" :key="part">
          <q-item-section>{{ t(`assets.win11.parts.${part}`) }}</q-item-section>
          <q-item-section side>
            <q-badge :color="partColor(readiness[part])" outline>
              {{ t(`assets.win11.check.${readiness[part]}`) }}
            </q-badge>
          </q-item-section>
        </q-item>
      </q-list>
      <q-card-section
        v-if="readiness.verdict !== 'already'"
        class="text-caption text-muted q-pt-sm"
      >
        {{ t('assets.win11.processorHint') }}
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';
import type { MachineDetail, Windows11Readiness } from 'src/services/machines';

const props = defineProps<{ machine: MachineDetail }>();

const PARTS = ['tpm', 'ram', 'disk', 'architecture', 'secure_boot', 'processor'] as const;

const readiness = computed<Windows11Readiness | null>(() => props.machine.windows11 ?? null);

const icon = computed(() => {
  switch (readiness.value?.verdict) {
    case 'already':
    case 'ready':
      return 'check_circle';
    case 'blocked':
      return 'block';
    default:
      return 'help';
  }
});

const color = computed(() => {
  switch (readiness.value?.verdict) {
    case 'already':
    case 'ready':
      return 'positive';
    case 'blocked':
      return 'negative';
    default:
      return 'warning';
  }
});

function partColor(value: string): string {
  if (value === 'ok') return 'positive';
  if (value === 'fail') return 'negative';
  if (value === 'check') return 'warning';
  return 'grey-7';
}
</script>
