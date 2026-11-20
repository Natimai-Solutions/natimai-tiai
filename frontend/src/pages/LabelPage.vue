<template>
  <!-- Where every printed label's QR code leads (`/a/<token>`), signed in or
       not: staff go on to the poste's fiche; anybody else gets the report
       form when the console opens it (C4), the login page otherwise. -->
  <div class="label-page column items-center q-pa-md">
    <div v-if="mode === 'loading'" class="row items-center q-gutter-sm q-mt-xl">
      <q-spinner color="primary" size="24px" />
      <span>{{ t('reports.form.loading') }}</span>
    </div>

    <div v-else-if="mode === 'invalid'" class="text-body1 text-muted q-mt-xl">
      {{ t('reports.form.invalid') }}
    </div>

    <q-card v-else-if="mode === 'form' || mode === 'sent'" flat bordered class="label-card">
      <q-card-section class="row items-center">
        <div class="text-h6">{{ t('reports.form.title') }}</div>
        <q-space />
        <q-btn-toggle
          :model-value="locale"
          dense
          flat
          no-caps
          toggle-color="primary"
          :options="[
            { label: 'FR', value: 'fr' },
            { label: 'EN', value: 'en' },
          ]"
          @update:model-value="setLocale"
        />
      </q-card-section>

      <q-card-section v-if="mode === 'sent'" class="q-gutter-md">
        <div class="row items-center no-wrap">
          <q-icon name="check_circle" color="positive" size="28px" class="q-mr-sm" />
          <div class="text-body1">{{ t('reports.form.sent') }}</div>
        </div>
        <q-btn flat no-caps color="primary" :label="t('reports.form.another')" @click="reset" />
      </q-card-section>

      <q-form v-else @submit="send">
        <q-card-section class="q-gutter-md">
          <div class="text-body2 text-muted">{{ t('reports.form.intro') }}</div>
          <q-select
            v-model="category"
            :options="categoryOptions"
            emit-value
            map-options
            outlined
            :label="t('reports.form.category')"
          />
          <q-input
            v-model="text"
            type="textarea"
            autogrow
            outlined
            maxlength="2000"
            :label="t('reports.form.text')"
            :hint="t('reports.form.textHint')"
            reactive-rules
            :rules="[(v: string) => (v ?? '').trim().length >= 3 || t('reports.form.textHint')]"
          />
          <q-input
            v-model="contact"
            outlined
            maxlength="200"
            :label="t('reports.form.contact')"
            :hint="t('reports.form.contactHint')"
          />
          <div v-if="error" class="text-negative">{{ error }}</div>
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md">
          <q-btn
            flat
            no-caps
            color="grey-8"
            :label="t('reports.form.staff')"
            :to="{ name: 'login', query: { redirect: route.fullPath } }"
          />
          <q-btn
            type="submit"
            color="primary"
            no-caps
            :label="t('reports.form.send')"
            :loading="sending"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { refreshSession } from 'boot/axios';
import { currentLocale, setLocale as applyLocale, t, type Locale } from 'src/i18n';
import { CHECK_CATEGORIES } from 'src/services/checks';
import { apiErrorCode } from 'src/services/errors';
import { getReportForm, submitReport } from 'src/services/reports';
import { ensureSession } from 'src/services/session';

const route = useRoute();
const router = useRouter();
const token = String(route.params.token ?? '');

const mode = ref<'loading' | 'form' | 'sent' | 'invalid'>('loading');
const locale = ref<Locale>(currentLocale());
const categories = ref<string[]>([...CHECK_CATEGORIES]);
const category = ref('hardware');
const text = ref('');
const contact = ref('');
const sending = ref(false);
const error = ref('');

const categoryOptions = computed(() =>
  categories.value.map((c) => ({ label: t(`checks.category.${c}`), value: c })),
);

function setLocale(value: Locale): void {
  locale.value = value;
  applyLocale(value);
}

function reset(): void {
  text.value = '';
  contact.value = '';
  error.value = '';
  mode.value = 'form';
}

async function send(): Promise<void> {
  if (text.value.trim().length < 3) return;
  sending.value = true;
  error.value = '';
  try {
    await submitReport(token, {
      category: category.value,
      text: text.value.trim(),
      contact: contact.value.trim() || null,
      language: locale.value,
    });
    mode.value = 'sent';
  } catch (e) {
    const code = apiErrorCode(e);
    error.value =
      code === 'request.rate_limited'
        ? t('reports.form.tooMany')
        : code === 'report.label.invalid'
          ? t('reports.form.invalid')
          : t('reports.form.failed');
  } finally {
    sending.value = false;
  }
}

onMounted(async () => {
  // Staff signed in: the poste's fiche, as the label always led.
  if (await ensureSession(refreshSession)) {
    await router.replace({ name: 'asset-token', params: { token } });
    return;
  }
  try {
    const form = await getReportForm(token);
    if (!form.enabled) {
      // Closed: the label is the staff's — the login page, then the fiche.
      await router.replace({ name: 'login', query: { redirect: route.fullPath } });
      return;
    }
    categories.value = form.categories;
    mode.value = 'form';
  } catch {
    mode.value = 'invalid';
  }
});
</script>

<style scoped>
.label-page {
  min-height: 100vh;
}
.label-card {
  width: 560px;
  max-width: 100%;
}
</style>
