<template>
  <q-dialog v-model="open">
    <q-card style="width: 560px; max-width: 95vw">
      <q-card-section class="text-h6">{{ t('machine.merge.title') }}</q-card-section>

      <!-- Which record is kept, said with the UUID and not only the hostname:
           two records of one poste carry the *same* hostname, and naming both
           sides "PC-042" is what made the dialog read as a merge with itself. -->
      <q-card-section class="q-pt-none">
        <div class="text-caption text-muted">{{ t('machine.merge.kept') }}</div>
        <div class="text-body2 text-weight-medium">{{ title }}</div>
        <div class="text-caption text-muted merge-uuid">{{ machine?.machine_uuid }}</div>
        <div class="text-caption text-muted q-mt-xs">
          {{
            t('machine.merge.enrolledSeen', {
              enrolled: formatDateTime(machine?.first_seen),
              seen: formatDateTime(machine?.last_seen),
            })
          }}
        </div>
        <div class="text-caption text-muted q-mt-sm">
          {{ t('machine.merge.warning') }}
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
              {{
                t('machine.merge.enrolledSeen', {
                  enrolled: formatDateTime(d.first_seen),
                  seen: formatDateTime(d.last_seen),
                })
              }}
              ({{ timeAgoLabel(d.last_seen) }})
            </q-item-label>
            <q-item-label caption>{{ matchReasonHint(d.match_reason) }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn
              dense
              color="primary"
              :label="t('machine.merge.mergeHere')"
              @click="doMerge(d)"
            />
          </q-item-section>
        </q-item>
        <q-item v-if="!duplicates.length">
          <q-item-section class="text-muted">
            {{ t('machine.merge.none') }}
          </q-item-section>
        </q-item>
      </q-list>

      <q-separator />
      <!-- Manual search, because detection cannot cover the case that most
           needs merging: when the anchor itself drifted, the two records have
           nothing left in common for the server to match on. -->
      <q-card-section>
        <div class="text-caption text-muted q-mb-sm">
          {{ t('machine.merge.searchHint') }}
        </div>
        <q-input
          v-model="search"
          :aria-label="t('machine.merge.searchAria')"
          dense
          outlined
          clearable
          debounce="300"
          :placeholder="t('machine.merge.searchPlaceholder')"
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
              <q-item-label caption>{{
                t('machine.merge.seen', { date: formatDateTime(m.last_seen) })
              }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-btn
                dense
                flat
                color="primary"
                :label="t('machine.merge.mergeHere')"
                @click="doMerge(m)"
              />
            </q-item-section>
          </q-item>
        </q-list>
        <div v-else-if="search && !searching" class="text-caption text-muted q-mt-sm">
          {{ t('machine.merge.noMatch') }}
        </div>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn v-close-popup flat :label="t('machine.merge.close')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
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
import { escapeHtml } from 'src/utils/html';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

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

const title = computed(
  () => props.machine?.hostname || props.machine?.machine_uuid || t('machine.page.title'),
);

// A search left over from the previous opening would offer candidates gathered
// for another poste — or for this one before a merge already removed them.
watch(open, (isOpen) => {
  if (isOpen) {
    search.value = '';
    results.value = [];
  }
});

// Worded at render time, from `machine.merge.reasons` and `machine.merge.hints`.
function matchReasonLabel(reason: MatchReason): string {
  return t(`machine.merge.reasons.${reason}`);
}

function matchReasonHint(reason: MatchReason): string {
  return t(`machine.merge.hints.${reason}`);
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
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('machine.merge.searchFailed')),
    }));
  } finally {
    searching.value = false;
  }
}

function doMerge(source: Machine) {
  // Both UUIDs in the confirmation: on two records of one poste the hostnames
  // are identical, and a confirmation naming the same string twice is exactly
  // the one an administrator clicks through without reading.
  const removed = source.hostname
    ? `${escapeHtml(source.machine_uuid)} (${escapeHtml(source.hostname)})`
    : escapeHtml(source.machine_uuid);
  liveDialog($q, () => ({
    title: t('machine.merge.confirmTitle'),
    message:
      `<div>${t('machine.merge.confirmMessage', {
        removed: `<b>${removed}</b>`,
        kept: `<b>${escapeHtml(props.machine?.machine_uuid ?? title.value)}</b>`,
      })}</div>` + `<div class="q-mt-sm">${escapeHtml(t('machine.merge.irreversible'))}</div>`,
    html: true,
    cancel: true,
    persistent: true,
  })).onOk(() => {
    void runMerge(source.id);
  });
}

async function runMerge(sourceId: string) {
  try {
    await mergeMachines(props.machineId, sourceId);
    notify($q, () => ({ type: 'positive', message: t('machine.merge.merged') }));
    open.value = false;
    emit('merged');
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('machine.merge.failed')),
    }));
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
