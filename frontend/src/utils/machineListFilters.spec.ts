import { describe, expect, it } from 'vitest';
import {
  AGENT_OUTDATED,
  ROOM_NONE,
  clearMachineFilter,
  emptyMachineFilters,
  initialFleetOptions,
  isRamActive,
  machineFilterChips,
  machineFiltersFromQuery,
  machineFiltersToParams,
  machineFiltersToQuery,
  ramGbValue,
  type MachineFilters,
} from './machineListFilters';
import { machineListParamsFromQuery } from './machineQuery';

/** Every facet set at once, as the widgets would hold them. */
function everything(): MachineFilters {
  return {
    search: 'pc-12',
    domain: 'CORP',
    location: 'Papeete',
    building: 'b-1',
    room: 'r-1',
    mismatch: 'true',
    checkOpen: 'true',
    maintenance: 'overdue',
    antivirus: 'ESET',
    status: 'outdated',
    wu: 'pending',
    scan: 'full:30',
    os: 'Windows 11',
    agent: '1.4.0',
    threatsOnly: true,
    onlineOnly: true,
    model: 'OptiPlex',
    manufacturer: 'Dell',
    processor: 'i5-8',
    chassis: 'laptop',
    ramOp: 'min',
    ramGb: 16,
    diskFree: 10,
    usageBelow: 50,
    usageAbove: 10,
    usageDays: 30,
    softwareId: 42,
  };
}

describe('machineFiltersToQuery / machineFiltersFromQuery', () => {
  it('omits every default, so the common URL stays empty', () => {
    expect(machineFiltersToQuery(emptyMachineFilters())).toEqual({});
    expect(machineFiltersFromQuery({})).toEqual(emptyMachineFilters());
  });

  it('round-trips every facet through the URL', () => {
    const query = machineFiltersToQuery(everything());
    expect(query).toEqual({
      search: 'pc-12',
      domain: 'CORP',
      location: 'Papeete',
      building: 'b-1',
      room: 'r-1',
      location_mismatch: 'true',
      check_open: 'true',
      maintenance_state: 'overdue',
      antivirus: 'ESET',
      os_version: 'Windows 11',
      agent_version: '1.4.0',
      status: 'outdated',
      wu_status: 'pending',
      scan_type: 'full',
      scan_days: '30',
      with_active_threats: 'true',
      online: 'true',
      hw_model: 'OptiPlex',
      hw_manufacturer: 'Dell',
      cpu_model: 'i5-8',
      hw_chassis_type: 'laptop',
      ram_min_gb: '16',
      disk_free_below: '10',
      usage_hours_below: '50',
      usage_hours_above: '10',
      usage_days: '30',
      software_id: '42',
    });
    expect(machineFiltersFromQuery(query)).toEqual(everything());
  });

  it('writes the agent sentinel as its own flag, and reads it back', () => {
    const query = machineFiltersToQuery({ ...emptyMachineFilters(), agent: AGENT_OUTDATED });
    expect(query).toEqual({ agent_outdated: 'true' });
    expect(machineFiltersFromQuery(query).agent).toBe(AGENT_OUTDATED);
  });

  it('carries a memory bound only once both halves are set', () => {
    const half = { ...emptyMachineFilters(), ramOp: 'max' as const };
    expect(machineFiltersToQuery(half)).toEqual({});
    // QInput hands back what was typed: a string is as good as a number.
    expect(machineFiltersToQuery({ ...half, ramGb: '8' })).toEqual({ ram_max_gb: '8' });
  });

  it('keeps the lower memory bound when a URL carries both', () => {
    const f = machineFiltersFromQuery({ ram_min_gb: '8', ram_max_gb: '32' });
    expect([f.ramOp, f.ramGb]).toEqual(['min', 8]);
    const max = machineFiltersFromQuery({ ram_max_gb: '32' });
    expect([max.ramOp, max.ramGb]).toEqual(['max', 32]);
  });

  it('drops what no widget could have written', () => {
    const f = machineFiltersFromQuery({
      maintenance_state: 'whenever',
      status: 'shiny',
      wu_status: 'later',
      scan_type: 'deep',
      hw_chassis_type: 'spaceship',
      disk_free_below: '15',
      usage_days: '365',
      software_id: '-3',
      location_mismatch: 'yes',
    });
    expect(f).toEqual(emptyMachineFilters());
  });

  it('settles an unknown scan age on the first one offered', () => {
    expect(machineFiltersFromQuery({ scan_type: 'quick', scan_days: '12' }).scan).toBe('quick:7');
  });
});

describe('machineFiltersToParams', () => {
  it('sends nothing for the whole parc', () => {
    expect(machineFiltersToParams(emptyMachineFilters())).toEqual({});
  });

  // The list writes the URL and the fiche reads it back with
  // `machineListParamsFromQuery`: both must arrive at the same search, or the
  // fiche's previous/next would walk a different list than the one clicked.
  it('asks the server what the fiche will ask once the URL is read back', () => {
    for (const f of [
      everything(),
      { ...everything(), room: ROOM_NONE, agent: AGENT_OUTDATED, ramOp: 'max' as const },
    ]) {
      expect(machineFiltersToParams(f)).toEqual(
        machineListParamsFromQuery(machineFiltersToQuery(f)),
      );
    }
  });

  it('turns the « Sans salle » entry into its own flag', () => {
    expect(machineFiltersToParams({ ...emptyMachineFilters(), room: ROOM_NONE })).toEqual({
      without_room: true,
    });
  });
});

describe('ramGbValue / isRamActive', () => {
  it('reads a positive whole number, typed or parsed', () => {
    expect(ramGbValue({ ramGb: '16' })).toBe(16);
    expect(ramGbValue({ ramGb: 16 })).toBe(16);
    for (const ramGb of [null, '', '0', '-4', '7.5', 'abc']) {
      expect(ramGbValue({ ramGb })).toBeNull();
    }
  });

  it('needs the bound and the figure', () => {
    expect(isRamActive({ ramOp: 'min', ramGb: 16 })).toBe(true);
    expect(isRamActive({ ramOp: null, ramGb: 16 })).toBe(false);
    expect(isRamActive({ ramOp: 'min', ramGb: '' })).toBe(false);
  });
});

describe('machineFilterChips', () => {
  it('has no chip for the search and the toggles, which stay on the bar', () => {
    const f = { ...emptyMachineFilters(), search: 'pc', threatsOnly: true, onlineOnly: true };
    expect(machineFilterChips(f, initialFleetOptions(), 7)).toEqual([]);
  });

  it('labels each chip like the dropdown entry that set it, in the panel order', () => {
    const options = initialFleetOptions();
    options.location.push({ label: 'Papeete (40)', value: 'Papeete' });
    options.agent.push({ label: 'Agent obsolète (3)', value: AGENT_OUTDATED });
    const chips = machineFilterChips(
      { ...everything(), agent: AGENT_OUTDATED, usageAbove: null },
      options,
      7,
    );
    expect(chips.map((c) => c.key)).toEqual([
      'location',
      'building',
      'room',
      'mismatch',
      'check',
      'maintenance',
      'antivirus',
      'status',
      'wu',
      'scan',
      'os',
      'agent',
      'manufacturer',
      'model',
      'processor',
      'chassis',
      'ram',
      'disk',
      'usage',
      'software',
    ]);
    const label = (key: string) => chips.find((c) => c.key === key)!.label;
    expect(label('location')).toBe('Papeete (40)');
    expect(label('agent')).toBe('Agent obsolète (3)');
    // A value its list does not (yet) hold reads as itself rather than blank.
    expect(label('antivirus')).toBe('ESET');
    expect(label('scan')).toBe('Scan complet > 1 mois');
    expect(label('ram')).toBe('Mémoire ≥ 16 Gio');
    expect(label('disk')).toBe('Moins de 10 % libres');
    expect(label('usage')).toBe('Allumés moins de 50 h sur 7 j');
    expect(label('software')).toBe('Postes portant un logiciel');
  });

  it('names a memory ceiling with its own sign', () => {
    const f = { ...emptyMachineFilters(), ramOp: 'max' as const, ramGb: 8 };
    expect(machineFilterChips(f, initialFleetOptions(), 7)).toEqual([
      { key: 'ram', label: 'Mémoire ≤ 8 Gio' },
    ]);
  });
});

describe('clearMachineFilter', () => {
  it('clears the one facet a chip stands for', () => {
    const f = everything();
    expect(clearMachineFilter(f, 'check')).toEqual({ ...f, checkOpen: null });
    expect(clearMachineFilter(f, 'disk')).toEqual({ ...f, diskFree: null });
    expect(clearMachineFilter(f, 'software')).toEqual({ ...f, softwareId: null });
  });

  it('clears both halves of the memory filter', () => {
    expect(clearMachineFilter(everything(), 'ram')).toEqual({
      ...everything(),
      ramOp: null,
      ramGb: null,
    });
  });

  it('clears the usage window with its bounds — a widened window is part of it', () => {
    expect(clearMachineFilter(everything(), 'usage')).toEqual({
      ...everything(),
      usageBelow: null,
      usageAbove: null,
      usageDays: null,
    });
  });

  it('leaves the filters it was given untouched', () => {
    const f = everything();
    clearMachineFilter(f, 'os');
    expect(f).toEqual(everything());
  });
});
