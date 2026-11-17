/**
 * Give the focus back to what opened a dialog once it closes (item 12).
 *
 * QDialog refocuses the element that had the focus when it opened — but a
 * dialog opened from a row's menu was opened from a menu entry, which the
 * closing menu has already removed: Escape then left the focus on <body>, and
 * a keyboard reader at the top of the page. The menu's button is remembered
 * instead, and focused again when the dialog hides with the focus nowhere.
 */
export function useFocusReturn(): {
  remember: (event: Event | HTMLElement | null | undefined) => void;
  restore: () => void;
} {
  let trigger: HTMLElement | null = null;

  function remember(event: Event | HTMLElement | null | undefined) {
    if (!event) return;
    const el = event instanceof Event ? event.currentTarget : event;
    if (el instanceof HTMLElement) trigger = el;
  }

  function restore() {
    const target = trigger;
    if (!target) return;
    // After QDialog's own refocus has had its turn: when it found its element,
    // the focus is somewhere and is left there.
    setTimeout(() => {
      const active = document.activeElement;
      if ((!active || active === document.body) && target.isConnected) target.focus();
    }, 0);
  }

  return { remember, restore };
}
