<template>
  <q-card flat bordered>
    <!-- The five facts read on the way to an action, one glance each. -->
    <q-card-section class="row q-col-gutter-md">
      <div class="col-6 col-sm-4 col-md">
        <div class="text-caption text-muted">Antivirus</div>
        <q-badge :color="protectionColor(machine.is_up_to_date)" class="q-mt-xs">
          {{ antivirusLabel(machine.av_product_name) }}
        </q-badge>
        <div class="text-caption q-mt-xs">{{ protectionLabel(machine.is_up_to_date) }}</div>
      </div>
      <div class="col-6 col-sm-4 col-md">
        <div class="text-caption text-muted">Windows Update</div>
        <q-badge :color="wuPendingColor(machine.wu_pending_count)" class="q-mt-xs">
          {{ wuPendingLabel(machine.wu_pending_count) }}
        </q-badge>
        <q-icon
          v-if="machine.wu_reboot_required"
          name="restart_alt"
          color="orange"
          size="18px"
          class="q-ml-xs"
        >
          <q-tooltip>Redémarrage requis</q-tooltip>
        </q-icon>
        <div class="text-caption q-mt-xs">
          {{ machine.wu_pending_count ? 'en attente' : 'mises à jour' }}
        </div>
      </div>
      <div class="col-6 col-sm-4 col-md">
        <div class="text-caption text-muted">Disque système</div>
        <template v-if="machine.system_volume_total_mb">
          <q-linear-progress
            :value="usedRatio"
            :color="diskColor(free)"
            size="8px"
            rounded
            class="q-mt-sm"
            style="max-width: 140px"
          />
          <div class="text-caption q-mt-xs">
            {{ sizeLabel(machine.system_volume_free_mb) }} libres ({{ free }} %)
          </div>
        </template>
        <div v-else class="text-caption text-muted q-mt-xs">Non relevé</div>
      </div>
      <div class="col-6 col-sm-4 col-md">
        <div class="text-caption text-muted">Session</div>
        <q-badge :color="sessionColor(machine.session_user_present)" class="q-mt-xs">
          {{ sessionLabel(machine.session_user_present, machine.session_username) }}
        </q-badge>
        <div class="text-caption q-mt-xs">
          {{ sessionTypeLabel(machine.session_state, machine.session_is_remote) }}
        </div>
      </div>
      <div class="col-6 col-sm-4 col-md">
        <div class="text-caption text-muted">Dernier contact</div>
        <div class="q-mt-xs">
          <q-icon
            :name="onlineIcon(machine.is_online)"
            :color="onlineColor(machine.is_online)"
            size="12px"
            class="q-mr-xs"
          />
          {{ timeAgoLabel(machine.last_seen) }}
        </div>
        <div class="text-caption q-mt-xs">{{ onlineLabel(machine.is_online) }}</div>
      </div>
    </q-card-section>

    <q-separator />

    <!-- The findings. Each line is a place to go: clicking opens the tab that
         holds the detail behind it. -->
    <q-list v-if="alerts.length" dense>
      <q-item
        v-for="alert in alerts"
        :key="alert.key"
        clickable
        @click="emit('open-tab', alert.tab)"
      >
        <q-item-section avatar>
          <q-icon :name="alert.icon" :color="levelColor(alert.level)" />
        </q-item-section>
        <q-item-section>
          <q-item-label :class="levelClass(alert.level)">{{ alert.text }}</q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-icon name="chevron_right" color="grey-5" />
        </q-item-section>
      </q-item>
    </q-list>
    <q-card-section v-else class="row items-center text-positive">
      <q-icon name="check_circle" class="q-mr-sm" />
      Aucune alerte sur ce poste.
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { MachineTab } from './types';
import type { MachineDetail } from 'src/services/machines';
import { machineAlerts, type MachineAlert } from 'src/utils/machineAlerts';
import {
  antivirusLabel,
  diskColor,
  freePercent,
  onlineColor,
  onlineIcon,
  onlineLabel,
  protectionColor,
  protectionLabel,
  sessionColor,
  sessionLabel,
  sessionTypeLabel,
  sizeLabel,
  timeAgoLabel,
  wuPendingColor,
  wuPendingLabel,
} from 'src/utils/format';

/**
 * The head of the fiche: what the poste's state is, and what is wrong with it.
 * Everything else on the page is detail behind one of these lines.
 */
const props = defineProps<{
  machine: MachineDetail;
  /** Threats Defender has not dealt with — counted server-side, not paged. */
  activeThreats: number;
}>();

const emit = defineEmits<{ 'open-tab': [tab: MachineTab] }>();

const alerts = computed<MachineAlert[]>(() => machineAlerts(props.machine, props.activeThreats));

const free = computed(() =>
  freePercent(props.machine.system_volume_total_mb, props.machine.system_volume_free_mb),
);

/** The bar fills with what is *used*: a full disk is a full bar. */
const usedRatio = computed(() => {
  const total = props.machine.system_volume_total_mb;
  const freeMb = props.machine.system_volume_free_mb;
  if (!total || freeMb == null) return 0;
  return Math.min(1, Math.max(0, (total - freeMb) / total));
});

function levelColor(level: MachineAlert['level']): string {
  return level === 'negative' ? 'negative' : level === 'warning' ? 'orange' : 'grey-7';
}

function levelClass(level: MachineAlert['level']): string {
  return level === 'negative' ? 'text-negative text-weight-medium' : '';
}
</script>
