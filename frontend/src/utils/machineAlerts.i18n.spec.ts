import { afterEach, describe, expect, it } from 'vitest';
import { setLocale } from 'src/i18n';
import { machineDetail } from 'src/test/fixtures';
import { agentVersionLabel } from './agentVersion';
import { machineAlerts } from './machineAlerts';

/**
 * The findings of a computer's page and its agent's standing, in both
 * languages (plan console bilingue, lot A). The French is pinned by
 * `machineAlerts.spec.ts`; here, the plurals the extraction moved into the
 * catalogue, and the English.
 */

const NOW = new Date('2026-06-15T12:00:00Z');
const daysAgo = (n: number) => new Date(NOW.getTime() - n * 86_400_000).toISOString();

/** A computer with something to say on every line of the status card. */
function troubled() {
  return machineDetail({
    av_product_name: 'ESET Endpoint Security',
    av_product_is_defender: false,
    av_product_enabled: false,
    is_up_to_date: false,
    last_full_scan: null,
    system_volume_total_mb: 100_000,
    system_volume_free_mb: 5_000,
    disks: [
      {
        id: 'd1',
        device_id: 'PhysicalDrive0',
        model: 'Samsung SSD',
        media_type: 'SSD',
        bus_type: 'NVMe',
        size_mb: 500_000,
        serial: null,
        health_status: 'Warning',
      },
    ] as never,
    wu_pending_count: 3,
    pending_updates: [{ severity: 'critical' }, { severity: 'important' }] as never,
    wu_reboot_required: true,
    wu_last_search: daysAgo(40),
    agent_version: '0.4.1',
    agent_latest_version: '0.5.0',
    last_seen: daysAgo(10),
    inventory_last_seen: null,
    volumes: [{ is_system: true, encryption_status: 'FullyDecrypted' }] as never,
  });
}

afterEach(() => setLocale('fr'));

describe('machineAlerts — French plurals from the catalogue', () => {
  const text = (n: number, critical: number) =>
    machineAlerts(
      machineDetail({
        wu_pending_count: n,
        pending_updates: Array.from({ length: critical }, () => ({
          severity: 'critical',
        })) as never,
      }),
      n,
      NOW,
    ).map((a) => a.text);

  it('says one threat and one update in the singular', () => {
    expect(text(1, 1)).toEqual(
      expect.arrayContaining([
        "1 menace active — Defender n'a pas traité la détection",
        '1 mise à jour Windows en attente, dont 1 critique',
      ]),
    );
  });

  it('says several in the plural', () => {
    expect(text(4, 2)).toEqual(
      expect.arrayContaining([
        "4 menaces actives — Defender n'a pas traité les détections",
        '4 mises à jour Windows en attente, dont 2 critiques',
      ]),
    );
  });
});

describe('machineAlerts — English', () => {
  it('words every finding in English', () => {
    setLocale('en');
    const texts = machineAlerts(troubled(), 2, NOW).map((a) => a.text);

    expect(texts).toEqual([
      '2 active threats — Defender has not dealt with the detections',
      'ESET Endpoint Security: protection disabled',
      // No full-scan finding: Defender is not the antivirus here.
      expect.stringMatching(/^System disk almost full: .+ free \(5%\)$/),
      'Disk Samsung SSD in state “Warning”',
      '3 Windows updates pending, including 1 critical',
      'Restart required to finish an installation',
      'No search for updates for 40 days',
      'Agent 0.4.1 outdated: the fleet reference is 0.5.0',
      'No contact for 10 days',
      'No hardware inventory reported for this computer',
      'System disk not encrypted (BitLocker)',
    ]);
    for (const text of texts) expect(text).not.toMatch(/[éèàùç«»]/);
  });

  it('says one threat in the singular', () => {
    setLocale('en');
    const texts = machineAlerts(machineDetail(), 1, NOW).map((a) => a.text);
    expect(texts).toContain('1 active threat — Defender has not dealt with the detection');
  });

  it('follows the language at each call', () => {
    const m = machineDetail({ wu_reboot_required: true });
    expect(machineAlerts(m, 0, NOW).map((a) => a.text)).toContain(
      'Redémarrage requis pour terminer une installation',
    );
    setLocale('en');
    expect(machineAlerts(m, 0, NOW).map((a) => a.text)).toContain(
      'Restart required to finish an installation',
    );
  });
});

describe('agentVersionLabel', () => {
  it('says where the version stands, in French', () => {
    expect(agentVersionLabel('0.4.1', '0.5.0')).toBe('0.4.1 — obsolète (référence 0.5.0)');
    expect(agentVersionLabel('0.5.0', '0.5.0')).toBe('0.5.0 — à jour');
  });

  it('and in English', () => {
    setLocale('en');
    expect(agentVersionLabel('0.4.1', '0.5.0')).toBe('0.4.1 — outdated (reference 0.5.0)');
    expect(agentVersionLabel('0.5.0', '0.5.0')).toBe('0.5.0 — up to date');
    expect(agentVersionLabel(null, '0.5.0')).toBe('—');
  });
});
