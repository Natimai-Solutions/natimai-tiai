import common from './common';
import errors from './errors';
import packages from './packages';

/**
 * Every catalogue of the console, one domain per file, each with its French
 * and its English side by side (plan `dev/plan-console-bilingue.md`, §4.1).
 * A new domain is one import and one line in each object below.
 */
export const fr = {
  common: common.fr,
  errors: errors.fr,
  packages: packages.fr,
};

export const en = {
  common: common.en,
  errors: errors.en,
  packages: packages.en,
};

export type MessageSchema = typeof fr;
