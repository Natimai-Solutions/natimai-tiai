<template>
  <q-dialog :model-value="modelValue" @update:model-value="(v) => emit('update:modelValue', v)">
    <q-card style="width: 680px; max-width: 95vw">
      <q-card-section class="text-h6">
        {{ license ? t('licenses.dialog.editTitle') : t('licenses.dialog.createTitle') }}
      </q-card-section>
      <q-form @submit="submit">
        <q-card-section class="row q-col-gutter-md">
          <q-input
            v-model="form.name"
            class="col-12"
            :label="t('licenses.dialog.name')"
            :hint="t('licenses.dialog.nameHint')"
            outlined
            dense
            maxlength="200"
            autofocus
            reactive-rules
            :rules="[(v: string) => !!v?.trim() || t('licenses.dialog.required')]"
            data-test="license-name"
          />
          <!-- One pattern per chip: what a reader types after looking at the
               catalogue, every version of the program included. -->
          <q-select
            v-model="form.patterns"
            class="col-12"
            :label="t('licenses.dialog.patterns')"
            :hint="t('licenses.dialog.patternsHint')"
            outlined
            dense
            multiple
            use-chips
            use-input
            hide-dropdown-icon
            new-value-mode="add-unique"
            input-debounce="0"
            :error="patternError !== null"
            :error-message="patternError ?? ''"
            data-test="license-patterns"
            @new-value="addPattern"
          />
          <q-input
            v-model="form.publisher"
            class="col-12"
            :label="t('licenses.dialog.publisher')"
            :hint="t('licenses.dialog.publisherHint')"
            outlined
            dense
            maxlength="200"
          />
          <q-input
            v-model="form.seats"
            class="col-12 col-sm-6"
            type="number"
            min="0"
            :label="t('licenses.dialog.seats')"
            :hint="t('licenses.dialog.seatsHint')"
            outlined
            dense
            data-test="license-seats"
          />
          <q-input
            v-model="form.expires_on"
            class="col-12 col-sm-6"
            type="date"
            stack-label
            :label="t('licenses.dialog.expiresOn')"
            :hint="t('licenses.dialog.expiresOnHint')"
            outlined
            dense
          />
          <q-input
            v-model="form.vendor"
            class="col-12 col-sm-6"
            :label="t('licenses.dialog.vendor')"
            outlined
            dense
            maxlength="200"
          />
          <q-input
            v-model="form.reference"
            class="col-12 col-sm-6"
            :label="t('licenses.dialog.reference')"
            outlined
            dense
            maxlength="200"
          />
          <q-input
            v-model="form.notes"
            class="col-12"
            type="textarea"
            autogrow
            :label="t('licenses.dialog.notes')"
            outlined
            dense
            maxlength="5000"
          />
          <div class="col-12 text-caption text-muted">
            <q-icon name="key_off" class="q-mr-xs" />{{ t('licenses.dialog.noKey') }}
          </div>
        </q-card-section>

        <q-card-section v-if="validPatterns.length" class="q-pt-none" data-test="license-preview">
          <div class="text-subtitle2">{{ t('licenses.dialog.preview') }}</div>
          <q-inner-loading :showing="previewing" />
          <template v-if="preview">
            <div v-if="!preview.programs.length" class="text-muted">
              {{ t('licenses.dialog.previewNone') }}
            </div>
            <template v-else>
              <div class="text-caption q-mb-xs">
                {{ t('licenses.dialog.previewCount', { n: preview.installed }) }}
                <span v-if="preview.programs.length >= 50">
                  {{ t('licenses.dialog.previewMore') }}
                </span>
              </div>
              <div class="preview-list">
                <q-chip v-for="name in preview.programs" :key="name" dense square>
                  {{ name }}
                </q-chip>
              </div>
            </template>
          </template>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn
            v-close-popup
            flat
            no-caps
            :label="t('licenses.dialog.cancel')"
            :disable="saving"
          />
          <q-btn
            type="submit"
            color="primary"
            no-caps
            unelevated
            :label="t('licenses.dialog.save')"
            :loading="saving"
            data-test="license-save"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import { t } from 'src/i18n';
import { apiErrorMessage } from 'src/services/errors';
import {
  createLicense,
  previewLicense,
  updateLicense,
  type License,
  type LicenseFields,
  type LicensePreview,
} from 'src/services/licenses';
import { notify } from 'src/utils/notify';

const props = defineProps<{
  modelValue: boolean;
  /** The licence to edit; null for a new one. */
  license: License | null;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'saved', license: License): void;
}>();

const $q = useQuasar();
const saving = ref(false);
const touched = ref(false);

const empty = () => ({
  name: '',
  patterns: [] as string[],
  publisher: '',
  seats: '' as string | number,
  expires_on: '',
  vendor: '',
  reference: '',
  notes: '',
});
const form = reactive(empty());

/** What the patterns catch, refreshed as they change. */
const preview = ref<LicensePreview | null>(null);
const previewing = ref(false);
let previewSeq = 0;
let previewTimer: ReturnType<typeof setTimeout> | null = null;

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    Object.assign(form, empty());
    touched.value = false;
    if (previewTimer) clearTimeout(previewTimer);
    previewSeq += 1;
    preview.value = null;
    previewing.value = false;
    const lic = props.license;
    if (lic) {
      form.name = lic.name;
      form.patterns = [...lic.patterns];
      form.publisher = lic.publisher ?? '';
      form.seats = lic.seats ?? '';
      form.expires_on = lic.expires_on ?? '';
      form.vendor = lic.vendor ?? '';
      form.reference = lic.reference ?? '';
      form.notes = lic.notes ?? '';
    }
  },
  { immediate: true },
);

/** A pattern as the server keeps it: trimmed, two characters at least. */
function addPattern(
  value: string,
  done: (item?: string, mode?: 'add' | 'add-unique' | 'toggle') => void,
): void {
  touched.value = true;
  const text = value.trim();
  if (text.length < 2) {
    done();
    return;
  }
  if (form.patterns.some((p) => p.toLowerCase() === text.toLowerCase())) {
    done();
    return;
  }
  done(text, 'add-unique');
}

const validPatterns = computed(() => form.patterns.filter((p) => p.trim().length >= 2));

const patternError = computed(() =>
  touched.value && !validPatterns.value.length ? t('licenses.dialog.patternNeeded') : null,
);

watch(
  () => [validPatterns.value.join('\u0000'), form.publisher],
  () => {
    if (previewTimer) clearTimeout(previewTimer);
    if (!validPatterns.value.length) {
      preview.value = null;
      return;
    }
    previewTimer = setTimeout(() => void loadPreview(), 300);
  },
);

async function loadPreview(): Promise<void> {
  const seq = ++previewSeq;
  previewing.value = true;
  try {
    const res = await previewLicense(validPatterns.value, orNull(form.publisher));
    if (seq === previewSeq) preview.value = res;
  } catch {
    if (seq === previewSeq) preview.value = null;
  } finally {
    if (seq === previewSeq) previewing.value = false;
  }
}

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function payload(): LicenseFields {
  const seats = String(form.seats).trim();
  return {
    name: form.name.trim(),
    patterns: validPatterns.value,
    publisher: orNull(form.publisher),
    seats: seats === '' ? null : Math.max(0, Math.floor(Number(seats))),
    expires_on: orNull(form.expires_on),
    vendor: orNull(form.vendor),
    reference: orNull(form.reference),
    notes: orNull(form.notes),
  };
}

async function submit(): Promise<void> {
  touched.value = true;
  if (!validPatterns.value.length || !form.name.trim()) return;
  saving.value = true;
  try {
    const body = payload();
    const saved = props.license
      ? await updateLicense(props.license.id, body)
      : await createLicense(body);
    notify($q, () => ({ type: 'positive', message: t('licenses.saved') }));
    emit('saved', saved);
    emit('update:modelValue', false);
  } catch (e) {
    notify($q, () => ({ type: 'negative', message: apiErrorMessage(e) }));
  } finally {
    saving.value = false;
  }
}
</script>

<style scoped>
.preview-list {
  max-height: 160px;
  overflow-y: auto;
}
</style>
