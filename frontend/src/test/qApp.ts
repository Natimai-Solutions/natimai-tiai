/**
 * Stand-in for the Quasar CLI's `#q-app` in specs (see the alias in
 * vitest.config.ts). The real wrappers return their callback untouched; they
 * only exist to type it.
 */
export const defineBoot = <T>(callback: T): T => callback;
export const defineRouter = <T>(callback: T): T => callback;
