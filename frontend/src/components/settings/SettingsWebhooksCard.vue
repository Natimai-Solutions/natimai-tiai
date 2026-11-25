<template>
  <!-- Outbound webhooks (C8): the fleet's events sent to another tool. -->
  <q-card
    v-if="canRead"
    flat
    bordered
    style="max-width: 640px"
    class="q-mb-md"
    data-test="webhooks-card"
  >
    <q-card-section class="text-subtitle1 row items-center">
      {{ t('integrations.webhooks.title') }}
      <q-space />
      <q-btn
        v-if="canWrite && !restricted"
        outline
        no-caps
        color="primary"
        icon="add"
        :label="t('integrations.webhooks.add')"
        data-test="webhook-add"
        @click="openForm(null)"
      />
    </q-card-section>
    <q-card-section class="q-pt-none text-caption text-muted">
      {{ t('integrations.webhooks.caption') }}
    </q-card-section>
    <q-separator />
    <q-card-section v-if="restricted" class="text-caption text-muted">
      {{ t('integrations.webhooks.restricted') }}
    </q-card-section>
    <CardLoadError
      v-else-if="loadError"
      :what="t('integrations.webhooks.what')"
      :loading="loading"
      @retry="load"
    />
    <q-list v-else separator>
      <q-item v-if="!loading && !hooks.length">
        <q-item-section class="text-muted">{{ t('integrations.webhooks.empty') }}</q-item-section>
      </q-item>
      <q-expansion-item
        v-for="hook in hooks"
        :key="hook.id"
        :data-test="`webhook-${hook.id}`"
        @show="loadHistory(hook.id)"
      >
        <template #header>
          <q-item-section>
            <q-item-label>
              {{ hook.name }}
              <q-badge
                :color="hook.enabled ? 'positive' : 'grey-7'"
                :outline="!hook.enabled"
                class="q-ml-xs"
              >
                {{
                  hook.enabled
                    ? t('integrations.webhooks.enabled')
                    : t('integrations.webhooks.disabled')
                }}
              </q-badge>
            </q-item-label>
            <q-item-label caption class="ellipsis">{{ hook.url }}</q-item-label>
            <q-item-label caption>
              {{ t(`integrations.webhooks.formats.${hook.format}`) }} ·
              {{ hook.events.map(eventLabel).join(', ') }}
            </q-item-label>
            <q-item-label caption>
              <span v-if="hook.last_failure_at && hook.consecutive_failures" class="text-negative">
                {{
                  t('integrations.webhooks.lastFailure', {
                    at: formatDateTime(hook.last_failure_at),
                    error: hook.last_error ?? '',
                  })
                }}
              </span>
              <span v-else-if="hook.last_success_at">
                {{
                  t('integrations.webhooks.lastSuccess', {
                    at: formatDateTime(hook.last_success_at),
                  })
                }}
              </span>
              <span v-else>{{ t('integrations.webhooks.never') }}</span>
              <span v-if="hook.pending">
                · {{ t('integrations.webhooks.pending', { n: hook.pending }, hook.pending) }}
              </span>
            </q-item-label>
          </q-item-section>
        </template>
        <q-card-section class="q-pt-none">
          <div v-if="canWrite" class="row q-gutter-sm q-mb-sm">
            <q-btn
              outline
              dense
              no-caps
              color="primary"
              icon="send"
              :label="t('integrations.webhooks.test')"
              :loading="testing === hook.id"
              data-test="webhook-test"
              @click="test(hook)"
            />
            <q-btn
              flat
              dense
              no-caps
              icon="edit"
              :label="t('integrations.webhooks.edit')"
              @click="openForm(hook)"
            />
            <q-btn
              flat
              dense
              no-caps
              icon="key"
              :label="t('integrations.webhooks.renew')"
              @click="renew(hook)"
            />
            <q-btn
              flat
              dense
              no-caps
              color="negative"
              icon="delete"
              :label="t('integrations.webhooks.delete')"
              @click="remove(hook)"
            />
          </div>
          <div class="text-subtitle2">{{ t('integrations.webhooks.history') }}</div>
          <div v-if="!(history[hook.id] ?? []).length" class="text-caption text-muted">
            {{ t('integrations.webhooks.historyEmpty') }}
          </div>
          <q-markup-table v-else flat dense>
            <tbody>
              <tr v-for="d in history[hook.id]" :key="d.id">
                <td>{{ formatDateTime(d.created_at) }}</td>
                <td>{{ eventLabel(d.event) }}</td>
                <td>{{ t(`integrations.webhooks.status.${d.status}`) }}</td>
                <td class="text-muted">{{ d.response_status ?? '' }} {{ d.last_error ?? '' }}</td>
              </tr>
            </tbody>
          </q-markup-table>
        </q-card-section>
      </q-expansion-item>
    </q-list>

    <q-dialog v-model="formOpen">
      <q-card style="width: 560px; max-width: 95vw">
        <q-card-section class="text-h6">
          {{
            editing
              ? t('integrations.webhooks.form.editTitle')
              : t('integrations.webhooks.form.createTitle')
          }}
        </q-card-section>
        <q-form @submit="save">
          <q-card-section class="q-gutter-md q-pt-none">
            <q-input
              v-model="form.name"
              :label="t('integrations.webhooks.form.name')"
              outlined
              dense
              maxlength="100"
              autofocus
              reactive-rules
              :rules="[(v: string) => !!v.trim() || t('integrations.webhooks.form.required')]"
            />
            <q-input
              v-model="form.url"
              :label="t('integrations.webhooks.form.url')"
              :hint="t('integrations.webhooks.form.urlHint')"
              outlined
              dense
              maxlength="2000"
              reactive-rules
              :rules="[(v: string) => !!v.trim() || t('integrations.webhooks.form.required')]"
              data-test="webhook-url"
            />
            <q-select
              v-model="form.format"
              :options="formatOptions"
              emit-value
              map-options
              :label="t('integrations.webhooks.form.format')"
              outlined
              dense
            />
            <q-select
              v-if="form.format !== 'json'"
              v-model="form.language"
              :options="languageOptions"
              emit-value
              map-options
              :label="t('integrations.webhooks.form.language')"
              outlined
              dense
            />
            <div>
              <div class="text-subtitle2">{{ t('integrations.webhooks.form.events') }}</div>
              <q-option-group
                v-model="form.events"
                type="checkbox"
                :options="eventOptions"
                data-test="webhook-events"
              />
              <div v-if="eventsError" class="text-caption text-negative">{{ eventsError }}</div>
            </div>
            <q-toggle v-model="form.enabled" :label="t('integrations.webhooks.form.enabled')" />
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat no-caps :label="t('integrations.webhooks.form.cancel')" />
            <q-btn
              type="submit"
              color="primary"
              no-caps
              unelevated
              :label="t('integrations.webhooks.form.save')"
              :loading="saving"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="secretOpen" persistent>
      <q-card style="width: 520px; max-width: 95vw" data-test="webhook-secret">
        <q-card-section class="text-h6">{{
          t('integrations.webhooks.secret.title')
        }}</q-card-section>
        <q-card-section class="q-pt-none">
          <div class="q-mb-md">{{ t('integrations.webhooks.secret.intro') }}</div>
          <code class="secret">{{ secret }}</code>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            no-caps
            icon="content_copy"
            :label="t('integrations.webhooks.secret.copy')"
            @click="copySecret"
          />
          <q-btn
            color="primary"
            no-caps
            unelevated
            :label="t('integrations.webhooks.secret.done')"
            @click="secretOpen = false"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar } from 'quasar';
import CardLoadError from 'src/components/CardLoadError.vue';
import { t } from 'src/i18n';
import { apiErrorMessage, apiErrorCode } from 'src/services/errors';
import {
  WEBHOOK_EVENTS,
  WEBHOOK_FORMATS,
  createWebhook,
  deleteWebhook,
  listWebhookDeliveries,
  listWebhooks,
  renewWebhookSecret,
  testWebhook,
  updateWebhook,
  type Webhook,
  type WebhookDelivery,
  type WebhookEvent,
  type WebhookFormat,
} from 'src/services/webhooks';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();

const canRead = computed(() => auth.can('webhook', 'read'));
const canWrite = computed(() => auth.can('webhook', 'write'));

const hooks = ref<Webhook[]>([]);
const history = reactive<Record<string, WebhookDelivery[]>>({});
const loading = ref(false);
const loadError = ref<unknown>(null);
// A reader confined to some places: the API refuses the whole parc's events.
const restricted = ref(false);
const testing = ref<string | null>(null);

const formOpen = ref(false);
const editing = ref<Webhook | null>(null);
const saving = ref(false);
const triedSave = ref(false);
const form = reactive({
  name: '',
  url: '',
  format: 'json' as WebhookFormat,
  language: 'fr' as 'fr' | 'en',
  events: [] as WebhookEvent[],
  enabled: true,
});
const secretOpen = ref(false);
const secret = ref('');

function eventLabel(event: string): string {
  // Catalogue keys use « _ »: vue-i18n reads a dot as a path.
  const key = `integrations.webhooks.events.${event.replace('.', '_')}`;
  const worded = t(key);
  return worded === key ? event : worded;
}

const eventOptions = computed(() =>
  WEBHOOK_EVENTS.map((e) => ({ label: eventLabel(e), value: e })),
);
const formatOptions = computed(() =>
  WEBHOOK_FORMATS.map((f) => ({ label: t(`integrations.webhooks.formats.${f}`), value: f })),
);
const languageOptions = computed(() => [
  { label: t('common.language.fr'), value: 'fr' },
  { label: t('common.language.en'), value: 'en' },
]);
const eventsError = computed(() =>
  triedSave.value && !form.events.length ? t('integrations.webhooks.form.eventNeeded') : null,
);

async function load(): Promise<void> {
  if (!canRead.value) return;
  loading.value = true;
  try {
    hooks.value = await listWebhooks();
    restricted.value = false;
    loadError.value = null;
  } catch (e) {
    if (apiErrorCode(e) === 'auth.scope.restricted') restricted.value = true;
    else loadError.value = e;
  } finally {
    loading.value = false;
  }
}

async function loadHistory(id: string): Promise<void> {
  try {
    history[id] = await listWebhookDeliveries(id);
  } catch {
    history[id] = [];
  }
}

function openForm(hook: Webhook | null): void {
  editing.value = hook;
  triedSave.value = false;
  Object.assign(form, {
    name: hook?.name ?? '',
    url: hook?.url ?? '',
    format: hook?.format ?? 'json',
    language: hook?.language ?? 'fr',
    events: [...((hook?.events as WebhookEvent[] | undefined) ?? ['threat.detected'])],
    enabled: hook?.enabled ?? true,
  });
  formOpen.value = true;
}

function showSecret(value: string): void {
  secret.value = value;
  secretOpen.value = true;
}

async function save(): Promise<void> {
  triedSave.value = true;
  if (!form.events.length) return;
  saving.value = true;
  const fields = {
    name: form.name.trim(),
    url: form.url.trim(),
    format: form.format,
    language: form.language,
    events: form.events,
    enabled: form.enabled,
  };
  try {
    if (editing.value) {
      // Only what changed: an unchanged address is not checked again, and
      // an unchanged « Actif » does not count as switching it back on.
      const before = editing.value;
      const changed: Partial<typeof fields> = {};
      if (fields.name !== before.name) changed.name = fields.name;
      if (fields.url !== before.url) changed.url = fields.url;
      if (fields.format !== before.format) changed.format = fields.format;
      if (fields.language !== before.language) changed.language = fields.language;
      if (fields.events.join() !== before.events.join()) changed.events = fields.events;
      if (fields.enabled !== before.enabled) changed.enabled = fields.enabled;
      if (Object.keys(changed).length) await updateWebhook(before.id, changed);
    } else {
      const created = await createWebhook(fields);
      showSecret(created.secret);
    }
    formOpen.value = false;
    notify($q, () => ({ type: 'positive', message: t('integrations.webhooks.saved') }));
    await load();
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  } finally {
    saving.value = false;
  }
}

async function test(hook: Webhook): Promise<void> {
  testing.value = hook.id;
  try {
    const result = await testWebhook(hook.id);
    notify($q, () =>
      result.ok
        ? {
            type: 'positive',
            message: t('integrations.webhooks.testOk', { status: result.response_status ?? '' }),
          }
        : {
            type: 'negative',
            message: t('integrations.webhooks.testFailed', { error: result.error ?? '' }),
          },
    );
    await loadHistory(hook.id);
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  } finally {
    testing.value = null;
  }
}

function renew(hook: Webhook): void {
  liveDialog($q, () => ({
    message: t('integrations.webhooks.confirmRenew'),
    cancel: { flat: true, noCaps: true, label: t('integrations.webhooks.form.cancel') },
    ok: { color: 'primary', noCaps: true, label: t('integrations.webhooks.renew') },
  })).onOk(() => {
    void (async () => {
      try {
        showSecret((await renewWebhookSecret(hook.id)).secret);
      } catch (e) {
        notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
      }
    })();
  });
}

function remove(hook: Webhook): void {
  liveDialog($q, () => ({
    message: t('integrations.webhooks.confirmDelete', { name: hook.name }),
    cancel: { flat: true, noCaps: true, label: t('integrations.webhooks.form.cancel') },
    ok: { color: 'negative', noCaps: true, label: t('integrations.webhooks.delete') },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteWebhook(hook.id);
        notify($q, () => ({ type: 'positive', message: t('integrations.webhooks.deleted') }));
        await load();
      } catch (e) {
        notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
      }
    })();
  });
}

async function copySecret(): Promise<void> {
  try {
    await navigator.clipboard.writeText(secret.value);
    notify($q, () => ({ type: 'positive', message: t('integrations.webhooks.secret.copied') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  }
}

onMounted(load);

defineExpose({ load });
</script>

<style scoped>
.secret {
  display: block;
  font-size: 0.95rem;
  word-break: break-all;
}
</style>
