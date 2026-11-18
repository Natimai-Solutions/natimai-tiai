<template>
  <MachineInfoCard :title="t('machine.identity.title')" :rows="rows" />
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';
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

/** The room, and the site it puts the poste on when the agent disagrees. */
function roomRow(m: MachineDetail): string {
  if (!m.room_name) return '—';
  if (!m.location_mismatch) return m.room_name;
  return t('machine.identity.roomMismatch', { room: m.room_name, location: m.room_location });
}

const rows = computed<InfoRow[]>(() => {
  const m = props.machine;
  return [
    { label: t('machine.identity.name'), value: m.hostname ?? '—' },
    { label: t('machine.identity.uuid'), value: m.machine_uuid },
    { label: t('machine.identity.domain'), value: m.domain ?? '—' },
    // As the agent's configuration names it — a dash means the deployment set
    // none, and the wake relay then falls back on the domain.
    { label: t('machine.identity.location'), value: m.location ?? '—' },
    // Where the console filed it, right under where the agent says it is —
    // the two are read together, and the fiche says so when they disagree.
    { label: t('machine.identity.building'), value: m.building_name ?? '—' },
    { label: t('machine.identity.room'), value: roomRow(m) },
    // What the directory says, whatever ROOM_SOURCE does with it: the
    // input of an automatic placement, and what explains one.
    ...(m.ad_ou || m.ad_location || m.ad_distinguished_name
      ? [
          { label: t('machine.identity.adOu'), value: m.ad_ou ?? '—' },
          { label: t('machine.identity.adLocation'), value: m.ad_location ?? '—' },
          { label: t('machine.identity.adObject'), value: m.ad_distinguished_name ?? '—' },
        ]
      : []),
    { label: t('machine.identity.ip'), value: ipAddressLabel(m.ip_address, m.ip_prefix_length) },
    // Right under the address it was elected with, and for two reasons: it
    // is the wake target — a dash here means « Réveiller le poste » has
    // nothing to aim at — and it is what an admin compares against the
    // switch when a wake did not work.
    { label: t('machine.identity.mac'), value: m.mac_address ?? '—' },
    { label: t('machine.identity.os'), value: m.os_version ?? '—' },
    // With its standing, not just its number: "0.4.1" says nothing on its own,
    // "0.4.1 — obsolète (référence 0.5.0)" says the deployment missed this one.
    {
      label: t('machine.identity.agentVersion'),
      value: agentVersionLabel(m.agent_version, m.agent_latest_version),
    },
    { label: t('machine.identity.smbiosUuid'), value: m.smbios_uuid ?? '—' },
    { label: t('machine.identity.machineGuid'), value: m.machine_guid ?? '—' },
    {
      label: t('machine.identity.session'),
      value: sessionLabel(m.session_user_present, m.session_username),
    },
    {
      label: t('machine.identity.sessionType'),
      value: sessionTypeLabel(m.session_state, m.session_is_remote),
    },
    // Kept adjacent to the two rows above: the session is only as fresh as
    // the last heartbeat, and this is the timestamp that says how fresh.
    // The presence rides along rather than taking a row of its own — it is
    // read from this very timestamp, and it is what says whether a command
    // queued here will be picked up now or at the poste's next boot.
    {
      label: t('machine.identity.seen'),
      value: `${formatDateTime(m.last_seen)} (${timeAgoLabel(m.last_seen)}) — ${onlineLabel(
        m.is_online,
      )}`,
    },
  ];
});
</script>
