/**
 * Whether the click being handled ended a text selection — a hostname, an IP
 * dragged over to copy it. A table whose rows open on click must then do
 * nothing: the mouseup that ends a selection is also a click, and used to
 * navigate away from what was being copied.
 *
 * « Ended a selection », not « there is one »: a selection left on the page —
 * Ctrl+A, a word selected earlier — is not this click's doing when the click
 * lands inside it (the browser then keeps it through the click), and the row
 * it lands on must open. So the selection has to have changed since the mouse
 * button went down.
 */
let changedSincePress = true;

if (typeof document !== 'undefined') {
  // Capture: before any handler of the page can stop the event.
  document.addEventListener(
    'mousedown',
    () => {
      changedSincePress = false;
    },
    true,
  );
  document.addEventListener('selectionchange', () => {
    changedSincePress = true;
  });
}

export function hasTextSelection(): boolean {
  if (typeof window === 'undefined' || typeof window.getSelection !== 'function') return false;
  const selection = window.getSelection();
  return Boolean(
    changedSincePress && selection && !selection.isCollapsed && selection.toString().trim(),
  );
}
