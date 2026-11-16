/**
 * Whether the reader has just selected text — to copy a hostname, an IP. A
 * table whose rows open on click must then do nothing: the mouseup that ends
 * a selection is also a click, and used to navigate away from what was being
 * copied.
 */
export function hasTextSelection(): boolean {
  if (typeof window === 'undefined' || typeof window.getSelection !== 'function') return false;
  const selection = window.getSelection();
  return Boolean(selection && !selection.isCollapsed && selection.toString().trim());
}
