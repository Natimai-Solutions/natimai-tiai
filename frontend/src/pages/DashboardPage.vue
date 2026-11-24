<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <h1 class="text-h5 q-my-none">{{ t('dashboard.title') }}</h1>
      <q-space />
      <div v-if="lastRefreshedAt" class="text-caption text-muted q-mr-sm">
        {{ t('dashboard.refreshedAt', { time: lastRefreshLabel }) }}
      </div>
      <q-btn
        :aria-label="t('dashboard.refresh')"
        flat
        round
        icon="refresh"
        :loading="loading"
        @click="reload"
      >
        <q-tooltip>{{ autoRefreshHint }}</q-tooltip>
      </q-btn>
    </div>

    <LoadErrorBanner
      v-if="lastError && !lastRefreshedAt"
      :error="lastError"
      :loading="loading"
      @retry="reload"
    />

    <!-- Three rows, three readings. The first is the parc itself — its size,
         and how much its postes are used. The next two are what needs doing about it, most urgent first:
         the four findings that put a poste at risk today take the whole width
         and the large figure; the five that can wait for the week's round sit
         below, smaller. Every card is a list an administrator opens and acts on. -->
    <div class="row q-col-gutter-md q-mb-md">
      <div v-for="kpi in inventoryKpis" :key="kpi.label" class="col-12 col-sm-6 col-md-3">
        <router-link :to="kpi.to" class="card-link">
          <q-card v-ripple flat bordered class="cursor-pointer relative-position full-height">
            <q-card-section class="row items-center no-wrap">
              <q-icon :name="kpi.icon" :color="kpi.color" size="36px" class="q-mr-md" />
              <div>
                <div class="text-h4">{{ kpi.value }}</div>
                <div class="text-caption text-muted">{{ kpi.label }}</div>
                <div v-if="kpi.detail" class="text-caption text-muted">{{ kpi.detail }}</div>
                <div v-if="kpi.caption" class="text-caption text-warn">{{ kpi.caption }}</div>
              </div>
            </q-card-section>
          </q-card>
        </router-link>
      </div>
    </div>

    <div class="row q-col-gutter-md q-mb-md">
      <div v-for="kpi in priorityKpis" :key="kpi.label" class="col-12 col-sm-6 col-md-3">
        <router-link :to="kpi.to" class="card-link">
          <q-card
            v-ripple
            flat
            bordered
            class="cursor-pointer relative-position full-height"
            :class="kpi.value ? `priority-card priority-card--${kpi.color}` : ''"
          >
            <q-card-section class="row items-center no-wrap">
              <q-icon :name="kpi.icon" :color="kpi.color" size="40px" class="q-mr-md" />
              <div>
                <div class="text-h4">{{ kpi.value }}</div>
                <div class="text-caption text-muted">{{ kpi.label }}</div>
                <div v-if="kpi.caption" class="text-caption text-warn">{{ kpi.caption }}</div>
              </div>
            </q-card-section>
          </q-card>
        </router-link>
      </div>
    </div>

    <div class="row q-col-gutter-md q-mb-lg">
      <div v-for="kpi in alertKpis" :key="kpi.label" class="col-6 col-sm-4 col-md">
        <component
          :is="kpi.to ? RouterLink : 'div'"
          v-bind="kpi.to ? { to: kpi.to } : {}"
          class="card-link"
        >
          <q-card
            v-ripple="!!kpi.to"
            flat
            bordered
            class="relative-position full-height"
            :class="{ 'cursor-pointer': kpi.to }"
          >
            <q-card-section class="text-center">
              <q-icon :name="kpi.icon" :color="kpi.color" size="28px" />
              <div class="text-h5 q-mt-xs">{{ kpi.value }}</div>
              <div class="text-caption text-muted">{{ kpi.label }}</div>
              <div v-if="kpi.detail" class="text-caption text-muted">{{ kpi.detail }}</div>
              <div v-if="kpi.caption" class="text-caption text-warn">{{ kpi.caption }}</div>
            </q-card-section>
          </q-card>
        </component>
      </div>
    </div>

    <div class="row q-col-gutter-md">
      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1 row items-center">
            <q-icon name="gpp_maybe" color="warning" class="q-mr-sm" />
            {{ t('dashboard.outdated.title') }}
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
                    {{ t('dashboard.outdated.antivirusOutdated') }}
                  </q-badge>
                  <q-badge v-else-if="m.is_up_to_date === null" color="grey-6" class="q-ml-xs">
                    {{ t('dashboard.outdated.antivirusUnknown') }}
                  </q-badge>
                  <q-badge v-if="m.wu_pending_count" color="orange" class="q-ml-xs">
                    {{
                      t(
                        'dashboard.outdated.wuPending',
                        { count: m.wu_pending_count },
                        m.wu_pending_count,
                      )
                    }}
                  </q-badge>
                </q-item-label>
                <q-item-label caption>{{ m.domain || '—' }}</q-item-label>
              </q-item-section>
              <q-item-section side>{{ formatDateTime(m.last_seen) }}</q-item-section>
            </q-item>
            <q-item v-if="outdatedLoaded && !outdated.length">
              <q-item-section class="text-muted">{{
                t('dashboard.outdated.empty')
              }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <div v-if="complianceRows.length" class="col-12 col-md-6">
        <q-card flat bordered data-test="compliance-by-check">
          <q-card-section class="text-subtitle1 row items-center">
            <q-icon name="verified_user" color="negative" class="q-mr-sm" />
            {{ t('compliance.dashboard.byCheck') }}
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-item v-for="row in complianceRows" :key="row.check" clickable :to="row.to">
              <q-item-section>{{ complianceCheckLabel(row.check) }}</q-item-section>
              <q-item-section side>
                <q-badge color="negative">{{ row.count }}</q-badge>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <LicensesAttentionCard v-if="canReadLicenses" class="col-12 col-md-6" />

      <div v-if="canReadThreats" class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="text-subtitle1 row items-center">
            <q-icon name="coronavirus" color="negative" class="q-mr-sm" />
            {{ t('dashboard.threats.title') }}
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-item
              v-for="threat in threats"
              :key="threat.id"
              clickable
              :to="{ name: 'machine-detail', params: { id: threat.machine_id } }"
            >
              <q-item-section>
                <q-item-label class="threat-name">{{
                  threatNameLabel(threat.threat_name, threat.detection_id)
                }}</q-item-label>
                <q-item-label caption>
                  {{
                    t('dashboard.threats.line', {
                      severity: threatSeverityLabel(threat.severity),
                      status: threatStatusLabel(threat.status),
                    })
                  }}
                </q-item-label>
              </q-item-section>
              <q-item-section side>{{ formatDateTime(threat.detected_at) }}</q-item-section>
            </q-item>
            <q-item v-if="threatsLoaded && !threats.length">
              <q-item-section class="text-muted">{{ t('dashboard.threats.empty') }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { intlTag, t } from 'src/i18n';
import LoadErrorBanner from 'src/components/LoadErrorBanner.vue';
import LicensesAttentionCard from 'src/components/software/LicensesAttentionCard.vue';
import { computed, onMounted, ref } from 'vue';
import { RouterLink, type RouteLocationRaw } from 'vue-router';
import { rememberFleetThresholds } from 'src/composables/useFleetThresholds';
import { useQuasar } from 'quasar';
import { AUTO_REFRESH_INTERVAL_MS, useAutoRefresh } from 'src/composables/useAutoRefresh';
import { getOverview, type StatsOverview } from 'src/services/stats';
import { complianceCheckLabel } from 'src/services/compliance';
import { listMachines, type Machine } from 'src/services/machines';
import { listThreats, type Threat } from 'src/services/threats';
import { apiErrorMessage } from 'src/services/errors';
import { useAuthStore } from 'src/stores/auth';
import {
  formatDateTime,
  threatNameLabel,
  threatSeverityLabel,
  threatStatusLabel,
} from 'src/utils/format';
import { notify } from 'src/utils/notify';

const $q = useQuasar();
const stats = ref<StatsOverview | null>(null);
const outdated = ref<Machine[]>([]);
const threats = ref<Threat[]>([]);
const loading = ref(false);
// The empty messages say something only once their list has loaded: before
// that, or after a failure, « aucune menace » would be a claim (audit U07).
const outdatedLoaded = ref(false);
const threatsLoaded = ref(false);

interface Kpi {
  label: string;
  value: number;
  icon: string;
  color: string;
  /** Every card answers a click with the machine list already filtered on it. */
  to: RouteLocationRaw;
  caption?: string;
  /** A second, quiet line: what the figure was counted against. */
  detail?: string;
}

/** A card of the last row: a list to open where the list can show it, else a figure. */
interface AlertKpi extends Omit<Kpi, 'to'> {
  to?: RouteLocationRaw;
}

/**
 * The figures leave the retired postes out (decision 5): while the parc has
 * any, the lists the cards open leave them out too (`in_parc=true`), or the
 * card would read 3 and its list 4. Without retired postes the link stays as
 * it was, no chip to explain.
 */
/** The failed compliance checks, most failed first, each opening its list. */
const complianceRows = computed(() => {
  const by = stats.value?.compliance_by_check ?? {};
  return Object.entries(by)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([check, count]) =>
      inParc({
        check,
        count,
        to: { name: 'machines', query: { compliance_check: check } } as RouteLocationRaw,
      }),
    );
});

function inParc<T extends { to?: RouteLocationRaw }>(kpi: T): T {
  const retired = stats.value?.machines_retired ?? 0;
  const to = kpi.to;
  if (!retired || !to || typeof to !== 'object' || !('name' in to) || to.name !== 'machines')
    return kpi;
  const query = 'query' in to && to.query ? to.query : {};
  return { ...kpi, to: { ...to, query: { ...query, in_parc: 'true' } } };
}

/**
 * « comptage depuis le 12/10 » while the usage counters are younger than the
 * window they are read over — until then a parc reading « peu utilisé » is a
 * parc being counted since Tuesday, not a parc nobody uses. Undefined once the
 * window is full.
 */
function usageCountingCaption(s: StatsOverview): string | undefined {
  if (!s.usage_since) return t('dashboard.kpi.countingNotStarted');
  const since = new Date(s.usage_since);
  const full = since.getTime() + s.usage_window_days * 24 * 3600 * 1000;
  if (Date.now() >= full) return undefined;
  return t('dashboard.kpi.countingSince', {
    date: since.toLocaleDateString(intlTag(), { day: '2-digit', month: '2-digit' }),
  });
}

/**
 * The parc itself: how many postes, how many distinct programs on them — and
 * how much the postes are used, the two ends of it. Each usage card opens the
 * list on the very bounds it counted, so the card and the list agree.
 */
const inventoryKpis = computed<Kpi[]>(() => {
  const s = stats.value;
  if (!s) return [];
  const counting = usageCountingCaption(s);
  return [
    {
      label: t('dashboard.kpi.machines'),
      value: s.total,
      icon: 'devices',
      color: 'primary',
      to: { name: 'machines' },
    },
    {
      label: t('dashboard.kpi.software'),
      value: s.software_count,
      icon: 'inventory_2',
      color: 'primary',
      to: { name: 'software' },
    },
    {
      label: t('dashboard.kpi.usageLow'),
      value: s.machines_usage_low,
      icon: 'bedtime',
      color: 'blue-grey',
      to: { name: 'machines', query: { usage_hours_below: String(s.usage_low_hours) } },
      detail: t('dashboard.kpi.usageLowDetail', {
        hours: s.usage_low_hours,
        days: s.usage_window_days,
      }),
      ...(counting ? { caption: counting } : {}),
    },
    {
      label: t('dashboard.kpi.usageHigh'),
      value: s.machines_usage_high,
      icon: 'bolt',
      color: 'amber-8',
      to: { name: 'machines', query: { usage_hours_above: String(s.usage_high_hours) } },
      detail: t('dashboard.kpi.usageHighDetail', {
        hours: s.usage_high_hours,
        days: s.usage_window_days,
      }),
      ...(counting ? { caption: counting } : {}),
    },
  ].map(inParc);
});

/**
 * What puts a poste at risk today — the row that takes the whole width. Four
 * findings, each a list to act on this morning: a signature base the antivirus
 * cannot detect with, patches not applied, a threat on the poste, a disk about
 * to stop Windows from patching at all.
 */
const priorityKpis = computed<Kpi[]>(() => {
  const s = stats.value;
  if (!s) return [];
  const reboot = s.machines_reboot_required;
  return [
    {
      label: t('dashboard.kpi.antivirusOutdated'),
      value: s.outdated,
      icon: 'gpp_maybe',
      color: 'warning',
      to: { name: 'machines', query: { status: 'outdated' } },
    },
    {
      label: t('dashboard.kpi.wuPending'),
      value: s.machines_wu_pending,
      icon: 'system_update',
      color: 'warning',
      to: { name: 'machines', query: { wu_status: 'pending' } },
      // Not a subset of the count above: a poste can be fully patched and
      // still waiting on its restart.
      ...(reboot ? { caption: t('dashboard.kpi.rebootRequired', { count: reboot }, reboot) } : {}),
    },
    {
      label: t('dashboard.kpi.withThreats'),
      value: s.with_active_threats,
      icon: 'coronavirus',
      color: 'negative',
      to: { name: 'machines', query: { with_active_threats: 'true' } },
    },
    {
      // Beside the Windows Update card rather than among the inventory: below
      // roughly ten percent free, Windows stops being able to stage a
      // cumulative update, so a poste crosses this line and then quietly
      // stops patching.
      label: t('dashboard.kpi.lowDisk'),
      value: s.machines_low_disk,
      icon: 'storage',
      color: 'negative',
      to: {
        name: 'machines',
        query: { disk_free_below: String(s.low_disk_free_percent) },
      },
      caption: t('dashboard.kpi.lowDiskCaption', { percent: s.low_disk_free_percent }),
    },
  ].map(inParc);
});

/**
 * What needs doing this week. Each card is a list an administrator can open
 * and act on, which is the only reason a KPI earns a card here — the
 * encryption and hardware-age counts the API still serves have no such list
 * behind them yet, and a figure nobody can act on is noise on a wall screen.
 */
const alertKpis = computed<AlertKpi[]>(() => {
  const s = stats.value;
  if (!s) return [];
  return [
    // The rules the server evaluates: the page that lists them by rule.
    ...(s.machines_with_alerts !== undefined
      ? [
          {
            label: t('dashboard.kpi.alerts'),
            value: s.machines_with_alerts,
            icon: 'notifications_active',
            color: s.machines_with_alerts ? 'negative' : 'grey',
            to: { name: 'alerts' },
          },
        ]
      : []),
    // Compliance (C5): the postes failing a check of the closed list, the
    // compliant ones in the caption. Shown by a server that counts them.
    ...(s.machines_noncompliant !== undefined
      ? [
          {
            label: t('compliance.dashboard.noncompliant'),
            value: s.machines_noncompliant,
            icon: 'verified_user',
            color: s.machines_noncompliant ? 'negative' : 'grey',
            to: { name: 'machines', query: { compliance: 'failing' } },
            caption: t('compliance.dashboard.compliantCaption', {
              count: s.machines_compliant ?? 0,
            }),
          },
        ]
      : []),
    // The renewal plan's other half: postes that will not take Windows 11.
    ...(s.machines_win11_blocked
      ? [
          {
            label: t('dashboard.kpi.win11Blocked'),
            value: s.machines_win11_blocked,
            icon: 'upgrade',
            color: 'deep-orange',
            to: { name: 'machines', query: { win11_blocked: 'true' } },
          },
        ]
      : []),
    // Enrolment needing a decision: a reinstalled poste asking back in, or a
    // revoked one. Shown by a server that counts them (older ones do not).
    ...(s.machines_reenroll_pending !== undefined
      ? [
          {
            label: t('dashboard.kpi.reenrollPending'),
            value: s.machines_reenroll_pending,
            icon: 'key',
            color: 'orange',
            to: { name: 'machines', query: { enrollment: 'pending' } },
          },
        ]
      : []),
    ...(s.machines_token_revoked
      ? [
          {
            label: t('dashboard.kpi.tokenRevoked'),
            value: s.machines_token_revoked,
            icon: 'key_off',
            color: 'negative',
            to: { name: 'machines', query: { enrollment: 'revoked' } },
          },
        ]
      : []),
    {
      label: t('dashboard.kpi.needsVerification'),
      value: s.needs_verification,
      icon: 'help',
      color: 'orange',
      to: { name: 'machines', query: { status: 'needs_verification' } },
    },
    {
      // The task the console hands out, beside the findings the parc raised
      // itself: what somebody was asked to go and look at.
      label: t('dashboard.kpi.openChecks'),
      value: s.open_checks,
      icon: 'fact_check',
      color: 'primary',
      to: { name: 'machines', query: { check_open: 'true' } },
    },
    {
      label: t('dashboard.kpi.inactive'),
      value: s.inactive,
      icon: 'power_off',
      color: 'grey',
      to: { name: 'machines', query: { status: 'inactive' } },
    },
    {
      label: t('dashboard.kpi.maintenanceOverdue'),
      value: s.machines_maintenance_overdue,
      icon: 'build',
      color: 'negative',
      to: { name: 'machines', query: { maintenance_state: 'overdue' } },
      ...(s.machines_maintenance_due_soon
        ? {
            caption: t('dashboard.kpi.maintenanceDueSoon', {
              count: s.machines_maintenance_due_soon,
            }),
          }
        : {}),
    },
    {
      // The deployment's progress bar: how many postes the new agent has not
      // reached. Actionable like the others — the list it opens is the list to
      // go and see (or to wake), and the caption names what "à jour" means.
      label: t('dashboard.kpi.agentOutdated'),
      value: s.machines_agent_outdated,
      icon: 'system_update_alt',
      color: 'orange',
      to: { name: 'machines', query: { agent_outdated: 'true' } },
      ...(s.agent_latest_version
        ? { caption: t('dashboard.kpi.agentReference', { version: s.agent_latest_version }) }
        : {}),
    },
    {
      // The hardware-age setting, made visible — and the list it counts.
      label: t('dashboard.kpi.aging'),
      value: s.machines_aging,
      icon: 'hourglass_bottom',
      color: 'blue-grey',
      to: { name: 'machines', query: { hardware_aging: 'true' } },
      detail: t('dashboard.kpi.agingDetail', { years: s.hardware_aging_years }),
    },
  ].map(inParc);
});

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

// The counters need machine:read alone; the threat list asks for its own
// permission, which a group may not grant (audit B02).
const auth = useAuthStore();
const canReadThreats = computed(() => auth.can('threat', 'read'));
const canReadLicenses = computed(() => auth.can('license', 'read'));

async function fetchAll() {
  // The side lists sit beside cards that leave the retired postes out: so
  // do they (`in_parc`), or a retired poste's frozen badge would show under
  // a card that does not count it.
  const [s, av, wuBehind, th] = await Promise.allSettled([
    getOverview(),
    listMachines({ status: 'outdated', page_size: 5, in_parc: true }),
    listMachines({ wu_status: 'pending', page_size: 5, in_parc: true }),
    // The sample of threats is a side list: its failure leaves the counters
    // and the other list their fresh values — and is reported all the same.
    canReadThreats.value
      ? listThreats({ status: 'active', page_size: 5, in_parc: true })
      : Promise.resolve(null),
  ]);
  // Each list's « loaded » flag follows its *last* load, not its first: after
  // an outage, « Tous les postes sont à jour » left over from the morning
  // would be a claim about a parc nobody could read (audit U07).
  if (av.status === 'fulfilled' && wuBehind.status === 'fulfilled') {
    outdated.value = mergeOutdated(av.value.items, wuBehind.value.items);
    outdatedLoaded.value = true;
  } else {
    outdatedLoaded.value = false;
  }
  if (th.status === 'fulfilled' && th.value) {
    threats.value = th.value.items;
    threatsLoaded.value = true;
  } else {
    threatsLoaded.value = false;
  }
  if (s.status === 'rejected') throw s.reason;
  stats.value = s.value;
  // The fiche and the list colour their disks by the same threshold.
  rememberFleetThresholds(s.value);
  if (av.status === 'rejected') throw av.reason;
  if (wuBehind.status === 'rejected') throw wuBehind.reason;
  // Same rule for the threats as for the other list: the rows left on screen
  // are those of an earlier load, so this refresh did not succeed — « Actualisé
  // à » stays where it was, and a requested reload says it failed.
  if (th.status === 'rejected') throw th.reason;
}

// The dashboard is a wall screen as much as a page: left open, it has to keep
// telling the truth without anyone pressing anything.
const { lastRefreshedAt, lastError, refreshNow } = useAutoRefresh(fetchAll);

/**
 * The button's own load, spinner and all. The automatic ones deliberately do
 * *not* raise `loading`: a spinner blinking on its own every ninety seconds
 * reads as a page that is struggling rather than as one that is current.
 */
async function reload() {
  loading.value = true;
  try {
    await refreshNow();
  } finally {
    loading.value = false;
  }
  // The banner covers a page that never loaded; over figures already shown, a
  // requested reload that fails says so rather than leaving them to pass for
  // fresh ones (audit T20). The automatic refresh stays quiet.
  const error = lastError.value;
  if (error && lastRefreshedAt.value) {
    notify($q, () => ({
      type: 'negative',
      message: apiErrorMessage(error, t('dashboard.refreshFailed')),
      caption: t('dashboard.refreshFailedCaption'),
    }));
  }
}

const lastRefreshLabel = computed(() =>
  lastRefreshedAt.value ? lastRefreshedAt.value.toLocaleTimeString(intlTag()) : '',
);

const autoRefreshHint = computed(() =>
  t('dashboard.autoRefresh', { seconds: Math.round(AUTO_REFRESH_INTERVAL_MS / 1000) }),
);

onMounted(reload);
</script>

<style scoped>
/* A threat name is one word, sometimes of sixty characters: it breaks
   anywhere rather than widening the page on a phone. */
.threat-name {
  overflow-wrap: anywhere;
}
/* A coloured edge on a priority card that has something in it: the row is
   read from across the room, and a zero must stay quiet. */
.priority-card {
  border-left-width: 4px;
}
.priority-card--warning {
  border-left-color: var(--q-warning);
}
.priority-card--negative {
  border-left-color: var(--q-negative);
}
</style>
