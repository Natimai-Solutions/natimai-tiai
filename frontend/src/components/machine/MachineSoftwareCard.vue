<template>
  <q-card flat bordered class="q-mt-md">
    <q-card-section class="text-subtitle1 row items-center">
      <div>
        Logiciels installés
        <div class="text-caption text-muted">
          Lus dans le registre du poste, comme « Applications et fonctionnalités ». Les correctifs
          Windows n'y figurent pas : ils ont leur propre carte.
        </div>
      </div>
      <q-space />
      <q-badge
        v-if="machine.software.length"
        color="grey-7"
        :label="`${machine.software.length}`"
      />
    </q-card-section>
    <q-separator />
    <q-table
      :rows="machine.software"
      :columns="columns"
      row-key="software_id"
      :loading="loading"
      :filter="filter"
      flat
      :rows-per-page-options="[10, 25, 50, 0]"
      no-data-label="Aucun logiciel relevé — l'inventaire logiciel est peut-être désactivé sur ce poste."
    >
      <template #top-right>
        <q-input
          v-model="filter"
          aria-label="Filtrer les logiciels"
          dense
          outlined
          clearable
          debounce="200"
          placeholder="Filtrer…"
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
            aria-label="Voir les postes qui l'ont"
            flat
            dense
            round
            size="sm"
            icon="groups"
            color="primary"
            class="q-ml-xs"
            :to="{ name: 'machines', query: { software_id: props.row.software_id } }"
          >
            <q-tooltip>Voir les postes qui l'ont</q-tooltip>
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
import { ref } from 'vue';
import type { QTableColumn } from 'quasar';
import type { InstalledSoftware, MachineDetail } from 'src/services/machines';
import { formatDate } from 'src/utils/format';

defineProps<{ machine: MachineDetail; loading: boolean }>();

// Filtered client-side, unlike the two histories above: the whole list is
// already here — a few hundred rows the fiche fetched in one go — so a round
// trip per keystroke would buy nothing.
const filter = ref('');

const columns: QTableColumn<InstalledSoftware>[] = [
  { name: 'name', label: 'Nom', field: 'name', align: 'left', sortable: true },
  { name: 'version', label: 'Version', field: 'version', align: 'left', sortable: true },
  { name: 'publisher', label: 'Éditeur', field: 'publisher', align: 'left', sortable: true },
  {
    name: 'install_date',
    label: 'Installé le',
    field: 'install_date',
    align: 'left',
    sortable: true,
  },
  // Which registry view it came from. Kept because "why does this program show
  // up as x86 on a 64-bit poste" is answered by it, and nowhere else.
  { name: 'arch', label: 'Arch.', field: 'arch', align: 'left', sortable: true },
];
</script>
