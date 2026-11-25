<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 560px; max-width: 95vw" data-test="approval-dialog">
      <q-card-section class="text-h6">
        {{
          mode === 'approve'
            ? t('approvals.decision.titleApprove')
            : t('approvals.decision.titleReject')
        }}
      </q-card-section>
      <q-card-section v-if="approval" class="q-gutter-sm">
        <div class="text-body1" data-test="approval-summary">
          {{
            t(
              'approvals.decision.summary',
              {
                by: approval.requested_by,
                action: approvalAction(approval),
                count: approval.machine_count,
                target: approvalTarget(approval),
              },
              approval.machine_count,
            )
          }}
        </div>
        <div class="text-caption text-muted">
          {{
            t('approvals.decision.requestedAt', {
              at: formatDateTime(approval.requested_at),
              expires: formatDateTime(approval.expires_at),
            })
          }}
        </div>

        <div v-if="loadingDetail" class="text-caption text-muted">
          {{ t('approvals.decision.loading') }}
        </div>
        <div v-else-if="detailError" class="text-caption text-negative">
          {{ t('approvals.decision.loadFailed') }}
        </div>
        <template v-else-if="detail">
          <div v-if="detail.schedule" class="text-body2" data-test="approval-schedule">
            {{
              t(
                'approvals.decision.schedule',
                { name: detail.schedule.name, stages: detail.schedule.stages },
                detail.schedule.stages,
              )
            }}
          </div>
          <div v-if="detail.machines.length || detail.hidden">
            <div class="text-caption text-muted">{{ t('approvals.decision.machines') }}</div>
            <div class="text-body2" data-test="approval-machines">{{ machinesText }}</div>
            <q-btn
              v-if="!showAll && detail.machines.length > FOLDED"
              flat
              dense
              no-caps
              color="primary"
              :label="t('approvals.decision.showAll', { count: detail.machines.length })"
              data-test="approval-show-all"
              @click="showAll = true"
            />
            <div v-if="detail.hidden" class="text-caption text-warn" data-test="approval-hidden">
              {{ t('approvals.decision.hidden', { count: detail.hidden }, detail.hidden) }}
            </div>
          </div>
        </template>

        <q-input
          v-if="mode === 'reject'"
          v-model="note"
          type="textarea"
          autogrow
          outlined
          dense
          maxlength="500"
          :label="t('approvals.decision.note')"
          :hint="t('approvals.decision.noteHint')"
          reactive-rules
          :rules="noteRules"
          data-test="approval-note"
        />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn v-close-popup flat no-caps :label="t('approvals.decision.close')" />
        <q-btn
          v-if="mode === 'approve'"
          color="positive"
          no-caps
          :label="t('approvals.decision.approve')"
          :loading="busy"
          data-test="approval-approve"
          @click="approve(false)"
        />
        <q-btn
          v-else
          color="negative"
          no-caps
          :label="t('approvals.decision.reject')"
          :loading="busy"
          :disable="note.length > 500"
          data-test="approval-reject"
          @click="reject"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { notifyApprovalsChanged } from 'src/composables/useApprovalsBadge';
import {
  CLOSING_CODES,
  approvalAction,
  approvalTarget,
  approvedNotification,
  approveApproval,
  getApproval,
  rejectApproval,
  type Approval,
  type ApprovalDetail,
} from 'src/services/approvals';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
import { windowText, type ForbiddenWindow } from 'src/services/schedules';
import { formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

/** Beyond this many postes, the list is folded behind « Afficher ». */
const FOLDED = 20;

const props = defineProps<{
  modelValue: boolean;
  approval: Approval | null;
  mode: 'approve' | 'reject';
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', open: boolean): void;
  /** Decided, or found closed: the page reads its list again. */
  (e: 'done'): void;
}>();

const $q = useQuasar();
const detail = ref<ApprovalDetail | null>(null);
const detailError = ref<unknown>(null);
const loadingDetail = ref(false);
const showAll = ref(false);
const note = ref('');
const busy = ref(false);

// Built again on a change of language, with `reactive-rules`.
const noteRules = computed(() => [
  (v: string) => (v ?? '').length <= 500 || t('approvals.decision.noteTooLong'),
]);

const machinesText = computed(() => {
  const machines = detail.value?.machines ?? [];
  const shown = showAll.value ? machines : machines.slice(0, FOLDED);
  const names = shown.map((m) =>
    m.room ? `${m.hostname ?? m.id} (${m.room})` : (m.hostname ?? m.id),
  );
  return machines.length > shown.length ? `${names.join(', ')}…` : names.join(', ');
});

async function loadDetail(id: string): Promise<void> {
  loadingDetail.value = true;
  detail.value = null;
  detailError.value = null;
  try {
    detail.value = await getApproval(id);
  } catch (e) {
    detailError.value = e;
    if (isClosing(e)) closed(e);
  } finally {
    loadingDetail.value = false;
  }
}

watch(
  () => [props.modelValue, props.approval?.id] as const,
  ([open, id]) => {
    if (!open || !id) return;
    showAll.value = false;
    note.value = '';
    void loadDetail(id);
  },
  { immediate: true },
);

function isClosing(e: unknown): boolean {
  return (CLOSING_CODES as readonly string[]).includes(apiErrorCode(e) ?? '');
}

/** The request is closed (by this attempt, or before it): said, then the
 * page reads its list and the badge again. */
function closed(e: unknown): void {
  notify($q, () => ({
    type: 'negative',
    message: apiErrorMessage(e, t('approvals.actions.failed')),
  }));
  notifyApprovalsChanged();
  emit('done');
  emit('update:modelValue', false);
}

function finished(message: string): void {
  notify($q, () => ({ type: 'positive', message }));
  notifyApprovalsChanged();
  emit('done');
  emit('update:modelValue', false);
}

async function approve(confirmed: boolean): Promise<void> {
  const current = props.approval;
  if (!current) return;
  busy.value = true;
  try {
    const decided = await approveApproval(current.id, confirmed);
    finished(approvedNotification(decided));
  } catch (e) {
    if (!confirmed && apiErrorCode(e) === 'command.forbidden_window') {
      confirmForbidden(current, e);
    } else if (isClosing(e)) {
      closed(e);
    } else {
      notify($q, () => ({
        type: 'negative',
        message: apiErrorMessage(e, t('approvals.actions.failed')),
      }));
    }
  } finally {
    busy.value = false;
  }
}

/** Inside a forbidden window, now: the approver is asked as the author was
 * when sending — what the author confirmed then does not hold for now. */
function confirmForbidden(current: Approval, error: unknown): void {
  const details = (
    error as { response?: { data?: { error?: { details?: { window?: ForbiddenWindow } } } } }
  )?.response?.data?.error?.details;
  const window = details?.window ? windowText(details.window) : '';
  liveDialog($q, () => ({
    title: t('schedules.forbiddenConfirm.title'),
    message: t(
      'approvals.decision.forbiddenMessage',
      { window, count: current.machine_count },
      current.machine_count,
    ),
    cancel: { flat: true, noCaps: true, label: t('schedules.forbiddenConfirm.cancel') },
    ok: { color: 'negative', noCaps: true, label: t('approvals.decision.approve') },
    persistent: true,
  })).onOk(() => void approve(true));
}

async function reject(): Promise<void> {
  const current = props.approval;
  if (!current || note.value.length > 500) return;
  busy.value = true;
  try {
    await rejectApproval(current.id, note.value.trim() || null);
    finished(t('approvals.decision.rejected'));
  } catch (e) {
    if (isClosing(e)) closed(e);
    else
      notify($q, () => ({
        type: 'negative',
        message: apiErrorMessage(e, t('approvals.actions.failed')),
      }));
  } finally {
    busy.value = false;
  }
}
</script>
