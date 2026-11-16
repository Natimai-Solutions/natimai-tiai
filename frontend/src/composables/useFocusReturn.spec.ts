// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useFocusReturn } from './useFocusReturn';

describe('useFocusReturn (item 12)', () => {
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('focuses the menu button again when the dialog closes with the focus nowhere', () => {
    vi.useFakeTimers();
    const button = document.createElement('button');
    document.body.appendChild(button);
    const { remember, restore } = useFocusReturn();
    const click = new MouseEvent('click');
    Object.defineProperty(click, 'currentTarget', { value: button });
    remember(click);

    (document.activeElement as HTMLElement | null)?.blur();
    restore();
    vi.runAllTimers();
    expect(document.activeElement).toBe(button);
  });

  it('leaves the focus where the dialog put it', () => {
    vi.useFakeTimers();
    const button = document.createElement('button');
    const other = document.createElement('input');
    document.body.append(button, other);
    const { remember, restore } = useFocusReturn();
    remember(button);
    other.focus();
    restore();
    vi.runAllTimers();
    expect(document.activeElement).toBe(other);
  });
});
