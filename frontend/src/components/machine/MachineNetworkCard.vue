<template>
  <div class="col-12 col-md-6">
    <q-card flat bordered>
      <q-card-section class="text-subtitle1">
        {{ t('machine.network.title') }}
        <div class="text-caption text-muted">
          {{ t('machine.network.caption') }}
        </div>
      </q-card-section>
      <q-separator />
      <q-list v-if="machine.nics.length" dense>
        <q-item v-for="n in machine.nics" :key="n.id">
          <q-item-section avatar>
            <q-icon
              :name="n.type === 'wifi' ? 'wifi' : 'settings_ethernet'"
              :color="n.is_up ? 'positive' : 'grey-5'"
            >
              <q-tooltip>{{
                n.is_up ? t('machine.network.connected') : t('machine.network.disconnected')
              }}</q-tooltip>
            </q-icon>
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ n.name || n.mac }}
              <q-badge
                v-if="n.is_virtual"
                color="blue-grey-8"
                class="q-ml-sm"
                :label="t('machine.network.virtual')"
              />
              <q-badge
                v-if="isElected(n)"
                color="primary"
                class="q-ml-sm"
                :label="t('machine.network.elected')"
              />
            </q-item-label>
            <q-item-label caption>
              {{ nicTypeLabel(n.type) }}
              <span v-if="n.speed_mbps != null"> — {{ linkSpeedLabel(n.speed_mbps) }}</span>
              <span v-if="n.mac"> — {{ n.mac }}</span>
            </q-item-label>
            <q-item-label caption :class="{ 'text-weight-bold text-strong': isElected(n) }">
              {{ ipAddressLabel(n.ip_address, n.ip_prefix_length) }}
              <span v-if="n.gateway">
                — {{ t('machine.network.gateway', { gateway: n.gateway }) }}</span
              >
              <span v-if="n.is_dhcp != null">
                — {{ n.is_dhcp ? t('machine.network.dhcp') : t('machine.network.static') }}</span
              >
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <q-card-section v-else class="text-caption text-muted">
        {{ t('machine.network.none') }}
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { t } from 'src/i18n';
import type { MachineDetail, Nic } from 'src/services/machines';
import { ipAddressLabel, linkSpeedLabel, nicTypeLabel } from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail }>();

/**
 * Whether this row is the adapter the server talks to.
 *
 * Matched on the MAC, which is what the election reports alongside the address —
 * the two are read off the same adapter precisely so a wake cannot be broadcast
 * on the wrong subnet, and that is what makes the comparison meaningful here.
 */
function isElected(n: Nic): boolean {
  return n.mac != null && n.mac === props.machine.mac_address;
}
</script>
