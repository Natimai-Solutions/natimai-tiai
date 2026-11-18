<template>
  <MachineInfoCard :title="t('machine.defender.title')" :caption="caption" :rows="rows" />
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';
import MachineInfoCard from './MachineInfoCard.vue';
import type { InfoRow } from './types';
import type { MachineDetail } from 'src/services/machines';
import { boolLabel, formatDateTime, runningModeLabel } from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail }>();

const caption = computed(() =>
  props.machine.av_product_is_defender ? t('machine.defender.caption') : undefined,
);

const rows = computed<InfoRow[]>(() => {
  const m = props.machine;
  return [
    { label: t('machine.defender.enabled'), value: boolLabel(m.av_enabled) },
    { label: t('machine.defender.realTime'), value: boolLabel(m.rtp_enabled) },
    // Placed right under the two flags above: this is the row that explains
    // them reading "Non" on a machine that is in fact protected, a
    // third-party antivirus having pushed Defender into passive mode.
    { label: t('machine.defender.runningMode'), value: runningModeLabel(m.running_mode) },
    { label: t('machine.defender.upToDate'), value: boolLabel(m.is_up_to_date) },
    { label: t('machine.defender.signatureVersion'), value: m.signature_version ?? '—' },
    {
      label: t('machine.defender.signatureUpdated'),
      value: formatDateTime(m.signature_last_updated),
    },
    { label: t('machine.defender.signatureAge'), value: m.signature_age_days ?? '—' },
    { label: t('machine.defender.quickScan'), value: formatDateTime(m.last_quick_scan) },
    { label: t('machine.defender.fullScan'), value: formatDateTime(m.last_full_scan) },
  ];
});
</script>
