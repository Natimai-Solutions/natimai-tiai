import { readonly, ref } from 'vue';

/**
 * Bumped whenever the queue of reports changes — one sorted — so the menu's
 * badge reads again without waiting for a navigation (C4).
 */
const version = ref(0);

export const reportsVersion = readonly(version);

export function notifyReportsChanged(): void {
  version.value++;
}
