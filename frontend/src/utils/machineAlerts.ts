import type { MachineTab } from 'src/components/machine/types';
import { t } from 'src/i18n';
import type { MachineDetail } from 'src/services/machines';
import { isAgentOutdated } from './agentVersion';
import { diskThresholds, freePercent, sizeLabel } from './format';

/**
 * What is wrong with a poste, in the order it should be read.
 *
 * The fiche used to open on eleven cards of facts and leave the reader to find
 * the one that mattered. This turns the facts into findings: each rule below
 * is a question an administrator asks on opening a fiche — « est-il protégé ?
 * a-t-il de la place ? est-il à jour ? » — answered only when the answer is
 * bad. A poste with nothing to report gets an empty list, which the card
 * renders as one green line.
 *
 * Pure, so it is testable: everything time-dependent takes `now`. The texts are
 * worded in the language shown when it is called (`machine.alerts.*`): call it
 * at render time — the status card does, from a computed.
 */
export interface MachineAlert {
  key: string;
  /** negative = act now; warning = soon; info = worth knowing. */
  level: 'negative' | 'warning' | 'info';
  icon: string;
  text: string;
  /** Where the detail behind the finding lives. */
  tab: MachineTab;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Free space below which Windows Update stops staging cumulative updates —
 * the default of the parc's setting, which `machineAlerts` takes when given.
 */
export const DISK_CRITICAL_PERCENT = 10;
export const DISK_WARNING_PERCENT = 20;
/** A full scan older than this is a poste nothing has looked at in depth. */
export const FULL_SCAN_MAX_DAYS = 30;
/** A Windows Update search older than this is a poste that stopped checking. */
export const WU_SEARCH_MAX_DAYS = 30;
/** No heartbeat for this long, and the poste is worth a question. */
export const CONTACT_MAX_DAYS = 7;
/** An inventory older than this on a poste seen today is an agent not collecting. */
export const INVENTORY_MAX_DAYS = 3;

function ageDays(value: string | null | undefined, now: Date): number | null {
  if (!value) return null;
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return null;
  return Math.floor((now.getTime() - then) / DAY_MS);
}

export function machineAlerts(
  m: MachineDetail,
  activeThreats: number,
  now: Date = new Date(),
  lowDiskPercent?: number,
): MachineAlert[] {
  const alerts: MachineAlert[] = [];

  // --- Threats: the one finding that outranks everything else.
  if (activeThreats > 0) {
    alerts.push({
      key: 'threats',
      level: 'negative',
      icon: 'coronavirus',
      text: t('machine.alerts.threats', { count: activeThreats }, activeThreats),
      tab: 'antivirus',
    });
  }

  // --- Protection.
  if (m.av_product_name === '') {
    alerts.push({
      key: 'no-antivirus',
      level: 'negative',
      icon: 'gpp_bad',
      text: t('machine.alerts.noAntivirus'),
      tab: 'antivirus',
    });
  } else if (m.is_up_to_date === false) {
    alerts.push({
      key: 'av-outdated',
      level: 'negative',
      icon: 'gpp_maybe',
      text: antivirusOutdatedText(m),
      tab: 'antivirus',
    });
  } else if (m.is_up_to_date == null) {
    alerts.push({
      key: 'av-unknown',
      level: 'warning',
      icon: 'help',
      text: t('machine.alerts.avUnknown'),
      tab: 'antivirus',
    });
  }

  const fullScanAge = ageDays(m.last_full_scan, now);
  if (
    m.av_product_is_defender !== false &&
    (fullScanAge === null || fullScanAge > FULL_SCAN_MAX_DAYS)
  ) {
    alerts.push({
      key: 'full-scan',
      level: 'warning',
      icon: 'search_off',
      text:
        fullScanAge === null
          ? t('machine.alerts.fullScanNone')
          : t('machine.alerts.fullScanOld', { days: fullScanAge }),
      tab: 'antivirus',
    });
  }

  // --- Disk: a full C: is the first cause of a poste that stops patching.
  const free = freePercent(m.system_volume_total_mb, m.system_volume_free_mb);
  const disk = diskThresholds(lowDiskPercent);
  if (free != null && free < disk.warning) {
    const critical = free < disk.critical;
    alerts.push({
      key: 'disk',
      level: critical ? 'negative' : 'warning',
      icon: 'storage',
      text: t(critical ? 'machine.alerts.diskCritical' : 'machine.alerts.diskWarning', {
        size: sizeLabel(m.system_volume_free_mb),
        percent: free,
      }),
      tab: 'hardware',
    });
  }
  for (const d of m.disks) {
    if (d.health_status && d.health_status !== 'Healthy') {
      alerts.push({
        key: `disk-health-${d.id}`,
        level: 'negative',
        icon: 'sd_card_alert',
        text: t('machine.alerts.diskHealth', {
          name: d.model || d.device_id,
          status: d.health_status,
        }),
        tab: 'hardware',
      });
    }
  }

  // --- Windows Update.
  if (m.wu_pending_count != null && m.wu_pending_count > 0) {
    const critical = m.pending_updates.filter((u) => u.severity === 'critical').length;
    const n = m.wu_pending_count;
    alerts.push({
      key: 'wu-pending',
      level: critical > 0 ? 'negative' : 'warning',
      icon: 'system_update',
      text:
        t('machine.alerts.wuPending', { count: n }, n) +
        (critical > 0 ? t('machine.alerts.wuCritical', { count: critical }, critical) : ''),
      tab: 'windows_update',
    });
  }
  if (m.wu_reboot_required) {
    alerts.push({
      key: 'reboot',
      level: 'warning',
      icon: 'restart_alt',
      text: t('machine.alerts.reboot'),
      tab: 'windows_update',
    });
  }
  const searchAge = ageDays(m.wu_last_search, now);
  if (m.wu_pending_count == null) {
    alerts.push({
      key: 'wu-unknown',
      level: 'warning',
      icon: 'help',
      text: t('machine.alerts.wuUnknown'),
      tab: 'windows_update',
    });
  } else if (searchAge !== null && searchAge > WU_SEARCH_MAX_DAYS) {
    alerts.push({
      key: 'wu-stale',
      level: 'warning',
      icon: 'update_disabled',
      text: t('machine.alerts.wuStale', { days: searchAge }),
      tab: 'windows_update',
    });
  }

  // --- The agent itself. Info and not a warning: an old agent still reports,
  // it just reports less — and the finding is what names the postes a
  // deployment has not reached.
  if (isAgentOutdated(m.agent_version, m.agent_latest_version)) {
    alerts.push({
      key: 'agent-outdated',
      level: 'info',
      icon: 'system_update_alt',
      text: t('machine.alerts.agentOutdated', {
        version: m.agent_version,
        latest: m.agent_latest_version,
      }),
      tab: 'identity',
    });
  }

  // --- Presence and freshness.
  const contactAge = ageDays(m.last_seen, now);
  if (contactAge !== null && contactAge > CONTACT_MAX_DAYS) {
    alerts.push({
      key: 'contact',
      level: 'warning',
      icon: 'power_off',
      text: t('machine.alerts.contact', { days: contactAge }),
      tab: 'identity',
    });
  }
  const inventoryAge = ageDays(m.inventory_last_seen, now);
  if (m.inventory_last_seen == null) {
    alerts.push({
      key: 'inventory-none',
      level: 'info',
      icon: 'inventory',
      text: t('machine.alerts.inventoryNone'),
      tab: 'hardware',
    });
  } else if (
    inventoryAge !== null &&
    inventoryAge > INVENTORY_MAX_DAYS &&
    contactAge !== null &&
    contactAge <= 1
  ) {
    alerts.push({
      key: 'inventory-stale',
      level: 'info',
      icon: 'inventory',
      text: t('machine.alerts.inventoryStale', { days: inventoryAge }, inventoryAge),
      tab: 'hardware',
    });
  }

  // --- Encryption: worth knowing, not an alarm — the parc may not use BitLocker.
  const system = m.volumes.find((v) => v.is_system);
  if (system?.encryption_status === 'FullyDecrypted') {
    alerts.push({
      key: 'unencrypted',
      level: 'info',
      icon: 'lock_open',
      text: t('machine.alerts.unencrypted'),
      tab: 'hardware',
    });
  }

  return alerts;
}

/** Why the antivirus reads as outdated — the sentence the badge compresses. */
function antivirusOutdatedText(m: MachineDetail): string {
  if (m.av_product_is_defender === false) {
    if (m.av_product_enabled === false) {
      return t('machine.alerts.productDisabled', { product: m.av_product_name });
    }
    if (m.av_product_signatures_up_to_date === false) {
      return t('machine.alerts.productSignatures', { product: m.av_product_name });
    }
    return t('machine.alerts.productUnconfirmed', { product: m.av_product_name });
  }
  if (m.av_enabled === false || m.rtp_enabled === false) {
    return t('machine.alerts.defenderDisabled');
  }
  if (m.signature_age_days != null) {
    return t(
      'machine.alerts.defenderSignatures',
      { days: m.signature_age_days },
      m.signature_age_days,
    );
  }
  return t('machine.alerts.avOutdated');
}
