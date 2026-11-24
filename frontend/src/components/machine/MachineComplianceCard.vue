<template>
  <div class="row q-col-gutter-md">
    <!-- The closed list, « 7 sur 9 »: what to fix, not a score. -->
    <div class="col-12 col-md-6">
      <q-card flat bordered class="full-height">
        <q-card-section class="row items-center no-wrap">
          <div class="col">
            <div class="text-subtitle1">{{ t('compliance.card.title') }}</div>
            <div class="text-caption text-muted">{{ t('compliance.card.caption') }}</div>
          </div>
          <q-badge
            v-if="summary.total"
            data-test="compliance-summary"
            :color="summary.passed === summary.total ? 'positive' : 'negative'"
            class="text-body2 q-px-sm q-py-xs"
          >
            {{ t('compliance.card.summary', summary) }}
          </q-badge>
        </q-card-section>
        <q-separator />
        <div v-if="!checks.length" class="text-muted q-pa-md">{{ t('compliance.card.none') }}</div>
        <q-list v-else dense separator>
          <q-item v-for="c in checks" :key="c.check" :data-test="`check-${c.check}`">
            <q-item-section avatar>
              <q-icon :name="stateIcon(c.state)" :color="stateColor(c.state)" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ complianceCheckLabel(c.check) }}</q-item-label>
              <q-item-label v-if="detailText(c)" caption>{{ detailText(c) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-badge :color="stateColor(c.state)" outline>
                {{ t(`compliance.state.${c.state}`) }}
              </q-badge>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </div>

    <div class="col-12 col-md-6 column q-gutter-y-md">
      <q-card v-if="machine.local_admins" flat bordered>
        <q-card-section>
          <div class="text-subtitle1">{{ t('compliance.admins.title') }}</div>
          <div class="text-caption text-muted">{{ t('compliance.admins.hint') }}</div>
        </q-card-section>
        <q-separator />
        <q-list dense>
          <q-item v-for="a in machine.local_admins" :key="a.name">
            <q-item-section>{{ a.name }}</q-item-section>
            <q-item-section v-if="a.sid" side class="text-caption">{{ a.sid }}</q-item-section>
          </q-item>
        </q-list>
      </q-card>

      <q-card v-if="machine.winget_reported_at" flat bordered>
        <q-card-section>
          <div class="text-subtitle1">{{ t('compliance.winget.title') }}</div>
          <div class="text-caption text-muted">
            {{ t('compliance.winget.hint', { date: formatDateTime(machine.winget_reported_at) }) }}
          </div>
        </q-card-section>
        <q-separator />
        <div v-if="!packages.length" class="text-muted q-pa-md">
          {{ t('compliance.winget.none') }}
        </div>
        <q-markup-table v-else flat dense separator="horizontal">
          <thead>
            <tr>
              <th class="text-left">{{ t('compliance.winget.columns.name') }}</th>
              <th class="text-left">{{ t('compliance.winget.columns.version') }}</th>
              <th class="text-left">{{ t('compliance.winget.columns.available') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in packages" :key="p.winget_id" :data-test="`winget-${p.winget_id}`">
              <td>
                <div>{{ p.name ?? p.winget_id }}</div>
                <div class="text-caption text-muted">{{ p.winget_id }}</div>
              </td>
              <td>{{ p.version ?? '—' }}</td>
              <td>
                <q-badge v-if="p.available" color="orange-8">
                  {{ t('compliance.winget.available', { version: p.available }) }}
                </q-badge>
                <span v-else class="text-ok">{{ t('compliance.winget.upToDate') }}</span>
              </td>
            </tr>
          </tbody>
        </q-markup-table>
      </q-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from 'src/i18n';
import { complianceCheckLabel } from 'src/services/compliance';
import type { ComplianceCheckResult, MachineDetail } from 'src/services/machines';
import { formatDate, formatDateTime } from 'src/utils/format';

const props = defineProps<{ machine: MachineDetail }>();

const checks = computed(() => props.machine.compliance ?? []);
const packages = computed(() =>
  [...(props.machine.winget_packages ?? [])].sort(
    (a, b) => Number(!!b.available) - Number(!!a.available),
  ),
);

/** « N sur M »: the checks known, the passed among them — the server's count. */
const summary = computed(() => {
  const known = checks.value.filter((c) => c.state === 'pass' || c.state === 'fail');
  return {
    passed: known.filter((c) => c.state === 'pass').length,
    total: known.length,
  };
});

function stateIcon(state: string): string {
  if (state === 'pass') return 'check_circle';
  if (state === 'fail') return 'cancel';
  if (state === 'not_applicable') return 'remove_circle_outline';
  return 'help_outline';
}

function stateColor(state: string): string {
  if (state === 'pass') return 'positive';
  if (state === 'fail') return 'negative';
  return 'grey-7';
}

function str(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function list(value: unknown): string {
  return Array.isArray(value) ? value.map(str).join(', ') : '';
}

/** The values behind a check's verdict, worded. */
function detailText(c: ComplianceCheckResult): string {
  const d = c.detail ?? {};
  if (c.state === 'not_applicable') return t('compliance.detail.notApplicable');
  switch (c.check) {
    case 'encryption':
      return d.status ? t('compliance.detail.encryption', { status: str(d.status) }) : '';
    case 'tpm':
      if (d.absent) return t('compliance.detail.tpmAbsent');
      return d.version ? t('compliance.detail.tpm', { version: str(d.version) }) : '';
    case 'patches':
      return d.count
        ? t('compliance.detail.patches', {
            count: str(d.count),
            days: str(d.grace_days),
            updates: list(d.updates),
          })
        : '';
    case 'reboot':
      return d.since ? t('compliance.detail.reboot', { since: formatDateTime(str(d.since)) }) : '';
    case 'os_supported':
      return d.end_of_support
        ? t('compliance.detail.os_supported', { date: formatDate(str(d.end_of_support)) })
        : '';
    case 'agent_current':
      return d.version ? t('compliance.detail.agent_current', { version: str(d.version) }) : '';
    case 'firewall':
      return Array.isArray(d.profiles)
        ? t('compliance.detail.firewall', {
            profiles: d.profiles
              .map((p) =>
                ['domain', 'private', 'public'].includes(str(p))
                  ? t(`compliance.profiles.${str(p)}`)
                  : str(p),
              )
              .join(', '),
          })
        : '';
    case 'local_admins':
      return d.names ? t('compliance.detail.local_admins', { names: list(d.names) }) : '';
    default:
      return '';
  }
}
</script>
