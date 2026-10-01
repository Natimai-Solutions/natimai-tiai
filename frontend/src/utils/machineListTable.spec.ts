import { describe, expect, it } from 'vitest';
import type { Machine } from 'src/services/machines';
import { MACHINE_COLUMN_KEYS, DEFAULT_MACHINE_COLUMNS } from './machineColumns';
import {
  COLUMN_BY_SORT_FIELD,
  MACHINE_COLUMN_LABELS,
  MACHINE_TABLE_COLUMNS,
  SORT_FIELD_BY_COLUMN,
  antivirusTooltip,
  initialMachinePagination,
  machinePaginationFromQuery,
  machinePaginationToQuery,
  sortFieldOf,
  usedRatio,
  visibleMachineColumns,
} from './machineListTable';
import { isSortField } from './machineQuery';

describe('MACHINE_TABLE_COLUMNS', () => {
  it('defines a column for every key the layout may hold, and no other', () => {
    expect(MACHINE_TABLE_COLUMNS.map((c) => c.name).sort()).toEqual(
      [...MACHINE_COLUMN_KEYS].sort(),
    );
  });

  it('sorts only through fields the API knows', () => {
    for (const column of MACHINE_TABLE_COLUMNS.filter((c) => c.sortable)) {
      const field = SORT_FIELD_BY_COLUMN[column.name];
      expect(field && isSortField(field), column.name).toBe(true);
      expect(COLUMN_BY_SORT_FIELD[field!]).toBe(column.name);
    }
  });

  it('shows a dash for an empty site, building or address', () => {
    const format = (name: string) => MACHINE_TABLE_COLUMNS.find((c) => c.name === name)!.format!;
    for (const name of ['location', 'building', 'ip_address']) {
      expect(format(name)(null, {} as Machine)).toBe('—');
      expect(format(name)('x', {} as Machine)).toBe('x');
    }
  });

  it('labels every column for the « Colonnes » dialog', () => {
    expect(MACHINE_COLUMN_LABELS.hostname).toBe('Nom');
    expect(Object.keys(MACHINE_COLUMN_LABELS)).toHaveLength(MACHINE_COLUMN_KEYS.length);
  });
});

describe('visibleMachineColumns', () => {
  it('follows the reader’s order', () => {
    const cols = visibleMachineColumns(['hostname', 'last_seen', 'domain'], 7);
    expect(cols.map((c) => c.name)).toEqual(['hostname', 'last_seen', 'domain']);
  });

  it('names the usage window in the usage header', () => {
    const [usage] = visibleMachineColumns(['usage'], 28);
    expect(usage!.label).toBe('Allumé (28 j)');
    // The catalogue entry itself is left alone.
    expect(MACHINE_TABLE_COLUMNS.find((c) => c.name === 'usage')!.label).toBe('Heures allumées');
  });

  it('skips a name the catalogue does not hold', () => {
    const order = ['hostname', 'gone'] as unknown as typeof DEFAULT_MACHINE_COLUMNS;
    expect(visibleMachineColumns(order, 7).map((c) => c.name)).toEqual(['hostname']);
  });
});

describe('machinePaginationFromQuery / machinePaginationToQuery', () => {
  it('reads an empty URL as the server’s default: freshest first, page 1', () => {
    const p = machinePaginationFromQuery({}, { ...initialMachinePagination(), rowsNumber: 120 });
    expect(p).toEqual({ ...initialMachinePagination(), rowsNumber: 120 });
    expect(machinePaginationToQuery(p)).toEqual({});
  });

  it('round-trips a sort, a page and a page size', () => {
    const query = { sort_by: 'hw_model', sort_desc: 'false', page: '3', page_size: '100' };
    const p = machinePaginationFromQuery(query, initialMachinePagination());
    expect(p).toMatchObject({ sortBy: 'model', descending: false, page: 3, rowsPerPage: 100 });
    expect(machinePaginationToQuery(p)).toEqual(query);
  });

  it('writes the default order only when it is reversed', () => {
    const p = { ...initialMachinePagination(), descending: false };
    expect(machinePaginationToQuery(p)).toEqual({ sort_by: 'last_seen', sort_desc: 'false' });
  });

  it('falls back on the defaults for what it cannot read', () => {
    const p = machinePaginationFromQuery(
      { sort_by: 'shoe_size', page: '-2', page_size: '33' },
      initialMachinePagination(),
    );
    expect(p).toEqual(initialMachinePagination());
  });

  it('maps a column to its API field, or nothing', () => {
    expect(sortFieldOf({ sortBy: 'disk' })).toBe('disk_free_percent');
    expect(sortFieldOf({ sortBy: 'ip_address' })).toBeUndefined();
    expect(sortFieldOf({ sortBy: null })).toBeUndefined();
  });
});

describe('antivirusTooltip', () => {
  const machine = {
    is_up_to_date: true,
    av_product_name: 'Windows Defender',
    av_product_enabled: true,
    av_product_signatures_up_to_date: true,
    signature_version: '1.401.2',
  } as Machine;

  it('ends on the signature version when there is one', () => {
    expect(antivirusTooltip(machine)).toMatch(/ · signatures 1\.401\.2$/);
  });

  it('leaves it out when the agent reported none', () => {
    expect(antivirusTooltip({ ...machine, signature_version: null })).toBe(
      'À jour · Windows Defender — protection active, signatures à jour',
    );
  });
});

describe('usedRatio', () => {
  it('fills with what is used', () => {
    expect(usedRatio({ system_volume_total_mb: 1000, system_volume_free_mb: 250 })).toBe(0.75);
  });

  it('is empty when the disk was never measured, and stays within the bar', () => {
    expect(usedRatio({ system_volume_total_mb: null, system_volume_free_mb: 10 })).toBe(0);
    expect(usedRatio({ system_volume_total_mb: 100, system_volume_free_mb: null })).toBe(0);
    expect(usedRatio({ system_volume_total_mb: 100, system_volume_free_mb: 150 })).toBe(0);
  });
});
