import { describe, expect, it } from 'vitest';
import { applyPermissionChange, permissionRequires } from './permissions';

describe('permission dependencies in the group grid (item 4)', () => {
  it('ticks the read of a write, and the everyday commands of the risky ones', () => {
    expect(applyPermissionChange([], ['room:write'])).toEqual(['room:read', 'room:write']);
    expect(applyPermissionChange([], ['risky_command:execute'])).toEqual([
      'command:read',
      'command:execute',
      'risky_command:execute',
    ]);
  });

  it('unticks what needs a read when the read is unticked', () => {
    const before = ['command:read', 'command:execute', 'risky_command:execute', 'room:read'];
    expect(
      applyPermissionChange(before, ['command:execute', 'risky_command:execute', 'room:read']),
    ).toEqual(['room:read']);
  });

  it('leaves a read alone when its write is unticked', () => {
    expect(applyPermissionChange(['room:read', 'room:write'], ['room:read'])).toEqual([
      'room:read',
    ]);
  });

  it('names nothing for a read', () => {
    expect(permissionRequires('machine:read')).toEqual([]);
  });
});
