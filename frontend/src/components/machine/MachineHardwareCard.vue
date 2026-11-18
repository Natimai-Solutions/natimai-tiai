<template>
  <MachineInfoCard :title="t('machine.hardware.title')" :caption="caption" :rows="rows">
    <template #side>
      <q-badge v-if="machine.hw_is_virtual" color="blue-grey-8" class="q-ml-sm">
        {{ machine.hw_hypervisor || t('machine.hardware.virtual') }}
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
import {
  boolLabel,
  chassisLabel,
  cpuLabel,
  formatDate,
  formatDateTime,
  ramLabel,
} from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail }>();

/**
 * The date the inventory was taken, and deliberately not `last_seen`: a poste
 * seen a minute ago whose hardware was last read three weeks back is showing
 * stale facts, and the caption is where that gets admitted.
 */
const caption = computed(() =>
  props.machine.inventory_last_seen
    ? t('machine.hardware.readAt', { date: formatDateTime(props.machine.inventory_last_seen) })
    : t('machine.hardware.noInventory'),
);

const rows = computed<InfoRow[]>(() => {
  const m = props.machine;
  const rows: InfoRow[] = [
    { label: t('machine.hardware.manufacturer'), value: m.hw_manufacturer ?? '—' },
    { label: t('machine.hardware.model'), value: m.hw_model ?? '—' },
    { label: t('machine.hardware.serial'), value: m.hw_serial ?? '—' },
    { label: t('machine.hardware.chassis'), value: chassisLabel(m.hw_chassis_type) },
    { label: t('machine.hardware.motherboard'), value: motherboard(m) },
    { label: t('machine.hardware.bios'), value: bios(m) },
    {
      label: t('machine.hardware.cpu'),
      value: cpuLabel(m.cpu_model, m.cpu_cores, m.cpu_threads, m.cpu_count),
    },
    {
      label: t('machine.hardware.memory'),
      value: ramLabel(m.ram_total_mb, m.ram_slots_used, m.ram_slots_total),
    },
    { label: t('machine.hardware.architecture'), value: m.os_architecture ?? '—' },
    { label: t('machine.hardware.osInstalled'), value: formatDateTime(m.os_install_date) },
    { label: t('machine.hardware.lastBoot'), value: formatDateTime(m.last_boot_time) },
  ];
  // Secure Boot and the TPM are shown only where they mean something. A machine
  // with no UEFI has no Secure Boot to have off, and a virtual one has no TPM
  // chip — printing "Non" for either would read as a finding rather than as an
  // absence, and it is the sort of finding that generates a ticket.
  if (m.secure_boot != null) {
    rows.push({ label: t('machine.hardware.secureBoot'), value: boolLabel(m.secure_boot) });
  }
  if (m.tpm_version) {
    rows.push({ label: t('machine.hardware.tpm'), value: m.tpm_version });
  }
  return rows;
});

/** Manufacturer and model on one line: nobody reads them apart. */
function motherboard(m: MachineDetail): string {
  const parts = [m.mb_manufacturer, m.mb_model].filter(Boolean);
  return parts.length ? parts.join(' ') : '—';
}

/** Version and date together — the date is what says how old the machine is. */
function bios(m: MachineDetail): string {
  if (!m.bios_version && !m.bios_date) return '—';
  const version = m.bios_version ?? '—';
  return m.bios_date ? `${version} (${formatDate(m.bios_date)})` : version;
}
</script>
