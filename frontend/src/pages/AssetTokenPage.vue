<template>
  <!-- Where a scanned label lands: the poste's fiche, or the equipment list
       on that equipment. Signed in first, by the router's guard. -->
  <q-page padding class="flex flex-center">
    <div v-if="notFound" class="text-body1 text-muted">{{ t('assets.token.notFound') }}</div>
    <div v-else-if="noAssetRead" class="text-body1 text-muted">
      {{ t('assets.token.noAssetRead') }}
    </div>
    <div v-else class="row items-center q-gutter-sm">
      <q-spinner color="primary" size="24px" />
      <span>{{ t('assets.token.resolving') }}</span>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { t } from 'src/i18n';
import { resolveAssetToken } from 'src/services/assets';
import { useAuthStore } from 'src/stores/auth';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const notFound = ref(false);
// Equipment, for a reader who cannot open « Matériels »: said, rather than
// sent to the dashboard by the router's guard.
const noAssetRead = ref(false);

onMounted(async () => {
  const token = String(route.params.token ?? '');
  try {
    const target = await resolveAssetToken(token);
    if (target.machine_id) {
      await router.replace({ name: 'machine-detail', params: { id: target.machine_id } });
    } else if (auth.can('asset', 'read')) {
      // The equipment list, on that equipment alone.
      await router.replace({ name: 'assets', query: { ids: target.asset_id } });
    } else {
      noAssetRead.value = true;
    }
  } catch {
    notFound.value = true;
  }
});
</script>
