import { describe, expect, it } from 'vitest';
import {
  DEFAULT_MACHINE_COLUMNS,
  MACHINE_COLUMN_KEYS,
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
    expect(a).toEqual(MACHINE_COLUMN_KEYS);
    expect(a).not.toBe(DEFAULT_MACHINE_COLUMNS);
  });
});

describe('isDefaultMachineColumns', () => {
  it('recognises the default layout and nothing else', () => {
    expect(isDefaultMachineColumns([...MACHINE_COLUMN_KEYS])).toBe(true);
    expect(isDefaultMachineColumns([...MACHINE_COLUMN_KEYS].reverse())).toBe(false);
    expect(isDefaultMachineColumns(MACHINE_COLUMN_KEYS.slice(0, 3))).toBe(false);
  });
});
