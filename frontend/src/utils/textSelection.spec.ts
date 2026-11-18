// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { hasTextSelection } from './textSelection';

function select(text: string | null) {
  return vi
    .spyOn(window, 'getSelection')
    .mockReturnValue(
      (text === null
        ? { isCollapsed: true, toString: () => '' }
        : { isCollapsed: false, toString: () => text }) as unknown as Selection,
    );
}
const press = () => document.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
const selectionChanged = () => document.dispatchEvent(new Event('selectionchange'));

describe('hasTextSelection — did this click select text?', () => {
  afterEach(() => vi.restoreAllMocks());

  it('is false with nothing selected, or only blanks', () => {
    press();
    select(null);
    expect(hasTextSelection()).toBe(false);
    select('  \n ');
    selectionChanged();
    expect(hasTextSelection()).toBe(false);
  });

  it('is true for a selection made by the press that ends in this click (a drag)', () => {
    press();
    select('PC-01');
    selectionChanged();
    expect(hasTextSelection()).toBe(true);
  });

  // Review finding 6, corollary: after Ctrl+A — or with any selection left
  // on the page — a plain click inside it selects nothing, and must not be
  // swallowed as if it had.
  it('is false for a selection that was there before the press and did not move', () => {
    select('Tout le contenu de la page');
    selectionChanged();
    press();
    expect(hasTextSelection()).toBe(false);
  });

  it('is true again when the same text is selected anew', () => {
    select('PC-01');
    selectionChanged();
    press();
    // The press collapses the old selection, the drag makes it again.
    selectionChanged();
    expect(hasTextSelection()).toBe(true);
  });
});
