<template>
  <MachineInfoCard title="Identité" :rows="rows" />
</template>

<script setup lang="ts">
import { computed } from 'vue';
import MachineInfoCard from './MachineInfoCard.vue';
import type { InfoRow } from './types';
import type { MachineDetail } from 'src/services/machines';
import { agentVersionLabel } from 'src/utils/agentVersion';
import {
  formatDateTime,
  ipAddressLabel,
  onlineLabel,
  sessionLabel,
  sessionTypeLabel,
  timeAgoLabel,
} from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail }>();

const rows = computed<InfoRow[]>(() => {
  const m = props.machine;
  return [
    { label: 'Nom', value: m.hostname ?? '—' },
    { label: 'UUID machine', value: m.machine_uuid },
    { label: 'Domaine', value: m.domain ?? '—' },
    // As the agent's configuration names it — a dash means the deployment set
    // none, and the wake relay then falls back on the domain.
    { label: 'Emplacement', value: m.location ?? '—' },
    { label: 'Adresse IP', value: ipAddressLabel(m.ip_address, m.ip_prefix_length) },
    // Right under the address it was elected with, and for two reasons: it
    // is the wake target — a dash here means « Réveiller le poste » has
    // nothing to aim at — and it is what an admin compares against the
    // switch when a wake did not work.
    { label: 'Adresse MAC', value: m.mac_address ?? '—' },
    { label: 'OS', value: m.os_version ?? '—' },
    // With its standing, not just its number: "0.4.1" says nothing on its own,
    // "0.4.1 — obsolète (référence 0.5.0)" says the deployment missed this one.
    { label: 'Version agent', value: agentVersionLabel(m.agent_version, m.agent_latest_version) },
    { label: 'SMBIOS UUID', value: m.smbios_uuid ?? '—' },
    { label: 'MachineGuid', value: m.machine_guid ?? '—' },
    { label: 'Session', value: sessionLabel(m.session_user_present, m.session_username) },
    {
      label: 'Type de session',
      value: sessionTypeLabel(m.session_state, m.session_is_remote),
    },
    // Kept adjacent to the two rows above: the session is only as fresh as
    // the last heartbeat, and this is the timestamp that says how fresh.
    // The presence rides along rather than taking a row of its own — it is
    // read from this very timestamp, and it is what says whether a command
    // queued here will be picked up now or at the poste's next boot.
    {
      label: 'Vu le',
      value: `${formatDateTime(m.last_seen)} (${timeAgoLabel(m.last_seen)}) — ${onlineLabel(
        m.is_online,
      )}`,
    },
  ];
});
</script>
