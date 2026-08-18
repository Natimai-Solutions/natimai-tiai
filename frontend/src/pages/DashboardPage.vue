<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5">Tableau de bord</div>
      <q-space />
      <q-btn flat round icon="refresh" :loading="loading" @click="load" />
    </div>

    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="kpi in kpis" :key="kpi.label" class="col-6 col-sm-4 col-md-2">
        <q-card
          v-ripple
          flat
          bordered
          class="cursor-pointer relative-position full-height"
          @click="go(kpi.to)"
        >
          <q-card-section class="text-center">
            <q-icon :name="kpi.icon" :color="kpi.color" size="28px" />
            <div class="text-h5 q-mt-xs">{{ kpi.value }}</div>
            <div class="text-caption text-grey">{{ kpi.label }}</div>
            <div v-if="kpi.caption" class="text-caption text-orange">{{ kpi.caption }}</div>
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
                <q-item-label>
                  {{ m.hostname || m.machine_uuid }}
                  <!-- Unknown is not « périmé » : a poste the agent could not
                       measure gets its own grey badge, not an accusation. -->
                  <q-badge v-if="m.is_up_to_date === false" color="warning" class="q-ml-xs">
                    Antivirus périmé
                  </q-badge>
                  <q-badge v-else-if="m.is_up_to_date === null" color="grey-6" class="q-ml-xs">
                    Antivirus inconnu
                  </q-badge>
                  <q-badge v-if="m.wu_pending_count" color="orange" class="q-ml-xs">
                    {{ m.wu_pending_count }} MAJ Windows
                  </q-badge>
                </q-item-label>
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
                <q-item-label caption>
                  {{ threatSeverityLabel(t.severity) }} — {{ threatStatusLabel(t.status) }}
                </q-item-label>
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
import { useRouter, type RouteLocationRaw } from 'vue-router';
import { getOverview, type StatsOverview } from 'src/services/stats';
import { listMachines, type Machine } from 'src/services/machines';
import { listThreats, type Threat } from 'src/services/threats';
import { formatDateTime, threatSeverityLabel, threatStatusLabel } from 'src/utils/format';

const router = useRouter();

const stats = ref<StatsOverview | null>(null);
const outdated = ref<Machine[]>([]);
const threats = ref<Threat[]>([]);
const loading = ref(false);

interface Kpi {
  label: string;
  value: number;
  icon: string;
  color: string;
  /** Every card answers a click with the machine list already filtered on it. */
  to: RouteLocationRaw;
  caption?: string;
}

const kpis = computed<Kpi[]>(() => {
  const s = stats.value;
  if (!s) return [];
  const reboot = s.machines_reboot_required;
  return [
    {
      label: 'Postes',
      value: s.total,
      icon: 'devices',
      color: 'primary',
      to: { name: 'machines' },
    },
    {
      label: 'Base antivirus périmée',
      value: s.outdated,
      icon: 'gpp_maybe',
      color: 'warning',
      to: { name: 'machines', query: { status: 'outdated' } },
    },
    {
      label: 'Mise à jour Windows requise',
      value: s.machines_wu_pending,
      icon: 'system_update',
      color: 'warning',
      to: { name: 'machines', query: { wu_status: 'pending' } },
      // Not a subset of the count above: a poste can be fully patched and
      // still waiting on its restart.
      ...(reboot ? { caption: `${reboot} redémarrage${reboot > 1 ? 's' : ''} requis` } : {}),
    },
    {
      label: 'Avec menaces',
      value: s.with_active_threats,
      icon: 'coronavirus',
      color: 'negative',
      to: { name: 'machines', query: { with_active_threats: 'true' } },
    },
    {
      label: 'À vérifier',
      value: s.needs_verification,
      icon: 'help',
      color: 'orange',
      to: { name: 'machines', query: { status: 'needs_verification' } },
    },
    {
      label: 'Inactifs',
      value: s.inactive,
      icon: 'power_off',
      color: 'grey',
      to: { name: 'machines', query: { status: 'inactive' } },
    },
  ];
});

function go(to: RouteLocationRaw) {
  void router.push(to);
}

/**
 * Union of the two "behind" teasers — a poste can be behind on both — freshest
 * first. Capped like the threats list beside it: the dashboard shows a sample,
 * the cards' links show everything.
 */
function mergeOutdated(av: Machine[], wuBehind: Machine[]): Machine[] {
  const byId = new Map<string, Machine>();
  for (const m of [...av, ...wuBehind]) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) => b.last_seen.localeCompare(a.last_seen)).slice(0, 5);
}

async function load() {
  loading.value = true;
  try {
    const [s, av, wuBehind, t] = await Promise.all([
      getOverview(),
      listMachines({ status: 'outdated', page_size: 5 }),
      listMachines({ wu_status: 'pending', page_size: 5 }),
      listThreats({ status: 'active', page_size: 5 }),
    ]);
    stats.value = s;
    outdated.value = mergeOutdated(av.items, wuBehind.items);
    threats.value = t.items;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>
