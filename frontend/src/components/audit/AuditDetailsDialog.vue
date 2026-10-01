<template>
  <q-dialog v-model="open">
    <q-card v-if="entry" style="width: 640px; max-width: 95vw">
      <q-card-section>
        <div class="text-h6">{{ auditActionLabel(entry.action) }}</div>
        <div class="text-caption text-grey">
          {{ formatDateTime(entry.at) }} · {{ entry.actor }}
          <span v-if="actionIsUnknown"> · {{ entry.action }}</span>
        </div>
      </q-card-section>
      <q-separator />

      <q-markup-table flat dense wrap-cells separator="horizontal">
        <tbody>
          <tr>
            <th class="text-left audit-key">Ressource</th>
            <td>
              {{ auditResourceTypeLabel(entry.resource_type) }}
              <template v-if="entry.resource_id">
                —
                <router-link v-if="resourceLink" :to="resourceLink" class="audit-mono">
                  {{ entry.resource_id }}
                </router-link>
                <span v-else class="audit-mono">{{ entry.resource_id }}</span>
              </template>
            </td>
          </tr>
          <tr v-for="row in detailRows" :key="row.key">
            <th class="text-left audit-key">
              {{ auditDetailKeyLabel(row.key) }}
              <div v-if="row.label !== row.key" class="text-caption text-grey audit-mono">
                {{ row.key }}
              </div>
            </th>
            <td>
              <!-- A poste named in the details (an intervention's, a check's)
                   opens like the resource does. -->
              <router-link v-if="row.link" :to="row.link" class="audit-mono">
                {{ row.value }}
              </router-link>
              <pre v-else-if="row.multiline" class="audit-json">{{ row.value }}</pre>
              <span v-else>{{ row.value }}</span>
            </td>
          </tr>
          <tr v-if="!detailRows.length">
            <td colspan="2" class="text-grey">Aucun détail enregistré.</td>
          </tr>
        </tbody>
      </q-markup-table>

      <q-expansion-item dense dense-toggle label="JSON brut" header-class="text-grey-8">
        <q-card-section class="q-pt-none">
          <pre class="audit-json">{{ rawJson }}</pre>
        </q-card-section>
      </q-expansion-item>

      <q-separator />
      <q-card-actions align="right">
        <!-- « What else happened to this thing » is the question an audit line
             raises next; the filter answers it without retyping the id. -->
        <q-btn
          v-if="entry.resource_id"
          v-close-popup
          flat
          no-caps
          color="primary"
          icon="filter_alt"
          label="Toutes les actions sur cette ressource"
          @click="emit('filter-resource', entry.resource_type, entry.resource_id)"
        />
        <q-btn flat icon="content_copy" label="Copier" @click="copy" />
        <q-btn v-close-popup flat label="Fermer" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useQuasar } from 'quasar';
import type { AuditEntry } from 'src/services/audit';
import {
  AUDIT_ACTION_LABELS,
  auditActionLabel,
  auditDetailKeyLabel,
  auditDetailValue,
  auditResourceLink,
  auditResourceTypeLabel,
} from 'src/utils/auditLabels';
import { formatDateTime } from 'src/utils/format';

const props = defineProps<{ entry: AuditEntry | null }>();
const emit = defineEmits<{
  (e: 'filter-resource', resourceType: string, resourceId: string): void;
}>();

const open = defineModel<boolean>({ required: true });

const $q = useQuasar();

const actionIsUnknown = computed(() => !!props.entry && !AUDIT_ACTION_LABELS[props.entry.action]);

const resourceLink = computed(() =>
  props.entry ? auditResourceLink(props.entry.resource_type, props.entry.resource_id) : null,
);

const detailRows = computed(() =>
  Object.entries(props.entry?.details ?? {}).map(([key, raw]) => {
    const value = auditDetailValue(raw);
    return {
      key,
      label: auditDetailKeyLabel(key),
      value,
      multiline: value.includes('\n'),
      link: key === 'machine_id' ? auditResourceLink('machine', String(raw)) : null,
    };
  }),
);

const rawJson = computed(() => JSON.stringify(props.entry ?? {}, null, 2));

async function copy() {
  try {
    await navigator.clipboard.writeText(rawJson.value);
    $q.notify({ type: 'positive', message: 'Copié dans le presse-papiers' });
  } catch {
    $q.notify({ type: 'negative', message: 'Copie impossible' });
  }
}
</script>

<style scoped>
.audit-key {
  width: 35%;
  vertical-align: top;
  font-weight: 500;
}
.audit-mono {
  font-family: monospace;
  font-size: 12px;
}
.audit-json {
  margin: 0;
  max-height: 40vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}
</style>
