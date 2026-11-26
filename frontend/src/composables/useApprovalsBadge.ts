import { readonly, ref } from 'vue';

/**
 * Bumped whenever a request for approval changes — one decided, cancelled,
 * or sent — so the menu's badge reads again without waiting for a
 * navigation (C10).
 */
const version = ref(0);

export const approvalsVersion = readonly(version);

export function notifyApprovalsChanged(): void {
  version.value++;
}
