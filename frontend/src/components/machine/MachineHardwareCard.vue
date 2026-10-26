<template>
  <MachineInfoCard title="Matériel" :caption="caption" :rows="rows">
    <template #side>
      <q-badge v-if="machine.hw_is_virtual" color="blue-grey-8" class="q-ml-sm">
        {{ machine.hw_hypervisor || 'Machine virtuelle' }}
      </q-badge>
    </template>
  </MachineInfoCard>
</template>

<script setup lang="ts">
import { computed } from 'vue';
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
    ? `Relevé le ${formatDateTime(props.machine.inventory_last_seen)}`
    : "Aucun inventaire relevé — l'agent de ce poste est antérieur au module, ou n'a pas encore tourné.",
);

const rows = computed<InfoRow[]>(() => {
  const m = props.machine;
  const rows: InfoRow[] = [
    { label: 'Constructeur', value: m.hw_manufacturer ?? '—' },
    { label: 'Modèle', value: m.hw_model ?? '—' },
    { label: 'N° de série', value: m.hw_serial ?? '—' },
    { label: 'Châssis', value: chassisLabel(m.hw_chassis_type) },
    { label: 'Carte mère', value: motherboard(m) },
    { label: 'BIOS', value: bios(m) },
    { label: 'Processeur', value: cpuLabel(m.cpu_model, m.cpu_cores, m.cpu_threads, m.cpu_count) },
    { label: 'Mémoire', value: ramLabel(m.ram_total_mb, m.ram_slots_used, m.ram_slots_total) },
    { label: 'Architecture', value: m.os_architecture ?? '—' },
    { label: 'Windows installé le', value: formatDateTime(m.os_install_date) },
    { label: 'Dernier démarrage', value: formatDateTime(m.last_boot_time) },
  ];
  // Secure Boot and the TPM are shown only where they mean something. A machine
  // with no UEFI has no Secure Boot to have off, and a virtual one has no TPM
  // chip — printing "Non" for either would read as a finding rather than as an
  // absence, and it is the sort of finding that generates a ticket.
  if (m.secure_boot != null) {
    rows.push({ label: 'Secure Boot', value: boolLabel(m.secure_boot) });
  }
  if (m.tpm_version) {
    rows.push({ label: 'TPM', value: m.tpm_version });
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
