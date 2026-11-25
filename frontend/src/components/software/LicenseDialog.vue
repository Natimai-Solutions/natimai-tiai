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
            @input-value="(v: string) => (pendingPattern = v)"
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
            :error="seatsError !== null"
            :error-message="seatsError ?? ''"
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
                {{ t('licenses.dialog.previewCount', { n: preview.installed }, preview.installed) }}
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
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
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
import { useAuthStore } from 'src/stores/auth';
import { notify } from 'src/utils/notify';

/** The server's bounds (`routes/licenses.py`). */
const MAX_PATTERNS = 20;
const PATTERN_MAX_LENGTH = 100;
const MAX_SEATS = 1_000_000;

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
const auth = useAuthStore();
const saving = ref(false);
const touched = ref(false);
/** Text typed in the patterns field and not yet confirmed with Enter. */
const pendingPattern = ref('');
/** Why the last pattern typed was not taken, until the next one is. */
const patternRefusal = ref<string | null>(null);

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
    pendingPattern.value = '';
    patternRefusal.value = null;
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

/** Why a pattern would be refused by the server, or null when it is taken. */
function refusal(text: string): string | null {
  if (text.length < 2) return t('licenses.dialog.minPattern');
  if (text.length > PATTERN_MAX_LENGTH) return t('licenses.dialog.maxPatternLength');
  if (form.patterns.length >= MAX_PATTERNS) return t('licenses.dialog.tooManyPatterns');
  return null;
}

/** A pattern as the server keeps it: trimmed, 2 to 100 characters, 20 at most. */
function addPattern(
  value: string,
  done: (item?: string, mode?: 'add' | 'add-unique' | 'toggle') => void,
): void {
  touched.value = true;
  pendingPattern.value = '';
  const text = value.trim();
  if (form.patterns.some((p) => p.toLowerCase() === text.toLowerCase())) {
    patternRefusal.value = null;
    done();
    return;
  }
  patternRefusal.value = refusal(text);
  if (patternRefusal.value) {
    done();
    return;
  }
  done(text, 'add-unique');
}

/** The text left in the field when saving: taken as a pattern, as if Enter
 *  had been pressed — a reader who typed « Office » and clicked Enregistrer
 *  meant it. Returns false when it cannot be taken. */
function takePending(): boolean {
  const text = pendingPattern.value.trim();
  if (!text) return true;
  if (form.patterns.some((p) => p.toLowerCase() === text.toLowerCase())) {
    pendingPattern.value = '';
    return true;
  }
  patternRefusal.value = refusal(text);
  if (patternRefusal.value) return false;
  form.patterns = [...form.patterns, text];
  pendingPattern.value = '';
  return true;
}

/** The number of postes as typed: empty (a site licence) or a whole number. */
const seatsError = computed(() => {
  const text = String(form.seats).trim();
  if (text === '') return null;
  const n = Number(text);
  return Number.isInteger(n) && n >= 0 && n <= MAX_SEATS ? null : t('licenses.dialog.seatsInvalid');
});

const validPatterns = computed(() => form.patterns.filter((p) => p.trim().length >= 2));

const patternError = computed(() => {
  if (patternRefusal.value) return patternRefusal.value;
  return touched.value && !validPatterns.value.length ? t('licenses.dialog.patternNeeded') : null;
});

watch(
  () => [validPatterns.value.join('\u0000'), form.publisher],
  () => {
    if (previewTimer) clearTimeout(previewTimer);
    // The program names are the catalogue's, read with machine:read.
    if (!validPatterns.value.length || !auth.can('machine', 'read')) {
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

onBeforeUnmount(() => {
  if (previewTimer) clearTimeout(previewTimer);
  previewSeq += 1;
});

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
    seats: seats === '' ? null : Number(seats),
    expires_on: orNull(form.expires_on),
    vendor: orNull(form.vendor),
    reference: orNull(form.reference),
    notes: orNull(form.notes),
  };
}

async function submit(): Promise<void> {
  touched.value = true;
  if (!takePending()) return;
  if (!validPatterns.value.length || !form.name.trim() || seatsError.value) return;
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
