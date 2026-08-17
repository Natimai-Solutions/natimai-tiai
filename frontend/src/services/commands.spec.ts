import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('boot/axios', () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

import { api } from 'boot/axios';
import {
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
      'maintenance',
      'diagnostic',
    ]);
  });

  it('drops the diagnostic section from the bulk menu', () => {
    const groups = commandActionGroups({ bulkOnly: true });
    expect(groups.map((s) => s.group)).toEqual(['defender', 'maintenance']);
    expect(groups.flatMap((s) => s.actions).every((a) => a.bulk)).toBe(true);
  });
});

describe('commandTypeLabel', () => {
  it('translates a known type', () => {
    expect(commandTypeLabel('dism_restore_health')).toBe('Réparer l’image système (DISM)');
  });

  it('falls back to the raw value for an unknown type', () => {
    // An older console against a newer server must show something, not a blank.
    expect(commandTypeLabel('wu_install')).toBe('wu_install');
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
