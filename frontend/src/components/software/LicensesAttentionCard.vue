<template>
  <!-- The dashboard's « Licences à revoir » (C6): shown only when one is
       over its count, ending or ended — a parc without licences, or without
       anything to look at, has no card. -->
  <div v-if="rows.length" data-test="licenses-attention">
    <q-card flat bordered>
      <q-card-section class="text-subtitle1 row items-center">
        <q-icon name="workspace_premium" color="warning" class="q-mr-sm" />
        {{ t('licenses.dashboard.title') }}
        <q-space />
        <q-btn
          flat
          dense
          no-caps
          color="primary"
          :label="t('licenses.dashboard.open')"
          :to="{ name: 'software', query: { view: 'licenses' } }"
        />
      </q-card-section>
      <div class="q-px-md text-caption text-muted">
        {{ t('licenses.dashboard.caption', { days: expiryDays }, expiryDays) }}
      </div>
      <q-list separator>
        <q-item v-for="lic in rows" :key="lic.id">
          <q-item-section>
            <q-item-label>{{ lic.name }}</q-item-label>
            <q-item-label v-if="lic.expires_on" caption>
              {{ formatDate(lic.expires_on) }}
            </q-item-label>
          </q-item-section>
          <q-item-section side class="row no-wrap items-center">
            <div>
              <q-badge v-if="lic.over" color="negative" class="q-mr-xs">
                {{ t('licenses.usage', { installed: lic.installed, seats: lic.seats ?? 0 }) }}
              </q-badge>
              <q-badge
                v-if="lic.expiry === 'soon' || lic.expiry === 'expired'"
                :color="lic.expiry === 'expired' ? 'negative' : 'warning'"
              >
                {{ t(`licenses.expiry.${lic.expiry}`) }}
              </q-badge>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { t } from 'src/i18n';
import { listLicenses, needsAttention, type License } from 'src/services/licenses';
import { formatDate } from 'src/utils/format';

const items = ref<License[]>([]);
const expiryDays = ref(60);

const rows = computed(() => items.value.filter(needsAttention));

/** Read again with the dashboard's own refresh. A failure keeps what was
 *  shown: the dashboard's other figures do not wait on the licences. */
async function load(): Promise<void> {
  try {
    const res = await listLicenses();
    items.value = res.items;
    expiryDays.value = res.expiry_days;
  } catch {
    // Left as it was.
  }
}

onMounted(load);

defineExpose({ load });
</script>
