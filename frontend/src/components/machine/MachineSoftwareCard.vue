<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="text-subtitle1 row items-center">
      <div>
        {{ t('machine.software.title') }}
        <div class="text-caption text-muted">
          {{ t('machine.software.caption') }}
        </div>
      </div>
      <q-space />
      <q-badge
        v-if="machine.software.length"
        color="grey-7"
        :label="`${machine.software.length}${machine.software_truncated ? '+' : ''}`"
      />
    </q-card-section>
    <q-separator />
    <!-- The list below is not the whole of it: said, rather than left to pass
         for a poste with few programs. -->
    <q-banner v-if="machine.software_truncated" class="surface-orange" dense>
      <template #avatar><q-icon name="hourglass_top" color="orange" /></template>
      {{ t('machine.software.truncated') }}
    </q-banner>
    <q-table
      :rows="machine.software"
      :columns="columns"
      row-key="software_id"
      :loading="loading"
      :filter="filter"
      flat
      :rows-per-page-options="[10, 25, 50, 0]"
      :no-data-label="t('machine.software.none')"
    >
      <template #top-right>
        <q-input
          v-model="filter"
          :aria-label="t('machine.software.filterAria')"
          dense
          outlined
          clearable
          debounce="200"
          :placeholder="t('machine.software.filterPlaceholder')"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </template>
      <template #body-cell-name="props">
        <q-td :props="props">
          {{ props.value }}
          <!-- The drill-down that makes an inventory a fleet tool: from one
               poste's program to every poste that carries it. -->
          <q-btn
            :aria-label="t('machine.software.whoHasIt')"
            flat
            dense
            round
            size="sm"
            icon="groups"
            color="primary"
            class="q-ml-xs"
            :to="{ name: 'machines', query: { software_id: props.row.software_id } }"
          >
            <q-tooltip>{{ t('machine.software.whoHasIt') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
      <template #body-cell-install_date="props">
        <q-td :props="props">{{ formatDate(props.value) }}</q-td>
      </template>
    </q-table>
  </q-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { t } from 'src/i18n';
import type { QTableColumn } from 'quasar';
import type { InstalledSoftware, MachineDetail } from 'src/services/machines';
import { formatDate } from 'src/utils/format';

defineProps<{ machine: MachineDetail; loading: boolean }>();

// Filtered client-side, unlike the two histories above: the whole list is
// already here — a few hundred rows the fiche fetched in one go — so a round
// trip per keystroke would buy nothing.
const filter = ref('');

// A computed: the headers follow the language when it changes.
const columns = computed<QTableColumn<InstalledSoftware>[]>(() => [
  {
    name: 'name',
    label: t('machine.software.columns.name'),
    field: 'name',
    align: 'left',
    sortable: true,
  },
  {
    name: 'version',
    label: t('machine.software.columns.version'),
    field: 'version',
    align: 'left',
    sortable: true,
  },
  {
    name: 'publisher',
    label: t('machine.software.columns.publisher'),
    field: 'publisher',
    align: 'left',
    sortable: true,
  },
  {
    name: 'install_date',
    label: t('machine.software.columns.installDate'),
    field: 'install_date',
    align: 'left',
    sortable: true,
  },
  // Which registry view it came from. Kept because "why does this program show
  // up as x86 on a 64-bit poste" is answered by it, and nowhere else.
  {
    name: 'arch',
    label: t('machine.software.columns.arch'),
    field: 'arch',
    align: 'left',
    sortable: true,
  },
]);
</script>
