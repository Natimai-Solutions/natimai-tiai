import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the axios boot module before importing the service under test.
vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  exportMachines,
  getDuplicates,
  getMachine,
  listAntivirusProducts,
  listChassisTypes,
  listExportColumns,
  listMachines,
  listManufacturers,
  listModels,
  listOsVersions,
  listProcessors,
  mergeMachines,
  allowReenroll,
  revokeToken,
  wakeMachines,
  wakeNotification,
} from './machines';

describe('listMachines', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('calls GET /machines with the given filters and returns the payload', async () => {
    const payload = { items: [], total: 0, page: 1, page_size: 50 };
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    const result = await listMachines({ search: 'pc-01', status: 'outdated' });

    expect(api.get).toHaveBeenCalledWith('/machines', {
      params: { search: 'pc-01', status: 'outdated' },
    });
    expect(result).toEqual(payload);
  });

  it('passes the antivirus filter through', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    });

    await listMachines({ antivirus: 'ESET Endpoint Security' });

    expect(api.get).toHaveBeenCalledWith('/machines', {
      params: { antivirus: 'ESET Endpoint Security' },
    });
  });

  it('passes the Windows Update and threat facets through', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    });

    // The two axes combine: the dashboard's cards each set one, and a user can
    // then narrow with the other without either clearing the first.
    await listMachines({ wu_status: 'pending', with_active_threats: true });

    expect(api.get).toHaveBeenCalledWith('/machines', {
      params: { wu_status: 'pending', with_active_threats: true },
    });
  });

  it('passes no params when called with no arguments', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    });

    await listMachines();

    expect(api.get).toHaveBeenCalledWith('/machines', { params: {} });
  });
});

describe('listAntivirusProducts', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('fetches the antivirus products present in the fleet', async () => {
    const products = [
      { name: 'ESET Endpoint Security', count: 12 },
      { name: 'Windows Defender', count: 3 },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: products });

    const result = await listAntivirusProducts();

    expect(api.get).toHaveBeenCalledWith('/machines/antivirus-products');
    expect(result).toEqual(products);
  });
});

describe('listOsVersions', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('fetches the OS versions present in the fleet', async () => {
    const versions = [
      { name: 'Windows 11 23H2', count: 40 },
      { name: 'Windows 10 22H2', count: 7 },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: versions });

    const result = await listOsVersions();

    expect(api.get).toHaveBeenCalledWith('/machines/os-versions');
    expect(result).toEqual(versions);
  });
});

describe('getMachine', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('fetches a single machine by id', async () => {
    const detail = { id: 'm-1', hostname: 'PC-01' };
    vi.mocked(api.get).mockResolvedValue({ data: detail });

    const result = await getMachine('m-1');

    expect(api.get).toHaveBeenCalledWith('/machines/m-1');
    expect(result).toEqual(detail);
  });
});

describe('revokeToken', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('posts to the revoke-token endpoint', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'revoked' } });

    await revokeToken('m-9');

    expect(api.post).toHaveBeenCalledWith('/machines/m-9/revoke-token');
  });
});

describe('allowReenroll', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('posts to the allow-reenroll endpoint', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'reenroll-allowed' } });

    await allowReenroll('m-9');

    expect(api.post).toHaveBeenCalledWith('/machines/m-9/allow-reenroll');
  });
});

describe('getDuplicates', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('fetches duplicate candidates for a machine', async () => {
    const dups = [{ id: 'm-2' }];
    vi.mocked(api.get).mockResolvedValue({ data: dups });

    const result = await getDuplicates('m-1');

    expect(api.get).toHaveBeenCalledWith('/machines/m-1/duplicates');
    expect(result).toEqual(dups);
  });
});

describe('mergeMachines', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('merges the source into the target and returns the updated target', async () => {
    const target = { id: 'm-keep', needs_verification: false };
    vi.mocked(api.post).mockResolvedValue({ data: target });

    const result = await mergeMachines('m-keep', 'm-drop');

    expect(api.post).toHaveBeenCalledWith('/machines/m-keep/merge', {
      source_id: 'm-drop',
    });
    expect(result).toEqual(target);
  });
});

describe('windows update fields', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('carries the pending updates through the machine detail', async () => {
    const payload = {
      id: 'm-1',
      wu_pending_count: 2,
      wu_reboot_required: true,
      wu_last_search: '2026-08-13T04:00:00Z',
      wu_last_install: '2026-08-01T03:12:00Z',
      pending_updates: [
        {
          id: 1,
          update_id: 'e6cf1350.201',
          kb: 'KB5063878',
          title: 'Mise à jour cumulative 2026-08',
          severity: 'critical',
          type: 'software',
          categories: 'Security Updates',
          is_downloaded: true,
          size_mb: 620.5,
          first_seen: '2026-08-13T04:00:00Z',
          last_seen: '2026-08-17T04:00:00Z',
        },
      ],
    };
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    const result = await getMachine('m-1');

    expect(api.get).toHaveBeenCalledWith('/machines/m-1');
    expect(result.wu_pending_count).toBe(2);
    expect(result.wu_reboot_required).toBe(true);
    expect(result.pending_updates[0]?.kb).toBe('KB5063878');
    expect(result.pending_updates[0]?.severity).toBe('critical');
  });

  it('keeps a never-reported machine distinguishable from a patched one', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { id: 'm-2', wu_pending_count: null, wu_reboot_required: false, pending_updates: [] },
    });

    const result = await getMachine('m-2');

    // null, not 0: the console renders the two differently on purpose.
    expect(result.wu_pending_count).toBeNull();
    expect(result.pending_updates).toEqual([]);
  });
});

describe('wakeMachines', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('posts the selection to the server, which emits the packets', async () => {
    const payload = {
      results: [{ machine_id: 'm-1', hostname: 'POSTE-1', ok: true, detail: 'émis' }],
      woken: 1,
      failed: 0,
    };
    vi.mocked(api.post).mockResolvedValue({ data: payload });

    const result = await wakeMachines(['m-1']);

    expect(api.post).toHaveBeenCalledWith('/machines/wake', { machine_ids: ['m-1'] });
    expect(result).toEqual(payload);
  });
});

describe('wakeNotification', () => {
  // Three outcomes, not two: an administrator waking a room needs to know that
  // two postes were left behind, and one that woke nothing needs the reason.
  it('reports a clean wake without promising the poste came back', () => {
    const note = wakeNotification({ results: [], woken: 4, failed: 0 });

    expect(note.type).toBe('positive');
    expect(note.message).toMatch(/4 poste/);
    // Wake-on-LAN acknowledges nothing: the console only learns of a wake when
    // the agent reports, so the wording says exactly that.
    expect(note.message).toMatch(/prochain démarrage/);
  });

  it('flags the postes it could not aim at', () => {
    const note = wakeNotification({ results: [], woken: 3, failed: 2 });

    expect(note.type).toBe('warning');
    expect(note.message).toMatch(/2 sans cible connue/);
  });

  it('quotes the server’s reason when a single wake failed', () => {
    const note = wakeNotification({
      results: [
        {
          machine_id: 'm-1',
          hostname: 'POSTE-1',
          ok: false,
          detail: 'Aucune adresse MAC connue pour ce poste.',
        },
      ],
      woken: 0,
      failed: 1,
    });

    expect(note.type).toBe('negative');
    expect(note.message).toMatch(/Aucune adresse MAC/);
  });

  it('does not quote a reason it cannot pick when several failed', () => {
    const note = wakeNotification({ results: [], woken: 0, failed: 5 });

    expect(note.type).toBe('negative');
    expect(note.message).toMatch(/5 poste/);
  });

  it('does not claim a packet was emitted when the server only relayed', () => {
    // A remote server hands the wake to a poste of the site; nothing has left
    // any wire when it answers, and the sentence must not say otherwise.
    const note = wakeNotification({ results: [], woken: 2, failed: 0, relayed: true });

    expect(note.type).toBe('positive');
    expect(note.message).toMatch(/confié aux postes voisins de 2 poste/);
    expect(note.message).not.toMatch(/émis/);
  });
});

describe('inventory fleet listings', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('lists the models present in the fleet', async () => {
    const payload = [{ name: 'OptiPlex 7010', count: 42 }];
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    const result = await listModels();

    expect(api.get).toHaveBeenCalledWith('/machines/models');
    expect(result).toEqual(payload);
  });

  it('lists the manufacturers present in the fleet', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    await listManufacturers();
    expect(api.get).toHaveBeenCalledWith('/machines/manufacturers');
  });
});

describe('exportMachines', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  // The export carries the same facets as the list: an export that silently
  // ignored half the filters the reader had set would be worse than none.
  it('asks for a CSV blob and forwards every filter', async () => {
    const blob = new Blob(['x']);
    vi.mocked(api.get).mockResolvedValue({ data: blob });

    const result = await exportMachines(
      { hw_model: 'OptiPlex', disk_free_below: 10 },
      { format: 'csv' },
    );

    expect(api.get).toHaveBeenCalledWith('/machines/export.csv', {
      params: { hw_model: 'OptiPlex', disk_free_below: 10 },
      responseType: 'blob',
    });
    expect(result).toBe(blob);
  });

  it('asks for a workbook with the chosen columns, in order, and the reader’s zone', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob() });

    await exportMachines(
      { online: true },
      { format: 'xlsx', columns: ['cpu_model', 'hostname'], tz: 'Pacific/Tahiti' },
    );

    expect(api.get).toHaveBeenCalledWith('/machines/export.xlsx', {
      params: { online: true, columns: 'cpu_model,hostname', tz: 'Pacific/Tahiti' },
      responseType: 'blob',
    });
  });

  it('sends no columns parameter when none are chosen — the server’s defaults apply', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob() });

    await exportMachines({}, { format: 'xlsx', columns: [] });

    expect(api.get).toHaveBeenCalledWith('/machines/export.xlsx', {
      params: {},
      responseType: 'blob',
    });
  });
});

describe('listExportColumns', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('reads the catalogue from the server', async () => {
    const columns = [
      {
        key: 'hostname',
        label: 'Nom',
        group: 'identity',
        group_label: 'Identité',
        kind: 'text',
        default: true,
      },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: columns });

    const result = await listExportColumns();

    expect(api.get).toHaveBeenCalledWith('/machines/export-columns');
    expect(result).toEqual(columns);
  });
});

describe('processor and chassis listings', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('read the two fleet listings behind the new filters', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [{ name: 'x', count: 1 }] });

    await listProcessors();
    await listChassisTypes();

    expect(api.get).toHaveBeenCalledWith('/machines/processors');
    expect(api.get).toHaveBeenCalledWith('/machines/chassis-types');
  });
});

describe('listMachines inventory facets', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('passes the model, disk and software filters through', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } });

    await listMachines({ hw_model: 'OptiPlex', disk_free_below: 10, software_id: 7 });

    expect(api.get).toHaveBeenCalledWith('/machines', {
      params: { hw_model: 'OptiPlex', disk_free_below: 10, software_id: 7 },
    });
  });
});
