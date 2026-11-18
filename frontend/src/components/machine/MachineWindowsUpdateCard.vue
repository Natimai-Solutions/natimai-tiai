<template>
  <MachineInfoCard :title="t('machine.windowsUpdate.title')" :rows="rows">
    <template #side>
      <q-badge v-if="machine.wu_reboot_required" color="orange" class="q-ml-sm">
        {{ t('machine.windowsUpdate.rebootRequired') }}
      </q-badge>
    </template>
  </MachineInfoCard>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';
import MachineInfoCard from './MachineInfoCard.vue';
import type { InfoRow } from './types';
import type { MachineDetail } from 'src/services/machines';
import { boolLabel, formatDateTime, wuPendingLabel } from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail }>();

const rows = computed<InfoRow[]>(() => {
  const m = props.machine;
  return [
    { label: t('machine.windowsUpdate.pending'), value: wuPendingLabel(m.wu_pending_count) },
    { label: t('machine.windowsUpdate.rebootRequired'), value: boolLabel(m.wu_reboot_required) },
    // Windows' own timestamps, not the agent's: they say when the machine
    // last managed to talk to its update source, which is what distinguishes
    // "nothing to install" from "has not checked since March".
    { label: t('machine.windowsUpdate.lastSearch'), value: formatDateTime(m.wu_last_search) },
    { label: t('machine.windowsUpdate.lastInstall'), value: formatDateTime(m.wu_last_install) },
  ];
});
</script>
