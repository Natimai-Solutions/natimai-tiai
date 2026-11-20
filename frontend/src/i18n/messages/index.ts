import account from './account';
import alerts from './alerts';
import audit from './audit';
import auth from './auth';
import checks from './checks';
import commands from './commands';
import common from './common';
import dashboard from './dashboard';
import errors from './errors';
import exports from './exports';
import format from './format';
import groups from './groups';
import interventions from './interventions';
import layout from './layout';
import machine from './machine';
import machines from './machines';
import maintenance from './maintenance';
import packagePages from './packagePages';
import packages from './packages';
import permissions from './permissions';
import rooms from './rooms';
import settings from './settings';
import settingsEnv from './settingsEnv';
import software from './software';
import tasks from './tasks';
import users from './users';

/**
 * Every catalogue of the console, one domain per file, each with its French
 * and its English side by side (plan `dev/plan-console-bilingue.md`, §4.1).
 * A domain's texts are `t('<domain>.<key>')`. The API's error codes have
 * their own table (`errorCodes.ts`).
 */
export const fr = {
  alerts: alerts.fr,
  common: common.fr,
  errors: errors.fr,
  packages: packages.fr,
  machine: machine.fr,
  machines: machines.fr,
  settings: settings.fr,
  settingsEnv: settingsEnv.fr,
  users: users.fr,
  groups: groups.fr,
  account: account.fr,
  audit: audit.fr,
  permissions: permissions.fr,
  rooms: rooms.fr,
  maintenance: maintenance.fr,
  checks: checks.fr,
  tasks: tasks.fr,
  interventions: interventions.fr,
  layout: layout.fr,
  auth: auth.fr,
  dashboard: dashboard.fr,
  software: software.fr,
  format: format.fr,
  packagePages: packagePages.fr,
  commands: commands.fr,
  exports: exports.fr,
};

export const en = {
  alerts: alerts.en,
  common: common.en,
  errors: errors.en,
  packages: packages.en,
  machine: machine.en,
  machines: machines.en,
  settings: settings.en,
  settingsEnv: settingsEnv.en,
  users: users.en,
  groups: groups.en,
  account: account.en,
  audit: audit.en,
  permissions: permissions.en,
  rooms: rooms.en,
  maintenance: maintenance.en,
  checks: checks.en,
  tasks: tasks.en,
  interventions: interventions.en,
  layout: layout.en,
  auth: auth.en,
  dashboard: dashboard.en,
  software: software.en,
  format: format.en,
  packagePages: packagePages.en,
  commands: commands.en,
  exports: exports.en,
};

export type MessageSchema = typeof fr;
