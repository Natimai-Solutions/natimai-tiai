<template>
  <q-dialog v-model="open">
    <q-card v-if="entry" style="width: 640px; max-width: 95vw">
      <q-card-section>
        <div class="text-h6">{{ auditActionLabel(entry.action) }}</div>
        <div class="text-caption text-muted">
          {{ formatDateTime(entry.at) }} · {{ entry.actor }}
          <span v-if="entry.ip"> · {{ t('audit.details.from', { ip: entry.ip }) }}</span>
          <span v-if="actionIsUnknown"> · {{ entry.action }}</span>
        </div>
      </q-card-section>
      <q-separator />

      <q-markup-table flat dense wrap-cells separator="horizontal">
        <tbody>
          <tr>
            <th class="text-left audit-key">{{ t('audit.details.resource') }}</th>
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
              <div v-if="row.label !== row.key" class="text-caption text-muted audit-mono">
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
            <td colspan="2" class="text-muted">{{ t('audit.details.none') }}</td>
          </tr>
        </tbody>
      </q-markup-table>

      <q-expansion-item
        dense
        dense-toggle
        :label="t('audit.details.rawJson')"
        header-class="text-muted"
      >
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
          :label="t('audit.details.filterResource')"
          @click="emit('filter-resource', entry.resource_type, entry.resource_id)"
        />
        <q-btn flat icon="content_copy" :label="t('audit.details.copy')" @click="copy" />
        <q-btn v-close-popup flat :label="t('audit.details.close')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { testResultText } from 'src/utils/emailSettings';
import type { EmailTestResult } from 'src/services/settings';
import { computed } from 'vue';
import { useQuasar } from 'quasar';
import type { AuditEntry } from 'src/services/audit';
import { t } from 'src/i18n';
import {
  auditActionLabel,
  auditDetailKeyLabel,
  auditDetailValue,
  auditResourceLink,
  auditResourceTypeLabel,
  isKnownAuditAction,
} from 'src/utils/auditLabels';
import { formatDateTime } from 'src/utils/format';

const props = defineProps<{ entry: AuditEntry | null }>();
const emit = defineEmits<{
  (e: 'filter-resource', resourceType: string, resourceId: string): void;
}>();

const open = defineModel<boolean>({ required: true });

const $q = useQuasar();

const actionIsUnknown = computed(() => !!props.entry && !isKnownAuditAction(props.entry.action));

const resourceLink = computed(() =>
  props.entry ? auditResourceLink(props.entry.resource_type, props.entry.resource_id) : null,
);

// A test e-mail's outcome carries its code and parameters beside its French
// message: the message is worded from them, as the Settings page words it,
// and they are not rows of their own. An older entry keeps its message.
const WORDING_KEYS = ['message_code', 'message_params'];

function detailValue(key: string, raw: unknown, details: Record<string, unknown>): string {
  if (key === 'message' && typeof raw === 'string' && typeof details.message_code === 'string') {
    return testResultText({
      ok: details.ok === 'oui', // i18n-ignore — the value the server stores
      message: raw,
      code: details.message_code,
      params: (details.message_params as Record<string, unknown> | null) ?? {},
    } as EmailTestResult);
  }
  return auditDetailValue(raw, key);
}

const detailRows = computed(() =>
  Object.entries(props.entry?.details ?? {})
    .filter(([key]) => !WORDING_KEYS.includes(key))
    .map(([key, raw]) => {
      const value = detailValue(key, raw, props.entry?.details ?? {});
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
    $q.notify({ type: 'positive', message: t('audit.details.copied') });
  } catch {
    $q.notify({ type: 'negative', message: t('audit.details.copyFailed') });
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
