import { describe, expect, it } from 'vitest';
import {
  DEFAULT_MACHINE_COLUMNS,
  MACHINE_COLUMN_KEYS,
  OPTIONAL_MACHINE_COLUMNS,
  isDefaultMachineColumns,
  resolveMachineColumns,
} from './machineColumns';

describe('resolveMachineColumns', () => {
  it('falls back on the default when nothing usable is stored', () => {
    expect(resolveMachineColumns(undefined)).toEqual(DEFAULT_MACHINE_COLUMNS);
    expect(resolveMachineColumns(null)).toEqual(DEFAULT_MACHINE_COLUMNS);
    expect(resolveMachineColumns('hostname')).toEqual(DEFAULT_MACHINE_COLUMNS);
    expect(resolveMachineColumns([])).toEqual(DEFAULT_MACHINE_COLUMNS);
    expect(resolveMachineColumns(['renamed_column', 42])).toEqual(DEFAULT_MACHINE_COLUMNS);
  });

  it('keeps the stored order and drops what it does not know', () => {
    expect(resolveMachineColumns(['hostname', 'agent', 'old_column', 'room'])).toEqual([
      'hostname',
      'agent',
      'room',
    ]);
  });

  it('collapses duplicates', () => {
    expect(resolveMachineColumns(['hostname', 'room', 'room', 'agent', 'hostname'])).toEqual([
      'hostname',
      'room',
      'agent',
    ]);
  });

  it('always puts the name column first, even when it was hidden or moved', () => {
    expect(resolveMachineColumns(['room', 'agent'])).toEqual(['hostname', 'room', 'agent']);
    expect(resolveMachineColumns(['room', 'hostname', 'agent'])).toEqual([
      'hostname',
      'room',
      'agent',
    ]);
  });

  it('does not share the default array with callers', () => {
    const a = resolveMachineColumns(undefined);
    expect(a).toEqual(DEFAULT_MACHINE_COLUMNS);
    expect(a).not.toBe(DEFAULT_MACHINE_COLUMNS);
  });
});

describe('isDefaultMachineColumns', () => {
  it('recognises the default layout and nothing else', () => {
    expect(isDefaultMachineColumns([...DEFAULT_MACHINE_COLUMNS])).toBe(true);
    expect(isDefaultMachineColumns([...DEFAULT_MACHINE_COLUMNS].reverse())).toBe(false);
    expect(isDefaultMachineColumns(DEFAULT_MACHINE_COLUMNS.slice(0, 3))).toBe(false);
    // Every column shown is a layout of its own, worth storing.
    expect(isDefaultMachineColumns([...MACHINE_COLUMN_KEYS])).toBe(false);
  });
});

describe('optional columns', () => {
  it('offers the usage column without showing it by default', () => {
    expect(MACHINE_COLUMN_KEYS).toContain('usage');
    expect(OPTIONAL_MACHINE_COLUMNS).toContain('usage');
    expect(DEFAULT_MACHINE_COLUMNS).not.toContain('usage');
  });

  it('keeps a stored layout that added it', () => {
    expect(resolveMachineColumns(['hostname', 'usage', 'room'])).toEqual([
      'hostname',
      'usage',
      'room',
    ]);
  });

  it('keeps the default layout in catalogue order', () => {
    const order = DEFAULT_MACHINE_COLUMNS.map((key) => MACHINE_COLUMN_KEYS.indexOf(key));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });
});
