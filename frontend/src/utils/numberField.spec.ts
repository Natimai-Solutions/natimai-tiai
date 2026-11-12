import { describe, expect, it } from 'vitest';
import { intFieldError } from './numberField';

describe('intFieldError', () => {
  it('refuses an emptied field rather than reading it as 0', () => {
    expect(intFieldError('', 0, 365)).toBe('Valeur requise');
    expect(intFieldError(null, 0, 365)).toBe('Valeur requise');
  });

  it('wants a whole number within the bounds', () => {
    expect(intFieldError(2.5, 0, 365)).toBe('Un nombre entier');
    expect(intFieldError('abc', 0, 365)).toBe('Un nombre entier');
    expect(intFieldError(0, 1, 3650)).toBe('Entre 1 et 3650');
    expect(intFieldError(5000, 0, 3650)).toBe('Entre 0 et 3650');
  });

  it('accepts the bounds themselves', () => {
    expect(intFieldError(0, 0, 365)).toBeNull();
    expect(intFieldError('99', 1, 99)).toBeNull();
  });
});
