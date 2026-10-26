<template>
  <q-dialog v-model="open">
    <q-card style="min-width: 560px; max-width: 90vw">
      <q-card-section class="text-h6">Fusionner un doublon</q-card-section>

      <!-- Which record is kept, said with the UUID and not only the hostname:
           two records of one poste carry the *same* hostname, and naming both
           sides "PC-042" is what made the dialog read as a merge with itself. -->
      <q-card-section class="q-pt-none">
        <div class="text-caption text-muted">Poste conservé (celui-ci)</div>
        <div class="text-body2 text-weight-medium">{{ title }}</div>
        <div class="text-caption text-muted merge-uuid">{{ machine?.machine_uuid }}</div>
        <div class="text-caption text-muted q-mt-xs">
          Enrôlé le {{ formatDateTime(machine?.first_seen) }} — vu le
          {{ formatDateTime(machine?.last_seen) }}
        </div>
        <div class="text-caption text-muted q-mt-sm">
          Le poste choisi ci-dessous sera supprimé : ses menaces et commandes seront rattachées à
          l'enregistrement conservé. Action irréversible.
        </div>
      </q-card-section>

      <q-separator />
      <q-list separator>
        <q-item v-for="d in duplicates" :key="d.id">
          <q-item-section>
            <q-item-label>
              {{ d.hostname || d.machine_uuid }}
              <q-badge
                :color="matchReasonColor(d.match_reason)"
                class="q-ml-sm"
                :label="matchReasonLabel(d.match_reason)"
              />
            </q-item-label>
            <!-- The three lines that distinguish two records of one poste:
                 its own UUID, when it was enrolled, when it last reported. -->
            <q-item-label caption class="merge-uuid">{{ d.machine_uuid }}</q-item-label>
            <q-item-label caption>
              Enrôlé le {{ formatDateTime(d.first_seen) }} — vu le
              {{ formatDateTime(d.last_seen) }} ({{ timeAgoLabel(d.last_seen) }})
            </q-item-label>
            <q-item-label caption>{{ matchReasonHint(d.match_reason) }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn dense color="primary" label="Fusionner ici" @click="doMerge(d)" />
          </q-item-section>
        </q-item>
        <q-item v-if="!duplicates.length">
          <q-item-section class="text-muted">
            Aucun doublon détecté : aucun autre poste ne partage l'ancre matérielle (SMBIOS ou TPM)
            ni le nom de celui-ci. Un doublon dont le nom a changé se cherche ci-dessous.
          </q-item-section>
        </q-item>
      </q-list>

      <q-separator />
      <!-- Manual search, because detection cannot cover the case that most
           needs merging: when the anchor itself drifted, the two records have
           nothing left in common for the server to match on. -->
      <q-card-section>
        <div class="text-caption text-muted q-mb-sm">
          Chercher un autre poste à fusionner dans celui-ci — vérifiez l'UUID avant de
          confirmer&nbsp;: rien ne garantit qu'il s'agisse du même matériel.
        </div>
        <q-input
          v-model="search"
          aria-label="Poste à fusionner"
          dense
          outlined
          clearable
          debounce="300"
          placeholder="Nom, IP ou UUID du poste à fusionner…"
          :loading="searching"
          @update:model-value="runSearch"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-list v-if="results.length" separator dense class="q-mt-sm">
          <q-item v-for="m in results" :key="m.id">
            <q-item-section>
              <q-item-label>{{ m.hostname || m.machine_uuid }}</q-item-label>
              <q-item-label caption class="merge-uuid">{{ m.machine_uuid }}</q-item-label>
              <q-item-label caption>Vu le {{ formatDateTime(m.last_seen) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn dense flat color="primary" label="Fusionner ici" @click="doMerge(m)" />
            </q-item-section>
          </q-item>
        </q-list>
        <div v-else-if="search && !searching" class="text-caption text-muted q-mt-sm">
          Aucun autre poste ne correspond.
        </div>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn v-close-popup flat label="Fermer" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import {
  listMachines,
  mergeMachines,
  type DuplicateCandidate,
  type Machine,
  type MachineDetail,
  type MatchReason,
} from 'src/services/machines';
import { apiErrorMessage } from 'src/services/errors';
import { formatDateTime, timeAgoLabel } from 'src/utils/format';

const props = defineProps<{
  /** The record being kept — the merge target. */
  machine: MachineDetail | null;
  /** Its id, which is known even before the fiche has loaded. */
  machineId: string;
  duplicates: DuplicateCandidate[];
}>();

const open = defineModel<boolean>({ required: true });

const emit = defineEmits<{ merged: [] }>();

const $q = useQuasar();

const search = ref('');
const results = ref<Machine[]>([]);
const searching = ref(false);

const title = computed(() => props.machine?.hostname || props.machine?.machine_uuid || 'Poste');

// A search left over from the previous opening would offer candidates gathered
// for another poste — or for this one before a merge already removed them.
watch(open, (isOpen) => {
  if (isOpen) {
    search.value = '';
    results.value = [];
  }
});

const MATCH_REASON_LABELS: Record<MatchReason, string> = {
  smbios_uuid: 'Même carte mère',
  tpm_ek_hash: 'Même TPM',
  hostname: 'Même nom',
};

const MATCH_REASON_HINTS: Record<MatchReason, string> = {
  smbios_uuid: 'Ancre matérielle identique (SMBIOS UUID) : très probablement le même poste.',
  tpm_ek_hash: 'Même clé TPM : très probablement le même poste.',
  hostname:
    'Seul le nom correspond — cela peut aussi être un poste remplacé qui a repris le nom de l’ancien. À vérifier avant de fusionner.',
};

function matchReasonLabel(reason: MatchReason): string {
  return MATCH_REASON_LABELS[reason];
}

function matchReasonHint(reason: MatchReason): string {
  return MATCH_REASON_HINTS[reason];
}

/** Hardware evidence in the accent colour, a name match in a warning one: the
 * badge has to say at a glance which of the two decisions this is. */
function matchReasonColor(reason: MatchReason): string {
  return reason === 'hostname' ? 'orange' : 'primary';
}

/** Free search over the fleet for a poste to merge in, current one excluded. */
async function runSearch() {
  const term = (search.value ?? '').trim();
  if (!term) {
    results.value = [];
    return;
  }
  searching.value = true;
  try {
    const data = await listMachines({ search: term, page_size: 10 });
    results.value = data.items.filter((m) => m.id !== props.machineId);
  } catch (e) {
    results.value = [];
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec de la recherche') });
  } finally {
    searching.value = false;
  }
}

function doMerge(source: Machine) {
  // Both UUIDs in the confirmation: on two records of one poste the hostnames
  // are identical, and a confirmation naming the same string twice is exactly
  // the one an administrator clicks through without reading.
  const kept = props.machine?.machine_uuid ?? title.value;
  const removed = source.hostname
    ? `${escapeHtml(source.machine_uuid)} (${escapeHtml(source.hostname)})`
    : escapeHtml(source.machine_uuid);
  $q.dialog({
    title: 'Fusionner les postes',
    message:
      `<div>Supprimer l'enregistrement <b>${removed}</b> et rattacher son historique à ` +
      `<b>${escapeHtml(kept)}</b> ?</div>` +
      `<div class="q-mt-sm">Cette action est irréversible.</div>`,
    html: true,
    cancel: true,
    persistent: true,
  }).onOk(() => {
    void runMerge(source.id);
  });
}

/** Escape interpolated machine-reported text before it goes into the dialog's
 * HTML: a hostname comes from a poste, not from this console. */
function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
}

async function runMerge(sourceId: string) {
  try {
    await mergeMachines(props.machineId, sourceId);
    $q.notify({ type: 'positive', message: 'Postes fusionnés' });
    open.value = false;
    emit('merged');
  } catch (e) {
    $q.notify({ type: 'negative', message: apiErrorMessage(e, 'Échec de la fusion') });
  }
}
</script>

<style scoped>
/* The UUID is read character by character when two records have to be told
   apart — the one place in this page where a monospace face earns its keep. */
.merge-uuid {
  font-family: monospace;
  font-size: 11px;
}
</style>
