import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('src/services/machines', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/machines')>()),
  getMachineUsage: vi.fn(),
  listMachines: vi.fn(),
  mergeMachines: vi.fn(),
}));

import { setLocale } from 'src/i18n';
import machineCatalogue from 'src/i18n/messages/machine';
import {
  getMachineUsage,
  listMachines,
  type DuplicateCandidate,
  type MachineDetail,
} from 'src/services/machines';
import { machineDetail } from 'src/test/fixtures';
import MachineAntivirusCard from './MachineAntivirusCard.vue';
import MachineDefenderCard from './MachineDefenderCard.vue';
import MachineGpuCard from './MachineGpuCard.vue';
import MachineHardwareCard from './MachineHardwareCard.vue';
import MachineIdentityCard from './MachineIdentityCard.vue';
import MachineMemoryCard from './MachineMemoryCard.vue';
import MachineMergeDialog from './MachineMergeDialog.vue';
import MachineNetworkCard from './MachineNetworkCard.vue';
import MachinePendingUpdatesCard from './MachinePendingUpdatesCard.vue';
import MachineSoftwareCard from './MachineSoftwareCard.vue';
import MachineStatusCard from './MachineStatusCard.vue';
import MachineStorageCard from './MachineStorageCard.vue';
import MachineThreatsCard from './MachineThreatsCard.vue';
import MachineUsageCard from './MachineUsageCard.vue';
import MachineWindowsUpdateCard from './MachineWindowsUpdateCard.vue';

/**
 * The cards of a computer's page in English (plan console bilingue, lot A).
 * The values some rows show come from `utils/format.ts`, translated by its own
 * batch: what is asserted here is this batch's wording — every label, caption
 * and empty state — and that none of its French is left.
 */

const ago = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString();

function leaves(tree: object): string[] {
  return Object.values(tree).flatMap((v) => (typeof v === 'string' ? [v] : leaves(v as object)));
}

/**
 * Words this batch's catalogue shares with the values of `utils/format.ts`
 * (« Non relevé », « À jour »): those values are another batch's to translate.
 */
const FORMAT_VALUES = new Set(['Non relevé', 'À jour']);

/** This batch's French, as the fragments between placeholders English does not share. */
const FRENCH = (() => {
  const fragments = (texts: string[]) =>
    texts.flatMap((s) => s.split(/\{[^}]*\}| \| /).map((f) => f.trim()));
  const english = new Set(fragments(leaves(machineCatalogue.en)));
  return [...new Set(fragments(leaves(machineCatalogue.fr)))].filter(
    // Several words, or an accent: a single plain word may sit inside English.
    (f) =>
      f.length >= 6 &&
      (f.includes(' ') || /[^\x00-\x7f]/.test(f)) &&
      !english.has(f) &&
      !FORMAT_VALUES.has(f),
  );
})();

function expectNoFrench(text: string) {
  for (const french of FRENCH) expect(text, french).not.toContain(french);
}

/** A fully inventoried computer, its data accent-free. */
function computer(overrides: Partial<MachineDetail> = {}): MachineDetail {
  return machineDetail({
    hostname: 'PC-LAB-01',
    room_name: 'Lab 1',
    room_location: 'Building B',
    location: 'Building A',
    location_mismatch: true,
    building_name: 'Main',
    ad_ou: 'Labs',
    mac_address: 'AA:BB:CC:DD:EE:01',
    hw_is_virtual: true,
    gpus: [
      {
        id: 1,
        name: 'Intel UHD 630',
        chipset: null,
        memory_mb: 1024,
        driver_version: '31.0.101',
        driver_date: '2025-01-10',
        resolution: '1920x1080',
      },
    ],
    memory_modules: [
      {
        id: 1,
        slot: 'DIMM A1',
        capacity_mb: 8192,
        type: null,
        speed_mhz: 3200,
        manufacturer: 'Kingston',
        serial: 'K123',
        form_factor: null,
      },
    ],
    nics: [
      {
        id: 1,
        name: 'Ethernet',
        mac: 'AA:BB:CC:DD:EE:01',
        type: 'ethernet',
        speed_mbps: 1000,
        is_up: true,
        is_virtual: true,
        ip_address: '10.0.0.1',
        ip_prefix_length: 24,
        is_dhcp: false,
        gateway: '10.0.0.254',
        driver_version: null,
      },
    ],
    disks: [
      {
        id: 1,
        device_id: 'PhysicalDrive0',
        model: 'Samsung SSD',
        serial: 'S123',
        firmware: null,
        media_type: 'SSD',
        bus_type: 'NVMe',
        size_mb: 500_000,
        health_status: 'Healthy',
        is_removable: false,
      },
    ],
    pending_updates: [
      {
        id: 1,
        update_id: 'u1',
        kb: 'KB5030000',
        title: 'Cumulative update',
        severity: 'critical',
        type: 'software',
        categories: null,
        is_downloaded: false,
        size_mb: 400,
        first_seen: ago(3),
        last_seen: ago(0),
      },
    ],
    software: [
      {
        software_id: 1,
        name: 'Firefox',
        version: '120.0',
        publisher: 'Mozilla',
        install_date: '2025-02-01',
        arch: 'x64',
        source: null,
        install_location: null,
        first_seen: ago(10),
      },
    ],
    software_truncated: true,
    wu_reboot_required: true,
    ...overrides,
  });
}

afterEach(() => setLocale('fr'));

describe('the computer cards — English', () => {
  it('Identity, Network, Hardware, Memory, Graphics cards', () => {
    setLocale('en');
    const m = computer();
    const text = [
      mount(MachineIdentityCard, { props: { machine: m } }),
      mount(MachineNetworkCard, { props: { machine: m } }),
      mount(MachineHardwareCard, { props: { machine: m } }),
      mount(MachineMemoryCard, { props: { machine: m } }),
      mount(MachineGpuCard, { props: { machine: m } }),
    ]
      .map((w) => w.text())
      .join('\n');

    for (const expected of [
      'Identity',
      'Machine UUID',
      'Building',
      'Lab 1 — location mismatch (the room is at “Building B”)',
      'Organisational unit (AD)',
      'Agent version',
      'Network adapters',
      'The address in bold is the one the server uses',
      'In use',
      'gateway 10.0.0.254',
      'static address',
      'Hardware',
      'Virtual machine',
      'Read on',
      'Serial number',
      'Motherboard',
      'Windows installed on',
      'Memory',
      'Unknown type',
      'S/N K123',
      'Graphics cards',
      'driver 31.0.101',
    ]) {
      expect(text, expected).toContain(expected);
    }
    expectNoFrench(text);
  });

  it('their empty states', () => {
    setLocale('en');
    const m = computer({ nics: [], gpus: [], memory_modules: [], volumes: [] });
    const text = [
      mount(MachineNetworkCard, { props: { machine: m } }),
      mount(MachineMemoryCard, { props: { machine: m } }),
      mount(MachineGpuCard, { props: { machine: m } }),
      mount(MachineStorageCard, { props: { machine: m } }),
      mount(MachineHardwareCard, { props: { machine: { ...m, inventory_last_seen: null } } }),
    ]
      .map((w) => w.text())
      .join('\n');

    expect(text).toContain('No network adapter reported on this computer.');
    expect(text).toContain('No memory module reported on this computer.');
    expect(text).toContain('No graphics card reported on this computer.');
    expect(text).toContain('No volume reported on this computer.');
    expect(text).toContain('No inventory reported');
    expectNoFrench(text);
  });

  it('Defender and the registered antivirus', () => {
    setLocale('en');
    const defender = mount(MachineDefenderCard, { props: { machine: computer() } }).text();
    expect(defender).toContain('Defender status');
    expect(defender).toContain(
      'Defender is the antivirus registered in the Windows Security Center.',
    );
    expect(defender).toContain('Real-time protection');
    expect(defender).toContain('Signature age (days)');

    const third = mount(MachineAntivirusCard, {
      props: { machine: computer({ av_product_name: 'ESET', av_product_is_defender: false }) },
    }).text();
    expect(third).toContain('Registered antivirus');
    expect(third).toContain('Signatures up to date');

    const unread = mount(MachineAntivirusCard, {
      props: { machine: computer({ av_product_name: null, av_product_is_defender: null }) },
    }).text();
    expect(unread).toContain('Never reported on this computer');
    expectNoFrench([defender, third, unread].join('\n'));
  });

  it('Storage, Windows Update and its pending updates', () => {
    setLocale('en');
    const m = computer({
      volumes: [
        {
          id: 1,
          letter: 'C:',
          label: 'System',
          filesystem: 'NTFS',
          total_mb: 500_000,
          free_mb: 250_000,
          is_system: true,
          encryption_status: null,
        },
      ],
    });
    const storage = mount(MachineStorageCard, { props: { machine: m } }).text();
    expect(storage).toContain('Storage');
    expect(storage).toContain('“Refresh the inventory” takes a new reading.');
    expect(storage).toMatch(/free of .+ \(50%\)/);
    expect(storage).toContain('Physical disks');
    expect(storage).toContain('S/N S123');

    const wu = mount(MachineWindowsUpdateCard, { props: { machine: m } }).text();
    expect(wu).toContain('Restart required');
    expect(wu).toContain('Last installation');

    const pending = mount(MachinePendingUpdatesCard, {
      props: { machine: m, loading: false },
    }).text();
    for (const expected of [
      'Pending updates',
      'Read at the agent’s last pass',
      'Title',
      'Severity',
      'Max. size',
      'Downloaded',
      'Pending since',
    ]) {
      expect(pending, expected).toContain(expected);
    }
    expectNoFrench([storage, wu, pending].join('\n'));
  });

  it('Software and the threat history', async () => {
    setLocale('en');
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/machines', name: 'machines', component: { render: () => null } }],
    });
    const software = mount(MachineSoftwareCard, {
      props: { machine: computer(), loading: false },
      global: { plugins: [router] },
    });
    for (const expected of [
      'Installed software',
      'Partial list',
      'Name',
      'Publisher',
      'Installed on',
    ]) {
      expect(software.text(), expected).toContain(expected);
    }
    expect(software.find('[aria-label="Filter software"]').exists()).toBe(true);
    expect(software.find('[aria-label="Show the computers that have it"]').exists()).toBe(true);

    const pagination = { page: 1, rowsPerPage: 10, rowsNumber: 0 };
    const threats = mount(MachineThreatsCard, {
      props: { threats: [], loading: false, pagination },
    });
    expect(threats.text()).toContain('Threat history');
    expect(threats.text()).toContain('No threats detected.');
    await threats.setProps({ failed: true });
    expect(threats.text()).toContain('Threats not loaded.');
    expectNoFrench([software.text(), threats.text()].join('\n'));
  });

  it('the status card: the five facts and the findings', () => {
    setLocale('en');
    const w = mount(MachineStatusCard, {
      props: { machine: computer({ wu_pending_count: 2 }), activeThreats: 1 },
    });
    const text = w.text();
    for (const expected of [
      'System disk',
      'Last contact',
      'pending',
      '1 active threat — Defender has not dealt with the detection',
      '2 Windows updates pending, including 1 critical',
    ]) {
      expect(text, expected).toContain(expected);
    }
    expectNoFrench(text);

    const healthy = mount(MachineStatusCard, {
      props: { machine: machineDetail(), activeThreats: 0 },
    }).text();
    expect(healthy).toContain('No alerts on this computer.');
  });

  it('the usage card', async () => {
    setLocale('en');
    const daily = Array.from({ length: 28 }, (_, i) => ({
      date: new Date(Date.UTC(2026, 9, 1 + i)).toISOString().slice(0, 10),
      hours: i === 27 ? 7.5 : 0,
    }));
    vi.mocked(getMachineUsage).mockResolvedValue({
      days: 28,
      tz: 'UTC',
      total_hours: 7.5,
      daily,
      first_seen: '2026-10-20T00:00:00Z',
      usage_since: '2026-01-01T00:00:00Z',
    });
    const w = mount(MachineUsageCard, { props: { machine: computer() } });
    await flushPromises();
    const text = w.text();
    expect(text).toContain('Usage');
    expect(text).toContain('Hours switched on per day over the last 28 days');
    expect(text).toContain('over the last 7 days');
    expect(text).toContain('over 28 days, 9 measured');
    expect(text).toContain('Grey background: Saturdays and Sundays.');
    expect(text).toContain('Hatching: days before counting began.');
    expect(w.find('[role="group"]').attributes('aria-label')).toContain(
      'Hours on per day over 28 days',
    );
    expect(w.find('.usage-col--unmeasured').attributes('aria-label')).toMatch(/: not measured$/);
    expectNoFrench(text);
  });

  it('the merge dialog', async () => {
    setLocale('en');
    vi.mocked(listMachines).mockResolvedValue({ items: [], total: 0 } as never);
    const duplicates = [
      {
        id: 'd1',
        machine_uuid: 'uuid-d1',
        hostname: 'PC-LAB-01',
        first_seen: ago(200),
        last_seen: ago(30),
        match_reason: 'hostname',
      },
    ] as unknown as DuplicateCandidate[];
    const w = mount(MachineMergeDialog, {
      props: { modelValue: true, machine: computer(), machineId: 'm1', duplicates },
      attachTo: document.body,
    });
    await flushPromises();
    const text = document.body.textContent ?? '';
    for (const expected of [
      'Merge a duplicate',
      'Computer kept (this one)',
      'Enrolled on',
      'last seen',
      'Same name',
      'Only the name matches',
      'Merge here',
      'Search for another computer to merge into this one',
      'Close',
    ]) {
      expect(text, expected).toContain(expected);
    }
    expectNoFrench(text);

    // The confirmation names both records, in English, the values still escaped.
    const dialog = vi.spyOn(w.vm.$q, 'dialog').mockReturnValue({ onOk: () => undefined } as never);
    const mergeHere = [...document.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Merge here'),
    )!;
    mergeHere.click();
    expect(dialog).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Merge computers',
        message:
          '<div>Delete the record <b>uuid-d1 (PC-LAB-01)</b> and move its history to ' +
          '<b>uuid-1</b>?</div><div class="q-mt-sm">This cannot be undone.</div>',
      }),
    );
    w.unmount();
  });

  it('follows a change of language while shown', async () => {
    const w = mount(MachineHardwareCard, { props: { machine: computer() } });
    expect(w.text()).toContain('Carte mère');
    setLocale('en');
    await nextTick();
    expect(w.text()).toContain('Motherboard');
    expect(w.text()).not.toContain('Carte mère');
  });

  it('names the usage chart’s days in the language shown, live', async () => {
    vi.mocked(getMachineUsage).mockResolvedValue({
      days: 28,
      tz: 'UTC',
      total_hours: 0,
      daily: Array.from({ length: 28 }, (_, i) => ({
        date: new Date(Date.UTC(2026, 9, 1 + i)).toISOString().slice(0, 10),
        hours: 0,
      })),
      first_seen: '2026-01-01T12:00:00Z',
      usage_since: '2026-01-01T12:00:00Z',
    });
    const w = mount(MachineUsageCard, { props: { machine: computer() } });
    await flushPromises();
    // 28/10/2026 is a Wednesday, the last column.
    const lastDay = () => w.findAll('.usage-col').at(-1)!.attributes('aria-label');
    expect(lastDay()).toMatch(/^mer\. 28\/10/);
    setLocale('en');
    await nextTick();
    expect(lastDay()).toMatch(/^Wed 28\/10/);
  });
});
