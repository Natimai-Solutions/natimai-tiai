import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from 'boot/axios';
import {
  bulkSendNotification,
  commandActionGroups,
  commandActions,
  commandTypeLabel,
  createCommands,
  listCommands,
  type CommandType,
} from './commands';

describe('createCommands', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it('posts the payload and returns the created ids', async () => {
    const payload = { created: ['c-1', 'c-2'], count: 2 };
    vi.mocked(api.post).mockResolvedValue({ data: payload });

    const result = await createCommands({ type: 'quick_scan', machine_ids: ['m-1', 'm-2'] });

    expect(api.post).toHaveBeenCalledWith('/commands', {
      type: 'quick_scan',
      machine_ids: ['m-1', 'm-2'],
    });
    expect(result).toEqual(payload);
  });
});

describe('command catalogue', () => {
  // Spelled out rather than derived from the catalogue: the closed set is the
  // security model (the agent holds the command lines, the wire carries only a
  // name), so a type appearing or disappearing should cost a deliberate edit
  // here — as it does in the backend enum and the agent's own table.
  const expected: CommandType[] = [
    'quick_scan',
    'full_scan',
    'update_signatures',
    'wu_scan',
    'wu_install',
    'wu_install_full',
    'wu_reset',
    'reboot',
    'gpo_update',
    'flush_dns',
    'time_resync',
    'cert_pulse',
    'spooler_reset',
    'sfc_scan',
    'dism_restore_health',
    'dism_component_cleanup',
    'chkdsk_scan',
    'gpo_report',
    'net_config',
  ];

  it('covers every command type exactly once', () => {
    expect(commandActions.map((a) => a.type)).toEqual(expected);
  });

  it('gives every action a label and an icon', () => {
    for (const action of commandActions) {
      expect(action.label.length).toBeGreaterThan(0);
      expect(action.icon.length).toBeGreaterThan(0);
    }
  });

  it('confirms every action that changes the machine or ties it up', () => {
    const needConfirm = commandActions.filter((a) => a.confirm).map((a) => a.type);
    expect(needConfirm).toEqual([
      'full_scan',
      // Installing patches ties the poste up for a while, and restarting it can
      // cost a user their unsaved work. wu_scan only reads, so it goes straight
      // through like the Defender scans.
      'wu_install',
      'wu_install_full',
      // Discards the update store, and with it the poste's update history.
      'wu_reset',
      'reboot',
      'spooler_reset',
      'sfc_scan',
      'dism_restore_health',
      'dism_component_cleanup',
      'chkdsk_scan',
    ]);
  });

  it('carries a hint on every action it asks confirmation for', () => {
    for (const action of commandActions.filter((a) => a.confirm)) {
      expect(action.hint, action.type).toBeTruthy();
    }
  });

  it('keeps the read-only diagnostics out of bulk actions', () => {
    const diagnostics = commandActions.filter((a) => a.group === 'diagnostic');
    expect(diagnostics.map((a) => a.type)).toEqual(['gpo_report', 'net_config']);
    expect(diagnostics.every((a) => !a.bulk)).toBe(true);
  });

  it('groups the menu in a stable order', () => {
    expect(commandActionGroups().map((s) => s.group)).toEqual([
      'defender',
      'windows_update',
      'maintenance',
      'diagnostic',
    ]);
  });

  it('drops the diagnostic section from the bulk menu', () => {
    const groups = commandActionGroups({ bulkOnly: true });
    expect(groups.map((s) => s.group)).toEqual(['defender', 'windows_update', 'maintenance']);
    expect(groups.flatMap((s) => s.actions).every((a) => a.bulk)).toBe(true);
  });
});

describe('the restart command', () => {
  // The one command in the catalogue that can cost a user unsaved work, so its
  // two guards are asserted by name rather than left to the generic checks: a
  // confirmation, and a hint that says what happens and when.
  it('always asks, and says what it will do', () => {
    const reboot = commandActions.find((a) => a.type === 'reboot');
    expect(reboot?.group).toBe('windows_update');
    expect(reboot?.confirm).toBe(true);
    expect(reboot?.hint).toMatch(/60 secondes/);
  });
});

describe('the Windows Update reset', () => {
  // Microsoft's own repair procedure, and the one command that throws data
  // away without installing anything — so what it costs has to be spelled out
  // before it is sent, not discovered afterwards in the update history.
  it('asks, and names what it discards', () => {
    const reset = commandActions.find((a) => a.type === 'wu_reset');
    expect(reset?.group).toBe('windows_update');
    expect(reset?.confirm).toBe(true);
    expect(reset?.hint).toMatch(/historique/);
    // No reboot hidden inside it: the restart stays a separate, explicit call.
    expect(reset?.hint).toMatch(/Rien n’est installé ni redémarré/);
  });

  it('sits after the installs, before the restart', () => {
    const wu = commandActions.filter((a) => a.group === 'windows_update');
    expect(wu.map((a) => a.type)).toEqual([
      'wu_scan',
      'wu_install',
      'wu_install_full',
      'wu_reset',
      'reboot',
    ]);
  });
});

describe('commandTypeLabel', () => {
  it('translates a known type', () => {
    expect(commandTypeLabel('dism_restore_health')).toBe('Réparer l’image système (DISM)');
  });

  it('falls back to the raw value for an unknown type', () => {
    // An older console against a newer server must show something, not a blank.
    expect(commandTypeLabel('install_package')).toBe('install_package');
  });
});

describe('bulkSendNotification', () => {
  it('reports a plain send', () => {
    expect(bulkSendNotification({ created: ['a', 'b'], count: 2, skipped: 0 })).toEqual({
      type: 'positive',
      message: '2 commande(s) envoyée(s)',
    });
  });

  it('names what was left alone', () => {
    const note = bulkSendNotification({ created: ['a'], count: 1, skipped: 3 });
    expect(note.type).toBe('positive');
    expect(note.message).toContain('1 commande(s) envoyée(s)');
    expect(note.message).toContain('3 déjà en attente');
  });

  it('warns rather than claiming a send when everything was skipped', () => {
    // The case that would otherwise read as a failure: the button pressed twice
    // before any poste has answered.
    const note = bulkSendNotification({ created: [], count: 0, skipped: 340 });
    expect(note.type).toBe('warning');
    expect(note.message).toContain('340 poste(s)');
  });

  it('treats a missing count as zero', () => {
    // An older server does not send the field; NaN in a notification is worse
    // than an undercount.
    expect(bulkSendNotification({ created: [], count: 0 })).toEqual({
      type: 'positive',
      message: '0 commande(s) envoyée(s)',
    });
  });
});

describe('listCommands', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('lists commands filtered by machine and status', async () => {
    const payload = { items: [], total: 0, page: 1, page_size: 50 };
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    const result = await listCommands({ machine_id: 'm-1', status: 'pending' });

    expect(api.get).toHaveBeenCalledWith('/commands', {
      params: { machine_id: 'm-1', status: 'pending' },
    });
    expect(result).toEqual(payload);
  });

  it('passes no params by default', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    });

    await listCommands();

    expect(api.get).toHaveBeenCalledWith('/commands', { params: {} });
  });
});
