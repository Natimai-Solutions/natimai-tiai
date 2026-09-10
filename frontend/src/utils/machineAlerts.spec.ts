import { describe, expect, it } from 'vitest';
import type { MachineDetail } from 'src/services/machines';
import { machineAlerts } from './machineAlerts';

const NOW = new Date('2026-09-04T10:00:00Z');

function daysAgo(days: number): string {
  return new Date(NOW.getTime() - days * 24 * 60 * 60 * 1000).toISOString();
}

/** A poste with nothing to report: every rule below flips one thing on it. */
function healthy(overrides: Partial<MachineDetail> = {}): MachineDetail {
  return {
    id: 'm1',
    machine_uuid: 'uuid-1',
    hostname: 'PC-01',
    domain: 'CORP',
    location: null,
    room_id: null,
    room_name: null,
    building_id: null,
    building_name: null,
    room_location: null,
    location_mismatch: false,
    check_open: false,
    check_assigned_to: null,
    open_check: null,
    ad_distinguished_name: null,
    ad_ou: null,
    ad_ou_dn: null,
    ad_location: null,
    ip_address: '10.0.0.1',
    os_version: 'Windows 11',
    agent_version: '0.3.0',
    is_up_to_date: true,
    needs_verification: false,
    signature_version: '1.2.3',
    av_product_name: 'Windows Defender',
    av_product_enabled: true,
    av_product_signatures_up_to_date: true,
    av_product_is_defender: true,
    session_user_present: true,
    session_username: 'alice',
    wu_pending_count: 0,
    wu_reboot_required: false,
    hw_model: 'OptiPlex',
    ram_total_mb: 16289,
    system_volume_total_mb: 500_000,
    system_volume_free_mb: 250_000,
    last_seen: daysAgo(0),
    is_online: true,
    mac_address: null,
    ip_prefix_length: 24,
    rtp_enabled: true,
    av_enabled: true,
    signature_last_updated: daysAgo(0),
    signature_age_days: 0,
    last_quick_scan: daysAgo(1),
    last_full_scan: daysAgo(5),
    running_mode: 'Normal',
    session_state: 'active',
    session_is_remote: false,
    wu_last_search: daysAgo(1),
    wu_last_install: daysAgo(3),
    pending_updates: [],
    machine_guid: null,
    smbios_uuid: null,
    tpm_ek_hash: null,
    token_revoked: false,
    first_seen: daysAgo(100),
    created_at: daysAgo(100),
    updated_at: daysAgo(0),
    hw_manufacturer: 'Dell',
    hw_serial: null,
    hw_chassis_type: 'desktop',
    hw_is_virtual: false,
    hw_hypervisor: null,
    mb_manufacturer: null,
    mb_model: null,
    mb_serial: null,
    bios_vendor: null,
    bios_version: null,
    bios_date: null,
    secure_boot: true,
    tpm_version: '2.0',
    cpu_model: 'i7',
    cpu_manufacturer: null,
    cpu_cores: 8,
    cpu_threads: 16,
    cpu_speed_mhz: null,
    cpu_count: 1,
    ram_slots_total: 2,
    ram_slots_used: 2,
    os_architecture: '64-bit',
    os_install_date: null,
    last_boot_time: null,
    inventory_last_seen: daysAgo(0),
    memory_modules: [],
    disks: [],
    volumes: [
      {
        id: 1,
        letter: 'C:',
        label: null,
        filesystem: 'NTFS',
        total_mb: 500_000,
        free_mb: 250_000,
        is_system: true,
        encryption_status: 'FullyEncrypted',
      },
    ],
    nics: [],
    gpus: [],
    software: [],
    agent_latest_version: '0.3.0',
    ...overrides,
  };
}

const keys = (m: MachineDetail, threats = 0) => machineAlerts(m, threats, NOW).map((a) => a.key);

describe('machineAlerts', () => {
  it('reports nothing on a healthy poste', () => {
    expect(keys(healthy())).toEqual([]);
  });

  it('puts active threats first, as the finding that outranks the rest', () => {
    const alerts = machineAlerts(healthy({ is_up_to_date: false }), 2, NOW);
    expect(alerts[0]?.key).toBe('threats');
    expect(alerts[0]?.level).toBe('negative');
    expect(alerts[0]?.text).toContain('2 menaces actives');
    expect(alerts[0]?.tab).toBe('antivirus');
  });

  it('tells no antivirus apart from an outdated one and an unknown one', () => {
    expect(keys(healthy({ av_product_name: '' }))).toContain('no-antivirus');
    expect(keys(healthy({ is_up_to_date: false }))).toContain('av-outdated');
    expect(keys(healthy({ is_up_to_date: null }))).toContain('av-unknown');
  });

  it('explains why the antivirus is outdated', () => {
    const stale = machineAlerts(healthy({ is_up_to_date: false, signature_age_days: 12 }), 0, NOW);
    expect(stale.find((a) => a.key === 'av-outdated')?.text).toContain('12 jours');

    const off = machineAlerts(
      healthy({
        is_up_to_date: false,
        av_product_is_defender: false,
        av_product_name: 'ESET',
        av_product_enabled: false,
      }),
      0,
      NOW,
    );
    expect(off.find((a) => a.key === 'av-outdated')?.text).toBe('ESET : protection désactivée');
  });

  it('flags a full scan that is missing or older than a month, on Defender only', () => {
    expect(keys(healthy({ last_full_scan: null }))).toContain('full-scan');
    expect(keys(healthy({ last_full_scan: daysAgo(45) }))).toContain('full-scan');
    expect(keys(healthy({ last_full_scan: daysAgo(10) }))).not.toContain('full-scan');
    // A third-party product runs its own scans Defender knows nothing about.
    expect(
      keys(
        healthy({ last_full_scan: null, av_product_is_defender: false, av_product_name: 'ESET' }),
      ),
    ).not.toContain('full-scan');
  });

  it('grades the system disk by percentage, red below ten', () => {
    const tight = machineAlerts(healthy({ system_volume_free_mb: 75_000 }), 0, NOW);
    expect(tight.find((a) => a.key === 'disk')?.level).toBe('warning');
    const full = machineAlerts(healthy({ system_volume_free_mb: 20_000 }), 0, NOW);
    expect(full.find((a) => a.key === 'disk')?.level).toBe('negative');
    expect(full.find((a) => a.key === 'disk')?.text).toContain('4 %');
    // Never reported is not a full disk.
    expect(
      keys(healthy({ system_volume_total_mb: null, system_volume_free_mb: null })),
    ).not.toContain('disk');
  });

  it('flags an unhealthy physical disk by name', () => {
    const m = healthy({
      disks: [
        {
          id: 7,
          device_id: '\\\\.\\PHYSICALDRIVE0',
          model: 'SAMSUNG 870',
          serial: null,
          firmware: null,
          media_type: 'SSD',
          bus_type: null,
          size_mb: 500_000,
          health_status: 'Warning',
          is_removable: false,
        },
      ],
    });
    const alert = machineAlerts(m, 0, NOW).find((a) => a.key === 'disk-health-7');
    expect(alert?.level).toBe('negative');
    expect(alert?.text).toContain('SAMSUNG 870');
  });

  it('counts pending updates and their critical ones', () => {
    const m = healthy({
      wu_pending_count: 3,
      pending_updates: [
        { severity: 'critical' },
        { severity: 'important' },
        { severity: null },
      ] as MachineDetail['pending_updates'],
    });
    const alert = machineAlerts(m, 0, NOW).find((a) => a.key === 'wu-pending');
    expect(alert?.level).toBe('negative');
    expect(alert?.text).toBe('3 mises à jour Windows en attente, dont 1 critique');

    const mild = machineAlerts(healthy({ wu_pending_count: 1 }), 0, NOW);
    expect(mild.find((a) => a.key === 'wu-pending')?.level).toBe('warning');
    expect(mild.find((a) => a.key === 'wu-pending')?.text).toBe('1 mise à jour Windows en attente');
  });

  it('reports a reboot, a never-reported Windows Update and a stale search', () => {
    expect(keys(healthy({ wu_reboot_required: true }))).toContain('reboot');
    expect(keys(healthy({ wu_pending_count: null }))).toContain('wu-unknown');
    expect(keys(healthy({ wu_last_search: daysAgo(40) }))).toContain('wu-stale');
    expect(keys(healthy({ wu_last_search: daysAgo(3) }))).not.toContain('wu-stale');
  });

  it('notes a poste out of contact for more than a week', () => {
    expect(keys(healthy({ last_seen: daysAgo(9), inventory_last_seen: daysAgo(9) }))).toContain(
      'contact',
    );
    expect(keys(healthy({ last_seen: daysAgo(2), inventory_last_seen: daysAgo(2) }))).not.toContain(
      'contact',
    );
  });

  it('notes a missing or stale inventory only on a poste that is around', () => {
    expect(keys(healthy({ inventory_last_seen: null }))).toContain('inventory-none');
    expect(keys(healthy({ inventory_last_seen: daysAgo(10) }))).toContain('inventory-stale');
    // Off for a week: the stale inventory is the least of it, and the contact
    // alert already says so.
    expect(
      keys(healthy({ last_seen: daysAgo(10), inventory_last_seen: daysAgo(10) })),
    ).not.toContain('inventory-stale');
  });

  it('mentions an unencrypted system volume as information, not alarm', () => {
    const m = healthy({
      volumes: [
        {
          id: 1,
          letter: 'C:',
          label: null,
          filesystem: 'NTFS',
          total_mb: 500_000,
          free_mb: 250_000,
          is_system: true,
          encryption_status: 'FullyDecrypted',
        },
      ],
    });
    const alert = machineAlerts(m, 0, NOW).find((a) => a.key === 'unencrypted');
    expect(alert?.level).toBe('info');
    expect(alert?.tab).toBe('hardware');
    // Not read is not "not encrypted".
    expect(keys(healthy({ volumes: [] }))).not.toContain('unencrypted');
  });
});

describe('machineAlerts — agent version', () => {
  it('names a poste the deployment missed', () => {
    const alerts = machineAlerts(healthy({ agent_latest_version: '0.5.0' }), 0, NOW);
    const agent = alerts.find((a) => a.key === 'agent-outdated');
    expect(agent?.level).toBe('info');
    expect(agent?.text).toContain('0.3.0');
    expect(agent?.text).toContain('0.5.0');
  });

  it('says nothing when the version is the reference, or unknown', () => {
    expect(keys(healthy())).toEqual([]);
    expect(keys(healthy({ agent_version: null, agent_latest_version: '0.5.0' }))).toEqual([]);
    expect(keys(healthy({ agent_latest_version: null }))).toEqual([]);
  });
});
