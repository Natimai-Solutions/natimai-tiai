<template>
  <div class="intervention-attachments" data-test="intervention-attachments">
    <div v-if="editable" class="text-caption text-muted q-mb-xs">
      {{ t('interventions.attachments.title') }}
    </div>

    <div v-if="list.length || pending.length" class="row items-center q-gutter-xs">
      <!-- A click downloads; an image has its preview beside its name. -->
      <q-chip
        v-for="a in list"
        :key="a.id"
        dense
        square
        clickable
        outline
        color="primary"
        :icon="iconOf(a.content_type)"
        :removable="editable"
        :aria-label="t('interventions.attachments.download', { name: a.filename })"
        :title="t('interventions.attachments.download', { name: a.filename })"
        data-test="attachment-chip"
        @click="download(a)"
        @remove="confirmDelete(a)"
      >
        <span class="ellipsis attachment-name">{{ a.filename }}</span>
        <span class="q-ml-xs text-muted">{{ formatSize(a.size) }}</span>
        <q-btn
          v-if="isPreviewable(a)"
          flat
          dense
          round
          size="xs"
          icon="visibility"
          class="q-ml-xs"
          :aria-label="t('interventions.attachments.previewOf', { name: a.filename })"
          :title="t('interventions.attachments.preview')"
          :loading="previewing === a.id"
          data-test="attachment-preview"
          @click.stop="preview(a)"
        />
      </q-chip>
      <!-- Picked while the line does not exist yet: sent once it is saved. -->
      <q-chip
        v-for="(f, i) in pending"
        :key="`pending-${i}-${f.name}`"
        dense
        square
        removable
        icon="schedule"
        :title="t('interventions.attachments.queued')"
        :aria-label="t('interventions.attachments.remove', { name: f.name })"
        data-test="attachment-queued"
        @remove="unqueue(i)"
      >
        <span class="ellipsis attachment-name">{{ f.name }}</span>
        <span class="q-ml-xs text-muted">{{ formatSize(f.size) }}</span>
      </q-chip>
    </div>

    <template v-if="editable">
      <div
        v-if="policy && !policy.store_available"
        class="text-caption text-warn q-mt-xs"
        data-test="attachment-store-unavailable"
      >
        {{ t('interventions.attachments.storeUnavailable') }}
      </div>
      <q-file
        :model-value="null"
        multiple
        :accept="ATTACHMENT_ACCEPT"
        :label="t('interventions.attachments.add')"
        outlined
        dense
        class="q-mt-xs"
        :disable="busy || (policy !== null && !policy.store_available)"
        data-test="attachment-input"
        @update:model-value="onPicked"
      >
        <template #prepend><q-icon name="attach_file" /></template>
      </q-file>
      <q-linear-progress
        v-if="uploadingName"
        :value="progress"
        class="q-mt-xs"
        data-test="attachment-progress"
      />
      <div v-if="uploadingName" class="text-caption text-muted">
        {{ t('interventions.attachments.uploading', { name: uploadingName }) }}
      </div>
      <div v-if="policy" class="text-caption text-muted q-mt-xs">
        {{
          t('interventions.attachments.limits', {
            size: formatSize(policy.max_bytes),
            max: policy.max_per_intervention,
          })
        }}
        {{ t('interventions.attachments.photosRedrawn') }}
        {{ retentionText }}
      </div>
      <div v-if="quotaWarn" class="text-caption text-warn q-mt-xs" data-test="attachment-quota">
        {{
          t('interventions.attachments.quotaWarning', {
            used: formatSize(policy!.used_bytes ?? 0),
            quota: formatSize(policy!.quota_bytes),
          })
        }}
      </div>
    </template>

    <q-dialog v-model="previewOpen">
      <q-card style="max-width: 95vw">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-subtitle1 ellipsis">
            {{ t('interventions.attachments.previewTitle', { name: previewName }) }}
          </div>
          <q-space />
          <q-btn
            v-close-popup
            flat
            dense
            round
            icon="close"
            :aria-label="t('interventions.attachments.close')"
          />
        </q-card-section>
        <q-card-section>
          <img
            v-if="previewUrl"
            :src="previewUrl"
            :alt="previewName"
            style="max-width: 100%; max-height: 75vh; display: block"
            data-test="attachment-preview-image"
          />
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import {
  ATTACHMENT_ACCEPT,
  attachmentDataUrl,
  attachmentErrorMessage,
  deleteAttachment,
  downloadAttachment,
  isPreviewable,
  prepareForUpload,
  quotaNearlyFull,
  uploadAttachment,
  type AttachmentOut,
  type AttachmentPolicy,
} from 'src/services/attachments';
import { apiErrorMessage } from 'src/services/errors';
import { t } from 'src/i18n';
import { formatSize } from 'src/utils/format';
import { liveDialog } from 'src/utils/liveDialog';
import { notify } from 'src/utils/notify';

/**
 * The attachments of one line of the journal (C11): a chip per file — a click
 * downloads it, an image has a preview — and, in the line's dialog, the
 * deletion and the upload. On an existing line a picked file is sent at once;
 * on a line being created it waits (`queued`) until the line exists.
 */
const props = withDefaults(
  defineProps<{
    attachments: AttachmentOut[];
    /** The line, once it exists; null while it is being created. */
    interventionId?: string | null;
    /** Add and delete (intervention:write, in the line's dialog). */
    editable?: boolean;
    /** The server's limits; null when they could not be read (the server judges). */
    policy?: AttachmentPolicy | null;
    /** Files picked for a line not yet created. */
    queued?: File[];
  }>(),
  { interventionId: null, editable: false, policy: null, queued: () => [] },
);
const emit = defineEmits<{
  (e: 'changed'): void;
  (e: 'update:queued', files: File[]): void;
}>();

const $q = useQuasar();
const list = ref<AttachmentOut[]>([...props.attachments]);
watch(
  () => props.attachments,
  (value) => (list.value = [...value]),
);
const pending = ref<File[]>([...props.queued]);
watch(
  () => props.queued,
  (value) => (pending.value = [...value]),
);

const busy = ref(false);
const uploadingName = ref<string | null>(null);
const progress = ref(0);
const previewOpen = ref(false);
const previewUrl = ref<string | null>(null);
const previewName = ref('');
const previewing = ref<string | null>(null);

const quotaWarn = computed(() => props.policy !== null && quotaNearlyFull(props.policy));
const retentionText = computed(() => {
  const days = props.policy?.retention_days ?? 0;
  return days > 0
    ? t('interventions.attachments.retentionDays', { count: days }, days)
    : t('interventions.attachments.retentionKept');
});

function iconOf(contentType: string): string {
  return contentType === 'application/pdf' ? 'picture_as_pdf' : 'image';
}

function refused(name: string, reason: string) {
  notify($q, () => ({
    type: 'negative',
    message: t('interventions.attachments.refused', { name, reason }),
  }));
}

/** Files picked in the input, checked and prepared one by one. */
async function onPicked(value: File[] | File | null) {
  const files = value === null ? [] : Array.isArray(value) ? value : [value];
  if (!files.length) return;
  busy.value = true;
  let changed = false;
  try {
    for (const file of files) {
      const count = list.value.length + pending.value.length;
      const ready = await prepareForUpload(file, props.policy, count);
      if ('reason' in ready) {
        refused(file.name, ready.reason);
        continue;
      }
      if (!props.interventionId) {
        pending.value = [...pending.value, ready.file];
        emit('update:queued', pending.value);
        continue;
      }
      uploadingName.value = ready.file.name;
      progress.value = 0;
      try {
        const added = await uploadAttachment(props.interventionId, ready.file, (f) => {
          progress.value = f;
        });
        list.value = [...list.value, added];
        changed = true;
        notify($q, () => ({ type: 'positive', message: t('interventions.attachments.uploaded') }));
      } catch (e) {
        const message = attachmentErrorMessage(e);
        refused(file.name, message);
      }
    }
  } finally {
    uploadingName.value = null;
    busy.value = false;
    if (changed) emit('changed');
  }
}

function unqueue(index: number) {
  pending.value = pending.value.filter((_, i) => i !== index);
  emit('update:queued', pending.value);
}

async function download(a: AttachmentOut) {
  try {
    await downloadAttachment(a);
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('interventions.attachments.downloadFailed')),
    }));
  }
}

async function preview(a: AttachmentOut) {
  previewing.value = a.id;
  try {
    previewUrl.value = await attachmentDataUrl(a);
    previewName.value = a.filename;
    previewOpen.value = true;
  } catch (e) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(e, t('interventions.attachments.previewFailed')),
    }));
  } finally {
    previewing.value = null;
  }
}
// The image leaves memory with the dialog.
watch(previewOpen, (open) => {
  if (!open) previewUrl.value = null;
});

function confirmDelete(a: AttachmentOut) {
  liveDialog($q, () => ({
    title: t('interventions.attachments.deleteTitle'),
    message: t('interventions.attachments.deleteAsk', { name: a.filename }),
    cancel: true,
    ok: { label: t('interventions.actions.delete'), color: 'negative' },
  })).onOk(() => {
    void (async () => {
      try {
        await deleteAttachment(a.id);
        list.value = list.value.filter((x) => x.id !== a.id);
        notify($q, () => ({ type: 'positive', message: t('interventions.attachments.deleted') }));
        emit('changed');
      } catch (e) {
        notify($q, () => ({
          type: 'negative',
          message: apiErrorMessage(e, t('interventions.attachments.deleteFailed')),
        }));
      }
    })();
  });
}
</script>

<style scoped>
.attachment-name {
  max-width: 220px;
}
</style>
