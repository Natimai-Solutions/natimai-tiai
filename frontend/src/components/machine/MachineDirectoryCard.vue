<template>
  <!-- The directory as a reader read it, beside the agent's word
       (plan-lecture-annuaire.md). Only where the server reads it. -->
  <div v-if="machine.directory_mode === 'relay'" class="col-12 col-md-6">
    <q-card flat bordered class="full-height" data-test="directory-card">
      <q-card-section class="row items-center no-wrap">
        <div class="col">
          <div class="text-subtitle1">{{ t('directory.card.title') }}</div>
          <div class="text-caption text-muted">{{ t('directory.card.caption') }}</div>
        </div>
        <q-badge v-if="status" :color="statusColor" data-test="directory-status">
          {{ t(`directory.status.${status}`) }}
          <q-tooltip>{{ t(`directory.statusHint.${status}`) }}</q-tooltip>
        </q-badge>
      </q-card-section>
      <q-separator />
      <q-markup-table flat dense wrap-cells separator="horizontal">
        <thead>
          <tr>
            <th />
            <th class="text-left">{{ t('directory.card.declared') }}</th>
            <th class="text-left">{{ t('directory.card.read') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.label" :class="{ 'text-warn': row.differs }">
            <td class="text-muted">{{ row.label }}</td>
            <td class="dn-cell">{{ row.declared }}</td>
            <td class="dn-cell">{{ row.read }}</td>
          </tr>
        </tbody>
      </q-markup-table>
      <q-card-section v-if="machine.directory_reader" class="text-caption">
        <q-icon name="menu_book" class="q-mr-xs" />
        {{ t('directory.card.reader', { date: formatDateTime(machine.directory_reader_since) }) }}
      </q-card-section>
      <q-card-actions v-if="canWrite" align="right">
        <q-btn
          v-if="machine.directory_reader"
          flat
          no-caps
          color="negative"
          :label="t('directory.card.revoke')"
          :loading="busy"
          @click="toggle(false)"
        />
        <q-btn
          v-else-if="machine.domain"
          flat
          no-caps
          color="primary"
          icon="menu_book"
          :label="t('directory.card.designate')"
          :loading="busy"
          @click="toggle(true)"
        >
          <q-tooltip max-width="320px">{{ t('directory.card.designateHint') }}</q-tooltip>
        </q-btn>
      </q-card-actions>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { designateReader, isDirectoryStatus, revokeReader } from 'src/services/directory';
import { apiErrorMessage } from 'src/services/errors';
import type { MachineDetail } from 'src/services/machines';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { notify } from 'src/utils/notify';

const props = defineProps<{ machine: MachineDetail }>();
const emit = defineEmits<{ changed: [] }>();

const $q = useQuasar();
const auth = useAuthStore();
const canWrite = computed(() => auth.can('settings', 'write'));
const busy = ref(false);

const status = computed(() => {
  const s = props.machine.directory_status ?? '';
  return isDirectoryStatus(s) ? s : null;
});

const statusColor = computed(() => {
  if (status.value === 'verified') return 'positive';
  if (status.value === 'mismatch') return 'orange-8';
  return 'grey-7';
});

function same(a: string | null | undefined, b: string | null | undefined): boolean {
  return (a ?? '').trim().toLowerCase() === (b ?? '').trim().toLowerCase();
}

const rows = computed(() => {
  const m = props.machine;
  const read = m.directory_status !== null && m.directory_status !== undefined;
  return [
    {
      label: t('directory.card.dn'),
      declared: m.ad_distinguished_name ?? '—',
      read: m.dir_distinguished_name ?? '—',
      differs:
        read &&
        !!m.ad_distinguished_name &&
        !same(m.ad_distinguished_name, m.dir_distinguished_name),
    },
    {
      label: t('directory.card.ou'),
      declared: m.ad_ou ?? '—',
      read: m.dir_ou ?? '—',
      differs: read && !!m.ad_ou && !same(m.ad_ou, m.dir_ou),
    },
    {
      label: t('directory.card.location'),
      declared: m.ad_location ?? '—',
      read: m.dir_location ?? '—',
      differs: read && !same(m.ad_location, m.dir_location),
    },
  ];
});

async function toggle(on: boolean): Promise<void> {
  busy.value = true;
  try {
    if (on) await designateReader(props.machine.id);
    else await revokeReader(props.machine.id);
    notify($q, () => ({
      type: 'positive',
      message: t(on ? 'directory.card.designated' : 'directory.card.revoked'),
    }));
    emit('changed');
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('directory.domain.failed')),
    }));
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.dn-cell {
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
