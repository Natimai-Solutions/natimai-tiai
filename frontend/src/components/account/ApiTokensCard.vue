<template>
  <!-- Personal API tokens (C8): for a script, within the account's rights. -->
  <q-card
    v-if="allowed"
    flat
    bordered
    class="q-mt-md"
    style="max-width: 520px"
    data-test="api-tokens-card"
  >
    <q-card-section class="text-subtitle1 row items-center">
      {{ t('integrations.tokens.title') }}
      <q-space />
      <q-btn
        v-if="canCreate"
        outline
        no-caps
        color="primary"
        icon="add"
        :label="t('integrations.tokens.add')"
        data-test="token-add"
        @click="openForm"
      />
    </q-card-section>
    <q-card-section class="q-pt-none text-caption text-muted">
      {{ t('integrations.tokens.caption') }}
    </q-card-section>
    <q-separator />
    <CardLoadError
      v-if="loadError"
      :what="t('integrations.tokens.what')"
      :loading="loading"
      @retry="load"
    />
    <q-list v-else separator>
      <q-item v-if="!loading && !tokens.length">
        <q-item-section class="text-muted">{{ t('integrations.tokens.empty') }}</q-item-section>
      </q-item>
      <q-item v-for="tok in tokens" :key="tok.id" :data-test="`token-${tok.id}`">
        <q-item-section>
          <q-item-label>
            {{ tok.name }}
            <code class="q-ml-xs text-muted">{{ tok.prefix }}…</code>
          </q-item-label>
          <q-item-label caption>
            {{
              tok.can_write ? t('integrations.tokens.readWrite') : t('integrations.tokens.readOnly')
            }}
            ·
            <span v-if="tok.revoked_at" class="text-negative">
              {{ t('integrations.tokens.revoked') }}
            </span>
            <span v-else-if="expired(tok)" class="text-warn">
              {{ t('integrations.tokens.expired') }}
            </span>
            <span v-else>
              {{ t('integrations.tokens.expires', { at: formatDateTime(tok.expires_at) }) }}
            </span>
          </q-item-label>
          <q-item-label caption>
            {{
              tok.last_used_at
                ? t('integrations.tokens.lastUsed', { at: formatDateTime(tok.last_used_at) })
                : t('integrations.tokens.neverUsed')
            }}
          </q-item-label>
        </q-item-section>
        <q-item-section v-if="!tok.revoked_at && !expired(tok)" side>
          <q-btn
            flat
            dense
            no-caps
            color="negative"
            :label="t('integrations.tokens.revoke')"
            data-test="token-revoke"
            @click="revoke(tok)"
          />
        </q-item-section>
      </q-item>
    </q-list>

    <q-dialog v-model="formOpen">
      <q-card style="width: 480px; max-width: 95vw">
        <q-card-section class="text-h6">{{ t('integrations.tokens.form.title') }}</q-card-section>
        <q-form @submit="create">
          <q-card-section class="q-gutter-md q-pt-none">
            <q-input
              v-model="form.name"
              :label="t('integrations.tokens.form.name')"
              :hint="t('integrations.tokens.form.nameHint')"
              outlined
              dense
              autofocus
              maxlength="100"
              reactive-rules
              :rules="[(v: string) => !!v.trim() || t('integrations.webhooks.form.required')]"
              data-test="token-name"
            />
            <q-input
              v-model.number="form.days"
              type="number"
              :label="t('integrations.tokens.form.days')"
              :suffix="t('integrations.tokens.form.daysSuffix')"
              :hint="t('integrations.tokens.form.daysHint')"
              outlined
              dense
              min="1"
              max="365"
              reactive-rules
              :rules="[
                (v: number) =>
                  (Number.isInteger(v) && v >= 1 && v <= 365) ||
                  t('integrations.tokens.form.daysHint'),
              ]"
            />
            <div>
              <q-toggle
                v-model="form.can_write"
                :label="t('integrations.tokens.form.canWrite')"
                data-test="token-write"
              />
              <div class="text-caption text-muted">
                {{ t('integrations.tokens.form.canWriteHint') }}
              </div>
            </div>
            <template v-if="local">
              <q-input
                v-model="form.current_password"
                type="password"
                autocomplete="current-password"
                :label="t('integrations.tokens.form.password')"
                :hint="t('integrations.tokens.form.passwordHint')"
                outlined
                dense
                reactive-rules
                :rules="[(v: string) => !!v || t('integrations.webhooks.form.required')]"
                data-test="token-password"
              />
              <q-input
                v-if="withCode"
                v-model="form.code"
                autocomplete="one-time-code"
                inputmode="numeric"
                :label="t('integrations.tokens.form.code')"
                outlined
                dense
                maxlength="32"
                reactive-rules
                :rules="[(v: string) => !!v.trim() || t('integrations.webhooks.form.required')]"
                data-test="token-code"
              />
            </template>
            <div v-else class="text-caption text-muted">
              {{ t('integrations.tokens.form.directoryProof') }}
            </div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat no-caps :label="t('integrations.tokens.form.cancel')" />
            <q-btn
              type="submit"
              color="primary"
              no-caps
              unelevated
              :label="t('integrations.tokens.form.create')"
              :loading="saving"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="createdOpen" persistent>
      <q-card style="width: 520px; max-width: 95vw" data-test="token-created">
        <q-card-section class="text-h6">{{
          t('integrations.tokens.created.title')
        }}</q-card-section>
        <q-card-section class="q-pt-none">
          <div class="q-mb-md">{{ t('integrations.tokens.created.intro') }}</div>
          <code class="secret">{{ clear }}</code>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn
            flat
            no-caps
            icon="content_copy"
            :label="t('integrations.tokens.created.copy')"
            @click="copy"
          />
          <q-btn
            color="primary"
            no-caps
            unelevated
            :label="t('integrations.tokens.created.done')"
            @click="done"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import CardLoadError from 'src/components/CardLoadError.vue';
import { t } from 'src/i18n';
import { createApiToken, listApiTokens, revokeApiToken, type ApiToken } from 'src/services/auth';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import { formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const auth = useAuthStore();
const tokens = ref<ApiToken[]>([]);

// Listing and revoking one's own tokens needs no right: an account that lost
// the right to make them still sees, and can end, those it made.
const canCreate = computed(() => auth.can('api_token', 'write'));
const enrolling = computed(() => auth.user?.enrolment_only === true);
const allowed = computed(() => !enrolling.value && (canCreate.value || tokens.value.length > 0));

const loading = ref(false);
const loadError = ref<unknown>(null);
const formOpen = ref(false);
const saving = ref(false);
// A local account proves itself with its password (and a code when it has
// a second factor); an account of the directory, by a recent sign-in.
const local = computed(() => auth.user?.auth_source !== 'oidc');
const withCode = computed(() => auth.user?.second_factor_enabled === true);
const form = reactive({ name: '', can_write: false, days: 90, current_password: '', code: '' });
const createdOpen = ref(false);
const clear = ref('');

function expired(tok: ApiToken): boolean {
  return new Date(tok.expires_at).getTime() <= Date.now();
}

async function load(): Promise<void> {
  if (enrolling.value) return;
  loading.value = true;
  try {
    tokens.value = await listApiTokens();
    loadError.value = null;
  } catch (e) {
    loadError.value = e;
  } finally {
    loading.value = false;
  }
}

function openForm(): void {
  Object.assign(form, { name: '', can_write: false, days: 90, current_password: '', code: '' });
  formOpen.value = true;
}

async function create(): Promise<void> {
  saving.value = true;
  try {
    const made = await createApiToken({
      name: form.name.trim(),
      can_write: form.can_write,
      days: form.days,
      ...(local.value ? { current_password: form.current_password } : {}),
      ...(local.value && withCode.value ? { code: form.code.trim() } : {}),
    });
    form.current_password = '';
    form.code = '';
    formOpen.value = false;
    clear.value = made.token;
    createdOpen.value = true;
    await load();
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  } finally {
    saving.value = false;
  }
}

function done(): void {
  // The value is not kept once the dialog is closed.
  clear.value = '';
  createdOpen.value = false;
}

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(clear.value);
    notify($q, () => ({ type: 'positive', message: t('integrations.tokens.created.copied') }));
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  }
}

function revoke(tok: ApiToken): void {
  liveDialog($q, () => ({
    message: t('integrations.tokens.confirmRevoke', { name: tok.name }),
    cancel: { flat: true, noCaps: true, label: t('integrations.tokens.form.cancel') },
    ok: { color: 'negative', noCaps: true, label: t('integrations.tokens.revoke') },
  })).onOk(() => {
    void (async () => {
      try {
        await revokeApiToken(tok.id);
        notify($q, () => ({ type: 'positive', message: t('integrations.tokens.revokedDone') }));
        await load();
      } catch (e) {
        notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
      }
    })();
  });
}

onMounted(load);
// An enrolment-only session that has just set up its second factor is a full
// one now: the tokens become reachable.
watch(enrolling, (now, before) => {
  if (before && !now) void load();
});

defineExpose({ load });
</script>

<style scoped>
.secret {
  display: block;
  font-size: 0.95rem;
  word-break: break-all;
}
</style>
