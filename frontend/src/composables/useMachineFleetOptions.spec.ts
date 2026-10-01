import { beforeEach, describe, expect, it, vi } from 'vitest';

// The rooms module is kept for its pure helpers (`roomLabel`); its client is
// stubbed so that importing it does not pull in the app's axios boot file.
vi.mock('boot/axios', () => ({ api: {} }));
vi.mock('src/services/machines', () => ({
  listAntivirusProducts: vi.fn(),
  listOsVersions: vi.fn(),
  listAgentVersions: vi.fn(),
  listLocations: vi.fn(),
  listModels: vi.fn(),
  listManufacturers: vi.fn(),
  listProcessors: vi.fn(),
  listChassisTypes: vi.fn(),
}));
vi.mock('src/services/rooms', async (importOriginal) => ({
  ...(await importOriginal<typeof import('src/services/rooms')>()),
  getRoomConfig: vi.fn(),
  listRooms: vi.fn(),
  listBuildings: vi.fn(),
}));

import * as machines from 'src/services/machines';
import * as rooms from 'src/services/rooms';
import { initialFleetOptions } from 'src/utils/machineListFilters';
import { chassisLabelOf, useMachineFleetOptions } from './useMachineFleetOptions';

/** Let every listing's promise settle. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function room(id: string, name: string, building: string | null, count: number) {
  return {
    id,
    name,
    building: building ? { id: `b-${building}`, name: building } : null,
    machine_count: count,
  } as unknown as rooms.Room;
}

describe('useMachineFleetOptions', () => {
  beforeEach(() => {
    vi.mocked(machines.listAntivirusProducts).mockResolvedValue([{ name: 'ESET', count: 12 }]);
    vi.mocked(machines.listOsVersions).mockResolvedValue([{ name: 'Windows 11', count: 30 }]);
    vi.mocked(machines.listAgentVersions).mockResolvedValue({
      latest: '1.4.0',
      versions: [
        { name: '1.4.0', count: 20, outdated: false },
        { name: '1.3.2', count: 4, outdated: true },
        { name: '1.2.0', count: 1, outdated: true },
      ],
    } as machines.AgentVersions);
    vi.mocked(machines.listLocations).mockResolvedValue([{ name: 'Papeete', count: 40 }]);
    vi.mocked(machines.listModels).mockResolvedValue([{ name: 'OptiPlex 7010', count: 9 }]);
    vi.mocked(machines.listManufacturers).mockResolvedValue([{ name: 'Dell', count: 25 }]);
    vi.mocked(machines.listProcessors).mockResolvedValue([{ name: 'i5-8500', count: 7 }]);
    vi.mocked(machines.listChassisTypes).mockResolvedValue([
      { name: 'laptop', count: 5 },
      { name: 'weird', count: 1 },
    ]);
    vi.mocked(rooms.getRoomConfig).mockResolvedValue({ manual: false } as rooms.RoomConfig);
    vi.mocked(rooms.listRooms).mockResolvedValue([
      room('r-1', 'B12', 'Nord', 8),
      room('r-2', 'Atelier', null, 3),
    ]);
    vi.mocked(rooms.listBuildings).mockResolvedValue([
      { id: 'b-1', name: 'Nord', location: 'Papeete', machine_count: 8 },
      { id: 'b-2', name: 'Sud', location: null, machine_count: 0 },
    ] as unknown as rooms.Building[]);
  });

  it('starts on each dropdown’s « Tous » entry alone', () => {
    const { options, manualMode } = useMachineFleetOptions();
    expect(options.value).toEqual(initialFleetOptions());
    expect(manualMode.value).toBe(true);
  });

  it('fills every dropdown from the fleet, counts in the labels', async () => {
    const { options, rooms: held, manualMode, loadAll } = useMachineFleetOptions();
    loadAll();
    await settle();

    const o = options.value;
    expect(o.antivirus).toEqual([
      { label: 'Tous les antivirus', value: null },
      { label: 'ESET (12)', value: 'ESET' },
    ]);
    expect(o.os[1]).toEqual({ label: 'Windows 11 (30)', value: 'Windows 11' });
    expect(o.location[1]).toEqual({ label: 'Papeete (40)', value: 'Papeete' });
    expect(o.model[1]).toEqual({ label: 'OptiPlex 7010 (9)', value: 'OptiPlex 7010' });
    expect(o.manufacturer[1]).toEqual({ label: 'Dell (25)', value: 'Dell' });
    expect(o.processor[1]).toEqual({ label: 'i5-8500 (7)', value: 'i5-8500' });
    // The chassis in the console's words; an unknown kind as reported.
    expect(o.chassis.slice(1)).toEqual([
      { label: 'Portable (5)', value: 'laptop' },
      { label: 'weird (1)', value: 'weird' },
    ]);
    expect(held.value).toHaveLength(2);
    expect(manualMode.value).toBe(false);
  });

  it('puts the stragglers first in the agent list, summed, and marks the reference', async () => {
    const { options, loadAll } = useMachineFleetOptions();
    loadAll();
    await settle();

    expect(options.value.agent).toEqual([
      { label: 'Agent : toutes versions', value: null },
      { label: 'Agent obsolète (5)', value: 'outdated' },
      { label: 'Agent 1.4.0 · référence (20)', value: '1.4.0' },
      { label: 'Agent 1.3.2 (4)', value: '1.3.2' },
      { label: 'Agent 1.2.0 (1)', value: '1.2.0' },
    ]);
  });

  it('offers « Sans salle » and tells two rooms of the same name apart', async () => {
    const { options, loadRooms } = useMachineFleetOptions();
    await loadRooms();

    expect(options.value.room).toEqual([
      { label: 'Toutes les salles', value: null },
      { label: 'Sans salle', value: 'none' },
      { label: 'Nord › B12 (8)', value: 'r-1' },
      { label: 'Atelier (3)', value: 'r-2' },
    ]);
    expect(options.value.building).toEqual([
      { label: 'Tous les bâtiments', value: null },
      { label: 'Nord — Papeete (8)', value: 'b-1' },
      { label: 'Sud (0)', value: 'b-2' },
    ]);
  });

  it('leaves a dropdown on « Tous » when its listing fails, the others filled', async () => {
    const down = new Error('502');
    vi.mocked(machines.listAntivirusProducts).mockRejectedValue(down);
    vi.mocked(machines.listOsVersions).mockRejectedValue(down);
    vi.mocked(machines.listAgentVersions).mockRejectedValue(down);
    vi.mocked(machines.listModels).mockRejectedValue(down);
    vi.mocked(rooms.getRoomConfig).mockRejectedValue(down);
    vi.mocked(rooms.listRooms).mockRejectedValue(down);
    const { options, manualMode, loadAll } = useMachineFleetOptions();
    loadAll();
    await settle();

    const initial = initialFleetOptions();
    for (const key of ['antivirus', 'os', 'agent', 'model', 'room', 'building'] as const) {
      expect(options.value[key], key).toEqual(initial[key]);
    }
    expect(options.value.manufacturer).toHaveLength(2);
    // Assumed manual: the worst case is a refusal the notification explains.
    expect(manualMode.value).toBe(true);
  });
});

describe('chassisLabelOf', () => {
  it('names a known kind in French, an unknown one as reported', () => {
    expect(chassisLabelOf('all-in-one')).toBe('Tout-en-un');
    expect(chassisLabelOf('boat')).toBe('boat');
  });
});
