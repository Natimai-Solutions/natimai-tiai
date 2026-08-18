<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5">Tableau de bord</div>
      <q-space />
      <q-btn flat round icon="refresh" :loading="loading" @click="load" />
    </div>

    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="kpi in kpis" :key="kpi.label" class="col-6 col-sm-4 col-md-3">
        <q-card flat bordered>
          <q-card-section class="text-center">
            <q-icon :name="kpi.icon" :color="kpi.color" size="28px" />
            <div class="text-h5 q-mt-xs">{{ kpi.value }}</div>
            <div class="text-caption text-grey">{{ kpi.label }}</div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <div class="row q-col-gutter-md">
      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1 row items-center">
            <q-icon name="gpp_maybe" color="warning" class="q-mr-sm" />
            Postes non à jour
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-item
              v-for="m in outdated"
              :key="m.id"
              clickable
              :to="{ name: 'machine-detail', params: { id: m.id } }"
            >
              <q-item-section>
                <q-item-label>{{ m.hostname || m.machine_uuid }}</q-item-label>
                <q-item-label caption>{{ m.domain || '—' }}</q-item-label>
              </q-item-section>
              <q-item-section side>{{ formatDateTime(m.last_seen) }}</q-item-section>
            </q-item>
            <q-item v-if="!outdated.length">
              <q-item-section class="text-grey">Aucun poste non à jour.</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1 row items-center">
            <q-icon name="coronavirus" color="negative" class="q-mr-sm" />
            Menaces actives
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-item
              v-for="t in threats"
              :key="t.id"
              clickable
              :to="{ name: 'machine-detail', params: { id: t.machine_id } }"
            >
              <q-item-section>
                <q-item-label>{{ t.threat_name || t.detection_id }}</q-item-label>
                <q-item-label caption>{{ t.severity || '—' }}</q-item-label>
              </q-item-section>
              <q-item-section side>{{ formatDateTime(t.detected_at) }}</q-item-section>
            </q-item>
            <q-item v-if="!threats.length">
              <q-item-section class="text-grey">Aucune menace active.</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { getOverview, type StatsOverview } from 'src/services/stats';
import { listMachines, type Machine } from 'src/services/machines';
import { listThreats, type Threat } from 'src/services/threats';
import { formatDateTime } from 'src/utils/format';

const stats = ref<StatsOverview | null>(null);
const outdated = ref<Machine[]>([]);
const threats = ref<Threat[]>([]);
const loading = ref(false);

const kpis = computed(() =>
  stats.value
    ? [
        { label: 'Postes', value: stats.value.total, icon: 'devices', color: 'primary' },
        {
          label: 'À jour',
          value: stats.value.up_to_date,
          icon: 'verified_user',
          color: 'positive',
        },
        { label: 'Non à jour', value: stats.value.outdated, icon: 'gpp_maybe', color: 'warning' },
        {
          label: 'À vérifier',
          value: stats.value.needs_verification,
          icon: 'help',
          color: 'orange',
        },
        { label: 'Inactifs', value: stats.value.inactive, icon: 'power_off', color: 'grey' },
        {
          label: 'Avec menaces',
          value: stats.value.with_active_threats,
          icon: 'coronavirus',
          color: 'negative',
        },
        {
          label: 'MAJ en attente',
          value: stats.value.machines_wu_pending,
          icon: 'system_update',
          color: 'warning',
        },
        {
          label: 'Redémarrage requis',
          value: stats.value.machines_reboot_required,
          icon: 'restart_alt',
          color: 'orange',
        },
      ]
    : [],
);

async function load() {
  loading.value = true;
  try {
    const [s, m, t] = await Promise.all([
      getOverview(),
      listMachines({ status: 'outdated', page_size: 5 }),
      listThreats({ status: 'active', page_size: 5 }),
    ]);
    stats.value = s;
    outdated.value = m.items;
    threats.value = t.items;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>
