import { describe, expect, it } from 'vitest';
import { hashUrlToHistory } from './legacyUrl';

describe('hashUrlToHistory', () => {
  it('turns a hash-mode link into its history path, query included', () => {
    expect(hashUrlToHistory('#/machines/42?tab=history', '/')).toBe('/machines/42?tab=history');
    expect(hashUrlToHistory('#/', '/')).toBe('/');
  });

  it('keeps a deployment base', () => {
    expect(hashUrlToHistory('#/tasks', '/console/')).toBe('/console/tasks');
  });

  it('leaves a plain anchor or no hash alone', () => {
    expect(hashUrlToHistory('', '/')).toBeNull();
    expect(hashUrlToHistory('#section', '/')).toBeNull();
  });
});
