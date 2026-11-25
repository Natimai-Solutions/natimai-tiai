<template>
  <!-- Two-person approval of mass actions (C10). Saved on its own; turning it
       on is refused by the server with fewer than two accounts able to
       approve, and greyed here for the same reason. -->
  <q-card flat bordered style="max-width: 640px" class="q-mb-md" data-test="approval-card">
    <q-card-section class="text-subtitle1">
      {{ t('settings.approval.title') }}
      <div class="text-caption text-muted">{{ t('settings.approval.caption') }}</div>
    </q-card-section>
    <q-separator />
    <q-card-section v-if="settings" class="q-gutter-md">
      <div>
        <q-toggle
          v-model="form.enabled"
          :label="t('settings.approval.enabled')"
          :disable="!canWrite || toggleLocked"
          data-test="approval-enabled"
        />
        <div class="text-caption text-muted">
          {{
            t('settings.approval.envHint', {
              value: settings.env_approval_enabled
                ? t('settings.approval.on')
                : t('settings.approval.off'),
            })
          }}
        </div>
      </div>
      <div class="text-body2" data-test="approval-eligible">
        {{ t('settings.approval.eligible', { count: eligible }, eligible) }}
      </div>
      <div v-if="eligible < 2" class="text-caption text-warn" data-test="approval-not-enough">
        {{ t('settings.approval.notEnough') }}
      </div>
      <div class="text-caption text-muted">{{ t('settings.approval.scopeNote') }}</div>
      <q-input
        v-model.number="form.threshold"
        type="number"
        min="2"
        max="10000"
        outlined
        dense
        :label="t('settings.approval.threshold')"
        :hint="
          t('settings.approval.thresholdHint', { value: settings.env_approval_threshold ?? 40 })
        "
        :error="thresholdError !== null"
        :error-message="thresholdError ?? ''"
        :disable="!canWrite"
        data-test="approval-threshold"
      />
      <q-input
        v-model.number="form.ttlHours"
        type="number"
        min="1"
        max="168"
        outlined
        dense
        :label="t('settings.approval.ttl')"
        :hint="t('settings.approval.ttlHint', { value: settings.env_approval_ttl_hours ?? 24 })"
        :error="ttlError !== null"
        :error-message="ttlError ?? ''"
        :disable="!canWrite"
        data-test="approval-ttl"
      />
      <div v-if="saveError" class="text-caption text-negative" data-test="approval-error">
        {{ saveError }}
      </div>
    </q-card-section>
    <q-card-actions v-if="canWrite && settings" align="right">
      <q-btn
        color="primary"
        :label="t('settings.save')"
        :loading="saving"
        :disable="thresholdError !== null || ttlError !== null"
        data-test="approval-save"
        @click="save"
      />
    </q-card-actions>
  </q-card>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { notifyApprovalsChanged } from 'src/composables/useApprovalsBadge';
import { apiErrorMessage } from 'src/services/errors';
import { updateSettings, type ConsoleSettings } from 'src/services/settings';
import { useAuthStore } from 'src/stores/auth';
import { notify } from 'src/utils/notify';
import { intFieldError } from 'src/utils/numberField';

const props = defineProps<{ settings: ConsoleSettings | null }>();
const emit = defineEmits<{ (e: 'saved', settings: ConsoleSettings): void }>();

const $q = useQuasar();
const auth = useAuthStore();
const canWrite = computed(() => auth.can('settings', 'write'));

const form = reactive({
  enabled: false,
  threshold: 40 as number | string,
  ttlHours: 24 as number | string,
});
const saving = ref(false);
// Kept as the error, worded at display: it follows a change of language.
const failure = ref<unknown>(null);
const saveError = computed(() =>
  failure.value ? apiErrorMessage(failure.value, t('settings.saveFailed')) : null,
);
const saved = ref('');

const eligible = computed(() => props.settings?.approval_eligible ?? 0);
// Off with fewer than two accounts able to approve: it cannot be turned on.
// On already (turned on when there were two), it can still be turned off.
const toggleLocked = computed(() => eligible.value < 2 && !props.settings?.approval_enabled);
const thresholdError = computed(() => intFieldError(form.threshold, 2, 10000));
const ttlError = computed(() => intFieldError(form.ttlHours, 1, 168));

function snapshot(): string {
  return JSON.stringify([form.enabled, Number(form.threshold), Number(form.ttlHours)]);
}

function fill(s: ConsoleSettings | null): void {
  if (!s) return;
  form.enabled = s.approval_enabled ?? false;
  form.threshold = s.approval_threshold ?? 40;
  form.ttlHours = s.approval_ttl_hours ?? 24;
  saved.value = snapshot();
}

// Filled again when its own values change — not when another card of the
// page saves, which would throw away what is being typed here.
watch(
  () => [
    props.settings !== null,
    props.settings?.approval_enabled,
    props.settings?.approval_threshold,
    props.settings?.approval_ttl_hours,
  ],
  () => fill(props.settings),
  { immediate: true },
);

/** Changes not saved yet: the page asks before it is left. */
const dirty = computed(() => props.settings !== null && snapshot() !== saved.value);
defineExpose({ dirty });

async function save(): Promise<void> {
  if (thresholdError.value || ttlError.value) return;
  saving.value = true;
  failure.value = null;
  try {
    const next = await updateSettings({
      approval_enabled: form.enabled,
      approval_threshold: Number(form.threshold),
      approval_ttl_hours: Number(form.ttlHours),
    });
    emit('saved', next);
    fill(next);
    // The menu's entry shows or hides with the setting.
    notifyApprovalsChanged();
    notify($q, () => ({ type: 'positive', message: t('settings.saved') }));
  } catch (e) {
    // Said in the card, next to the switch it is about.
    failure.value = e;
  } finally {
    saving.value = false;
  }
}
</script>
