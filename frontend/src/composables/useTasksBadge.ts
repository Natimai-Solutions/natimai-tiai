import { readonly, ref } from 'vue';

/**
 * Bumped whenever a page changes what « Mes tâches » counts — a check closed
 * or taken, a visit recorded — so the menu badge reads again without waiting
 * for a navigation (audit U19).
 */
const version = ref(0);

export const tasksVersion = readonly(version);

export function notifyTasksChanged(): void {
  version.value++;
}
