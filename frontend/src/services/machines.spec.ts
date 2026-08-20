import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the axios boot module before importing the service under test.
vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  getDuplicates,
  getMachine,
  listAntivirusProducts,
  listMachines,
  mergeMachines,
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
});
