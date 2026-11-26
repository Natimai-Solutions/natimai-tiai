<template>
  <q-page padding>
    <div class="row items-center q-col-gutter-md q-mb-sm">
      <h1 class="text-h5 q-my-none col-auto">{{ t('approvals.title') }}</h1>
      <q-space />
      <div class="col-auto">
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          :aria-label="t('approvals.refresh')"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>
    <div class="text-caption text-muted q-mb-md" data-test="approvals-subtitle">
      {{ enabled ? t('approvals.subtitle') : t('approvals.subtitleOff') }}
    </div>

    <q-tabs
      v-model="view"
      dense
      no-caps
      align="left"
      active-color="primary"
      indicator-color="primary"
      class="q-mb-sm"
    >
      <q-tab name="to_decide" data-test="tab-to-decide">
        <div class="row items-center no-wrap q-gutter-xs">
          <span>{{ t('approvals.tabs.toDecide') }}</span>
          <q-badge v-if="toDecide" color="orange-8" :label="toDecide" />
        </div>
      </q-tab>
      <q-tab name="mine" :label="t('approvals.tabs.mine')" data-test="tab-mine" />
    </q-tabs>

    <LoadErrorBanner v-if="loadError" :error="loadError" :loading="loading" @retry="load" />

    <q-card flat bordered>
      <q-table
        :rows="items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        flat
        :grid="$q.screen.lt.sm"
        :rows-per-page-options="[0]"
        hide-pagination
        :no-data-label="
          loadError
            ? t('approvals.empty.loadFailed')
            : view === 'mine'
              ? t('approvals.empty.mine')
              : t('approvals.empty.toDecide')
        "
      >
        <template #body-cell-action="props">
          <q-td :props="props" style="white-space: normal">
            {{ approvalAction(props.row) }}
          </q-td>
        </template>
        <template #body-cell-status="props">
          <q-td :props="props" style="white-space: normal; max-width: 320px">
            <q-badge :color="approvalStatusColor(props.row.status)" data-test="approval-status">
              {{ approvalStatusLabel(props.row.status) }}
            </q-badge>
            <div v-if="approvalOutcome(props.row)" class="text-caption text-muted">
              {{ approvalOutcome(props.row) }}
            </div>
            <div v-else-if="props.row.status === 'pending'" class="text-caption text-muted">
              {{ t('approvals.expiresIn', { at: formatDateTime(props.row.expires_at) }) }}
            </div>
          </q-td>
        </template>
        <template #body-cell-actions="props">
          <q-td :props="props" auto-width>
            <template v-if="view === 'to_decide'">
              <q-btn
                flat
                dense
                no-caps
                color="positive"
                icon="check"
                :label="t('approvals.actions.approve')"
                data-test="approve"
                @click="openDecision(props.row, 'approve')"
              />
              <q-btn
                flat
                dense
                no-caps
                color="negative"
                icon="block"
                :label="t('approvals.actions.reject')"
                data-test="reject"
                @click="openDecision(props.row, 'reject')"
              />
            </template>
            <q-btn
              v-else-if="props.row.status === 'pending'"
              flat
              dense
              no-caps
              icon="cancel"
              :label="t('approvals.actions.cancel')"
              data-test="cancel"
              @click="cancel(props.row)"
            />
          </q-td>
        </template>
      </q-table>
    </q-card>
    <div v-if="total > pageSize" class="row justify-center q-mt-md">
      <q-pagination v-model="page" :max="Math.ceil(total / pageSize)" @update:model-value="load" />
    </div>

    <!-- Decided or found closed: the dialog bumps the badge's version, which
         this page follows too. -->
    <ApprovalDecisionDialog v-model="deciding" :approval="current" :mode="mode" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import ApprovalDecisionDialog from 'src/components/approval/ApprovalDecisionDialog.vue';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import { t } from 'src/i18n';
import { approvalsVersion, notifyApprovalsChanged } from 'src/composables/useApprovalsBadge';
import {
  approvalAction,
  approvalOutcome,
  approvalStatusColor,
  approvalStatusLabel,
  approvalTarget,
  cancelApproval,
  getApprovalSummary,
  listApprovals,
  type Approval,
  type ApprovalView,
} from 'src/services/approvals';
import { apiErrorCode, apiErrorMessage } from 'src/services/errors';
import { formatDateTime } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

const $q = useQuasar();

const view = ref<ApprovalView>('to_decide');
const items = ref<Approval[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 50;
const loading = ref(false);
const loadError = ref<unknown>(null);
const enabled = ref(true);
const toDecide = ref(0);

const deciding = ref(false);
const current = ref<Approval | null>(null);
const mode = ref<'approve' | 'reject'>('approve');

const columns = computed<QTableColumn<Approval>[]>(() => {
  const cols: QTableColumn<Approval>[] = [];
  if (view.value === 'to_decide') {
    cols.push({
      name: 'requestedBy',
      label: t('approvals.columns.requestedBy'),
      field: 'requested_by',
      align: 'left',
    });
  }
  cols.push(
    { name: 'action', label: t('approvals.columns.action'), field: 'command_type', align: 'left' },
    {
      name: 'target',
      label: t('approvals.columns.target'),
      field: (row) => approvalTarget(row),
      align: 'left',
      style: 'white-space: normal',
    },
    {
      name: 'count',
      label: t('approvals.columns.count'),
      field: 'machine_count',
      align: 'right',
    },
    {
      name: 'requestedAt',
      label: t('approvals.columns.requestedAt'),
      field: (row) => formatDateTime(row.requested_at),
      align: 'left',
    },
  );
  if (view.value === 'to_decide') {
    cols.push({
      name: 'expires',
      label: t('approvals.columns.expires'),
      field: (row) => formatDateTime(row.expires_at),
      align: 'left',
    });
  } else {
    cols.push({
      name: 'status',
      label: t('approvals.columns.status'),
      field: 'status',
      align: 'left',
    });
  }
  cols.push({ name: 'actions', label: '', field: 'id', align: 'right' });
  return cols;
});

async function loadSummary(): Promise<void> {
  try {
    const summary = await getApprovalSummary();
    enabled.value = summary.enabled;
    toDecide.value = summary.to_decide;
  } catch {
    // The list below says what went wrong; the count is a hint.
  }
}

// Each load is numbered: a late answer for the other tab (or an earlier page)
// is dropped rather than shown, with its actions, under the tab now open.
let loadSeq = 0;

async function load(): Promise<void> {
  const seq = ++loadSeq;
  const asked = view.value;
  loading.value = true;
  try {
    const res = await listApprovals({ view: asked, page: page.value, page_size: pageSize });
    if (seq !== loadSeq) return;
    items.value = res.items;
    total.value = res.total;
    if (asked === 'to_decide') toDecide.value = res.total;
    loadError.value = null;
  } catch (e) {
    if (seq !== loadSeq) return;
    loadError.value = e;
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
  if (seq === loadSeq) void loadSummary();
}

watch(view, () => {
  page.value = 1;
  items.value = [];
  void load();
});

// A request sent or decided elsewhere in the console (the machine list, a
// schedule): this page follows, as the menu's badge does.
watch(approvalsVersion, () => void load());

function openDecision(a: Approval, how: 'approve' | 'reject'): void {
  current.value = a;
  mode.value = how;
  deciding.value = true;
}

function cancel(a: Approval): void {
  liveDialog($q, () => ({
    message: t('approvals.actions.cancelConfirm'),
    cancel: { flat: true, noCaps: true, label: t('approvals.actions.keep') },
    ok: { color: 'negative', noCaps: true, label: t('approvals.actions.cancel') },
  })).onOk(() => {
    void (async () => {
      try {
        await cancelApproval(a.id);
        notify($q, () => ({ type: 'positive', message: t('approvals.actions.cancelled') }));
      } catch (e) {
        notify($q, () => ({
          type: 'negative',
          message: apiErrorMessage(e, t('approvals.actions.failed')),
        }));
        // Already closed: the list says how.
        if (apiErrorCode(e) !== 'approval.not_pending') return;
      }
      notifyApprovalsChanged();
    })();
  });
}

onMounted(load);
</script>
