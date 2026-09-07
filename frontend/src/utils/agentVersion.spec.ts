import { describe, expect, it } from 'vitest';
import { agentVersionLabel, compareVersions, isAgentOutdated } from './agentVersion';

describe('compareVersions', () => {
  it('compares numeric fields as numbers, not strings', () => {
    expect(compareVersions('0.10.0', '0.9.0')).toBeGreaterThan(0);
    expect(compareVersions('1.0.0', '0.99.99')).toBeGreaterThan(0);
    expect(compareVersions('0.5.0', '0.5.0')).toBe(0);
  });

  it('puts a pre-release below its release and above the previous one', () => {
    expect(compareVersions('0.5.0-dev.abc1234', '0.5.0')).toBeLessThan(0);
    expect(compareVersions('0.5.0-dev.abc1234', '0.4.9')).toBeGreaterThan(0);
  });

  it('ignores a leading v', () => {
    expect(compareVersions('v0.5.0', '0.5.0')).toBe(0);
  });
});

describe('isAgentOutdated', () => {
  it('flags only a version below the reference', () => {
    expect(isAgentOutdated('0.4.1', '0.5.0')).toBe(true);
    expect(isAgentOutdated('0.5.0', '0.5.0')).toBe(false);
    // Ahead of a pinned reference: not behind.
    expect(isAgentOutdated('0.6.0', '0.5.0')).toBe(false);
  });

  it('treats an unknown version or an empty parc as not behind', () => {
    expect(isAgentOutdated(null, '0.5.0')).toBe(false);
    expect(isAgentOutdated('0.4.1', null)).toBe(false);
  });
});

describe('agentVersionLabel', () => {
  it('says where the version stands', () => {
    expect(agentVersionLabel('0.4.1', '0.5.0')).toBe('0.4.1 — obsolète (référence 0.5.0)');
    expect(agentVersionLabel('0.5.0', '0.5.0')).toBe('0.5.0 — à jour');
    expect(agentVersionLabel('0.5.0', null)).toBe('0.5.0');
    expect(agentVersionLabel(null, '0.5.0')).toBe('—');
  });
});
